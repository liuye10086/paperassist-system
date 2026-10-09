"""Historical projections use original jobs without creating execution history."""
import base64
import json

import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud, prepared, seed_legacy, generate  # noqa: F401
from tests.integration.test_explanations import writer, ready, seed_legacy as seed_explanation, recover  # noqa: F401
from tests.api.test_task_workspace import counts


def identity(job, kind='plot'):
    return 'legacy-' + kind + ':' + base64.urlsafe_b64encode(job['id'].encode()).decode().rstrip('=')


def originals():
    with database_connection() as db:
        return {table: [dict(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY id').fetchall()]
                for table in ('figure_jobs', 'explanation_jobs', 'figures', 'explanations', 'reports')}


def change_job(job, table='figure_jobs', **changes):
    updated = {**job, **changes}
    with database_connection(write=True) as db:
        db.execute('UPDATE ' + table + ' SET job_json=%s WHERE id=%s', (json.dumps(updated), job['id']))
    return updated


def test_mixed_list_readonly_and_safe_legacy_details(client, cloud, monkeypatch):
    from tests.api.test_task_workspace import create_task
    project, request, base, result, service, unified = create_task(client)
    url = base + '/analysis-runs/' + result['id'] + '/boxplot'
    job = seed_legacy(client, url, status='failed')
    job = change_job(job, message_code='private-error-marker', message='private-message-marker')
    legacy_id = identity(job)
    before, ledger = originals(), counts()
    from app.adapters.storage import ProjectStore
    monkeypatch.setattr(ProjectStore, 'figure_job', lambda *a: pytest.fail('latest job read'))
    page = client.get(f'/api/v1/projects/{project}/tasks').json()
    assert page['total'] == 2
    item = next(item for item in page['items'] if item['task']['id'] == legacy_id)
    task = item['task']
    assert task['origin'] == 'legacy' and task['status'] == 'failed'
    assert task['error_code'] == 'internal_error'
    assert all(task[field] is None for field in ('revision', 'current_attempt', 'retry_count', 'updated_at'))
    assert task['input_version'] == {'setup_revision': result['setup_revision'], 'output_language': 'zh-CN'}
    assert client.get('/api/v1/tasks/' + legacy_id).json() == task
    workspace = client.get('/api/v1/tasks/' + legacy_id + '/workspace').json()
    assert workspace['wait'] is None and workspace['allowed_actions'] == []
    assert workspace['artifacts'] == {'figure': None, 'explanation': None, 'report': None}
    events = client.get('/api/v1/tasks/' + legacy_id + '/events?after=9').json()
    assert events == {'task_id': legacy_id, 'items': [], 'next_cursor': 9, 'has_more': False}
    filtered = client.get(f'/api/v1/projects/{project}/tasks?status=failed&page_size=1').json()
    assert filtered['total'] == 1 and filtered['items'][0]['task']['id'] == legacy_id
    assert client.get(f'/api/v1/projects/{project}/tasks?page=2&page_size=1').json()['items'][0]['task']['id'] == unified['id']
    for suffix, body in [('retry', {'expected_revision': 1}), ('resume', {
        'operation': 'retry', 'wait_id': None, 'expected_task_revision': 1,
        'input_version': {'setup_revision': 1, 'output_language': 'zh-CN'}})]:
        response = client.post('/api/v1/tasks/' + legacy_id + '/' + suffix, json=body,
                               headers={'Idempotency-Key': 'legacy-rejected'})
        assert response.status_code == 409 and response.json()['detail']['code'] == 'task_transition_invalid'
    assert originals() == before and counts() == ledger and cloud.calls == []
    assert 'private-' not in json.dumps(workspace)


def test_original_job_retrieval_updates_stable_projection_without_submit(client, cloud):
    _, _, _, url = prepared(client)
    job = seed_legacy(client, url)
    endpoint = '/api/v1/tasks/' + identity(job) + '/workspace'
    assert client.get(endpoint).json()['task']['status'] == 'running'
    figure = generate(client, url)
    first = client.get(endpoint)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data['task']['status'] == 'succeeded' and data['task']['result_figure_id'] == figure['id']
    assert data['artifacts']['figure'] and data['artifacts']['report'] is None
    png = client.get(data['artifacts']['figure']['download_url']).content
    before, ledger = originals(), counts()
    assert client.get(endpoint).json() == data
    assert client.get(data['artifacts']['figure']['download_url']).content == png
    assert originals() == before and counts() == ledger and cloud.calls == []


@pytest.mark.parametrize('conflict', ['response_id', 'container_id', 'source_sha256', 'setup_revision', 'engine'])
def test_plot_never_claims_conflicting_saved_artifact(client, cloud, conflict):
    _, _, _, url = prepared(client)
    job = seed_legacy(client, url)
    figure = generate(client, url)
    with database_connection(write=True) as db:
        if conflict in ('response_id', 'container_id'):
            figure['provenance'][conflict] = 'another-job'
        elif conflict == 'setup_revision':
            figure[conflict] += 1
        elif conflict == 'engine':
            figure['engine']['id'] = 'another-engine'
        else:
            figure[conflict] = 'another-source'
        db.execute('UPDATE figures SET figure_json=%s WHERE id=%s', (json.dumps(figure), figure['id']))
    response = client.get('/api/v1/tasks/' + identity(job) + '/workspace')
    assert response.status_code == 200, response.text
    assert response.json()['task']['result_figure_id'] is None
    assert response.json()['artifacts']['figure'] is None


def test_same_source_failed_job_does_not_claim_later_success(client, cloud):
    _, _, result, url = prepared(client)
    first = seed_legacy(client, url, status='failed', response_id='resp_first')
    second = seed_legacy(client, url)
    figure = generate(client, url)
    assert client.get('/api/v1/tasks/' + identity(first)).json()['result_figure_id'] is None
    assert client.get('/api/v1/tasks/' + identity(second)).json()['result_figure_id'] == figure['id']
    # Existing scanner may mark a different response completed; attribution
    # must still be independent of that historical status reconciliation.
    change_job(first, status='completed')
    assert client.get('/api/v1/tasks/' + identity(first)).json()['result_figure_id'] is None


def test_explanation_exact_result_and_input_digest(client, cloud, writer):
    _, _, _, figure, url = ready(client)
    job = seed_explanation(client, url, figure)
    endpoint = '/api/v1/tasks/' + identity(job, 'explanation') + '/workspace'
    assert client.get(endpoint).json()['task']['status'] == 'running'
    recover()
    data = client.get(endpoint).json()
    assert data['task']['result_explanation_id'] and data['artifacts']['explanation']['sections']
    assert data['artifacts']['figure'] is None and data['artifacts']['report'] is None
    with database_connection(write=True) as db:
        row = db.execute('SELECT * FROM explanations').fetchone()
        saved = json.loads(row['explanation_json'])
        saved['provenance']['input_sha256'] = 'bad-digest'
        db.execute('UPDATE explanations SET explanation_json=%s WHERE id=%s', (json.dumps(saved), row['id']))
    assert client.get(endpoint).json()['artifacts']['explanation'] is None
    assert writer.calls == [] and cloud.calls == []


def test_legacy_ownership_and_noncanonical_identifiers(client, cloud):
    from tests.integration.test_project_ownership import account_client
    _, _, _, url = prepared(client)
    job = seed_legacy(client, url)
    endpoint = '/api/v1/tasks/' + identity(job)
    for role in ('user', 'admin'):
        stranger, _ = account_client('legacy-' + role + '@example.test', role)
        try:
            for suffix in ('', '/events', '/workspace'):
                assert stranger.get(endpoint + suffix).status_code == 404
            assert stranger.post(endpoint + '/retry', json={'expected_revision': 1}).status_code == 404
        finally:
            stranger.close()
    for bad in ('legacy-plot:', identity(job) + '=', 'legacy-plot:_w', 'legacy-plot:YQ+', 'legacy-explanation:eA'):
        assert client.get('/api/v1/tasks/' + bad).status_code == 404
    from tests.helpers.tasks import task_owner
    owner = task_owner(client)
    with database_connection(write=True) as db:
        db.execute('UPDATE users SET active=FALSE WHERE id=%s', (owner,))
    assert client.get(endpoint).status_code == 401


def test_unicode_long_identity_and_unknown_state(client, cloud):
    _, _, _, url = prepared(client)
    job = seed_legacy(client, url)
    long_id = '历史/任务?编号-' + '长' * 180
    changed = {**job, 'id': long_id, 'status': 'unknown', 'message': 'private-marker'}
    with database_connection(write=True) as db:
        db.execute('UPDATE figure_jobs SET id=%s,job_json=%s WHERE id=%s', (long_id, json.dumps(changed), job['id']))
    endpoint = '/api/v1/tasks/' + identity(changed)
    response = client.get(endpoint)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'failed' and response.json()['error_code'] == 'internal_error'
    project = url.split('/')[4]
    page = client.get(f'/api/v1/projects/{project}/tasks').json()
    assert page['items'][0]['task']['id'] == identity(changed)


def test_unified_metadata_contract_remains_nonnull(client):
    from tests.api.test_task_workspace import create_task
    from app.domain.tasks.contracts import TaskView
    from pydantic import ValidationError
    *_, task = create_task(client)
    assert TaskView.model_validate({key: value for key, value in task.items() if key != 'origin'}).origin == 'unified'
    for field in ('revision', 'current_attempt', 'retry_count', 'updated_at'):
        with pytest.raises(ValidationError):
            TaskView.model_validate({**task, field: None})


@pytest.mark.parametrize('state,status,reason', [
    ('submitting', 'running', None), ('running', 'running', None),
    ('uncertain', 'waiting_confirmation', 'submission_unknown'), ('failed', 'failed', 'execution_failed')])
def test_all_original_pending_states_remain_observational(client, cloud, state, status, reason):
    _, _, _, url = prepared(client)
    job = seed_legacy(client, url, status=state, response_id=None)
    before, ledger = originals(), counts()
    response = client.get('/api/v1/tasks/' + identity(job)).json()
    assert response['status'] == status and response['reason_code'] == reason
    assert originals() == before and counts() == ledger and cloud.calls == []


@pytest.mark.parametrize('conflict', ['response', 'payload', 'run', 'figure_hash', 'source', 'version', 'engine'])
def test_explanation_conflicts_never_claim_same_source_artifact(client, cloud, writer, conflict):
    _, _, _, figure, url = ready(client)
    job = seed_explanation(client, url, figure)
    recover()
    with database_connection(write=True) as db:
        row = db.execute('SELECT * FROM explanations').fetchone()
        saved = json.loads(row['explanation_json'])
        if conflict == 'response':
            saved['provenance']['response_id'] = 'other-job'
        elif conflict == 'payload':
            changed = {**job, 'status': 'completed', 'payload': {**job['payload'], 'language': 'en'}}
            db.execute('UPDATE explanation_jobs SET job_json=%s WHERE id=%s', (json.dumps(changed), job['id']))
        elif conflict == 'run':
            saved['analysis_run_id'] = 'another-run'
        elif conflict == 'figure_hash':
            saved['figure_sha256'] = 'b' * 64
        elif conflict == 'source':
            saved['source_sha256'] = 'b' * 64
        elif conflict == 'version':
            saved['setup_revision'] += 1
        else:
            saved['engine']['id'] = 'another-engine'
        db.execute('UPDATE explanations SET explanation_json=%s WHERE id=%s', (json.dumps(saved), saved['id']))
    response = client.get('/api/v1/tasks/' + identity(job, 'explanation') + '/workspace')
    assert response.status_code == 200, response.text
    assert response.json()['task']['result_explanation_id'] is None
    assert response.json()['artifacts']['explanation'] is None


def test_explanation_cross_run_table_reference_is_hidden(client, cloud, writer):
    _, _, result, figure, url = ready(client)
    job = seed_explanation(client, url, figure)
    _, _, other, _ = prepared(client)
    with database_connection(write=True) as db:
        db.execute('UPDATE explanation_jobs SET analysis_run_id=%s WHERE id=%s', (other['id'], job['id']))
    assert client.get('/api/v1/tasks/' + identity(job, 'explanation')).status_code == 404
    project = url.split('/')[4]
    assert client.get(f'/api/v1/projects/{project}/tasks?task_type=explanation').json()['total'] == 0


def test_mapped_jobs_do_not_claim_word_or_fabricate_costs(client, cloud, writer):
    from tests.integration.test_reports import report_ready, export
    _, _, _, figure, explanation, url = report_ready(client)
    response = export(client, url, figure, explanation)
    assert response.status_code == 200, response.text
    report = response.json()['report']
    word_url = url + '/' + report['id'] + '/download'
    word_bytes = client.get(word_url).content
    project = url.split('/')[4]
    before, ledger = originals(), counts()
    items = client.get(f'/api/v1/projects/{project}/tasks').json()['items']
    history = [item for item in items if item['task']['origin'] == 'legacy']
    assert len(history) == 2
    for item in history:
        endpoint = '/api/v1/tasks/' + item['task']['id']
        workspace = client.get(endpoint + '/workspace').json()
        assert workspace['artifacts']['report'] is None
        assert workspace['task']['result_report_id'] is None
        assert client.get(endpoint + '/model-usage').status_code == 404
    usage = client.get(f'/api/v1/projects/{project}/model-usage').json()
    assert usage['enforcement_scope'] == 'unified_only'
    assert usage['total'] == 0
    assert client.get(word_url).content == word_bytes
    assert originals() == before and counts() == ledger and cloud.calls == [] and writer.calls == []


def test_failed_first_explanation_never_claims_later_success(client, cloud, writer):
    _, _, _, figure, url = ready(client)
    first = seed_explanation(client, url, figure, status='failed', response_id='first-response')
    from app.adapters.explanation_store import ExplanationStore
    from app.adapters.storage import get_project_store
    from app.domain.explanation_content import build_payload
    store = get_project_store()
    result = store.analysis_result_by_id(url.split('/')[4], url.split('/')[6], url.split('/')[8])
    repository = ExplanationStore(store)
    second, _ = repository.begin(result, figure, build_payload(result, figure), 'test-model', True)
    second = repository.update_job(second['id'], status='running', response_id='second-response')
    recover()
    assert client.get('/api/v1/tasks/' + identity(first, 'explanation')).json()['result_explanation_id'] is None
    assert client.get('/api/v1/tasks/' + identity(second, 'explanation')).json()['result_explanation_id']
    change_job(first, table='explanation_jobs', status='completed')
    assert client.get('/api/v1/tasks/' + identity(first, 'explanation')).json()['result_explanation_id'] is None


def test_canonical_encoding_and_column_source_ignore_private_json_ids(client, cloud):
    _, _, result, url = prepared(client)
    job = seed_legacy(client, url)
    changed = {**job, 'id': 'a', 'project_id': 'private-project', 'file_id': 'private-file',
               'setup_revision': 99, 'updated_at': 'private-time', 'revision': 99}
    with database_connection(write=True) as db:
        db.execute('UPDATE figure_jobs SET id=%s,job_json=%s WHERE id=%s', ('a', json.dumps(changed), job['id']))
    response = client.get('/api/v1/tasks/legacy-plot:YQ')
    assert response.status_code == 200, response.text
    task = response.json()
    assert task['project_id'] == url.split('/')[4]
    assert task['input_version']['setup_revision'] == result['setup_revision']
    assert task['revision'] is None and task['updated_at'] is None
    assert 'private-' not in response.text
    # YR decodes to the same UTF-8 byte but has nonzero unused padding bits.
    assert client.get('/api/v1/tasks/legacy-plot:YR').status_code == 404
