"""Exercise inherited W1 writing with synthetic HTTP only; no API/DB/model work."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest


def test_shared_offline_self_test_uses_only_supported_request_models():
    path = Path(__file__).resolve().parents[1] / 'dev/cr_b04_downstream.py'
    completed = subprocess.run([sys.executable, str(path), '--self-test'],
                               capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result['offline_self_test'] == 'passed'
    assert result['checks'] == ['unknown_get_first_no_repost', 'explicit_retry_same_key_body',
                                'complete_rows_literal_zero_NA', 'six_actual_request_models']


def acceptance(tmp_path, monkeypatch, *, publish=True):
    path = Path(__file__).resolve().parents[1] / 'dev/cr_b06_w1_acceptance.py'
    spec = importlib.util.spec_from_file_location('cr_b06_w1_word_only_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / 'output'
    base = '/api/v1/projects/synthetic-project'
    kinds = ('sci_draft', 'thesis_draft')
    deliveries = [dict(id='delivery-' + kind, kind=kind, active=True) for kind in kinds]
    chapter = dict(id='results', title='Results', level=1, purpose='results',
                   output_language='zh-CN', result_group_ids=['research-results'])
    thesis = dict(confirmation_id='fixed-confirmation', profile_revision=1, chapters=[chapter])
    requests, candidates, previews = [], {}, {}
    exports = {}
    raw_docx = b'synthetic downloaded DOCX bytes; not a rendered Word document'
    behavior = dict(candidate_target=None, published_root=None, corrupt_docx=False)

    def preview(body):
        sources = [dict(id=identity, kind=source_kind, content={})
                   for field, source_kind in [('finding_version_ids', 'research_finding_version'),
                                              ('figure_version_ids', 'research_figure_version'),
                                              ('report_version_ids', 'research_report_version')]
                   for identity in body[field]]
        context = (dict(chapters=[chapter], confirmation={'chapters': [chapter]})
                   if 'thesis' in body else None)
        value = dict(body, schema_version=1, fact_projection_version=2, sources=sources,
                     project_id='synthetic-project', base_snapshot=None, thesis_context=context,
                     selected_source_ids=[s['id'] for s in sources],
                     document_context=dict(delivery_id=body['delivery_id'],
                                           document_kind='thesis' if context else 'sci'),
                     writing_scope='results_methods', real_model_calls=False, real_network_calls=False)
        value['merge_preview'] = module.compose(value)
        return value

    def respond(request):
        requests.append(request)
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        if 'pdf' in path:
            raise AssertionError('Word-only writing must not request PDF generation or downloads')
        if path == '/api/v1/auth/login':
            return httpx.Response(200, json={'csrf_token': 'synthetic-csrf'})
        if path.startswith('/api/v1/tasks/'):
            return httpx.Response(200, json=dict(id=path.rsplit('/', 1)[1], status='succeeded'))
        if path == base + '/research-intake':
            return httpx.Response(200, json={'deliveries': deliveries})
        if path == base + '/deliveries':
            return httpx.Response(200, json={'items': deliveries})
        if path == base + '/thesis-profile':
            return httpx.Response(200, json=dict(bound_confirmation_id='fixed-confirmation', revision=1))
        if path == base + '/research-results/writing-selection':
            kind = body['delivery_id'].removeprefix('delivery-')
            previews[kind] = preview(body)
            return httpx.Response(200, json=previews[kind])
        if path == base + '/research-manuscript-candidates':
            kind = body['delivery_id'].removeprefix('delivery-')
            candidate = previews[kind]['merge_preview']
            value = dict(id='candidate-' + kind, task_id='candidate-task-' + kind,
                         delivery_id=body['delivery_id'], manuscript_id=behavior['candidate_target'],
                         base_version_id=None, expected_revision=0, published_version_id=None,
                         candidate_sha256=module.digest(candidate), candidate=candidate)
            candidates[kind] = value
            return httpx.Response(202, json=value)
        for kind in kinds:
            candidate_path = base + '/research-manuscript-candidates/candidate-' + kind
            root = behavior['published_root'] or 'new-root-' + kind
            endpoint = base + '/manuscripts/' + root
            if path == candidate_path:
                return httpx.Response(200, json=candidates[kind])
            if path == candidate_path + '/publish':
                # The actual W1 override must review the exact candidate before the request.
                review = json.loads((output / kind / 'engineering-review.json').read_text(encoding='utf-8'))
                assert review['candidate_sha256'] == candidates[kind]['candidate_sha256']
                assert review['exact_compose_matches'] and review['expected_revision'] == 0
                result = dict(manuscript_id=root, version_id='version-' + kind, revision=1,
                              candidate_id=candidates[kind]['id'])
                return httpx.Response(200, json=result)
            if path == endpoint + '/versions/1':
                return httpx.Response(200, json={'id': 'version-' + kind, 'revision': 1})
            if path == endpoint + '/versions/1/writing-materials':
                return httpx.Response(200, json={'sources': previews[kind]['sources']})
            if path == endpoint + '/versions/1/exports':
                value = dict(id='export-' + kind, task_id='export-task-' + kind,
                             version_id='version-' + kind, sha256=module.sha(raw_docx),
                             download_url=endpoint + '/exports/export-' + kind + '/download')
                exports[kind] = value
                return httpx.Response(202, json=value)
            if path == endpoint + '/exports/export-' + kind:
                return httpx.Response(200, json=exports[kind])
            if path == endpoint + '/exports/export-' + kind + '/download':
                return httpx.Response(200, content=raw_docx + (b'changed' if behavior['corrupt_docx'] else b''))
        raise AssertionError('Unexpected synthetic HTTP request: ' + request.method + ' ' + path)

    real_client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(respond)))
    (tmp_path / 'credentials.json').write_text(json.dumps({'review': dict(
        id='synthetic-owner', email='synthetic@example.test', password='synthetic-unused')}), encoding='utf-8')
    args = SimpleNamespace(project_id='synthetic-project', result_id=[], figure_result_id=[],
                           retry_original=[], wait_seconds=60, publish=publish,
                           thesis_selection=None, school_export_options=None)
    state = dict(schema='synthetic', url='https://fixture.invalid', assets=str(tmp_path / 'assets'))
    run = module.W1Acceptance(args, state, output)
    run.record.update(protected_before={'manuscripts': {'protected-root': 'original'}},
                      thesis_selection=thesis)
    inputs = (dict(id='fixed-finding'), dict(id='fixed-figure'),
              {'en': dict(id='fixed-en-report'), 'zh-CN': dict(id='fixed-zh-report')})
    return SimpleNamespace(run=run, inputs=inputs, requests=requests, behavior=behavior,
                           exports=exports, raw_docx=raw_docx, module=module)


def test_w1_inherited_writing_finishes_both_new_roots_with_docx_only(tmp_path, monkeypatch):
    fixture = acceptance(tmp_path, monkeypatch)
    run = fixture.run
    try:
        assert type(run).writing is fixture.module.Acceptance.writing
        run.writing(*fixture.inputs)
        assert [item['kind'] for item in run.record['published']] == ['sci_draft', 'thesis_draft']
        for item in run.record['published']:
            kind = item['kind']
            assert item['manuscript_id'] == 'new-root-' + kind
            assert item['version_id'] == 'version-' + kind
            assert item['docx_export_id'] == 'export-' + kind
            assert 'pdf_id' not in item
            assert (run.output / kind / 'analysis.docx').read_bytes() == fixture.raw_docx
            assert run.record['candidate_reviews'][kind]['fixed_sources_verified'] is True
        exports = [r for r in fixture.requests if r.method == 'POST' and r.url.path.endswith('/exports')]
        assert [json.loads(r.content) for r in exports] == [{}, {'school': {'include_toc': False}}]
        assert not any('pdf' in r.url.path for r in fixture.requests)
    finally:
        run.client.close()


def test_without_explicit_publish_writing_stops_before_root_and_exports(tmp_path, monkeypatch):
    fixture = acceptance(tmp_path, monkeypatch, publish=False)
    try:
        fixture.run.writing(*fixture.inputs)
        assert fixture.run.record['published'] == []
        assert set(fixture.run.record['actions']) == {'candidate-sci_draft', 'candidate-thesis_draft'}
        assert not any('/manuscripts/' in r.url.path or r.url.path.endswith('/publish')
                       for r in fixture.requests)
    finally:
        fixture.run.client.close()


@pytest.mark.parametrize('boundary', ['candidate_target', 'published_root', 'corrupt_docx'])
def test_word_only_writing_keeps_new_root_and_download_hash_guards(tmp_path, monkeypatch, boundary):
    fixture = acceptance(tmp_path, monkeypatch)
    fixture.behavior[boundary] = True if boundary == 'corrupt_docx' else 'protected-root'
    expected = {'candidate_target': 'old manuscript', 'published_root': 'protected old manuscript',
                'corrupt_docx': 'exact member SHA'}[boundary]
    try:
        with pytest.raises((ValueError, AssertionError), match=expected):
            fixture.run.writing(*fixture.inputs)
        assert not list(fixture.run.output.rglob('*.docx'))
    finally:
        fixture.run.client.close()


def test_w1_resume_recovers_original_docx_requests_for_the_exact_versions(tmp_path, monkeypatch):
    fixture = acceptance(tmp_path, monkeypatch)
    run = fixture.run
    try:
        run.writing(*fixture.inputs)
        actions = run.record['actions']
        original = {label: (entry['key'], entry['digest']) for label, entry in actions.items()}
        for kind in ('sci_draft', 'thesis_draft'):
            actions['manuscript-docx-' + kind].pop('response')
        recovered = []

        def lookup(table, column, key, *, version):
            assert (table, column) == ('manuscript_exports', 'idempotency_key')
            kind = version.removeprefix('version-')
            assert key == original['manuscript-docx-' + kind][0]
            recovered.append((kind, version))
            return fixture.exports[kind]['id']

        monkeypatch.setattr(run, 'lookup_sql', lookup)
        fixture.requests.clear()
        run.writing(*fixture.inputs)
        assert recovered == [('sci_draft', 'version-sci_draft'), ('thesis_draft', 'version-thesis_draft')]
        assert {label: (entry['key'], entry['digest']) for label, entry in actions.items()} == original
        assert all(r.method == 'GET' or r.url.path.endswith('/writing-selection') for r in fixture.requests)
        assert not any(r.url.path.endswith('/download') for r in fixture.requests)
        assert all(actions['manuscript-docx-' + kind]['status'] == 'recovered' for kind, _ in recovered)
    finally:
        run.client.close()
