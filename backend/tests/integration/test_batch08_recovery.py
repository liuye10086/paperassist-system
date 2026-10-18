"""Batch08 recovery evidence: isolated PostgreSQL, synthetic providers, real workers."""
from copy import deepcopy
import json

import pytest

from app.adapters.models.openai_responses import ModelProviderError
from app.adapters.task_execution_store import TaskExecutionStore
from app.adapters.task_store import TaskStore
from app.db.database import database_connection
from app.domain.figure_workbench.execution import run_figure_workbench_task, run_figure_explanation_task
from tests.api.test_analysis import client  # noqa: F401
from tests.integration.test_batch05_figure_execution import (
    queued_figure, IndependentLineProvider, FigureExplanationProvider,
)
from tests.integration.test_batch06_pipeline import IndependentV2LineProvider, checked_policy


class PendingExplanationProvider(FigureExplanationProvider):
    def __init__(self, *, pending=True):
        super().__init__()
        self.pending, self.gets, self.fail_create = pending, [], False

    def create(self, **kwargs):
        self.instructions = kwargs['instructions']
        self.saved = super().create(**kwargs)
        if self.fail_create:
            raise RuntimeError('synthetic submission interruption')
        return self.receipt()

    def receipt(self):
        receipt = deepcopy(self.saved)
        receipt['status'] = receipt['response']['status'] = 'in_progress' if self.pending else 'completed'
        return receipt

    def retrieve(self, response_id, *, policy):
        self.gets.append(response_id)
        return self.receipt()


def raw_task(task):
    with database_connection() as db:
        return dict(db.execute('SELECT * FROM tasks WHERE id=%s', (task['id'],)).fetchone())


def saved_call(task):
    with database_connection() as db:
        rows = db.execute('SELECT * FROM model_calls WHERE task_id=%s', (task['id'],)).fetchall()
        assert len(rows) == 1
        return dict(rows[0])


def configured_case(client, monkeypatch, version, kind='plot'):
    workbench, project, result, configuration, task = queued_figure(client, monkeypatch, contract_version=version)
    provider = (IndependentV2LineProvider if version == 2 else IndependentLineProvider)(result, pending=True)
    create_plot = provider.create_plot
    def capture_plot(**kwargs):
        provider.instructions = kwargs['instructions']
        return create_plot(**kwargs)
    monkeypatch.setattr(provider, 'create_plot', capture_plot)
    worker = run_figure_workbench_task
    if kind == 'explanation':
        from app.adapters.figure_workbench_store import read_bundle
        from app.domain.figure_workbench.contracts import GenerateFigure
        from app.domain.figure_workbench.explanations import build_payload
        from app.domain.figure_workbench.tasks import submit
        from app.domain.external_processing import digest
        provider.pending = False
        task = finish(task, provider, worker)
        bundle = read_bundle(workbench.assets, project, task['result_figure_id'])
        monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', checked_policy)
        request = GenerateFigure(idempotency_key='batch08-explanation', external_processing={
            'confirmed': True, 'payload_sha256': digest(build_payload(bundle))})
        task = submit(workbench, project, result['file_id'], result['id'], configuration,
            request, figure_id=bundle['figure']['id'])['task']
        provider, worker = PendingExplanationProvider(), run_figure_explanation_task
    return workbench, project, result, configuration, task, provider, worker


def step(task, provider, worker):
    result = worker(task['id'], task['revision'], provider_factory=lambda: provider)
    assert result is not None
    return result


def finish(task, provider, worker):
    for _ in range(5):
        task = step(task, provider, worker)
        if task['status'] in ('succeeded', 'failed', 'waiting_confirmation'):
            return task
    raise AssertionError(task)


def pending(task, provider, worker, kind):
    for _ in range(3 if kind == 'plot' else 1):
        task = step(task, provider, worker)
    assert task['status'] == 'running'
    assert saved_call(task)['provider_response_id']
    return task


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('kind', ['plot', 'explanation'])
def test_configured_changed_source_still_accounts_existing_response(client, monkeypatch, version, kind):
    _, _, _, configuration, task, provider, worker = configured_case(client, monkeypatch, version, kind)
    original = raw_task(task)['input_snapshot']
    task = pending(task, provider, worker, kind)
    call_before = saved_call(task)
    # Simulate an integrity failure in the persisted configuration, not a new user intent.
    with database_connection(write=True) as db:
        db.execute('UPDATE figure_config_versions SET sha256=%s WHERE id=%s', ('0' * 64, configuration))
    provider.pending = False
    task = step(task, provider, worker)
    assert provider.gets == [call_before['provider_response_id']]
    assert task['status'] == 'failed' and task['error_code'] == 'task_source_conflict'
    assert saved_call(task)['provider_status'] == 'completed'
    assert raw_task(task)['input_snapshot'] == original
    assert len(provider.posts) == (3 if kind == 'plot' else 1)
    assert task['result_figure_id' if kind == 'plot' else 'result_explanation_id'] is None


@pytest.mark.parametrize('kind', ['plot', 'explanation'])
@pytest.mark.parametrize('damage', ['prompt_version', 'tools', 'input_token_allowance'])
def test_configured_changed_policy_accounts_receipt_but_never_publishes(client, monkeypatch, kind, damage):
    from psycopg.types.json import Jsonb
    _, _, _, _, task, provider, worker = configured_case(client, monkeypatch, 2, kind)
    task = pending(task, provider, worker, kind)
    call_before = saved_call(task)
    snapshot = raw_task(task)['input_snapshot']
    key = 'boxplot_policy' if kind == 'plot' else 'explanation_policy'
    if damage == 'input_token_allowance':
        snapshot[key][damage] = 1
    elif damage == 'tools':
        snapshot[key]['policy'][damage] = [] if kind == 'plot' else ['code_interpreter']
    else:
        snapshot[key]['policy'][damage] = 'forged_prompt_contract'
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET input_snapshot=%s WHERE id=%s', (Jsonb(snapshot), task['id']))
    provider.pending = False
    done = step(task, provider, worker)
    assert provider.gets == [call_before['provider_response_id']]
    assert done['status'] == 'failed'
    assert done['error_code'] == (('plot_input_limit' if kind == 'plot' else 'explanation_input_limit')
        if damage == 'input_token_allowance' else 'task_source_conflict')
    call = saved_call(task)
    assert call['status'] == 'completed' and call['policy_snapshot'] == call_before['policy_snapshot']
    assert call['input_digest'] == call_before['input_digest']
    assert len(provider.posts) == (3 if kind == 'plot' else 1)
    assert done['result_figure_id' if kind == 'plot' else 'result_explanation_id'] is None


@pytest.mark.parametrize('code', ['model_provider_request_failed', 'plot_container_expired'])
def test_configured_download_failure_uses_bounded_read_recovery(client, monkeypatch, code):
    _, _, _, _, task, provider, worker = configured_case(client, monkeypatch, 2)
    task = pending(task, provider, worker, 'plot')
    provider.pending = False
    original_download = provider.download
    def interrupted(*args, **kwargs):
        raise ModelProviderError(code, status_code=404 if code == 'plot_container_expired' else 503)
    monkeypatch.setattr(provider, 'download', interrupted)
    task = step(task, provider, worker)
    assert saved_call(task)['provider_status'] == 'completed'
    assert len(provider.posts) == 3
    if code == 'plot_container_expired':
        assert task['status'] == 'failed' and task['error_code'] == code
    else:
        assert task['status'] == 'running'
        with database_connection() as db:
            attempt = db.execute('SELECT * FROM task_attempts WHERE task_id=%s', (task['id'],)).fetchone()
            assert attempt['lease_owner'] is None
        monkeypatch.setattr(provider, 'download', original_download)
        done = step(task, provider, worker)
        assert done['status'] == 'succeeded'
        assert provider.gets == [saved_call(task)['provider_response_id']] * 2
        assert len(provider.posts) == 3


@pytest.mark.parametrize('kind', ['plot', 'explanation'])
@pytest.mark.parametrize('body', [None, []])
def test_configured_invalid_recorded_body_fails_without_repost(client, monkeypatch, kind, body):
    _, _, _, _, task, provider, worker = configured_case(client, monkeypatch, 2, kind)
    task = pending(task, provider, worker, kind)
    provider.pending = False
    receipt = provider.receipt
    def malformed():
        value = receipt()
        value['response'] = body
        return value
    monkeypatch.setattr(provider, 'receipt', malformed)
    done = step(task, provider, worker)
    assert done['status'] == 'failed'
    assert done['error_code'] == ('model_response_invalid' if body is None else
        'plot_invalid_result' if kind == 'plot' else 'explanation_invalid_json')
    assert saved_call(task)['status'] == 'completed'
    assert len(provider.posts) == (3 if kind == 'plot' else 1)
    assert len(provider.gets) == 1


def test_configured_download_retry_exhaustion_and_explicit_retry_keep_same_call(client, monkeypatch):
    from app.domain.tasks.resume import TaskResumeService
    workbench, _, _, _, task, provider, worker = configured_case(client, monkeypatch, 2)
    task = pending(task, provider, worker, 'plot')
    provider.pending = False
    download = provider.download
    monkeypatch.setattr(provider, 'download', lambda *args, **kwargs: (_ for _ in ()).throw(
        ModelProviderError('model_provider_request_failed', status_code=503)))
    for retry, seconds in enumerate((10, 30, 90), 1):
        task = step(task, provider, worker)
        assert task['status'] == 'running' and raw_task(task)['retry_count'] == retry
        with database_connection() as db:
            event = db.execute('SELECT * FROM task_outbox WHERE task_id=%s ORDER BY task_revision DESC LIMIT 1',
                (task['id'],)).fetchone()
            assert (event['available_at'] - event['created_at']).total_seconds() >= seconds
    failed = step(task, provider, worker)
    assert failed['status'] == 'failed' and failed['error_code'] == 'model_provider_unavailable'
    call = saved_call(task)
    request = {'operation': 'retry', 'wait_id': None, 'expected_task_revision': failed['revision'],
        'input_version': failed['input_version']}
    recovery = TaskResumeService(workbench.tasks.user_id)
    queued = recovery.resume(task['id'], request, idempotency_key='retry-known-response')
    monkeypatch.setattr(provider, 'download', download)
    done = step(queued, provider, worker)
    assert done['status'] == 'succeeded'
    assert recovery.resume(task['id'], request, idempotency_key='retry-known-response') == queued
    current = saved_call(task)
    assert {k: v for k, v in current.items() if k != 'updated_at'} == {
        k: v for k, v in call.items() if k != 'updated_at'}
    assert current['updated_at'] >= call['updated_at']
    assert provider.posts == ['container', 'upload', 'response']
    assert provider.gets == [call['provider_response_id']] * 5
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM usage_events WHERE call_id=%s', (call['id'],)).fetchone()['n'] == 2
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests WHERE task_id=%s', (task['id'],)).fetchone()['n'] == 1


def assert_receipts(task, original_snapshot, *, explanation=False):
    """DB09: independently named persisted fields, not only public success status."""
    current = raw_task(task)
    call = saved_call(task)
    assert current['input_snapshot'] == original_snapshot
    assert call['task_id'] == task['id'] and call['attempt_no'] == 1
    assert call['input_digest'] and len(call['input_digest']) == 64
    policy = original_snapshot['explanation_policy' if explanation else 'boxplot_policy']['policy']
    assert call['model'] == policy['model']
    assert call['policy_snapshot']['prompt_version'] == policy['prompt_version']
    assert call['price_snapshot']['version'] == 'synthetic-only'
    assert call['provider_request_id'] == ('req_new_explanation' if explanation else 'req_response')
    assert call['provider_response_id'] == ('resp_new_figure_explanation' if explanation else 'resp_plot_synthetic')
    assert call['status'] == call['provider_status'] == 'completed'
    assert call['estimated_cost_micro_usd'] == 1
    assert call['actual_token_micro_usd'] is None and call['actual_tool_micro_usd'] is None
    assert call['reconciliation_revision'] == 0
    assert call['usage_status'] == ('estimated' if explanation else 'pending')
    with database_connection() as db:
        events = db.execute('SELECT * FROM usage_events WHERE call_id=%s ORDER BY created_at', (call['id'],)).fetchall()
        assert len(events) == 2  # The identical in-progress poll is not a new accounting observation.
        assert all(event['event_type'] == 'observation' for event in events)
        assert all(event['event_key'].startswith('response:') for event in events)
        assert events[-1]['provider_usage'] == {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150,
            'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}}
        assert events[-1]['reason_code'] == (None if explanation else 'tool_cost_unknown')
        reservations = db.execute('SELECT * FROM budget_reservations WHERE call_id=%s', (call['id'],)).fetchall()
        assert len(reservations) == 3
        assert {r['accounted_micro_usd'] for r in reservations} == {1}
        assert {r['status'] for r in reservations} == ({'settled'} if explanation else {'held'})
        assert all(r['reserved_micro_usd'] > 0 for r in reservations)
        assert db.execute('SELECT count(*) AS n FROM task_attempts WHERE task_id=%s', (task['id'],)).fetchone()['n'] == 1
        if explanation:
            value = json.loads(db.execute('SELECT explanation_json FROM explanations WHERE id=%s',
                (task['result_explanation_id'],)).fetchone()['explanation_json'])
            assert value['draft'] and value['sections'] and value['verification']['status'] == 'references_checked'
        else:
            value = json.loads(db.execute('SELECT figure_json FROM figures WHERE id=%s',
                (task['result_figure_id'],)).fetchone()['figure_json'])
            assert value['statistics']['series'][0]['points'][0]['y'] == 9.
            assert value['verification']['status'] == 'matched'
            assert value['provenance']['code'] == ['# synthetic Python']
            assert call['provider_state'] == {'version': 1, 'phase': 'response_ready', 'container_id': 'cntr_synthetic',
                'container_request_id': 'req_container', 'input_file_id': 'cfile_input',
                'input_file_path': '/mnt/data/data.json', 'upload_request_id': 'req_upload'}
        assert value['source'] == original_snapshot['source']
        assert value['provenance']['model_call_id'] == call['id']
        assert value['provenance']['model_input_digest'] == call['input_digest']
        assert value['provenance']['response_id'] == call['provider_response_id']
    return value


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('kind', ['plot', 'explanation'])
def test_configured_saved_response_get_only_duplicate_delivery_and_durable_fields(client, monkeypatch, version, kind):
    _, _, _, _, task, provider, worker = configured_case(client, monkeypatch, version, kind)
    original = deepcopy(task)
    snapshot = raw_task(task)['input_snapshot']
    task = pending(task, provider, worker, kind)
    task = step(task, provider, worker)
    provider.pending = False
    task = step(task, provider, worker)
    assert task['status'] == 'succeeded'
    assert worker(original['id'], original['revision'], provider_factory=lambda: provider) is None
    assert worker(task['id'], task['revision'], provider_factory=lambda: provider) is None
    assert len(provider.posts) == (3 if kind == 'plot' else 1)
    assert provider.gets == [saved_call(task)['provider_response_id']] * 2
    from app.domain.model_usage.gateway import input_digest
    assert saved_call(task)['input_digest'] == input_digest(instructions=provider.instructions,
        payload=provider.posts[0] if kind == 'explanation' else provider.payload)
    assert_receipts(task, snapshot, explanation=kind == 'explanation')


@pytest.mark.parametrize('phase', ['container', 'upload', 'response', 'explanation'])
def test_configured_unknown_submission_repeated_delivery_and_resume_never_posts_again(client, monkeypatch, phase):
    from app.core.exceptions import StorageError
    from app.domain.tasks.workspace import TaskWorkspaceService
    from app.domain.tasks.resume import TaskResumeService
    kind = 'explanation' if phase == 'explanation' else 'plot'
    workbench, _, _, _, task, provider, worker = configured_case(client, monkeypatch, 2, kind)
    original = deepcopy(task)
    snapshot = raw_task(task)['input_snapshot']
    if kind == 'plot':
        provider.fail_post = phase
    else:
        provider.fail_create = True
    task = finish(task, provider, worker)
    assert task['status'] == 'waiting_confirmation' and task['reason_code'] == 'submission_unknown'
    count = len(provider.posts)
    call = saved_call(task)
    assert call['status'] == 'submission_unknown' and call['provider_response_id'] is None
    assert call['estimated_cost_micro_usd'] is None and call['usage_status'] == 'pending'
    workspace = TaskWorkspaceService(workbench.tasks.user_id).get(task['id'])
    assert workspace['allowed_actions'] == [] and workspace['wait']['status'] == 'open'
    for _ in range(2):
        assert worker(original['id'], original['revision'], provider_factory=lambda: provider) is None
        assert worker(task['id'], task['revision'], provider_factory=lambda: provider) is None
        TaskExecutionStore().recover_expired()
        with pytest.raises(StorageError) as error:
            TaskResumeService(workbench.tasks.user_id).resume(task['id'], {'operation': 'resume',
                'wait_id': workspace['wait']['id'], 'expected_task_revision': task['revision'],
                'input_version': task['input_version']}, idempotency_key='unknown-must-not-repost')
        assert error.value.code == 'task_transition_invalid'
    assert len(provider.posts) == count == (1 if kind == 'explanation' else ['container', 'upload', 'response'].index(phase) + 1)
    assert not provider.gets and saved_call(task) == call and raw_task(task)['input_snapshot'] == snapshot
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests WHERE task_id=%s', (task['id'],)).fetchone()['n'] == 0
        reservations = db.execute('SELECT * FROM budget_reservations WHERE call_id=%s', (call['id'],)).fetchall()
        assert len(reservations) == 3 and {r['status'] for r in reservations} == {'held'}
        assert {r['accounted_micro_usd'] for r in reservations} == {0}
        assert all(r['reserved_micro_usd'] > 0 for r in reservations)


@pytest.mark.parametrize('kind', ['plot', 'explanation'])
def test_configured_budget_resume_replays_receipt_and_keeps_budget_revision(client, monkeypatch, kind):
    from app.domain.model_usage.service import ModelUsageService
    from app.domain.tasks.workspace import TaskWorkspaceService
    from app.domain.tasks.resume import TaskResumeService
    workbench, _, _, _, task, provider, worker = configured_case(client, monkeypatch, 2, kind)
    snapshot = raw_task(task)['input_snapshot']
    service = ModelUsageService(workbench.tasks.user_id)
    service.set_budget('task', task['id'], 0, 1)
    waiting = step(task, provider, worker)
    assert waiting['status'] == 'waiting_confirmation' and waiting['reason_code'] == 'budget_exceeded'
    assert provider.posts == []
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s', (task['id'],)).fetchone()['n'] == 0
    service.set_budget('task', task['id'], 1000000, 2)
    workspace = TaskWorkspaceService(workbench.tasks.user_id).get(task['id'])
    request = {'operation': 'resume', 'wait_id': workspace['wait']['id'],
        'expected_task_revision': waiting['revision'], 'input_version': waiting['input_version']}
    recovery = TaskResumeService(workbench.tasks.user_id)
    resumed = recovery.resume(task['id'], request, idempotency_key='budget-once')
    assert recovery.resume(task['id'], request, idempotency_key='budget-once') == resumed
    provider.pending = False
    done = finish(resumed, provider, worker)
    assert done['status'] == 'succeeded'
    assert recovery.resume(task['id'], request, idempotency_key='budget-once') == resumed
    assert len(provider.posts) == (3 if kind == 'plot' else 1)
    assert raw_task(task)['input_snapshot'] == snapshot
    with database_connection() as db:
        budget = db.execute("SELECT * FROM model_budgets WHERE scope_type='task' AND scope_key=%s", (task['id'],)).fetchone()
        assert budget['revision'] == 3 and budget['limit_micro_usd'] == 1000000
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests WHERE task_id=%s', (task['id'],)).fetchone()['n'] == 1
        wait = db.execute('SELECT * FROM task_waits WHERE id=%s', (workspace['wait']['id'],)).fetchone()
        assert wait['status'] == 'resolved'


@pytest.mark.parametrize('corrupt', ['numeric', 'method', 'source'])
def test_configured_malicious_manifest_is_rejected_with_evidence_and_no_png(client, monkeypatch, corrupt):
    _, _, _, _, task, provider, worker = configured_case(client, monkeypatch, 2)
    snapshot = raw_task(task)['input_snapshot']
    original_download = provider.download
    def malformed(file_id, *args, **kwargs):
        raw = original_download(file_id, *args, **kwargs)
        if file_id == 'cfile_png':
            return raw
        value = json.loads(raw)
        if corrupt == 'numeric':
            value['statistics']['series'][0]['points'][0]['y'] = 999.
        elif corrupt == 'method':
            value['method'] = {'id': 'forged_regression'}
        else:
            value['source'] = {'file_id': 'forged-file', 'analysis_run_id': 'forged-analysis'}
        return json.dumps(value).encode()
    monkeypatch.setattr(provider, 'download', malformed)
    provider.pending = False
    task = finish(task, provider, worker)
    assert task['status'] == 'failed' and task['error_code'] == 'plot_result_mismatch'
    record = raw_task(task)
    evidence = record['verification_failure']
    call = saved_call(task)
    assert evidence['status'] == 'mismatched' and evidence['differences']
    assert evidence['model_call_id'] == call['id'] and evidence['response_id'] == call['provider_response_id']
    assert record['input_snapshot'] == snapshot and record['figure_candidate'] is None
    assert provider.posts == ['container', 'upload', 'response'] and provider.downloads == ['cfile_result']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM figures').fetchone()['n'] == 0


@pytest.mark.parametrize('corrupt', ['numeric', 'method', 'source'])
def test_configured_explanation_rejects_forged_facts_and_preserves_figure(client, monkeypatch, corrupt):
    workbench, project, _, _, task, provider, worker = configured_case(client, monkeypatch, 2, 'explanation')
    from app.adapters.figure_workbench_store import read_bundle
    snapshot = raw_task(task)['input_snapshot']
    figure = deepcopy(snapshot['figure'])
    png = workbench.assets.figure_png(figure)
    original = provider.receipt
    def malicious():
        receipt = original()
        part = receipt['response']['output'][0]['content'][0]
        draft = json.loads(part['text'])
        draft['methods'] += {'numeric': ' Mean is 999.', 'method': ' Regression was performed.',
            'source': ' {{source.forged_file}}'}[corrupt]
        part['text'] = json.dumps(draft)
        return receipt
    monkeypatch.setattr(provider, 'receipt', malicious)
    provider.pending = False
    failed = step(task, provider, worker)
    assert failed['status'] == 'failed' and failed['error_code'] == 'explanation_invalid'
    assert len(provider.posts) == 1 and saved_call(task)['status'] == 'completed'
    assert read_bundle(workbench.assets, project, figure['id'])['figure'] == figure
    assert workbench.assets.figure_png(figure) == png
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM explanations').fetchone()['n'] == 0


@pytest.mark.parametrize('after_bytes', [False, True])
def test_configured_candidate_write_interruption_recovers_without_another_post(client, monkeypatch, after_bytes):
    from tests.integration.test_boxplot_execution import lease_for
    from tests.integration.test_task_execution import expired
    from app.adapters.figure_workbench_store import read_bundle
    import app.domain.figure_workbench.execution as execution
    workbench, project, _, _, task, provider, worker = configured_case(client, monkeypatch, 2)
    snapshot = raw_task(task)['input_snapshot']
    provider.pending = False
    task = step(step(task, provider, worker), provider, worker)
    write = execution.write_candidate
    def interrupted(*args):
        if after_bytes:
            write(*args)
        raise OSError('synthetic asset write interruption')
    monkeypatch.setattr(execution, 'write_candidate', interrupted)
    assert worker(task['id'], task['revision'], provider_factory=lambda: provider) is None
    candidate = raw_task(task)['figure_candidate']
    assert candidate and raw_task(task)['result_figure_id'] is None
    path = workbench.assets.figures_dir / (candidate['id'] + '.png')
    assert path.exists() is after_bytes
    expired(lease_for(task))
    assert TaskExecutionStore().recover_expired() == 1
    task = TaskStore(workbench.tasks.user_id).get(task['id'])
    monkeypatch.setattr(execution, 'write_candidate', write)
    def local_only():
        raise AssertionError('The durable candidate must not initialize a provider.')
    done = worker(task['id'], task['revision'], provider_factory=local_only if after_bytes else lambda: provider)
    assert done and done['status'] == 'succeeded'
    assert raw_task(task)['input_snapshot'] == snapshot and raw_task(task)['figure_candidate'] is None
    assert provider.posts == ['container', 'upload', 'response']
    assert provider.gets == ([] if after_bytes else ['resp_plot_synthetic'])
    assert read_bundle(workbench.assets, project, done['result_figure_id'])['figure']['id'] == candidate['id']
    assert path.read_bytes() == provider.png
    assert worker(done['id'], done['revision'], provider_factory=local_only) is None
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM figures').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s', (task['id'],)).fetchone()['n'] == 1


@pytest.mark.parametrize('kind', ['plot', 'explanation'])
def test_configured_disabled_owner_never_retrieves_paid_response(client, monkeypatch, kind):
    workbench, _, _, _, task, provider, worker = configured_case(client, monkeypatch, 2, kind)
    task = pending(task, provider, worker, kind)
    before = saved_call(task)
    with database_connection(write=True) as db:
        db.execute('UPDATE users SET active=FALSE WHERE id=%s', (workbench.tasks.user_id,))
    assert worker(task['id'], task['revision'], provider_factory=lambda: provider) is None
    assert provider.gets == [] and saved_call(task) == before
    assert raw_task(task)['status'] == 'failed' and raw_task(task)['error_code'] == 'task_owner_unavailable'


@pytest.mark.parametrize('kind', ['plot', 'explanation'])
def test_configured_changed_source_before_submission_initializes_no_provider(client, monkeypatch, kind):
    _, _, _, configuration, task, provider, worker = configured_case(client, monkeypatch, 2, kind)
    with database_connection(write=True) as db:
        db.execute('UPDATE figure_config_versions SET sha256=%s WHERE id=%s', ('0' * 64, configuration))
    done = worker(task['id'], task['revision'], provider_factory=lambda: (_ for _ in ()).throw(
        AssertionError('Source rejection must precede provider initialization.')))
    assert done and done['status'] == 'failed' and done['error_code'] == 'task_source_conflict'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s', (task['id'],)).fetchone()['n'] == 0


@pytest.mark.parametrize('contract', [2, 3, 4])
def test_modern_analysis_plot_and_explanation_reuse_recorded_response(client, contract):
    from app.domain.tasks.execution import run_boxplot_task, run_explanation_task
    from tests.integration.test_correlation_artifact_chain import ModernExplanationProvider
    if contract == 2:
        from tests.integration.test_correlation_artifact_chain import result_for, modern_task as create, ModernPlotProvider
        base, file, result = result_for(client)
        provider = ModernPlotProvider()
    elif contract == 3:
        from tests.integration.test_comparison_artifact_chain import result_for, comparison_task as create, ComparisonPlotProvider
        base, file, result = result_for(client)
        provider = ComparisonPlotProvider()
    else:
        from tests.integration.test_modeling_artifact_chain import result_for, artifact_task as create, ModelingPlotProvider
        base, file, result = result_for(client, 'roc_auc')
        provider = ModelingPlotProvider()
    task, _ = create(client, base, file, result, 'boxplot')
    snapshot = raw_task(task)['input_snapshot']
    provider.pending = True
    task = pending(task, provider, run_boxplot_task, 'plot')
    task = step(task, provider, run_boxplot_task)
    provider.pending = False
    done = step(task, provider, run_boxplot_task)
    assert done['status'] == 'succeeded'
    assert provider.posts == ['container', 'upload', 'response']
    assert provider.gets == ['resp_plot_synthetic'] * 2
    assert raw_task(task)['input_snapshot'] == snapshot
    with database_connection() as db:
        figure = json.loads(db.execute('SELECT figure_json FROM figures WHERE id=%s',
            (done['result_figure_id'],)).fetchone()['figure_json'])
        assert figure['schema_version'] == contract and figure['source'] == result['source']
        assert figure['provenance']['model_call_id'] == saved_call(task)['id']
        assert db.execute('SELECT count(*) AS n FROM usage_events WHERE call_id=%s',
            (saved_call(task)['id'],)).fetchone()['n'] == 2
    task, _ = create(client, base, file, result, 'explanation', figure)
    snapshot = raw_task(task)['input_snapshot']
    prose = ModernExplanationProvider(pending=True)
    task = pending(task, prose, run_explanation_task, 'explanation')
    task = step(task, prose, run_explanation_task)
    prose.pending = False
    done = step(task, prose, run_explanation_task)
    assert done['status'] == 'succeeded'
    assert len(prose.posts) == 1 and prose.gets == [prose.response_id] * 2
    assert raw_task(task)['input_snapshot'] == snapshot
    assert run_explanation_task(done['id'], done['revision'], provider_factory=lambda: prose) is None
    with database_connection() as db:
        explanation = json.loads(db.execute('SELECT explanation_json FROM explanations WHERE id=%s',
            (done['result_explanation_id'],)).fetchone()['explanation_json'])
        assert explanation['schema_version'] == contract and explanation['source'] == result['source']
        assert explanation['provenance']['model_call_id'] == saved_call(task)['id']
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 2
    assert client.get(base + '/analysis-runs/' + result['id'] + '/figures/' + figure['id'] + '/download').content == provider.png


@pytest.mark.parametrize('after_bytes', [False, True])
def test_collection_word_write_failure_retry_preserves_old_download_and_publishes_once(client, monkeypatch, after_bytes):
    from io import BytesIO
    from zipfile import ZipFile
    from app.adapters.collection_store import CollectionStore
    from app.domain.report_collections.contracts import CollectionRequest
    from app.domain.report_collections.execution import run_collection_word_task
    from app.domain.tasks.resume import TaskResumeService
    import app.domain.report_collections.execution as execution
    workbench, project, _, _, task, provider, worker = configured_case(client, monkeypatch, 2, 'explanation')
    provider.pending = False
    explanation = finish(task, provider, worker)
    assert explanation['status'] == 'succeeded'
    snapshot = raw_task(task)['input_snapshot']
    figure = snapshot['figure']
    png = workbench.assets.figure_png(figure)
    repository = CollectionStore(workbench.assets)
    body = CollectionRequest(title='Batch08 immutable report', language='en',
        items=[{'figure_id': figure['id'], 'explanation_id': explanation['result_explanation_id']}])
    state = repository.create(project, body, 'batch08-collection')
    initial = state['versions'][0]['requests'][0]
    assert run_collection_word_task(initial['task_id'], 1)['status'] == 'succeeded'
    state = repository.get(project, state['id'])
    old = state['versions'][0]['requests'][0]['report']
    old_meta, old_bytes = repository.download(project, state['id'], old['id'])
    build = repository.export(project, state['id'], state['current_version_id'], 'batch08-second-export')
    assert repository.export(project, state['id'], state['current_version_id'], 'batch08-second-export') == build
    task = TaskStore(workbench.tasks.user_id).get(build['task_id'])
    frozen = raw_task(task)['input_snapshot']
    if after_bytes:
        original_finish = execution.TaskExecutionStore._finish
        def interrupted(self, db, active, status, error_code):
            if active['id'] == task['id'] and status == 'succeeded':
                raise OSError('synthetic database boundary interruption after file rename')
            return original_finish(self, db, active, status, error_code)
        monkeypatch.setattr(execution.TaskExecutionStore, '_finish', interrupted)
    else:
        original_render = execution.build_collection_report
        monkeypatch.setattr(execution, 'build_collection_report', lambda *args: (_ for _ in ()).throw(
            OSError('synthetic local asset interruption before write')))
    failed = run_collection_word_task(task['id'], task['revision'])
    assert failed and failed['status'] == 'failed' and failed['error_code'] == 'storage_unavailable'
    assert repository.download(project, state['id'], old['id']) == (old_meta, old_bytes)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM collection_reports WHERE build_request_id=%s', (build['id'],)).fetchone()['n'] == 0
    if after_bytes:
        monkeypatch.setattr(execution.TaskExecutionStore, '_finish', original_finish)
    else:
        monkeypatch.setattr(execution, 'build_collection_report', original_render)
    request = {'operation': 'retry', 'wait_id': None, 'expected_task_revision': failed['revision'],
        'input_version': failed['input_version']}
    resume = TaskResumeService(workbench.tasks.user_id)
    queued = resume.resume(task['id'], request, idempotency_key='batch08-word-retry')
    assert resume.resume(task['id'], request, idempotency_key='batch08-word-retry') == queued
    done = run_collection_word_task(queued['id'], queued['revision'])
    assert done and done['status'] == 'succeeded'
    assert run_collection_word_task(queued['id'], queued['revision']) is None
    assert resume.resume(task['id'], request, idempotency_key='batch08-word-retry') == queued
    assert raw_task(task)['input_snapshot'] == frozen
    state = repository.get(project, state['id'])
    new = next(r['report'] for r in state['versions'][0]['requests'] if r['id'] == build['id'])
    _, content = repository.download(project, state['id'], new['id'])
    with ZipFile(BytesIO(content)) as archive:
        assert [archive.read(n) for n in archive.namelist() if n.startswith('word/media/')] == [png]
    assert repository.download(project, state['id'], old['id']) == (old_meta, old_bytes)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 2
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s', (task['id'],)).fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM collection_reports WHERE build_request_id=%s', (build['id'],)).fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM task_resume_requests WHERE task_id=%s', (task['id'],)).fetchone()['n'] == 1
