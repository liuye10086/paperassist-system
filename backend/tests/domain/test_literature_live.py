"""Bounded live policy, exercised exclusively with synthetic local responses."""
from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
import os

import pytest
import requests

from app.adapters.ncbi import BASE_URL, NcbiClient, NcbiSettings
from app.adapters.doi import DoiClient


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


class Response:
    def __init__(self, raw=b'', status=200):
        self.raw, self.status_code, self.closed = raw, status, False
        self.headers = {'Location': 'https://publisher.example/synthetic'}

    def iter_content(self, chunk_size):
        yield self.raw

    @property
    def content(self):
        raise AssertionError('response body property forbidden')

    def close(self):
        self.closed = True


class Transport:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def search_bytes(ids):
    return json.dumps({'esearchresult': {'count': str(len(ids)), 'idlist': ids}}).encode()


def xml_bytes(ids):
    return ('<PubmedArticleSet>' + ''.join(
        '<PubmedArticle><MedlineCitation><PMID>' + pmid + '</PMID><Article>'
        '<ArticleTitle>Synthetic</ArticleTitle></Article></MedlineCitation><PubmedData>'
        '<ArticleIdList><ArticleId IdType="doi">10.1234/synthetic-' + pmid +
        '</ArticleId></ArticleIdList></PubmedData></PubmedArticle>' for pmid in ids
    ) + '</PubmedArticleSet>').encode()


def build(tmp_path, responses):
    from app.domain.literature_live import LiveLedger, LiveTransport
    ledger = LiveLedger(tmp_path / 'ledger.jsonl', batch_id='test-batch')
    wire = Transport(responses)
    guard = LiveTransport(ledger, transport=wire)
    settings = NcbiSettings(True, 'PaperAssist', 'hidden@example.invalid', 'hidden-key')
    return ledger, wire, guard, NcbiClient(settings, session=guard.ncbi_session(settings))


def test_two_exact_queries_derive_fetch_and_doi_allowlists_and_offline_replay(tmp_path):
    from app.domain.literature_live import INITIAL_QUERY, SUPPLEMENT_QUERY
    ledger, wire, guard, client = build(tmp_path, [Response(search_bytes(['12'])), Response(xml_bytes(['12'])),
                                                 Response(search_bytes(['34'])), Response(xml_bytes(['34']))])
    assert client.search(INITIAL_QUERY, 20, 'relevance').pmids == ['12']
    assert client.fetch(['12']).records[0]['doi'] == '10.1234/synthetic-12'
    assert client.search(SUPPLEMENT_QUERY, 20, 'relevance').pmids == ['34']
    assert client.fetch(['34']).records[0]['pmid'] == '34'
    assert ledger.allowed_dois() == ['10.1234/synthetic-12', '10.1234/synthetic-34']
    assert ledger.summary()['ncbi_attempts'] == 4
    ledger.complete()
    replay = ledger.recorded_ncbi_client()
    assert replay.search(INITIAL_QUERY, 20, 'relevance').pmids == ['12']
    assert replay.fetch(['34']).raw == xml_bytes(['34'])
    assert len(wire.calls) == 4


def test_budget_reserved_before_dispatch_failure_consumes_and_reopen_never_resets(tmp_path):
    from app.domain.literature_live import INITIAL_QUERY, LiveLedger, LiveTransport, LivePolicyError
    ledger, wire, guard, client = build(tmp_path, [requests.Timeout('hidden-key')] * 10)
    for _ in range(10):
        with pytest.raises(Exception, match='ncbi_unavailable'):
            client.search(INITIAL_QUERY, 20, 'relevance')
    reopened = LiveLedger(tmp_path / 'ledger.jsonl', batch_id='test-batch')
    client.session = LiveTransport(reopened, transport=wire).ncbi_session(client.settings)
    with pytest.raises(LivePolicyError, match='live_budget_exhausted'):
        client.search(INITIAL_QUERY, 20, 'relevance')
    assert reopened.summary()['ncbi_attempts'] == 10 and len(wire.calls) == 10


def test_preflight_denies_unknown_host_query_ids_and_kwargs_without_charge(tmp_path):
    from app.domain.literature_live import INITIAL_QUERY, LivePolicyError
    ledger, wire, guard, client = build(tmp_path, [Response(search_bytes(['12', '34']))])
    for query in ['other query', INITIAL_QUERY + ' ']:
        with pytest.raises(LivePolicyError):
            client.search(query, 20, 'relevance')
    with pytest.raises(LivePolicyError):
        client.fetch(['12'])
    with pytest.raises(LivePolicyError):
        client.session.get('https://publisher.example/efetch.fcgi', params={})
    assert ledger.summary()['ncbi_attempts'] == 0 and not wire.calls
    client.search(INITIAL_QUERY, 20, 'relevance')
    with pytest.raises(LivePolicyError):
        client.fetch(['12', '99'])
    with pytest.raises(LivePolicyError):
        client.fetch(['12'])  # Fetch binds to one whole actual search result.
    assert ledger.summary()['ncbi_attempts'] == 1 and len(wire.calls) == 1


def test_invalid_response_does_not_authorize_or_retain_secret_echo(tmp_path):
    from app.domain.literature_live import INITIAL_QUERY, LivePolicyError
    bad = b'{"esearchresult":{"count":"1","idlist":["12"],"querytranslation":"hidden-key"}}'
    ledger, wire, guard, client = build(tmp_path, [Response(bad)])
    with pytest.raises(Exception, match='ncbi_response_invalid'):
        client.search(INITIAL_QUERY, 20, 'relevance')
    with pytest.raises(LivePolicyError):
        client.fetch(['12'])
    for path in tmp_path.rglob('*'):
        if path.is_file():
            assert b'hidden-key' not in path.read_bytes()
            assert b'hidden@example.invalid' not in path.read_bytes()
    assert ledger.summary()['ncbi_attempts'] == 1


def test_doi_derived_from_fetched_xml_five_distinct_ten_attempts_no_body(tmp_path):
    from app.domain.literature_live import INITIAL_QUERY, LivePolicyError
    ids = [str(i) for i in range(1, 7)]
    ledger, wire, guard, client = build(tmp_path, [Response(search_bytes(ids)), Response(xml_bytes(ids))] + [Response(status=302)] * 10)
    client.search(INITIAL_QUERY, 20, 'relevance')
    client.fetch(ids)
    for doi in ledger.allowed_dois()[:5]:
        c = DoiClient(enabled=True, session=guard.doi_session(), allowed_dois=[doi])
        assert c.resolve(doi)['status'] == 'resolved'
    sixth = ledger.allowed_dois()[5]
    c = DoiClient(enabled=True, session=guard.doi_session(), allowed_dois=[sixth])
    with pytest.raises(LivePolicyError, match='live_doi_limit'):
        c.resolve(sixth)
    for _ in range(5):
        doi = ledger.allowed_dois()[0]
        assert DoiClient(enabled=True, session=guard.doi_session(), allowed_dois=[doi]).resolve(doi)['network_attempted']
    with pytest.raises(LivePolicyError, match='live_budget_exhausted'):
        DoiClient(enabled=True, session=guard.doi_session(), allowed_dois=[doi]).resolve(doi)
    assert ledger.summary()['doi_attempts'] == 10
    assert len(wire.calls) == 12
    assert all(call[1]['headers'] == {'Accept': 'text/html'} for call in wire.calls[2:])


def test_complete_persists_and_malformed_or_truncated_ledger_fails_closed(tmp_path):
    from app.domain.literature_live import INITIAL_QUERY, LiveLedger, LivePolicyError
    ledger, wire, guard, client = build(tmp_path, [])
    ledger.complete()
    with pytest.raises(LivePolicyError, match='live_closed'):
        client.search(INITIAL_QUERY, 20, 'relevance')
    with pytest.raises(LivePolicyError, match='live_batch_mismatch'):
        LiveLedger(tmp_path / 'ledger.jsonl', batch_id='another-batch')
    path = tmp_path / 'ledger.jsonl'
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(LivePolicyError, match='live_ledger_invalid'):
        LiveLedger(path, batch_id='test-batch')
    assert not wire.calls


def test_identity_loader_exact_fields_hidden_and_enabled_only_in_process(tmp_path, monkeypatch):
    from app.domain.literature_live import load_private_identity, LivePolicyError
    path = tmp_path / 'private.json'
    config = dict(enabled=False, tool='PaperAssist', email='hidden@example.invalid', api_key='hidden-key')
    path.write_text(json.dumps(config))
    original_env = dict(os.environ)
    settings = load_private_identity(path, enabled=True)
    assert settings.enabled and settings.api_key == 'hidden-key'
    assert json.loads(path.read_text()) == config and dict(os.environ) == original_env
    assert 'hidden' not in repr(settings)
    path.write_text(json.dumps({**config, 'unexpected': 'secret'}))
    with pytest.raises(LivePolicyError, match='live_identity_invalid'):
        load_private_identity(path, enabled=True)


def _process_attempt(path):
    from app.domain.literature_live import INITIAL_QUERY, LiveLedger, LiveTransport, LivePolicyError
    ledger = LiveLedger(path, batch_id='test-batch')
    transport = Transport([requests.Timeout('private exception')])
    settings = NcbiSettings(True, 'PaperAssist', 'hidden@example.invalid', '')
    client = NcbiClient(settings, session=LiveTransport(ledger, transport=transport).ncbi_session(settings))
    try:
        client.search(INITIAL_QUERY, 20, 'relevance')
    except Exception as error:
        return str(error)


def _process_open(path):
    from app.domain.literature_live import LiveLedger
    return LiveLedger(path, batch_id='test-batch').summary()['ncbi_attempts']


def test_cross_process_initial_creation_shares_one_stable_ledger(tmp_path):
    path = tmp_path / 'new-ledger.jsonl'
    with multiprocessing.get_context('spawn').Pool(3) as pool:
        assert pool.map(_process_open, [str(path)] * 6) == [0] * 6
    assert path.read_bytes().count(b'"event":"opened"') == 1


def test_cross_process_and_thread_races_never_overspend(tmp_path):
    from app.domain.literature_live import LiveLedger
    path = tmp_path / 'ledger.jsonl'
    ledger = LiveLedger(path, batch_id='test-batch')
    with multiprocessing.get_context('spawn').Pool(3) as pool:
        results = pool.map(_process_attempt, [str(path)] * 6)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results += list(pool.map(_process_attempt, [str(path)] * 8))
    assert results.count('ncbi_unavailable') == 10
    assert results.count('live_budget_exhausted') == 4
    assert ledger.summary()['ncbi_attempts'] == 10


def test_rate_separation_shared_between_objects_and_ledger_reserved_on_wire(tmp_path):
    from app.domain.literature_live import INITIAL_QUERY, LiveLedger, LiveTransport
    import time
    ledger, wire, guard, client = build(tmp_path, [])
    times = []
    class Observe:
        def get(self, *args, **kwargs):
            times.append(time.time())
            # Reservation must already be durable before the request starts.
            events = [json.loads(line) for line in ledger.path.read_text().splitlines()]
            assert sum(e['event'] == 'reserved' for e in events) == len(times)
            raise requests.Timeout()
    for _ in range(2):
        reopened = LiveLedger(ledger.path, batch_id='test-batch')
        client.session = LiveTransport(reopened, transport=Observe()).ncbi_session(client.settings)
        with pytest.raises(Exception, match='ncbi_unavailable'):
            client.search(INITIAL_QUERY, 20, 'relevance')
    assert times[1] - times[0] >= 0.49


def test_missing_previously_initialized_ledger_does_not_reset_budget(tmp_path):
    from app.domain.literature_live import LiveLedger, LivePolicyError
    ledger, wire, guard, client = build(tmp_path, [])
    ledger.path.rename(tmp_path / 'preserved-journal')
    with pytest.raises(LivePolicyError, match='live_ledger_invalid'):
        LiveLedger(ledger.path, batch_id='test-batch')


@pytest.mark.parametrize('response', [Response(b'hidden-key', 503),
                                    Response(b'{"error":"hidden-key"}'),
                                    Response(b'x' * (8 * 1024 * 1024 + 1))])
def test_http_error_invalid_and_oversized_body_not_retained_or_authorized(tmp_path, response):
    from app.domain.literature_live import INITIAL_QUERY, LivePolicyError
    ledger, wire, guard, client = build(tmp_path, [response])
    with pytest.raises(Exception, match='ncbi_'):
        client.search(INITIAL_QUERY, 20, 'relevance')
    assert ledger.summary()['ncbi_attempts'] == 1
    assert not list(tmp_path.rglob('*.bin'))
    assert response.closed
    with pytest.raises(LivePolicyError):
        client.fetch(['12'])


def test_corrupt_retained_receipt_and_changed_policy_fail_closed(tmp_path):
    from app.domain.literature_live import INITIAL_QUERY, LiveLedger, LivePolicyError
    ledger, wire, guard, client = build(tmp_path, [Response(search_bytes(['12']))])
    client.search(INITIAL_QUERY, 20, 'relevance')
    artifact = next(tmp_path.rglob('*.bin'))
    original = artifact.read_bytes()
    artifact.write_bytes(b'{}')
    with pytest.raises(LivePolicyError, match='live_ledger_invalid'):
        ledger.summary()
    artifact.write_bytes(original)
    original_journal = ledger.path.read_bytes()
    ledger.path.write_bytes(original_journal.replace(b'interval0.5', b'interval0.0'))
    with pytest.raises(LivePolicyError, match='live_ledger_invalid'):
        LiveLedger(ledger.path, batch_id='test-batch')


def test_doi_encoded_path_no_body_failure_consumes_and_denied_headers_no_charge(tmp_path):
    from app.domain.literature_live import INITIAL_QUERY, LiveLedger, LivePolicyError
    doi = '10.1234/a/../b?x#z%p'
    xml = xml_bytes(['12']).replace(b'10.1234/synthetic-12', doi.encode())
    ledger, wire, guard, client = build(tmp_path, [Response(search_bytes(['12'])), Response(xml),
                                                requests.Timeout('hidden-key'), Response(status=404)])
    client.search(INITIAL_QUERY, 20, 'relevance')
    client.fetch(['12'])
    session = guard.doi_session()
    options = dict(allow_redirects=False, timeout=(3.05, 8), stream=True, headers={'Accept': 'text/html'})
    with pytest.raises(LivePolicyError):
        session.get('https://publisher.example/secret', **options)
    with pytest.raises(LivePolicyError):
        session.get('https://doi.org/10.1234/a%2F..%2Fb%3Fx%23z%25p',
                    **{**options, 'headers': {'Accept': 'text/html', 'Authorization': 'secret'}})
    assert ledger.summary()['doi_attempts'] == 0
    result = DoiClient(enabled=True, session=session, allowed_dois=[doi]).resolve(doi)
    assert result['status'] == 'timeout' and result['network_attempted']
    reopened = LiveLedger(ledger.path, batch_id='test-batch')
    assert reopened.summary()['doi_attempts'] == 1
    assert DoiClient(enabled=True, session=session, allowed_dois=[doi]).resolve(doi)['status'] == 'not_found'
    assert wire.calls[-1][0] == 'https://doi.org/10.1234/a%2F..%2Fb%3Fx%23z%25p'


def test_invalid_fetch_does_not_grant_doi_and_secret_encoding_rejected(tmp_path):
    from app.domain.literature_live import INITIAL_QUERY
    encoded_secret = b'{"esearchresult":{"count":"1","idlist":["12"],"querytranslation":"hidden-\\u006bey"}}'
    ledger, wire, guard, client = build(tmp_path, [Response(encoded_secret), Response(search_bytes(['12'])),
                                                Response(xml_bytes(['99']))])
    with pytest.raises(Exception, match='ncbi_response_invalid'):
        client.search(INITIAL_QUERY, 20, 'relevance')
    client.search(INITIAL_QUERY, 20, 'relevance')
    with pytest.raises(Exception, match='ncbi_response_invalid'):
        client.fetch(['12'])
    assert ledger.allowed_dois() == [] and ledger.summary()['ncbi_attempts'] == 3


def test_successful_query_cannot_start_a_second_round(tmp_path):
    from app.domain.literature_live import INITIAL_QUERY, LivePolicyError
    ledger, wire, guard, client = build(tmp_path, [Response(search_bytes(['12']))])
    client.search(INITIAL_QUERY, 20, 'relevance')
    with pytest.raises(LivePolicyError, match='live_request_denied'):
        client.search(INITIAL_QUERY, 20, 'relevance')
    assert ledger.summary()['ncbi_attempts'] == 1 and len(wire.calls) == 1


@pytest.mark.parametrize('keep', ['header', 'without_last_event'])
def test_complete_jsonl_event_rollback_fails_closed_without_dispatch(tmp_path, keep):
    from app.domain.literature_live import INITIAL_QUERY, LiveLedger, LivePolicyError
    ledger, wire, guard, client = build(tmp_path, [requests.Timeout('synthetic')])
    with pytest.raises(Exception, match='ncbi_unavailable'):
        client.search(INITIAL_QUERY, 20, 'relevance')
    assert ledger.summary()['ncbi_attempts'] == 1
    lines = ledger.path.read_bytes().splitlines(keepends=True)
    ledger.path.write_bytes(b''.join(lines[:1] if keep == 'header' else lines[:-1]))
    with pytest.raises(LivePolicyError, match='live_ledger_invalid'):
        LiveLedger(ledger.path, batch_id='test-batch')
    with pytest.raises(LivePolicyError, match='live_ledger_invalid'):
        client.search(INITIAL_QUERY, 20, 'relevance')
    assert len(wire.calls) == 1


def test_complete_event_rollback_cannot_reopen_closed_live_entry(tmp_path):
    from app.domain.literature_live import LiveLedger, LivePolicyError
    ledger, wire, guard, client = build(tmp_path, [])
    ledger.complete()
    lines = ledger.path.read_bytes().splitlines(keepends=True)
    ledger.path.write_bytes(b''.join(lines[:-1]))
    with pytest.raises(LivePolicyError, match='live_ledger_invalid'):
        LiveLedger(ledger.path, batch_id='test-batch')


def test_uncommitted_complete_event_does_not_repair_checkpoint_mismatch(tmp_path):
    from app.domain.literature_live import LiveLedger, LivePolicyError
    ledger, wire, guard, client = build(tmp_path, [])
    with ledger.path.open('ab') as stream:
        stream.write(b'{"event":"completed","at":1}\n')
    with pytest.raises(LivePolicyError, match='live_ledger_invalid'):
        LiveLedger(ledger.path, batch_id='test-batch')


def test_watermark_rollback_and_partial_checkpoint_fail_closed(tmp_path):
    from app.domain.literature_live import LiveLedger, LivePolicyError
    ledger, wire, guard, client = build(tmp_path, [])
    lock_path = ledger.path.with_name(ledger.path.name + '.lock')
    old_checkpoint = lock_path.read_bytes()
    ledger.complete()
    new_checkpoint = lock_path.read_bytes()
    for broken in (old_checkpoint, new_checkpoint + b'{"length":'):
        lock_path.write_bytes(broken)
        with pytest.raises(LivePolicyError, match='live_ledger_invalid'):
            LiveLedger(ledger.path, batch_id='test-batch')


def test_reserved_without_dispatch_or_finish_cannot_roll_back_to_header(tmp_path):
    from app.domain.literature_live import LiveLedger, LivePolicyError
    ledger, wire, guard, client = build(tmp_path, [])
    with ledger.locked() as state:
        ledger.reserve(state, 'ncbi', {'query': 'initial'})
    assert ledger.summary()['ncbi_attempts'] == 1
    header = ledger.path.read_bytes().splitlines(keepends=True)[0]
    ledger.path.write_bytes(header)
    with pytest.raises(LivePolicyError, match='live_ledger_invalid'):
        LiveLedger(ledger.path, batch_id='test-batch')
    assert not wire.calls
