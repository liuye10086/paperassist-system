"""Real isolated PostgreSQL transactions; no unified worker or cloud execution."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json

import pytest

from app.core.exceptions import StorageError
from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.helpers.tasks import boxplot_task_input, task_owner


def services(client):
    from app.domain.tasks.service import TaskService
    from app.adapters.task_store import TaskStore
    user = task_owner(client)
    return TaskService(user), TaskStore(user)


def counts():
    with database_connection() as db:
        return {table: db.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n']
                for table in ('tasks', 'task_attempts', 'task_events', 'task_outbox')}


def test_creation_persists_snapshot_event_and_outbox_without_running_business(client):
    project, request, _, result = boxplot_task_input(client)
    service, store = services(client)
    task, created = service.create(project, request, idempotency_key='create-one')
    assert created and task['status'] == 'queued' and task['phase'] == 'compute'
    assert task['revision'] == 1 and task['current_attempt'] == 0
    assert task['input_version'] == {'setup_revision': 1, 'output_language': 'zh-CN'}
    assert counts() == {'tasks': 1, 'task_attempts': 0, 'task_events': 1, 'task_outbox': 1}
    with database_connection() as db:
        raw = db.execute('SELECT * FROM tasks WHERE id=%s', (task['id'],)).fetchone()
        assert raw['input_snapshot']['result'] == result
        assert len(raw['input_digest']) == 64
        assert db.execute('SELECT count(*) AS n FROM figure_jobs').fetchone()['n'] == 0
    assert store.get(task['id']) == task
    assert not {'input_snapshot', 'input_digest', 'idempotency_key', 'user_id'} & task.keys()
    page = store.events(task['id'])
    assert [event['event_type'] for event in page['items']] == ['created']
    assert page['next_cursor'] == 1 and not page['has_more']


def test_idempotency_replay_is_stable_after_config_changes_but_new_request_is_rejected(client):
    project, request, base, result = boxplot_task_input(client)
    service, _ = services(client)
    task, _ = service.create(project, request, idempotency_key='same')
    client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'changed'})
    again, created = service.create(project, request, idempotency_key='same')
    assert not created and again == task
    with pytest.raises(StorageError) as conflict:
        service.create(project, request.model_copy(update={'expected_revision': 2}), idempotency_key='same')
    assert (conflict.value.code, conflict.value.status) == ('task_idempotency_conflict', 409)
    with pytest.raises(StorageError) as stale:
        service.create(project, request, idempotency_key='new')
    assert (stale.value.code, stale.value.status) == ('task_source_conflict', 409)
    assert counts()['tasks'] == 1


def test_concurrent_same_key_creates_one_task_and_one_outbox(client):
    project, request, _, _ = boxplot_task_input(client)
    service, _ = services(client)
    ready = Barrier(4)
    def submit(_):
        ready.wait(timeout=10)
        return service.create(project, request, idempotency_key='concurrent')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(4)))
    assert sum(created for _, created in results) == 1
    assert len({task['id'] for task, _ in results}) == 1
    assert counts() == {'tasks': 1, 'task_attempts': 0, 'task_events': 1, 'task_outbox': 1}


def test_task_event_and_outbox_failure_rolls_back_whole_creation(client, monkeypatch):
    from app.db.database import DatabaseConnection
    project, request, _, _ = boxplot_task_input(client)
    service, _ = services(client)
    original = DatabaseConnection.execute
    def reject(db, sql, parameters=()):
        if sql.startswith('INSERT INTO task_outbox'):
            raise RuntimeError('injected-outbox-failure')
        return original(db, sql, parameters)
    with monkeypatch.context() as patch:
        patch.setattr(DatabaseConnection, 'execute', reject)
        with pytest.raises(RuntimeError, match='injected-outbox-failure'):
            service.create(project, request, idempotency_key='rollback')
    assert all(value == 0 for value in counts().values())
    assert service.create(project, request, idempotency_key='rollback')[1]


def test_task_ownership_is_checked_before_replaying_or_reading(client):
    from app.auth.service import create_user
    from app.domain.tasks.service import TaskService
    from app.adapters.task_store import TaskStore
    project, request, _, _ = boxplot_task_input(client)
    service, store = services(client)
    task, _ = service.create(project, request, idempotency_key='private')
    for role in ('user', 'admin'):
        stranger = create_user(role + '@task.local', 'safe-test-password-2026', role=role)
        other = TaskStore(stranger['id'])
        for operation in (lambda: other.get(task['id']), lambda: other.events(task['id'])):
            with pytest.raises(StorageError) as hidden:
                operation()
            assert (hidden.value.code, hidden.value.status) == ('task_not_found', 404)
        with pytest.raises(StorageError) as hidden:
            TaskService(stranger['id']).create(project, request, idempotency_key='private')
        assert hidden.value.status == 404
    owner_id = task_owner(client)
    with database_connection(write=True) as db:
        db.execute('UPDATE users SET active=false WHERE id=%s', (owner_id,))
    for operation in (lambda: store.get(task['id']),
                      lambda: service.create(project, request, idempotency_key='private')):
        with pytest.raises(StorageError) as disabled:
            operation()
        assert disabled.value.status == 404


def test_same_owner_cross_project_and_cross_file_sources_are_rejected(client):
    project, request, _, _ = boxplot_task_input(client)
    other_project, other_request, _, _ = boxplot_task_input(client)
    service, _ = services(client)
    for owner_project, inputs in [(other_project, request),
            (project, request.model_copy(update={'analysis_run_id': other_request.analysis_run_id}))]:
        with pytest.raises(StorageError) as rejected:
            service.create(owner_project, inputs, idempotency_key='wrong-chain')
        assert rejected.value.status in (404, 409)
    assert counts()['tasks'] == 0


def test_states_attempts_events_and_requeue_are_atomic_and_revision_checked(client):
    project, request, _, _ = boxplot_task_input(client)
    service, store = services(client)
    task, _ = service.create(project, request, idempotency_key='states')
    started = service.transition(task['id'], expected_revision=1, status='running')
    assert started['revision'] == 2 and started['current_attempt'] == 1
    assert service.transition(task['id'], expected_revision=2, status='running') == started
    waiting = service.transition(task['id'], expected_revision=2,
        status='waiting_confirmation', reason_code='submission_unknown')
    assert waiting['display_status'] == 'waiting_confirmation'
    with pytest.raises(StorageError) as conflict:
        service.transition(task['id'], expected_revision=2, status='running')
    assert conflict.value.code == 'task_revision_conflict'
    service.transition(task['id'], expected_revision=3, status='queued', reason_code='confirmation_received')
    service.transition(task['id'], expected_revision=4, status='running')
    service.transition(task['id'], expected_revision=5, status='running', phase='verify')
    final = service.transition(task['id'], expected_revision=6, status='succeeded')
    assert final['revision'] == 7 and final['current_attempt'] == 2
    assert final['display_status'] == 'succeeded' and final['phase'] == 'verify'
    with pytest.raises(StorageError):
        service.transition(task['id'], expected_revision=7, status='queued', reason_code='retry_requested')
    assert counts() == {'tasks': 1, 'task_attempts': 2, 'task_events': 7, 'task_outbox': 2}
    with database_connection() as db:
        attempts = db.execute('SELECT * FROM task_attempts ORDER BY attempt_no').fetchall()
    assert [attempt['status'] for attempt in attempts] == ['waiting_confirmation', 'succeeded']
    assert all(attempt['finished_at'] is not None for attempt in attempts)
    page = store.events(task['id'], after=0, limit=3)
    assert [event['seq'] for event in page['items']] == [1, 2, 3]
    assert page['next_cursor'] == 3 and page['has_more']
    page = store.events(task['id'], after=page['next_cursor'], limit=100)
    assert [event['seq'] for event in page['items']] == [4, 5, 6, 7] and not page['has_more']
    assert store.events(task['id'], after=7)['next_cursor'] == 7


def test_concurrent_revision_updates_commit_only_one_event_and_attempt(client):
    project, request, _, _ = boxplot_task_input(client)
    service, _ = services(client)
    task, _ = service.create(project, request, idempotency_key='race')
    def start(_):
        try:
            return service.transition(task['id'], expected_revision=1, status='running')['status']
        except StorageError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(start, range(2))) == ['running', 'task_revision_conflict']
    assert counts() == {'tasks': 1, 'task_attempts': 1, 'task_events': 2, 'task_outbox': 1}


def test_word_and_explanation_snapshots_bind_existing_artifacts_without_new_calls(client, cloud, writer):
    from app.domain.tasks.contracts import TaskCreateRequest
    from tests.integration.test_reports import report_ready
    base, file, result, figure, explanation, _ = report_ready(client)
    project = base.split('/')[4]
    service, _ = services(client)
    before = (len(cloud.calls), len(writer.calls))
    values = dict(file_id=file['id'], analysis_run_id=result['id'], expected_revision=1, figure_id=figure['id'])
    for task_type, extra in [('explanation', {}), ('word_report', {'explanation_id': explanation['id']})]:
        task, _ = service.create(project, TaskCreateRequest(task_type=task_type, **values, **extra), idempotency_key='same')
        assert task['phase'] == ('interpret' if task_type == 'explanation' else 'export')
    assert before == (len(cloud.calls), len(writer.calls))
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM reports').fetchone()['n'] == 0


def test_reads_and_events_do_not_change_task_or_legacy_job_state(client):
    project, request, _, _ = boxplot_task_input(client)
    service, store = services(client)
    task, _ = service.create(project, request, idempotency_key='readonly')
    before = counts()
    for _ in range(2):
        assert store.get(task['id']) == task
        store.events(task['id'])
    assert counts() == before


@pytest.mark.parametrize('damage', ['run_id', 'run_hash', 'setup_file', 'setup_selection', 'invalid_json', 'nonfinite'])
def test_corrupted_saved_inputs_are_rejected_without_partial_task(client, damage):
    project, request, _, _ = boxplot_task_input(client)
    service, _ = services(client)
    with database_connection(write=True) as db:
        table, column, key = ('analysis_setups', 'setup_json', 'file_id') if damage.startswith('setup') else (
            'analysis_runs', 'result_json', 'id')
        identity = request.file_id if key == 'file_id' else request.analysis_run_id
        value = json.loads(db.execute(f'SELECT {column} FROM {table} WHERE {key}=%s', (identity,)).fetchone()[column])
        if damage == 'run_id':
            value['id'] = 'another-run'
        elif damage == 'run_hash':
            value['source_sha256'] = '0' * 64
        elif damage == 'setup_file':
            value['file_id'] = 'another-file'
        elif damage == 'setup_selection':
            value['selection']['unit'] = 'different unit'
        elif damage == 'nonfinite':
            value['overall']['mean'] = float('nan')
        encoded = '{broken' if damage == 'invalid_json' else json.dumps(value)
        db.execute(f'UPDATE {table} SET {column}=%s WHERE {key}=%s', (encoded, identity))
    with pytest.raises(StorageError) as invalid:
        service.create(project, request, idempotency_key='damaged')
    assert (invalid.value.code, invalid.value.status) == ('task_source_conflict', 409)
    assert all(value == 0 for value in counts().values())


@pytest.mark.parametrize('damage', ['figure_id', 'figure_verification', 'explanation_figure', 'explanation_provenance'])
def test_artifact_snapshot_rejects_inconsistent_saved_source_chain(client, cloud, writer, damage):
    from app.domain.tasks.contracts import TaskCreateRequest
    from tests.integration.test_reports import report_ready
    base, file, result, figure, explanation, _ = report_ready(client)
    service, _ = services(client)
    is_figure = damage.startswith('figure')
    value = figure if is_figure else explanation
    identity = value['id']
    if damage == 'figure_id':
        value['id'] = 'another-figure'
    elif damage == 'figure_verification':
        value['verification']['status'] = 'unverified'
    elif damage == 'explanation_figure':
        value['figure_id'] = 'another-figure'
    else:
        value['provenance']['input_sha256'] = '0' * 64
    table, column = ('figures', 'figure_json') if is_figure else ('explanations', 'explanation_json')
    with database_connection(write=True) as db:
        db.execute(f'UPDATE {table} SET {column}=%s WHERE id=%s', (json.dumps(value), identity))
    inputs = TaskCreateRequest(task_type='word_report', file_id=file['id'], analysis_run_id=result['id'],
        expected_revision=1, figure_id=identity if is_figure else figure['id'], explanation_id=explanation['id'])
    with pytest.raises(StorageError) as invalid:
        service.create(base.split('/')[4], inputs, idempotency_key='broken-chain')
    assert invalid.value.code == 'task_source_conflict'
    assert all(value == 0 for value in counts().values())


def test_transition_event_failure_rolls_back_attempt_and_revision(client, monkeypatch):
    project, request, _, _ = boxplot_task_input(client)
    service, store = services(client)
    task, _ = service.create(project, request, idempotency_key='event-rollback')
    def fail_event(*args):
        raise RuntimeError('synthetic event persistence failure')
    with monkeypatch.context() as patched:
        patched.setattr(service.store, 'append_event', fail_event)
        with pytest.raises(RuntimeError):
            service.transition(task['id'], expected_revision=1, status='running')
    assert store.get(task['id']) == task
    assert counts() == {'tasks': 1, 'task_attempts': 0, 'task_events': 1, 'task_outbox': 1}
    assert service.transition(task['id'], expected_revision=1, status='running')['current_attempt'] == 1


def test_failed_and_input_waiting_require_explicit_requeue_reason(client):
    project, request, _, _ = boxplot_task_input(client)
    service, store = services(client)
    task, _ = service.create(project, request, idempotency_key='explicit-retry')
    service.transition(task['id'], expected_revision=1, status='running')
    waiting = service.transition(task['id'], expected_revision=2, status='waiting_input', reason_code='input_required')
    assert service.transition(task['id'], expected_revision=3, status='waiting_input', reason_code='input_required') == waiting
    for changes in [dict(status='queued'), dict(status='running'), dict(status='waiting_input', reason_code='execution_failed')]:
        with pytest.raises(StorageError) as invalid:
            service.transition(task['id'], expected_revision=3, **changes)
        assert invalid.value.code == 'task_transition_invalid'
    service.transition(task['id'], expected_revision=3, status='queued', reason_code='input_provided')
    service.transition(task['id'], expected_revision=4, status='running')
    service.transition(task['id'], expected_revision=5, status='failed', reason_code='execution_failed')
    service.transition(task['id'], expected_revision=6, status='queued', reason_code='retry_requested')
    assert store.get(task['id'])['revision'] == 7
    assert counts() == {'tasks': 1, 'task_attempts': 2, 'task_events': 7, 'task_outbox': 3}


def test_invalid_internal_transition_types_leave_state_unchanged(client):
    project, request, _, _ = boxplot_task_input(client)
    service, store = services(client)
    task, _ = service.create(project, request, idempotency_key='types')
    for changes in [dict(phase=[]), dict(expected_revision=True), dict(status=[]), dict(reason_code={})]:
        kwargs = dict(expected_revision=1, status='running') | changes
        with pytest.raises(StorageError) as invalid:
            service.transition(task['id'], **kwargs)
        assert invalid.value.code == 'task_transition_invalid'
    assert store.get(task['id']) == task


def test_real_task_http_reads_are_scoped_and_leave_tasks_unchanged(client):
    from app.auth.service import create_user
    project, request, _, _ = boxplot_task_input(client)
    service, store = services(client)
    task, _ = service.create(project, request, idempotency_key='http-real')
    before = counts()
    url = '/api/v1/tasks/' + task['id']
    response = client.get(url)
    assert response.status_code == 200 and response.json() == task
    assert response.headers['X-Request-ID']
    response = client.get(url + '/events')
    assert response.status_code == 200 and response.json() == store.events(task['id'])
    assert counts() == before
    stranger = create_user('task-http-admin@local.test', 'safe-test-password-2026', role='admin')
    assert client.post('/api/v1/auth/login', json={
        'email': stranger['email'], 'password': 'safe-test-password-2026'}).status_code == 200
    for suffix in ('', '/events'):
        response = client.get(url + suffix)
        assert response.status_code == 404 and response.json()['detail']['code'] == 'task_not_found'
    assert counts() == before


@pytest.mark.parametrize('damage', ['missing_hash', 'bad_hash', 'missing_series'])
def test_explanation_requires_complete_figure_metadata(client, cloud, writer, damage):
    from app.domain.tasks.contracts import TaskCreateRequest
    from tests.integration.test_reports import report_ready
    base, file, result, figure, _, _ = report_ready(client)
    if damage == 'missing_hash':
        del figure['sha256']
    elif damage == 'bad_hash':
        figure['sha256'] = 'invalid'
    else:
        del figure['series']
    with database_connection(write=True) as db:
        db.execute('UPDATE figures SET figure_json=%s WHERE id=%s', (json.dumps(figure), figure['id']))
    service, _ = services(client)
    request = TaskCreateRequest(task_type='explanation', file_id=file['id'], analysis_run_id=result['id'],
        expected_revision=1, figure_id=figure['id'])
    with pytest.raises(StorageError) as invalid:
        service.create(base.split('/')[4], request, idempotency_key='figure-metadata')
    assert invalid.value.code == 'task_source_conflict'
    assert counts()['tasks'] == 0
