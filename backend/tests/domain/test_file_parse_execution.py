"""Fenced parser publication through a deterministic injected parser."""
from datetime import datetime, timedelta, timezone

import pytest

from tests.api.test_projects import client, create_project  # noqa: F401
from tests.api.test_file_batches import register
from app.db.database import database_connection
from app.adapters.excel import parse_workbook
from app.core.config import ExcelSettings
from app.core.exceptions import StorageError
from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost


def queued(client):
    project = create_project(client)
    base, batch, item, content = register(client, project)
    result = client.post(base + '/' + batch['id'] + '/items/' + item['client_id'],
                         files={'file': (item['filename'], content)})
    assert result.status_code == 202, result.text
    return project, result.json(), content


def deterministic(content, filename, settings, **kwargs):
    return parse_workbook(content, filename, ExcelSettings(**settings['excel']))


def test_parse_success_duplicate_delivery_and_revision(client):
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    project, item, _ = queued(client)
    result = run_parse_file_task(item['task']['id'], 1, parser=deterministic)
    assert result['status'] == 'succeeded'
    assert run_parse_file_task(item['task']['id'], 1, parser=deterministic) is None
    url = f"/api/v1/projects/{project['id']}/files/{item['file_id']}"
    details = client.get(url + '/details').json()
    assert details['parse_status'] == 'parsed' and details['parse_revision'] == 3
    assert details['source']['kind'] == 'excel_parse'
    assert client.get(url + '/preview').status_code == 200
    with database_connection() as db:
        saved = db.execute('SELECT * FROM file_parse_results').fetchone()
        assert saved['result_json']['preview']['filename'] == 'data.xlsx'
        assert saved['completed_at'] is not None


@pytest.mark.parametrize('session_timezone,project_is_newer', [
    ('Asia/Shanghai', False), ('Asia/Shanghai', True), ('UTC', False),
])
def test_parse_publication_keeps_project_timestamp_utc_and_monotonic(client, monkeypatch, session_timezone, project_is_newer):
    from app.adapters.file_parse_store import FileParseStore
    project, item, content = queued(client)
    repository = TaskExecutionStore()
    lease = repository.claim(item['task']['id'], 1, task_type='parse_file')
    store = FileParseStore(repository)
    snapshot, _ = store.load(lease)
    prior = datetime.now(timezone.utc) + timedelta(hours=1 if project_is_newer else -1)
    with database_connection(write=True) as db:
        db.execute('UPDATE projects SET updated_at=%s WHERE id=%s', (prior.isoformat(), project['id']))
    original_now = repository.now

    def session_now(db):
        db.execute("SELECT set_config('TimeZone', %s, true)", (session_timezone,))
        value = original_now(db)
        assert value.utcoffset() == timedelta(hours=8 if session_timezone == 'Asia/Shanghai' else 0)
        return value

    monkeypatch.setattr(repository, 'now', session_now)
    assert store.complete(lease, snapshot, deterministic(content, 'data.xlsx', snapshot['settings']))['status'] == 'succeeded'
    with database_connection() as db:
        completed = db.execute('SELECT completed_at FROM file_parse_results WHERE task_id=%s', (item['task']['id'],)).fetchone()['completed_at']
        saved = db.execute('SELECT updated_at FROM projects WHERE id=%s', (project['id'],)).fetchone()['updated_at']
    assert saved == max(prior, completed).astimezone(timezone.utc).isoformat()


def test_parse_failure_retry_resume_and_fixed_source(client):
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    _, item, _ = queued(client)
    def timeout(*args, **kwargs):
        raise StorageError('parse_timeout', 'timeout', 422)
    failed = run_parse_file_task(item['task']['id'], 1, parser=timeout)
    assert failed['status'] == 'failed' and failed['error_code'] == 'parse_timeout'
    url = '/api/v1/tasks/' + failed['id']
    assert client.get(url + '/workspace').json()['allowed_actions'] == ['retry']
    retry = client.post(url + '/resume', headers={'Idempotency-Key': 'retry'}, json={
        'operation': 'retry', 'wait_id': None, 'expected_task_revision': failed['revision'],
        'input_version': failed['input_version']})
    assert retry.status_code == 202, retry.text
    assert retry.json()['status'] == 'queued'
    success = run_parse_file_task(failed['id'], retry.json()['revision'], parser=deterministic)
    assert success['status'] == 'succeeded' and success['input_version'] == failed['input_version']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM file_parse_results').fetchone()['n'] == 1


def test_expired_lease_fenced_and_recovered(client):
    from app.adapters.file_parse_store import FileParseStore
    _, item, content = queued(client)
    repository = TaskExecutionStore()
    lease = repository.claim(item['task']['id'], 1, task_type='parse_file')
    assert lease is not None
    parse_store = FileParseStore(repository)
    snapshot, raw = parse_store.load(lease)
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second'")
    with pytest.raises(LeaseLost):
        parse_store.complete(lease, snapshot, deterministic(content, 'data.xlsx', snapshot['settings']))
    assert repository.recover_expired() == 1
    with database_connection() as db:
        file = db.execute('SELECT * FROM files').fetchone()
        assert file['parse_status'] == 'queued' and file['parse_revision'] == 4
        task = db.execute('SELECT * FROM tasks').fetchone()
        assert task['status'] == 'queued'
        assert db.execute('SELECT result_json FROM file_parse_results').fetchone()['result_json'] is None


@pytest.mark.parametrize('code', ['invalid_workbook', 'workbook_too_large', 'parse_failed', 'parse_output_invalid'])
def test_deterministic_failure_never_offers_retry(client, code):
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    _, item, _ = queued(client)
    def invalid(*args, **kwargs):
        raise StorageError(code, 'unsafe source details must not escape', 422)
    failed = run_parse_file_task(item['task']['id'], 1, parser=invalid)
    url = '/api/v1/tasks/' + failed['id']
    workspace = client.get(url + '/workspace').json()
    assert workspace['allowed_actions'] == []
    assert client.post(url + '/retry', json={'expected_revision': failed['revision']}).status_code == 409
    with database_connection() as db:
        file = db.execute('SELECT * FROM files').fetchone()
        assert file['parse_status'] == 'failed' and file['parse_revision'] == 3
        assert 'unsafe source' not in file['error_json']
        assert db.execute('SELECT result_json FROM file_parse_results').fetchone()['result_json'] is None


@pytest.mark.parametrize('change', ['bytes', 'metadata', 'owner'])
def test_changed_source_or_disabled_owner_cannot_publish(client, change):
    from app.adapters.file_parse_store import FileParseStore
    from app.core.config import get_data_dir
    _, item, content = queued(client)
    repository = TaskExecutionStore()
    lease = repository.claim(item['task']['id'], 1, task_type='parse_file')
    store = FileParseStore(repository)
    snapshot, _ = store.load(lease)
    if change == 'bytes':
        (get_data_dir() / snapshot['file']['object_key']).write_bytes(b'x' * len(content))
    else:
        with database_connection(write=True) as db:
            if change == 'metadata':
                db.execute("UPDATE files SET sha256=%s", ('b' * 64,))
            else:
                db.execute('UPDATE users SET active=false')
    with pytest.raises(StorageError) as caught:
        store.complete(lease, snapshot, deterministic(content, 'data.xlsx', snapshot['settings']))
    assert caught.value.code in ('file_changed', 'task_source_conflict', 'task_owner_unavailable')
    with database_connection() as db:
        assert db.execute('SELECT status FROM tasks').fetchone()['status'] == 'running'
        assert db.execute('SELECT result_json FROM file_parse_results').fetchone()['result_json'] is None


def test_publication_transaction_failure_rolls_back_all_outputs(client, reject_database_write):
    from app.adapters.file_parse_store import FileParseStore
    _, item, content = queued(client)
    repository = TaskExecutionStore()
    lease = repository.claim(item['task']['id'], 1, task_type='parse_file')
    store = FileParseStore(repository)
    snapshot, _ = store.load(lease)
    with reject_database_write('files', 'UPDATE'):
        with pytest.raises(StorageError):
            store.complete(lease, snapshot, deterministic(content, 'data.xlsx', snapshot['settings']))
    with database_connection() as db:
        file = db.execute('SELECT * FROM files').fetchone()
        assert file['parse_status'] == 'parsing' and file['preview_json'] is None and file['parse_revision'] == 2
        assert db.execute('SELECT status FROM tasks').fetchone()['status'] == 'running'
        assert db.execute("SELECT count(*) AS n FROM task_events WHERE event_type='succeeded'").fetchone()['n'] == 0
        assert db.execute('SELECT result_json FROM file_parse_results').fetchone()['result_json'] is None
    assert store.complete(lease, snapshot, deterministic(content, 'data.xlsx', snapshot['settings']))['status'] == 'succeeded'


def test_crash_recovery_stops_after_three_attempts_and_old_token_cannot_fail(client):
    from app.adapters.file_parse_store import FileParseStore
    _, item, content = queued(client)
    repository = TaskExecutionStore()
    task_id = item['task']['id']
    first = None
    for attempt in range(1, 4):
        with database_connection() as db:
            revision = db.execute('SELECT revision FROM tasks').fetchone()['revision']
        lease = repository.claim(task_id, revision, task_type='parse_file')
        assert lease.attempt_no == attempt
        first = first or lease
        with database_connection(write=True) as db:
            db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE attempt_no=%s", (attempt,))
        assert repository.recover_expired() == 1
    with pytest.raises(LeaseLost):
        FileParseStore(repository).fail(first, 'parse_timeout')
    with database_connection() as db:
        assert db.execute('SELECT status FROM tasks').fetchone()['status'] == 'failed'
        assert db.execute('SELECT parse_status FROM files').fetchone()['parse_status'] == 'failed'
        assert db.execute('SELECT result_json FROM file_parse_results').fetchone()['result_json'] is None


@pytest.mark.parametrize('mutation', ['schema', 'kind', 'extra', 'workflow', 'file_extra', 'settings_extra', 'bool_version'])
def test_parse_snapshot_strict_dispatch_rejects_unknown_shape(client, mutation):
    from app.domain.file_parsing import validate_snapshot
    _, item, _ = queued(client)
    with database_connection() as db:
        task = dict(db.execute('SELECT * FROM tasks').fetchone())
    snapshot = task['input_snapshot']
    if mutation == 'schema': snapshot['schema_version'] = 2
    elif mutation == 'bool_version': snapshot['schema_version'] = True
    elif mutation == 'kind': snapshot['kind'] = 'boxplot'
    elif mutation == 'extra': snapshot['result'] = {}
    elif mutation == 'workflow': task['workflow_version'] = 'word_report_v1'
    elif mutation == 'file_extra': snapshot['file']['password'] = 'bad'
    else: snapshot['settings']['process']['unlimited'] = True
    with pytest.raises(StorageError) as caught:
        validate_snapshot(task)
    assert caught.value.code == 'task_source_conflict'
