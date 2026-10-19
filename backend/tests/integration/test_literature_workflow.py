"""Real PostgreSQL/checkpoints with explicitly synthetic E-utilities responses."""
import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature import project, request, create
from tests.helpers.literature import SyntheticNcbi


def execute(task, provider=None):
    from app.domain.literature.execution import run_literature_task
    return run_literature_task(task['id'], task['revision'], client=provider)


def test_disabled_ncbi_saves_a_durable_wait_without_fake_candidates(client, monkeypatch):
    monkeypatch.setenv('PAPERASSIST_NCBI_ENABLED', '0')
    pid = project(client)
    task = create(client, pid).json()
    result = execute(task)
    assert result['status'] == 'waiting_confirmation' and result['error_code'] == 'ncbi_not_configured'
    workspace = client.get('/api/v1/tasks/' + task['id'] + '/workspace').json()
    assert workspace['wait']['kind'] == 'literature_configuration' and workspace['allowed_actions'] == []
    with database_connection() as db:
        for table in ('literature_records','project_references','literature_fetch_receipts','model_calls','budget_reservations'):
            assert db.execute('SELECT count(*) AS n FROM ' + table).fetchone()['n'] == 0


def test_batch_retrieval_missing_fields_provenance_and_project_candidate_decisions(client):
    pid = project(client)
    task = create(client, pid, {**request(), 'limit': 50}).json()
    provider = SyntheticNcbi(25, omit=['990000024'])
    result = execute(task, provider)
    assert result['status'] == 'succeeded', result
    assert [call[0] for call in provider.calls] == ['esearch','efetch','efetch']
    search = client.get(f'/api/v1/projects/{pid}/literature/searches/{task["id"]}').json()
    assert search['matched_count'] == 25 and search['retrieved_count'] == 24
    assert search['missing_pmids'] == ['990000024']
    first = client.get(f'/api/v1/projects/{pid}/literature/references').json()
    assert first['total'] == 24 and len(first['items']) == 10
    second = client.get(f'/api/v1/projects/{pid}/literature/references?page=2').json()
    assert not {r['id'] for r in first['items']} & {r['id'] for r in second['items']}
    candidate = first['items'][0]
    assert candidate['record']['full_text_status'] == 'not_acquired'
    assert candidate['record']['verification_status'] == 'not_verified'
    assert candidate['source']['source_kind'] == 'synthetic_fixture'
    source = client.get(candidate['source']['source_download_url'])
    assert source.status_code == 200 and b'Synthetic' in source.content
    assert 'email=' not in source.text and 'api_key=' not in source.text
    selected = client.patch(f'/api/v1/projects/{pid}/literature/references/{candidate["id"]}',
        json={'expected_revision': 1, 'status': 'shortlisted', 'note': 'Keep pending evidence review'})
    assert selected.status_code == 200 and selected.json()['selection']['revision'] == 2
    assert selected.json()['record']['verification_status'] == 'not_verified'
    replay = client.patch(f'/api/v1/projects/{pid}/literature/references/{candidate["id"]}',
        json={'expected_revision': 1, 'status': 'shortlisted', 'note': 'Keep pending evidence review'})
    assert replay.status_code == 200 and replay.json() == selected.json()
    conflict = client.patch(f'/api/v1/projects/{pid}/literature/references/{candidate["id"]}',
        json={'expected_revision': 1, 'status': 'excluded', 'note': ''})
    assert conflict.status_code == 409
    detail = client.get(f'/api/v1/projects/{pid}/literature/references/{candidate["id"]}').json()
    assert len(detail['decisions']) == 1 and detail['sources']['total'] == 1
    with database_connection() as db:
        missing = db.execute("SELECT record_json FROM literature_search_hits WHERE record_json->>'pmid'='990000001'").fetchone()['record_json']
        assert missing['year'] is None and missing['doi'] is None and missing['abstract'] == []
        assert missing['abstract_status'] == 'not_returned'
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n'] == 0


def test_repeated_queries_deduplicate_bibliography_and_keep_every_search_origin(client):
    pid = project(client)
    provider = SyntheticNcbi(2)
    first = create(client, pid, key='first').json()
    assert execute(first, provider)['status'] == 'succeeded'
    second = create(client, pid, key='second').json()
    assert execute(second, provider)['status'] == 'succeeded'
    assert len(provider.calls) == 2  # Fresh project-local response cache, no repeated HTTP attempts.
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM literature_records').fetchone()['n'] == 2
        assert db.execute('SELECT count(*) AS n FROM project_references').fetchone()['n'] == 2
        assert db.execute('SELECT count(*) AS n FROM literature_search_hits').fetchone()['n'] == 4
        assert db.execute('SELECT count(*) AS n FROM literature_fetch_receipts WHERE cached_from_id IS NOT NULL').fetchone()['n'] == 2
    candidate = client.get(f'/api/v1/projects/{pid}/literature/references').json()['items'][0]
    detail = client.get(f'/api/v1/projects/{pid}/literature/references/{candidate["id"]}').json()
    assert {s['search_id'] for s in detail['sources']['items']} == {first['id'],second['id']}
    assert execute(second, provider) is None


@pytest.mark.parametrize(('sort', 'limit'), [('relevance', 50), ('pub_date', 100)])
def test_search_candidate_pages_preserve_hit_order_across_batches_and_existing_candidates(client, sort, limit):
    pid = project(client)
    provider = SyntheticNcbi(25, omit=['990000013'])
    provider.ids.reverse()
    seed_provider = SyntheticNcbi(2)
    seed_provider.ids = [provider.ids[0], provider.ids[21]]
    seed = create(client, pid, {**request(), 'query': 'synthetic seed query'}, key='seed').json()
    assert execute(seed, seed_provider)['status'] == 'succeeded'
    with database_connection(write=True) as db:
        db.execute("UPDATE project_references SET created_at=created_at-interval '1 day' WHERE project_id=%s", (pid,))
        old_ids = {row['id'] for row in db.execute('SELECT id FROM project_references WHERE project_id=%s', (pid,)).fetchall()}

    task = create(client, pid, {**request(), 'sort': sort, 'limit': limit}, key='ordered').json()
    assert execute(task, provider)['status'] == 'succeeded'
    assert [call[0] for call in provider.calls] == ['esearch', 'efetch', 'efetch']
    expected_pmids = [pmid for pmid in provider.ids if pmid not in provider.omit]
    with database_connection() as db:
        project_order = [row['id'] for row in db.execute(
            'SELECT id FROM project_references WHERE project_id=%s ORDER BY created_at DESC,id', (pid,)).fetchall()]

    search_items, project_items = [], []
    for page in range(1, 4):
        response = client.get(f'/api/v1/projects/{pid}/literature/references',
            params={'search_id': task['id'], 'page': page})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['total'] == 24 and data['page_size'] == 10 and data['page'] == page
        search_items.extend(data['items'])
        project_items.extend(client.get(f'/api/v1/projects/{pid}/literature/references',
            params={'page': page}).json()['items'])
    assert [item['id'] for item in project_items] == project_order
    assert [item['pmid'] for item in search_items] == expected_pmids
    assert [item['source']['ordinal'] for item in search_items] == [
        index + 1 for index, pmid in enumerate(provider.ids) if pmid not in provider.omit]
    assert all(item['source']['search_id'] == task['id'] for item in search_items)
    assert old_ids <= {item['id'] for item in search_items}

    shortlisted = search_items[1::2]
    for item in shortlisted:
        response = client.patch(f'/api/v1/projects/{pid}/literature/references/{item["id"]}',
            json={'expected_revision': 1, 'status': 'shortlisted', 'note': ''})
        assert response.status_code == 200, response.text
    selected_items = []
    for page in (1, 2):
        response = client.get(f'/api/v1/projects/{pid}/literature/references',
            params={'search_id': task['id'], 'selection': 'shortlisted', 'page': page})
        assert response.status_code == 200, response.text
        assert response.json()['total'] == 12
        selected_items.extend(response.json()['items'])
    assert [item['id'] for item in selected_items] == [item['id'] for item in shortlisted]


def test_sci_and_thesis_reuse_public_pmid_without_sharing_candidates_or_sources(client):
    sci, thesis = project(client), project(client, 'thesis')
    provider = SyntheticNcbi(1)
    first, second = create(client,sci,key='sci').json(), create(client,thesis,key='thesis').json()
    assert execute(first,provider)['status'] == execute(second,provider)['status'] == 'succeeded'
    a = client.get(f'/api/v1/projects/{sci}/literature/references').json()['items'][0]
    b = client.get(f'/api/v1/projects/{thesis}/literature/references').json()['items'][0]
    assert a['reference_id'] == b['reference_id'] and a['id'] != b['id']
    assert client.get(f'/api/v1/projects/{thesis}/literature/references/{a["id"]}').status_code == 404
    assert client.get(a['source']['source_download_url'].replace(sci,thesis)).status_code == 404
    assert client.get(f'/api/v1/projects/{thesis}/literature/references?search_id={first["id"]}').status_code == 404
    assert len(provider.calls) == 4  # No cross-project query/response-cache disclosure.


def test_fetch_retry_reuses_saved_search_and_never_duplicates_published_page(client):
    pid = project(client)
    task = create(client,pid).json()
    provider = SyntheticNcbi(3, fail_fetches=1)
    deferred = execute(task,provider)
    assert deferred['status'] == 'running' and deferred['retry_count'] == 1
    assert deferred['error_code'] == 'ncbi_unavailable'
    resumed = execute(deferred,provider)
    assert resumed['status'] == 'succeeded'
    assert [c[0] for c in provider.calls] == ['esearch','efetch','efetch']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM literature_search_hits').fetchone()['n'] == 3
        assert db.execute("SELECT count(*) AS n FROM literature_fetch_receipts WHERE status='failed'").fetchone()['n'] == 1
    events = client.get('/api/v1/tasks/'+task['id']+'/events').json()['items']
    assert any(e['retry_delay_seconds'] == 10 for e in events)


def test_retry_budget_is_finite_and_saved_candidates_and_inputs_survive(client):
    pid = project(client)
    task = create(client,pid).json()
    provider = SyntheticNcbi(1, fail_fetches=10)
    current = task
    for _ in range(4):
        current = execute(current, provider)
    assert current['status'] == 'failed' and current['retry_count'] == 3
    assert [c[0] for c in provider.calls].count('esearch') == 1
    assert [c[0] for c in provider.calls].count('efetch') == 4
    assert client.get(f'/api/v1/projects/{pid}/literature/searches/{task["id"]}').json()['input'] == request()


def test_source_bytes_tamper_is_reported_without_recomputation(client):
    from app.domain.literature.objects import LiteratureObjects
    pid = project(client)
    provider = SyntheticNcbi(1)
    task = create(client,pid).json()
    assert execute(task,provider)['status'] == 'succeeded'
    candidate = client.get(f'/api/v1/projects/{pid}/literature/references').json()['items'][0]
    with database_connection() as db:
        row = db.execute('SELECT * FROM literature_fetch_receipts WHERE id=%s',(candidate['source']['receipt_id'],)).fetchone()
    path = LiteratureObjects().path(row['object_key'])
    path.write_bytes(b'altered synthetic evidence')
    assert client.get(candidate['source']['source_download_url']).status_code == 409
    assert len(provider.calls) == 2


def test_old_search_keeps_its_own_snapshot_after_a_later_retrieval(client):
    pid = project(client)
    first = create(client,pid,key='old').json()
    assert execute(first,SyntheticNcbi(1,suffix='old'))['status'] == 'succeeded'
    with database_connection(write=True) as db:
        db.execute("UPDATE literature_fetch_receipts SET attempted_at=attempted_at-interval '25 hours'")
    second = create(client,pid,key='new').json()
    assert execute(second,SyntheticNcbi(1,suffix='new'))['status'] == 'succeeded'
    old = client.get(f'/api/v1/projects/{pid}/literature/references?search_id={first["id"]}').json()['items'][0]
    assert old['record']['title'].endswith('old')
    assert old['source']['search_id'] == first['id']


def test_candidate_detail_keeps_requested_search_snapshot_and_rejects_unrelated_searches(client):
    pid = project(client)
    first = create(client, pid, key='detail-old').json()
    assert execute(first, SyntheticNcbi(2, suffix='old'))['status'] == 'succeeded'
    with database_connection(write=True) as db:
        db.execute("UPDATE literature_fetch_receipts SET attempted_at=attempted_at-interval '25 hours'")
    provider = SyntheticNcbi(2, suffix='new')
    provider.ids = ['990000001', '990000003']
    second = create(client, pid, key='detail-new').json()
    assert execute(second, provider)['status'] == 'succeeded'
    candidates = client.get(f'/api/v1/projects/{pid}/literature/references', params={'search_id': second['id']}).json()['items']
    shared = next(item for item in candidates if item['pmid'] == '990000001')
    added = next(item for item in candidates if item['pmid'] == '990000003')
    url = f'/api/v1/projects/{pid}/literature/references/{shared["id"]}'
    assert client.get(url).json()['record']['title'].endswith('new')
    old = client.get(url, params={'search_id': first['id']})
    assert old.status_code == 200, old.text
    assert old.json()['record']['title'].endswith('old')
    assert old.json()['source']['search_id'] == first['id']
    assert {source['search_id'] for source in old.json()['sources']['items']} == {first['id'], second['id']}
    selected = client.patch(url, json={'expected_revision': 1, 'status': 'shortlisted', 'note': 'Synthetic decision'})
    assert selected.status_code == 200, selected.text
    refreshed = client.get(url, params={'search_id': first['id'], 'page': 2}).json()
    assert refreshed['record'] == old.json()['record']
    assert refreshed['source'] == old.json()['source']
    assert refreshed['selection']['status'] == 'shortlisted'
    assert refreshed['sources']['items'] == [] and refreshed['sources']['total'] == 2
    no_hit = client.get(f'/api/v1/projects/{pid}/literature/references/{added["id"]}', params={'search_id': first['id']})
    assert no_hit.status_code == 404
    other = create(client, project(client), key='other-project').json()
    assert client.get(url, params={'search_id': other['id']}).status_code == 404
    assert client.get(url, params={'search_id': 'missing-search'}).status_code == 404


def test_corrupt_checkpoint_cannot_skip_a_page(client):
    from psycopg.types.json import Jsonb
    pid = project(client)
    task = create(client,pid).json()
    with database_connection(write=True) as db:
        row = db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s',(task['id'],)).fetchone()
        state = {**row['state_json'],'next_offset':20}
        db.execute('UPDATE task_checkpoints SET state_json=%s WHERE id=%s',(Jsonb(state),row['id']))
    provider = SyntheticNcbi(1)
    result = execute(task,provider)
    assert result['status'] == 'failed' and result['error_code'] == 'task_source_conflict'
    assert provider.calls == []


def test_crash_after_first_page_recovers_without_late_or_duplicate_publication(client):
    from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
    from app.domain.literature.execution import Retrieval
    pid = project(client)
    original = create(client,pid,{**request(),'limit':50}).json()
    repository = TaskExecutionStore()
    lease = repository.claim(original['id'],original['revision'],task_type='literature_search')
    provider = SyntheticNcbi(25)
    retrieval = Retrieval(repository,lease,provider)
    with repository.connection() as db:
        _, snapshot, _ = retrieval.load(db)
    retrieval.search(snapshot)
    with repository.connection() as db:
        _, _, checkpoint = retrieval.load(db)
    retrieval.fetch(checkpoint['state_json'])
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(original['id'],))
    assert repository.recover_expired() == 1
    with database_connection() as db:
        resumed = dict(db.execute('SELECT * FROM tasks WHERE id=%s',(original['id'],)).fetchone())
    import pytest
    with pytest.raises(LeaseLost):
        retrieval.fetch({**checkpoint['state_json'],'next_offset':20})
    assert execute(resumed,provider)['status'] == 'succeeded'
    assert [c[0] for c in provider.calls] == ['esearch','efetch','efetch']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM literature_search_hits').fetchone()['n'] == 25
        assert db.execute("SELECT count(*) AS n FROM task_events WHERE event_type='succeeded'").fetchone()['n'] == 1


def test_disabled_wait_resumes_idempotently_only_after_local_identity_configuration(client,monkeypatch):
    pid = project(client)
    task = create(client,pid).json()
    waiting = execute(task)
    workspace = client.get('/api/v1/tasks/'+task['id']+'/workspace').json()
    payload = dict(operation='resume',wait_id=workspace['wait']['id'],
        expected_task_revision=waiting['revision'],input_version=waiting['input_version'])
    url = '/api/v1/tasks/'+task['id']+'/resume'
    headers = {'Idempotency-Key':'resume-literature'}
    assert client.post(url,json=payload,headers=headers).status_code == 409
    monkeypatch.setenv('PAPERASSIST_NCBI_ENABLED','1')
    monkeypatch.setenv('PAPERASSIST_NCBI_EMAIL','synthetic@example.invalid')
    response = client.post(url,json=payload,headers=headers)
    assert response.status_code == 202,response.text
    assert client.post(url,json=payload,headers=headers).json() == response.json()
    assert execute(response.json(),SyntheticNcbi(0))['status'] == 'succeeded'


def test_shared_limiter_reserves_distinct_slots_for_parallel_workers(client):
    from concurrent.futures import ThreadPoolExecutor
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.literature.execution import reserve_request
    pid = project(client)
    repository = TaskExecutionStore()
    tasks = [create(client,pid,key='parallel-'+str(i)).json() for i in range(3)]
    leases = [repository.claim(t['id'],t['revision'],task_type='literature_search') for t in tasks]
    with ThreadPoolExecutor(max_workers=3) as pool:
        delays = sorted(pool.map(lambda lease: reserve_request(repository,lease),leases))
    assert delays[0] == 0 and delays[1] > .3 and delays[2] > .7
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM ncbi_rate_limits').fetchone()['n'] == 1
