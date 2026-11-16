"""Exercise the report narrative product entry point against isolated PostgreSQL."""
import base64
from datetime import datetime, timedelta, timezone
import io
import json

import pytest
from psycopg.types.json import Jsonb

from app.db.database import database_connection
from tests.api.test_research_findings import client, selected_cell
from tests.api.test_school_rule_suggestions import Fixture


@pytest.fixture(autouse=True)
def reader_policy(tmp_path, monkeypatch):
    path = tmp_path / 'reader-policy.json'
    path.write_text(json.dumps(dict(
        input_token_allowance=100000, task_limit_micro_usd=300000,
        policy=dict(model='gpt-6.1-sol', max_output_tokens=22000,
                    price=dict(version='fixture', model='gpt-6.1-sol', input_micro_usd_per_million=1_000_000,
                               cached_input_micro_usd_per_million=100_000, output_micro_usd_per_million=1_000_000)),
    )), encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_READER_REPORT_POLICY_FILE', str(path))


def report_request(client):
    base, source = selected_cell(client)
    finding = client.post(base + '/research-findings', json={'title': 'Fixed results', 'sources': [source]},
                          headers={'Idempotency-Key': 'reader-report-finding'})
    assert finding.status_code == 201, finding.text
    return base + '/research-report-narratives', dict(title='Research report', finding_version_id=finding.json()['id'],
                                                       language='en')


def test_preview_and_idempotent_admission_do_not_call_model(client):
    endpoint, report = report_request(client)
    preview = client.post(endpoint + '/preview', json=report)
    assert preview.status_code == 200, preview.text
    preview = preview.json()
    assert preview['figures'] == [] and 'facts' in preview
    assert preview['facts']['facts'][0]['value'] == 0
    request = dict(report=report, bundle_sha256=preview['bundle_sha256'], confirmed_external_processing=True)
    assert client.post(endpoint, json=request | {'confirmed_external_processing': 1},
                       headers={'Idempotency-Key': 'invalid-confirmation'}).status_code == 422
    assert client.post(endpoint, json=request | {'bundle_sha256': 'f'*64},
                       headers={'Idempotency-Key': 'stale-preview'}).status_code == 409
    created = client.post(endpoint, json=request, headers={'Idempotency-Key': 'prepare-report'})
    assert created.status_code == 202, created.text
    queued = created.json()
    assert queued['binding_sha256'] == preview['binding_sha256']
    assert queued['task']['status'] == 'queued'
    assert queued['result'] is None and queued['model_calls'] == []
    workspace = client.get('/api/v1/tasks/' + queued['task']['id'] + '/workspace')
    assert workspace.status_code == 200, workspace.text
    assert 'bio_reader_report_context_id' not in workspace.json()['artifacts']
    reused = client.post(endpoint, json=request, headers={'Idempotency-Key': 'prepare-report-alias'})
    assert reused.status_code == 200 and reused.json()['id'] == queued['id']
    assert client.get(endpoint + '/requests/prepare-report-alias').json()['id'] == queued['id']
    assert client.get(endpoint + '/' + queued['id']).json() == queued
    assert client.post(endpoint, json=request | {'report': report | {'title': 'Another report'}},
                       headers={'Idempotency-Key': 'prepare-report-alias'}).status_code == 409
    with database_connection() as db:
        calls = db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s', (queued['task']['id'],)).fetchone()
        budgets = db.execute('SELECT scope_type FROM model_budgets WHERE user_id=(SELECT user_id FROM tasks WHERE id=%s)',
                             (queued['task']['id'],)).fetchall()
    assert calls['n'] == 0
    assert [budget['scope_type'] for budget in budgets] == ['task']


def queue_narrative(client, endpoint, report):
    preview = client.post(endpoint + '/preview', json=report)
    assert preview.status_code == 200, preview.text
    request = dict(report=report, bundle_sha256=preview.json()['bundle_sha256'], confirmed_external_processing=True)
    response = client.post(endpoint, json=request, headers={'Idempotency-Key': 'narrative'})
    assert response.status_code == 202, response.text
    return request, response.json()


def test_immutable_disabled_admin_configuration_blocks_new_task(client, monkeypatch):
    from app.domain.reader_reports import service

    endpoint, report = report_request(client)
    original = service.resolve
    monkeypatch.setattr(service, 'resolve', lambda db: {'bundle': {'models': {'real_calls_enabled': False}}})
    preview = client.post(endpoint + '/preview', json=report).json()
    assert preview['real_calls_enabled'] is False
    request = dict(report=report, bundle_sha256=preview['bundle_sha256'], confirmed_external_processing=True)
    headers = {'Idempotency-Key': 'requires-enabled-configuration'}
    rejected = client.post(endpoint, json=request, headers=headers)
    assert rejected.status_code == 409, rejected.text
    with database_connection() as db:
        assert not db.execute("SELECT 1 FROM tasks WHERE task_type='reader_report_narrative'").fetchone()
        assert not db.execute('SELECT 1 FROM model_calls').fetchone()
    monkeypatch.setattr(service, 'resolve', original)
    assert client.post(endpoint, json=request, headers=headers).status_code == 202


def worker(queued, provider):
    from app.domain.reader_reports.execution import run_reader_report_task

    return run_reader_report_task(queued['task']['id'], queued['task']['revision'], provider=provider)


def authorize_user_and_project(queued, *, limit=1_000_000):
    from app.domain.model_usage.service import ModelUsageService

    task = queued['task']
    with database_connection() as db:
        user_id = db.execute('SELECT user_id FROM tasks WHERE id=%s', (task['id'],)).fetchone()['user_id']
    service = ModelUsageService(user_id)
    service.set_budget('user', user_id, limit, 0)
    service.set_budget('project', task['project_id'], limit, 0)
    return user_id


def narrative_fixture():
    from app.adapters.bio_reader_narrative import NARRATIVE_FIELDS

    return dict(narrative={key: 'The saved values support an exploratory description of this result.'
                           for key in NARRATIVE_FIELDS}, figures=[])


def test_budget_wait_retries_original_and_success_is_reusable(client):
    endpoint, report = report_request(client)
    request, queued = queue_narrative(client, endpoint, report)
    provider = Fixture(narrative_fixture())
    task = worker(queued, provider)
    assert task['status'] == 'waiting_confirmation' and task['error_code'] == 'model_budget_missing'
    assert provider.posts == []

    path = endpoint + '/' + queued['id']
    waiting = client.get(path).json()
    assert waiting['allowed_actions'] == ['resume'] and waiting['wait']['kind'] == 'budget_confirmation'
    user_id = authorize_user_and_project(queued)
    retry = client.post(path + '/retry', json={'expected_revision': task['revision']})
    assert retry.status_code == 202, retry.text
    done = worker(retry.json(), provider)
    assert done['status'] == 'succeeded', done
    assert len(provider.posts) == 1

    saved = client.get(path).json()
    assert saved['artifact_sha256'] and saved['result']['figures'] == []
    assert saved['model_calls'][0]['provider_provenance'] == 'synthetic_fixture'
    assert client.post(endpoint + '/preview', json=report).json()['cached'] is True
    assert client.post(endpoint + '/preview', json=report).json()['reserved_micro_usd'] == 0
    assert client.get('/api/v1/tasks/' + done['id'] + '/workspace').status_code == 200
    for usage_path in (endpoint.rsplit('/', 1)[0], '/api/v1/tasks/' + done['id']):
        usage = client.get(usage_path + '/model-usage')
        assert usage.status_code == 200, usage.text
        call, = usage.json()['items']
        assert call['task_type'] == 'reader_report_narrative'
        assert call['provider_provenance'] == 'synthetic_fixture'
        assert call['estimated_cost_micro_usd'] == 40
    replay = client.post(endpoint, json=request, headers={'Idempotency-Key': 'second-success-key'})
    assert replay.status_code == 200 and replay.json() == saved
    assert len(provider.posts) == 1

    from app.core.exceptions import StorageError
    from app.domain.reader_reports.service import ReaderReportService
    from app.domain.report_collections.service import scoped_store
    from app.domain.research_results.contracts import ResearchReportRequest
    service = ReaderReportService(scoped_store(user_id))
    with service.store.connection() as db:
        base, _, _ = service._base(db, task['project_id'], ResearchReportRequest.model_validate(report))
        record = service.record_for(db, task['project_id'], queued['id'], base)
        with pytest.raises(StorageError):
            service.record_for(db, task['project_id'], queued['id'], base | {'title': 'Changed after admission'})
    assert record['provenance']['artifact_sha256'] == saved['artifact_sha256']


def test_unknown_submission_cannot_create_another_billable_attempt(client):
    endpoint, report = report_request(client)
    request, queued = queue_narrative(client, endpoint, report)
    authorize_user_and_project(queued)
    provider = Fixture(narrative_fixture(), unknown=True)
    task = worker(queued, provider)
    assert task['status'] == 'waiting_confirmation' and task['reason_code'] == 'submission_unknown'
    path = endpoint + '/' + queued['id']
    assert client.get(path).json()['allowed_actions'] == []
    assert client.post(path + '/retry', json={'expected_revision': task['revision']}).status_code == 409
    replay = client.post(endpoint, json=request, headers={'Idempotency-Key': 'new-key-same-material'})
    assert replay.status_code == 200 and replay.json()['id'] == queued['id']
    assert len(provider.posts) == 1


def test_paid_call_remains_the_reusable_candidate_after_get_retries_are_exhausted(client):
    from app.adapters.models.openai_responses import ModelProviderError

    endpoint, report = report_request(client)
    request, queued = queue_narrative(client, endpoint, report)
    authorize_user_and_project(queued)

    class TemporarilyUnavailable(Fixture):
        def retrieve(self, response_id, **options):
            if self.pending:
                raise ModelProviderError('model_provider_request_failed', status_code=503)
            return super().retrieve(response_id, **options)

    provider = TemporarilyUnavailable(narrative_fixture())
    provider.pending = True
    task = worker(queued, provider)
    for _ in range(4):
        task = worker({'task': task}, provider)
    assert task['status'] == 'failed' and task['error_code'] == 'model_provider_unavailable'
    replay = client.post(endpoint, json=request, headers={'Idempotency-Key': 'same-paid-call-after-failure'})
    assert replay.status_code == 200 and replay.json()['id'] == queued['id']
    path = endpoint + '/' + queued['id']
    resumed = client.post(path + '/retry', json={'expected_revision': task['revision']})
    assert resumed.status_code == 202, resumed.text
    provider.pending = False
    assert worker(resumed.json(), provider)['status'] == 'succeeded'
    assert len(provider.posts) == 1 and provider.gets == [provider.response_id]


@pytest.mark.parametrize('provider_status', ['completed', 'incomplete'])
def test_report_page_continues_expired_observation_with_one_get(client, provider_status):
    endpoint, report = report_request(client)
    _, queued = queue_narrative(client, endpoint, report)
    authorize_user_and_project(queued)

    class DelayedResponse(Fixture):
        def retrieve(self, response_id, **options):
            receipt = super().retrieve(response_id, **options)
            if provider_status == 'incomplete':
                receipt.update(status='incomplete', response={'status': 'incomplete', 'output': []})
            return receipt

    provider = DelayedResponse(narrative_fixture())
    provider.pending = True
    deferred = worker(queued, provider)
    assert deferred['status'] == 'running'
    started = datetime.now(timezone.utc) - timedelta(minutes=21)
    deadline = started + timedelta(minutes=20)
    with database_connection(write=True) as db:
        db.execute("""UPDATE model_calls SET provider_state=jsonb_set(provider_state, '{observation}', %s)
            WHERE task_id=%s""", (Jsonb(dict(version=1, started_at=started.isoformat(),
                deadline_at=deadline.isoformat(), continuations=0)), deferred['id']))
    waiting = worker({'task': deferred}, provider)
    assert waiting['reason_code'] == 'observation_expired'
    assert provider.gets == []

    path = endpoint + '/' + queued['id']
    wait = client.get(path).json()['wait']
    assert wait['kind'] == 'remote_observation'
    request = {'expected_revision': waiting['revision']}
    resumed = client.post(path + '/retry', json=request)
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()['task']['id'] == waiting['id']
    assert client.post(path + '/retry', json=request).status_code == 409

    provider.pending = False
    done = worker(resumed.json(), provider)
    assert provider.gets == [provider.response_id]
    assert len(provider.posts) == 1
    assert done['status'] == ('succeeded' if provider_status == 'completed' else 'failed'), done
    saved = client.get(path).json()
    assert saved['wait'] is None
    assert saved['can_regenerate'] is (provider_status == 'incomplete')
    with database_connection() as db:
        resume = db.execute('SELECT * FROM task_resume_requests WHERE task_id=%s', (waiting['id'],)).fetchall()
        assert len(resume) == 1 and resume[0]['wait_id'] == wait['id'] and resume[0]['operation'] == 'resume'
        call, = db.execute('SELECT * FROM model_calls WHERE task_id=%s', (waiting['id'],)).fetchall()
        observation = call['provider_state']['observation']
        assert observation['deadline_at'] == deadline.isoformat()
        assert observation['retrieval_grant']['consumed_at'] is not None


def exhaust_reader_worker_recovery(client, path, task, start_attempt):
    from app.adapters.task_execution_store import AUTO_ATTEMPTS, TaskExecutionStore

    repository = TaskExecutionStore()
    for _ in range(AUTO_ATTEMPTS):
        start_attempt(task)
        with database_connection(write=True) as db:
            updated = db.execute("""UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second'
                WHERE task_id=%s AND status='running'""", (task['id'],))
            assert updated.rowcount == 1
        assert repository.recover_expired() == 1
        task = client.get(path).json()['task']
    assert task['status'] == 'failed' and task['error_code'] == 'task_worker_interrupted', task
    return task


def test_unsubmitted_original_cannot_retry_over_a_replacement(client):
    from app.adapters.task_execution_store import TaskExecutionStore

    endpoint, report = report_request(client)
    request, queued = queue_narrative(client, endpoint, report)
    authorize_user_and_project(queued)
    repository = TaskExecutionStore()

    def claim_without_submitting(task):
        assert repository.claim(task['id'], task['revision'], task_type='reader_report_narrative') is not None

    path = endpoint + '/' + queued['id']
    task = exhaust_reader_worker_recovery(client, path, queued['task'], claim_without_submitting)
    replacement = client.post(endpoint, json=request, headers={'Idempotency-Key': 'same-report-after-interruption'})
    assert replacement.status_code == 202 and replacement.json()['id'] != queued['id']
    retry = client.post(path + '/retry', json={'expected_revision': task['revision']})
    assert retry.status_code == 409, retry.text
    provider = Fixture(narrative_fixture())
    assert worker(replacement.json(), provider)['status'] == 'succeeded'
    retry_from_tasks = client.post('/api/v1/tasks/' + task['id'] + '/resume', json={
        'operation': 'retry', 'expected_task_revision': task['revision'], 'input_version': task['input_version'], 'wait_id': None,
    }, headers={'Idempotency-Key': 'superseded-reader-task'})
    assert retry_from_tasks.status_code == 409, retry_from_tasks.text
    assert client.get(path).json()['task'] == task
    assert client.get(path).json()['model_calls'] == []
    assert len(provider.posts) == 1


@pytest.mark.parametrize('legacy_replacement', [False, True], ids=['new-request', 'existing-budget-wait'])
def test_replay_reuses_failed_unsubmitted_task_with_held_budget(client, monkeypatch, legacy_replacement):
    from app.adapters.task_execution_store import LeaseLost
    from app.domain.model_usage.service import ModelUsageService
    from app.domain.reader_reports.service import ReaderReportService

    endpoint, report = report_request(client)
    request, queued = queue_narrative(client, endpoint, report)
    limit = client.post(endpoint + '/preview', json=report).json()['reserved_micro_usd']
    authorize_user_and_project(queued, limit=limit)
    provider = Fixture(narrative_fixture())

    def stop_before_post(*args, **kwargs):
        raise LeaseLost()

    def claim_and_reserve(task):
        assert worker({'task': task}, provider) is None

    path = endpoint + '/' + queued['id']
    with monkeypatch.context() as interrupted:
        interrupted.setattr(ModelUsageService, 'begin_submission', stop_before_post)
        task = exhaust_reader_worker_recovery(client, path, queued['task'], claim_and_reserve)
    assert provider.posts == []
    reserved, = client.get(path).json()['model_calls']
    assert reserved['status'] == 'reserved'

    headers = {'Idempotency-Key': 'confirmed-after-reservation'}
    if legacy_replacement:
        original_reusable = ReaderReportService._reusable

        def original_admission(service, *args, **kwargs):
            return original_reusable(service, *args, **{**kwargs, 'reuse_reservation': False})

        with monkeypatch.context() as legacy:
            legacy.setattr(ReaderReportService, '_reusable', original_admission)
            replay = client.post(endpoint, json=request, headers=headers)
        assert replay.status_code == 202, replay.text
        replacement = worker(replay.json(), provider)
        assert replacement['status'] == 'waiting_confirmation' and replacement['reason_code'] == 'budget_exceeded'
        replacement_path = endpoint + '/' + replay.json()['id']
        assert client.get(replacement_path).json()['model_calls'] == []
    else:
        replay = client.post(endpoint, json=request, headers=headers)
        assert replay.status_code == 200 and replay.json()['id'] == queued['id'], replay.text

    retry = client.post(path + '/retry', json={'expected_revision': task['revision']})
    assert retry.status_code == 202, retry.text
    if legacy_replacement:
        redirected = client.post(replacement_path + '/retry', json={'expected_revision': replacement['revision']})
        assert redirected.status_code == 409, redirected.text
    assert worker(retry.json(), provider)['status'] == 'succeeded'
    saved, = client.get(path).json()['model_calls']
    assert saved['id'] == reserved['id'] and len(provider.posts) == 1


def test_invalid_model_output_does_not_become_a_report_record(client):
    endpoint, report = report_request(client)
    request, queued = queue_narrative(client, endpoint, report)
    authorize_user_and_project(queued)
    provider = Fixture({'narrative': {'abstract': 'Incomplete response'}, 'figures': []})
    task = worker(queued, provider)
    assert task['status'] == 'failed' and task['error_code'] == 'model_response_invalid'
    assert len(provider.posts) == 1
    value = client.get(endpoint + '/' + queued['id']).json()
    assert value['result'] is None and value['artifact_sha256'] is None and value['allowed_actions'] == []
    assert value['can_regenerate'] is True
    with database_connection() as db:
        row = db.execute('SELECT raw_output_json,result_json FROM reader_report_narratives WHERE id=%s',
                         (queued['id'],)).fetchone()
    assert row['raw_output_json'] == provider.draft
    assert row['result_json'] == {'validation_status': 'invalid'}
    fresh = client.post(endpoint, json=request, headers={'Idempotency-Key': 'confirmed-regeneration'})
    assert fresh.status_code == 202 and fresh.json()['id'] != queued['id']


def test_ordered_fixed_figures_are_sent_once_and_remote_response_is_retrieved(client, tmp_path):
    from PIL import Image
    from app.adapters.research_figure_render import render_figure
    from app.domain.research_results.execution import run_research_figure_task
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from tests.api.test_file_batches import register
    from tests.helpers.ocr_samples import ocr_result

    endpoint, report = report_request(client)
    project_path = endpoint.rsplit('/', 1)[0]
    project_id = project_path.rsplit('/', 1)[-1]
    figures = []
    for index, color in enumerate(('red', 'blue'), 1):
        stream = io.BytesIO()
        Image.new('RGB', (80, 40), color).save(stream, 'PNG')
        base, batch, item, raw = register(client, {'id': project_id}, content=stream.getvalue(),
                                          filename=f'report-{index}.png', key=f'reader-figure-source-{index}')
        stored = client.post(base + '/' + batch['id'] + '/items/' + item['client_id'],
                             files={'file': (item['filename'], raw)})
        assert stored.status_code == 202, stored.text
        parse = stored.json()['task']
        assert run_parse_file_task(parse['id'], parse['revision'], parser=ocr_result)['status'] == 'succeeded'
        created = client.post(project_path + '/research-figures',
                              json=dict(mode='reuse', title=f'Observation panel {index}', formats=['png'],
                                        panels=[dict(source=dict(source_kind='original_file', source_id=stored.json()['file_id']))]),
                              headers={'Idempotency-Key': f'reader-figure-{index}'})
        assert created.status_code == 201, created.text
        created = created.json()
        rendered = run_research_figure_task(created['task_id'], created['task']['revision'], engine=render_figure,
                                            staging_directory=tmp_path/'staging')
        assert rendered and rendered['status'] == 'succeeded', rendered
        saved = client.get(project_path + '/research-figures/' + created['id']).json()
        member = next(member for member in saved['members'] if member['role'] == 'figure' and member['format'] == 'png')
        figures.append((created['id'], client.get(member['download_url']).content))

    selected = [figures[1][0], figures[0][0]]
    report['figure_version_ids'] = selected
    expected = client.post(endpoint + '/preview', json=report).json()
    reversed_preview = client.post(endpoint + '/preview', json=report | {'figure_version_ids': selected[::-1]}).json()
    assert reversed_preview['bundle_sha256'] != expected['bundle_sha256']
    assert reversed_preview['binding_sha256'] != expected['binding_sha256']
    assert [(item['number'], item['title']) for item in expected['figures']] == [(1, 'Observation panel 2'), (2, 'Observation panel 1')]

    _, queued = queue_narrative(client, endpoint, report)
    authorize_user_and_project(queued)
    draft = narrative_fixture()
    draft['figures'] = [dict(number=index, title=item['title'], reading='Read the selected panel for its saved observation.',
                            observations='The panel contains a single colored region in the synthetic fixture.',
                            interpretation='It provides a visual check of the selected figure before export.',
                            limitations='The panel cannot establish an independent sample count.')
                        for index, item in enumerate(expected['figures'], 1)]
    provider = Fixture(draft)
    provider.pending = True
    deferred = worker(queued, provider)
    assert deferred and deferred['status'] == 'running', deferred
    with database_connection() as db:
        row = db.execute('SELECT input_snapshot FROM reader_report_narratives WHERE id=%s', (queued['id'],)).fetchone()
    assert 'data:image' not in json.dumps(row['input_snapshot'])
    assert len(provider.posts) == 1
    wire_figures = provider.posts[0]['payload']['figures']
    assert [base64.b64decode(item['image_url'].split(',', 1)[1]) for item in wire_figures] == [figures[1][1], figures[0][1]]
    provider.pending = False
    assert worker({'task': deferred}, provider)['status'] == 'succeeded'
    assert len(provider.posts) == 1 and provider.gets == [provider.response_id]


def test_account_erasure_includes_sealed_narrative_and_receipts(client):
    from app.auth import service as auth
    from app.domain.account_deletion import delete_account
    from tests.api.test_admin_operations import PASSWORD
    from tests.api.test_projects import create_project

    endpoint, report = report_request(client)
    _, queued = queue_narrative(client, endpoint, report)
    owner = authorize_user_and_project(queued)
    assert worker(queued, Fixture(narrative_fixture()))['status'] == 'succeeded'

    # A narrative cannot be fetched under another project belonging to the same owner.
    other_project = create_project(client)['id']
    other_path = f"/api/v1/projects/{other_project}/research-report-narratives/{queued['id']}"
    assert client.get(other_path).status_code == 404
    with pytest.raises(Exception, match='Saved reader report narrative is immutable'):
        with database_connection(write=True) as db:
            db.execute('UPDATE reader_report_narratives SET result_json=result_json WHERE id=%s', (queued['id'],))

    admin = auth.create_user('admin@reader-erase.test', PASSWORD, 'admin')
    assert delete_account(admin['id'], owner, 1) == {'id': owner, 'deleted': True}
    with database_connection() as db:
        for table in ('reader_report_narratives', 'reader_report_narrative_requests', 'model_calls', 'model_budgets', 'tasks'):
            assert not db.execute(f'SELECT 1 FROM {table} WHERE user_id=%s', (owner,)).fetchone()
        assert db.execute('SELECT id FROM users WHERE id=%s', (admin['id'],)).fetchone()
