"""Leased plot execution against isolated PostgreSQL and synthetic cloud receipts."""
from io import BytesIO
import hashlib
import json

from PIL import Image
from psycopg.types.json import Jsonb
import pytest

from app.adapters.task_execution_store import LeaseLost, TaskExecutionStore, TaskLease
from app.adapters.task_store import TaskStore
from app.db.database import database_connection
from app.domain.tasks.service import TaskService
from tests.api.test_analysis import client  # noqa: F401
from tests.helpers.tasks import boxplot_task_input, task_owner
from tests.integration.test_task_execution import expired


def queued(client, *, configured=True, key='plot-execution'):
    from app.domain.model_usage.service import ModelUsageService
    project, request, base, result = boxplot_task_input(client)
    owner = task_owner(client)
    task, _ = TaskService(owner).create(project, request, idempotency_key=key)
    if configured:
        frozen = {'policy': {'model': 'test-plot', 'prompt_version': 'openai_boxplot_v1',
            'max_output_tokens': 16000, 'timeout_seconds': 15, 'tools': ['code_interpreter'],
            'output_format': 'text', 'price': {'version': 'synthetic-only', 'model': 'test-plot',
                'input_micro_usd_per_million': 100, 'cached_input_micro_usd_per_million': 50,
                'output_micro_usd_per_million': 200}}, 'input_token_allowance': 100000,
            'task_limit_micro_usd': 1000000, 'tool_reserve_micro_usd': 1000,
            'tool_reserve_version': 'synthetic-tool-only'}
        with database_connection(write=True) as db:
            db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{boxplot_policy}',%s) WHERE id=%s",
                       (Jsonb(frozen), task['id']))
        service = ModelUsageService(owner)
        for scope, scope_key in [('user', owner), ('project', project), ('task', task['id'])]:
            budget = service.get_budget(scope, scope_key)
            if budget['limit_micro_usd'] is None:
                service.set_budget(scope, scope_key, 1000000, 0)
    return task, owner, base, result


def run(task, provider):
    from app.domain.tasks import execution
    assert hasattr(execution, 'run_boxplot_task'), 'A unified boxplot executor is required.'
    return execution.run_boxplot_task(task['id'], task['revision'], provider_factory=lambda: provider)


def lease_for(task):
    with database_connection() as db:
        row = db.execute('SELECT * FROM task_attempts WHERE task_id=%s ORDER BY attempt_no DESC LIMIT 1',
                         (task['id'],)).fetchone()
        return TaskLease(task['id'], row['attempt_no'], row['lease_owner'])


class SyntheticPlotProvider:
    def __init__(self, result, *, pending=True):
        self.result, self.pending = result, pending
        self.posts, self.gets, self.downloads, self.closed = [], [], [], 0
        self.payload = None
        self.on_post = self.on_download = None
        self.fail_post = self.fail_get = self.fail_download = False
        self.expired_container = self.corrupt = False
        buffer = BytesIO()
        Image.new('RGB', (1600, 1200), 'white').save(buffer, format='PNG')
        self.png = buffer.getvalue()

    def post(self, phase):
        self.posts.append(phase)
        if self.on_post:
            self.on_post(phase)
        if self.fail_post == phase:
            raise RuntimeError('synthetic provider interruption')

    def create_container(self, *, policy, call_id):
        self.post('container')
        return {'container_id': 'cntr_synthetic', 'request_id': 'req_container'}

    def upload_input(self, container_id, payload, *, policy):
        self.post('upload')
        self.payload = payload
        return {'input_file_id': 'cfile_input', 'input_file_path': '/mnt/data/data.json',
                'request_id': 'req_upload'}

    def create_plot(self, *, policy, instructions, container_id, input_file_path):
        self.post('response')
        return self.receipt()

    def receipt(self):
        usage = {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150,
                 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}}
        response = {'id': 'resp_plot_synthetic', 'model': 'test-plot',
            'status': 'in_progress' if self.pending else 'completed', 'usage': usage,
            'output': [{'type': 'code_interpreter_call', 'status': 'completed',
                        'container_id': 'cntr_synthetic', 'code': '# synthetic Python'},
                       {'type': 'message', 'content': [{'type': 'output_text', 'annotations': [
                           {'type': 'container_file_citation', 'container_id': 'cntr_synthetic',
                            'file_id': 'cfile_png', 'filename': '/mnt/data/boxplot.png'},
                           {'type': 'container_file_citation', 'container_id': 'cntr_synthetic',
                            'file_id': 'cfile_result', 'filename': '/mnt/data/result.json'}]}]}]}
        return {'response_id': response['id'], 'request_id': 'req_response', 'model': response['model'],
                'status': response['status'], 'usage': usage, 'response': response}

    def retrieve(self, response_id, *, policy):
        self.gets.append(response_id)
        if self.fail_get:
            raise RuntimeError('synthetic transient retrieval')
        return self.receipt()

    def download(self, file_id, container_id, limit, *, policy):
        from app.adapters.models.openai_responses import ModelProviderError
        self.downloads.append(file_id)
        if self.on_download:
            self.on_download()
        if self.expired_container:
            raise ModelProviderError('plot_container_expired', status_code=404)
        if self.fail_download:
            raise ModelProviderError(self.fail_download if isinstance(self.fail_download, str) else 'model_provider_request_failed')
        if file_id == 'cfile_png':
            return self.png
        from app.domain.boxplot import plot_data
        result, payload = self.result, self.payload
        groups = {item['label']: item['values'] for item in payload['groups']}
        figure = plot_data(result, payload['values'], groups)
        metrics = ('n', 'mean', 'std', 'min', 'q1', 'median', 'q3', 'max', 'iqr')
        manifest = {'analysis_run_id': result['id'], 'source_sha256': result['source_sha256'],
            **payload['labels'], 'overall': {k: result['overall'][k] for k in metrics},
            'groups': [{'label': g['label'], 'statistics': {k: g['statistics'][k] for k in metrics}}
                       for g in result['groups']], 'series': figure['series']}
        if self.corrupt:
            manifest['overall']['mean'] += 5
        return json.dumps(manifest, ensure_ascii=False).encode('utf-8')

    def close(self):
        self.closed += 1


def until_response(task, provider):
    for index in range(3):
        task = run(task, provider)
        assert task is not None
        assert len(provider.posts) == index + 1
    return task


def test_boxplot_claim_defer_and_dispatch_preserve_attempt(client):
    from app.workers.dispatcher import dispatch_once
    task, owner, *_ = queued(client, configured=False)
    published = []
    assert dispatch_once(publish=published.append) == 1
    assert set(published[0]) == {'id', 'task_id', 'task_revision'}
    store = TaskExecutionStore()
    lease = store.claim(task['id'], task['revision'])
    assert lease is not None, 'Boxplot tasks must be claimable.'
    deferred = store.defer(lease)
    assert deferred['current_attempt'] == 1 and deferred['revision'] == 3
    assert not store.heartbeat(lease)
    assert store.recover_expired() == 0
    resumed = store.claim(task['id'], deferred['revision'])
    assert resumed.attempt_no == 1 and resumed.lease_owner != lease.lease_owner
    with pytest.raises(LeaseLost):
        store.fail(lease, 'task_execution_failed')
    assert TaskStore(owner).get(task['id'])['status'] == 'running'


def test_boxplot_one_post_per_slice_then_original_png_and_ledger(client):
    task, _, _, result = queued(client)
    provider = SyntheticPlotProvider(result)
    pending = until_response(task, provider)
    assert pending['status'] == 'running' and pending['current_attempt'] == 1
    again = run(pending, provider)
    provider.pending = False
    complete = run(again, provider)
    assert complete['status'] == 'succeeded' and complete['result_figure_id']
    assert provider.posts == ['container', 'upload', 'response']
    assert provider.gets == ['resp_plot_synthetic'] * 2
    with database_connection() as db:
        figure = json.loads(db.execute('SELECT figure_json FROM figures').fetchone()['figure_json'])
        call = db.execute('SELECT * FROM model_calls').fetchone()
        assert figure['id'] == complete['result_figure_id']
        assert figure['sha256'] == hashlib.sha256(provider.png).hexdigest()
        assert TaskExecutionStore().assets.figure_png(figure) == provider.png
        assert figure['provenance']['model_call_id'] == call['id']
        assert figure['engine']['id'] == 'openai_boxplot_v1'
        assert call['provider_status'] == 'completed'
        assert {row['status'] for row in db.execute('SELECT status FROM budget_reservations')} == {'held'}
        assert len(db.execute('SELECT id FROM task_attempts').fetchall()) == 1


def test_boxplot_unconfigured_waits_without_provider(client):
    task, _, _, result = queued(client, configured=False)
    provider = SyntheticPlotProvider(result)
    waiting = run(task, provider)
    assert waiting['status'] == 'waiting_confirmation' and waiting['reason_code'] == 'budget_exceeded'
    assert provider.posts == [] and provider.closed == 0


@pytest.mark.parametrize('phase', ['container', 'upload', 'response'])
def test_boxplot_unknown_side_effect_never_reposts(client, phase):
    task, owner, _, result = queued(client)
    provider = SyntheticPlotProvider(result)
    provider.fail_post = phase
    for _ in range(['container', 'upload', 'response'].index(phase) + 1):
        task = run(task, provider)
    assert task['status'] == 'waiting_confirmation' and task['reason_code'] == 'submission_unknown'
    calls = list(provider.posts)
    assert run(task, provider) is None
    assert provider.posts == calls
    with database_connection() as db:
        assert len(db.execute('SELECT * FROM model_calls').fetchall()) == 1
        assert {r['status'] for r in db.execute('SELECT status FROM budget_reservations')} == {'held'}


def test_boxplot_missing_budget_never_creates_container(client):
    task, _, _, result = queued(client)
    with database_connection(write=True) as db:
        db.execute("DELETE FROM model_budgets WHERE scope_type='task'")
    provider = SyntheticPlotProvider(result)
    waiting = run(task, provider)
    assert waiting['status'] == 'waiting_confirmation' and waiting['reason_code'] == 'budget_exceeded'
    assert provider.posts == []
    with database_connection() as db:
        assert not db.execute('SELECT id FROM model_calls').fetchall()


def change_source():
    with database_connection(write=True) as db:
        db.execute('UPDATE analysis_setups SET revision=revision+1')


def test_boxplot_changed_source_before_first_post_never_initializes_provider(client):
    task, _, _, result = queued(client)
    change_source()
    provider = SyntheticPlotProvider(result)
    failed = run(task, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == 'task_source_conflict'
    assert not provider.posts and provider.closed == 0


def test_boxplot_changed_source_still_gets_terminal_usage_before_rejecting_artifact(client):
    task, _, _, result = queued(client)
    provider = SyntheticPlotProvider(result)
    pending = until_response(task, provider)
    change_source()
    provider.pending = False
    failed = run(pending, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == 'task_source_conflict'
    assert provider.gets == ['resp_plot_synthetic'] and not provider.downloads
    with database_connection() as db:
        call = db.execute('SELECT * FROM model_calls').fetchone()
        assert call['provider_status'] == 'completed' and call['estimated_cost_micro_usd'] > 0
        assert not db.execute('SELECT id FROM figures').fetchall()


@pytest.mark.parametrize('code', ['plot_container_expired', 'plot_output_limit', 'plot_receipt_invalid', 'model_input_invalid'])
def test_boxplot_permanent_download_failure_keeps_usage_without_reposting(client, code):
    task, _, _, result = queued(client)
    provider = SyntheticPlotProvider(result)
    pending = until_response(task, provider)
    provider.pending = False
    provider.fail_download = code
    failed = run(pending, provider)
    assert failed['status'] == 'failed'
    assert len(provider.posts) == 3
    with database_connection() as db:
        assert db.execute('SELECT provider_status FROM model_calls').fetchone()['provider_status'] == 'completed'
        assert not db.execute('SELECT id FROM figures').fetchall()


def test_boxplot_transient_download_releases_lease_and_reuses_response(client):
    task, _, _, result = queued(client)
    provider = SyntheticPlotProvider(result)
    pending = until_response(task, provider)
    provider.pending, provider.fail_download = False, True
    waiting = run(pending, provider)
    assert waiting['status'] == 'running' and waiting['current_attempt'] == 1
    with database_connection() as db:
        attempt = db.execute('SELECT lease_owner FROM task_attempts').fetchone()
        outbox = db.execute('SELECT * FROM task_outbox ORDER BY task_revision DESC LIMIT 1').fetchone()
        assert attempt['lease_owner'] is None
        assert (outbox['available_at'] - outbox['created_at']).total_seconds() >= 30
    provider.fail_download = False
    complete = run(waiting, provider)
    assert complete['status'] == 'succeeded' and len(provider.posts) == 3 and len(provider.gets) == 2


@pytest.mark.parametrize('shape', ['content_null', 'annotations_null'])
def test_boxplot_malformed_response_fails_after_recording_usage(client, shape):
    task, _, _, result = queued(client)
    provider = SyntheticPlotProvider(result)
    pending = until_response(task, provider)
    provider.pending = False
    receipt = provider.receipt
    def malformed():
        value = receipt()
        message = value['response']['output'][1]
        if shape == 'content_null':
            message['content'] = None
        else:
            message['content'][0]['annotations'] = None
        return value
    provider.receipt = malformed
    failed = run(pending, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == 'plot_invalid_result'
    with database_connection() as db:
        assert db.execute('SELECT provider_status FROM model_calls').fetchone()['provider_status'] == 'completed'


@pytest.mark.parametrize('checkpoint', ['part', 'candidate', 'target'])
def test_boxplot_durable_candidate_survives_crash_without_remote_access(client, monkeypatch, checkpoint):
    import os
    from pathlib import Path
    from app.domain.tasks.execution import run_boxplot_task
    task, owner, _, result = queued(client)
    provider = SyntheticPlotProvider(result, pending=False)
    task = run(run(task, provider), provider)
    original_replace = os.replace
    def crash(source, target):
        destination = Path(target)
        if checkpoint == 'part' and destination.suffix == '.candidate':
            raise SystemExit('simulated hard exit after fsync')
        original_replace(source, target)
        if (checkpoint == 'candidate' and destination.suffix == '.candidate'
                or checkpoint == 'target' and destination.suffix == '.png'):
            raise SystemExit('simulated hard exit after rename')
    with monkeypatch.context() as patch:
        patch.setattr(os, 'replace', crash)
        with pytest.raises(SystemExit):
            run(task, provider)
    with database_connection() as db:
        current = db.execute('SELECT * FROM tasks WHERE id=%s', (task['id'],)).fetchone()
        assert current['figure_candidate'] is not None and current['status'] == 'running'
        assert not db.execute('SELECT id FROM figures').fetchall()
    expired(lease_for(task))
    assert TaskExecutionStore().recover_expired() == 1
    current = TaskStore(owner).get(task['id'])
    def forbidden():
        raise AssertionError('Complete local candidate must not initialize a provider.')
    complete = run_boxplot_task(current['id'], current['revision'], provider_factory=forbidden)
    assert complete['status'] == 'succeeded' and complete['current_attempt'] == 2
    assert provider.posts == ['container', 'upload', 'response']
    assert provider.downloads == ['cfile_result', 'cfile_png'] and provider.gets == []
    with database_connection() as db:
        figure = json.loads(db.execute('SELECT figure_json FROM figures').fetchone()['figure_json'])
        assert TaskExecutionStore().assets.figure_png(figure) == provider.png
        assert db.execute('SELECT figure_candidate FROM tasks').fetchone()['figure_candidate'] is None


@pytest.mark.parametrize('completed_steps', [1, 2])
def test_boxplot_known_preparation_receipt_resumes_after_expired_lease(client, monkeypatch, completed_steps):
    task, owner, _, result = queued(client)
    provider = SyntheticPlotProvider(result, pending=False)
    for _ in range(completed_steps - 1):
        task = run(task, provider)
    def interrupted(*args, **kwargs):
        raise SystemExit('simulated crash after durable remote receipt')
    with monkeypatch.context() as patch:
        patch.setattr(TaskExecutionStore, 'defer', interrupted)
        with pytest.raises(SystemExit):
            run(task, provider)
    expired(lease_for(task))
    assert TaskExecutionStore().recover_expired() == 1
    task = TaskStore(owner).get(task['id'])
    assert task['status'] == 'queued'
    for _ in range(3 - completed_steps):
        task = run(task, provider)
    assert task['status'] == 'succeeded'
    assert provider.posts == ['container', 'upload', 'response']


@pytest.mark.parametrize('phase', ['container', 'upload', 'response'])
def test_boxplot_crashed_inflight_post_recovers_to_unknown_not_another_post(client, phase):
    task, owner, _, result = queued(client)
    provider = SyntheticPlotProvider(result)
    for _ in range(['container', 'upload', 'response'].index(phase)):
        task = run(task, provider)
    def hard_exit(current):
        if current == phase:
            raise SystemExit('synthetic no receipt')
    provider.on_post = hard_exit
    with pytest.raises(SystemExit):
        run(task, provider)
    expired(lease_for(task))
    assert TaskExecutionStore().recover_expired() == 1
    current = TaskStore(owner).get(task['id'])
    assert current['status'] == 'waiting_confirmation' and current['reason_code'] == 'submission_unknown'
    before = list(provider.posts)
    assert run(current, provider) is None and provider.posts == before


@pytest.mark.parametrize('recovery', ['deferred', 'expired'])
def test_boxplot_durable_preparation_expiry_finishes_task_without_another_post(client, recovery):
    task, owner, _, result = queued(client)
    provider = SyntheticPlotProvider(result)
    task = run(task, provider)
    store = TaskExecutionStore()
    if recovery == 'expired':
        lease = store.claim(task['id'], task['revision'])
    # This is the receipt already committed by the gateway before a process
    # interruption can prevent the task from recording its terminal business state.
    with database_connection(write=True) as db:
        db.execute("UPDATE model_calls SET status='failed',error_code='plot_container_expired'")
    if recovery == 'expired':
        expired(lease)
        assert store.recover_expired() == 1
        failed = TaskStore(owner).get(task['id'])
    else:
        failed = run(task, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == 'plot_container_expired'
    assert provider.posts == ['container']
    with database_connection() as db:
        assert {row['status'] for row in db.execute('SELECT status FROM budget_reservations')} == {'held'}


@pytest.mark.parametrize('tamper', ['path', 'provenance'])
def test_boxplot_candidate_cannot_change_storage_path_or_call_identity(client, monkeypatch, tmp_path, tamper):
    task, owner, _, result = queued(client)
    provider = SyntheticPlotProvider(result, pending=False)
    task = run(run(task, provider), provider)
    def interrupted(*args, **kwargs):
        raise SystemExit('candidate intent exists before any file write')
    with monkeypatch.context() as patch:
        patch.setattr(TaskExecutionStore, 'write_figure_candidate', interrupted)
        with pytest.raises(SystemExit):
            run(task, provider)
    sentinel = tmp_path / 'do-not-touch.png'
    sentinel.write_bytes(b'protected local content')
    with database_connection(write=True) as db:
        candidate = db.execute('SELECT figure_candidate FROM tasks').fetchone()['figure_candidate']
        if tamper == 'path':
            candidate['path'] = str(sentinel)
        else:
            candidate['figure']['provenance']['model_input_digest'] = '0' * 64
        db.execute('UPDATE tasks SET figure_candidate=%s', (Jsonb(candidate),))
    expired(lease_for(task))
    assert TaskExecutionStore().recover_expired() == 1
    failed = run(TaskStore(owner).get(task['id']), provider)
    assert failed['status'] == 'failed' and failed['error_code'] == 'task_source_conflict'
    assert sentinel.read_bytes() == b'protected local content'
    assert provider.posts == ['container', 'upload', 'response'] and provider.gets == []


def test_boxplot_saved_figure_is_reused_before_missing_configuration_or_provider(client):
    from app.domain.tasks.contracts import TaskCreateRequest
    task, owner, _, result = queued(client)
    provider = SyntheticPlotProvider(result, pending=False)
    finished = until_response(task, provider)
    second, _ = TaskService(owner).create(task['project_id'], TaskCreateRequest(
        task_type='boxplot', file_id=result['file_id'], analysis_run_id=result['id'],
        expected_revision=result['setup_revision']), idempotency_key='another-plot-request')
    clean = SyntheticPlotProvider(result)
    reused = run(second, clean)
    assert reused['status'] == 'succeeded' and reused['result_figure_id'] == finished['result_figure_id']
    assert clean.posts == [] and clean.closed == 0
    with database_connection() as db:
        assert len(db.execute('SELECT id FROM model_calls').fetchall()) == 1
        assert len(db.execute('SELECT id FROM figures').fetchall()) == 1


@pytest.mark.parametrize('phase', ['container', 'upload', 'response'])
def test_boxplot_late_receipt_requeues_unknown_task_once_without_repeating_known_post(client, phase):
    task, owner, _, result = queued(client)
    provider = SyntheticPlotProvider(result, pending=False)
    store = TaskExecutionStore()
    for _ in range(['container', 'upload', 'response'].index(phase)):
        task = run(task, provider)
    def expires_before_receipt(current):
        if current == phase:
            expired(lease_for(task))
            assert store.recover_expired() == 1
            assert TaskStore(owner).get(task['id'])['reason_code'] == 'submission_unknown'
    provider.on_post = expires_before_receipt
    assert run(task, provider) is None
    waiting = TaskStore(owner).get(task['id'])
    assert waiting['status'] == 'waiting_confirmation'
    assert store.recover_expired() == 1, 'A durable late receipt must make the original task recoverable.'
    resumed = TaskStore(owner).get(task['id'])
    assert resumed['status'] == 'queued' and resumed['reason_code'] == 'confirmation_received'
    assert resumed['revision'] == waiting['revision'] + 1
    assert store.recover_expired() == 0
    assert TaskStore(owner).get(task['id']) == resumed
    events = TaskStore(owner).events(task['id'])['items']
    assert [event['event_type'] for event in events].count('requeued') == 1
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_outbox WHERE task_id=%s AND task_revision=%s',
                          (task['id'], resumed['revision'])).fetchone()['n'] == 1
    provider.on_post = None
    for _ in range(3):
        resumed = run(resumed, provider)
        if resumed['status'] == 'succeeded':
            break
    assert resumed['status'] == 'succeeded' and resumed['current_attempt'] == 2
    assert provider.posts == ['container', 'upload', 'response']
    assert provider.gets == (['resp_plot_synthetic'] if phase == 'response' else [])


@pytest.mark.parametrize('phase', ['container', 'upload', 'response'])
def test_boxplot_unknown_without_late_receipt_stays_blocked_across_scans(client, phase):
    task, owner, _, result = queued(client)
    provider = SyntheticPlotProvider(result)
    store = TaskExecutionStore()
    for _ in range(['container', 'upload', 'response'].index(phase)):
        task = run(task, provider)
    def no_receipt(current):
        if current == phase:
            expired(lease_for(task))
            assert store.recover_expired() == 1
            raise SystemExit('No remote receipt can be recovered.')
    provider.on_post = no_receipt
    with pytest.raises(SystemExit):
        run(task, provider)
    waiting = TaskStore(owner).get(task['id'])
    assert waiting['status'] == 'waiting_confirmation' and waiting['reason_code'] == 'submission_unknown'
    assert store.recover_expired() == store.recover_expired() == 0
    assert TaskStore(owner).get(task['id']) == waiting
    assert run(waiting, provider) is None


def test_boxplot_late_receipt_with_disabled_owner_never_requeues_or_uses_network(client):
    task, owner, _, result = queued(client)
    provider = SyntheticPlotProvider(result)
    store = TaskExecutionStore()
    def expires_before_receipt(current):
        expired(lease_for(task))
        assert store.recover_expired() == 1
    provider.on_post = expires_before_receipt
    assert run(task, provider) is None
    with database_connection(write=True) as db:
        db.execute('UPDATE users SET active=FALSE WHERE id=%s', (owner,))
    assert store.recover_expired() == 0
    with database_connection() as db:
        current = dict(db.execute('SELECT * FROM tasks WHERE id=%s', (task['id'],)).fetchone())
        assert current['status'] == 'waiting_confirmation'
    assert run(current, provider) is None
    assert provider.posts == ['container'] and provider.gets == []


def test_boxplot_late_definite_upload_expiry_finishes_unknown_task_with_ledger_intact(client):
    from app.adapters.models.openai_responses import ModelProviderError
    task, owner, _, result = queued(client)
    provider = SyntheticPlotProvider(result)
    store = TaskExecutionStore()
    task = run(task, provider)
    def expired_upload(**kwargs):
        provider.posts.append('upload')
        expired(lease_for(task))
        assert store.recover_expired() == 1
        raise ModelProviderError('plot_container_expired', status_code=404)
    provider.upload_input = expired_upload
    assert run(task, provider) is None
    assert TaskStore(owner).get(task['id'])['status'] == 'waiting_confirmation'
    assert store.recover_expired() == 1
    failed = TaskStore(owner).get(task['id'])
    assert failed['status'] == 'failed' and failed['error_code'] == 'plot_container_expired'
    assert store.recover_expired() == 0 and provider.posts == ['container', 'upload']
    with database_connection() as db:
        assert {row['status'] for row in db.execute('SELECT status FROM budget_reservations')} == {'held'}
