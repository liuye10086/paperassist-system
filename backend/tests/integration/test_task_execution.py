"""Real PostgreSQL and local DOCX execution; no broker or model is contacted."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from app.db.database import database_connection
from app.domain.tasks.contracts import TaskCreateRequest
from app.domain.tasks.service import TaskService
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.integration.test_reports import report_ready
from tests.helpers.tasks import task_owner


def queued(client, key='word-request'):
    base, file, result, figure, explanation, url = report_ready(client)
    task, _ = TaskService(task_owner(client)).create(base.split('/')[4], TaskCreateRequest(
        task_type='word_report', file_id=file['id'], analysis_run_id=result['id'],
        expected_revision=result['setup_revision'], figure_id=figure['id'], explanation_id=explanation['id']),
        idempotency_key=key)
    return task, base, result, url


def expired(lease):
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s AND attempt_no=%s",
                   (lease.task_id, lease.attempt_no))


def test_real_word_execution_saves_success_and_duplicate_message_is_noop(client, cloud, writer, tmp_path):
    from app.domain.tasks.execution import run_word_task
    task, _, _, url = queued(client)
    finished = run_word_task(task['id'], task['revision'])
    assert finished['status'] == 'succeeded' and finished['result_report_id']
    download = client.get(url + '/' + finished['result_report_id'] + '/download')
    assert download.status_code == 200 and download.content.startswith(b'PK')
    assert run_word_task(task['id'], task['revision']) is None
    with database_connection() as db:
        reports = db.execute('SELECT * FROM reports').fetchall()
        assert len(reports) == 1
        assert json.loads(reports[0]['report_json'])['created_at'].endswith('+00:00')
        assert len(db.execute('SELECT * FROM task_attempts').fetchall()) == 1
        assert [r['event_type'] for r in db.execute('SELECT * FROM task_events ORDER BY seq')] == ['created', 'started', 'succeeded']
    assert len(list((tmp_path / 'data' / 'reports').glob('*.docx'))) == 1


def test_claim_competition_and_heartbeat_does_not_add_events(client, cloud, writer):
    from app.adapters.task_execution_store import TaskExecutionStore
    task, *_ = queued(client)
    store = TaskExecutionStore()
    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(lambda _: store.claim(task['id'], task['revision']), range(2)))
    lease = next(item for item in leases if item)
    assert sum(item is not None for item in leases) == 1
    assert store.heartbeat(lease)
    with database_connection() as db:
        attempt = db.execute('SELECT * FROM task_attempts').fetchone()
        assert attempt['heartbeat_at'] >= attempt['started_at']
        assert attempt['lease_expires_at'] > attempt['heartbeat_at']
        assert len(db.execute('SELECT * FROM task_events').fetchall()) == 2


def test_expired_lease_requeues_and_fences_old_worker(client, cloud, writer):
    from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
    from app.domain.tasks.execution import run_word_task
    task, *_ = queued(client)
    store = TaskExecutionStore()
    old = store.claim(task['id'], task['revision'])
    expired(old)
    assert store.recover_expired() == 1
    assert not store.heartbeat(old)
    with pytest.raises(LeaseLost):
        store.fail(old, 'storage_unavailable')
    with database_connection() as db:
        current = db.execute('SELECT * FROM tasks WHERE id=%s', (task['id'],)).fetchone()
    assert current['status'] == 'queued'
    done = run_word_task(task['id'], current['revision'])
    assert done['status'] == 'succeeded' and done['current_attempt'] == 2


def test_lost_workers_stop_after_three_attempts(client, cloud, writer):
    from app.adapters.task_execution_store import TaskExecutionStore
    task, *_ = queued(client)
    store = TaskExecutionStore()
    for number in range(1, 4):
        with database_connection() as db:
            revision = db.execute('SELECT revision FROM tasks WHERE id=%s', (task['id'],)).fetchone()['revision']
        lease = store.claim(task['id'], revision)
        assert lease.attempt_no == number
        expired(lease)
        assert store.recover_expired() == 1
    with database_connection() as db:
        current = db.execute('SELECT * FROM tasks').fetchone()
    assert current['status'] == 'failed' and current['error_code'] == 'task_worker_interrupted'


def test_queued_configuration_change_fails_without_report(client, cloud, writer, tmp_path):
    from app.domain.tasks.execution import run_word_task
    task, base, result, _ = queued(client)
    client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'new'})
    done = run_word_task(task['id'], task['revision'])
    assert done['status'] == 'failed' and done['error_code'] == 'task_source_conflict'
    assert not list((tmp_path / 'data').rglob('*.docx'))


@pytest.mark.parametrize('timing', ['queued', 'rendered'])
def test_disabled_owner_does_not_publish_report(client, cloud, writer, monkeypatch, timing):
    from app.domain.tasks import execution
    task, *_ = queued(client)
    owner = task_owner(client)
    def disable():
        with database_connection(write=True) as db:
            db.execute('UPDATE users SET active=FALSE WHERE id=%s', (owner,))
    if timing == 'queued':
        disable()
    else:
        original = execution.build_report
        def build(*args):
            content = original(*args)
            disable()
            return content
        monkeypatch.setattr(execution, 'build_report', build)
    execution.run_word_task(task['id'], task['revision'])
    with database_connection() as db:
        current = db.execute('SELECT * FROM tasks').fetchone()
        assert current['status'] == 'failed' and current['error_code'] == 'task_owner_unavailable'
        assert not db.execute('SELECT * FROM reports').fetchall()


def test_report_and_terminal_state_rollback_together(client, cloud, writer, monkeypatch):
    from app.domain.tasks.execution import run_word_task
    from app.adapters.task_store import TaskStore
    task, *_ = queued(client)
    append = TaskStore.append_event
    def rejected(db, current, event_type):
        if event_type == 'succeeded':
            raise RuntimeError('injected before commit')
        return append(db, current, event_type)
    with monkeypatch.context() as patch:
        patch.setattr(TaskStore, 'append_event', staticmethod(rejected))
        run_word_task(task['id'], task['revision'])
    with database_connection() as db:
        assert not db.execute('SELECT * FROM reports').fetchall()
        current = db.execute('SELECT * FROM tasks').fetchone()
        assert current['status'] != 'succeeded' and current['result_report_id'] is None


def test_source_tasks_share_one_report(client, cloud, writer):
    from app.domain.tasks.execution import run_word_task
    first, *_ = queued(client)
    with database_connection() as db:
        source = db.execute('SELECT * FROM tasks').fetchone()
    snap = source['input_snapshot']
    second, _ = TaskService(source['user_id']).create(source['project_id'], TaskCreateRequest(
        task_type='word_report', file_id=snap['file']['id'], analysis_run_id=snap['result']['id'],
        expected_revision=snap['result']['setup_revision'], figure_id=snap['figure']['id'],
        explanation_id=snap['explanation']['id']), idempotency_key='another-request')
    one = run_word_task(first['id'], first['revision'])
    two = run_word_task(second['id'], second['revision'])
    assert one['result_report_id'] == two['result_report_id']
    with database_connection() as db:
        assert len(db.execute('SELECT * FROM reports').fetchall()) == 1


def test_stage_write_failure_removes_only_its_new_partial(client, cloud, writer, monkeypatch, tmp_path):
    from app.domain.tasks.execution import run_word_task
    import os
    task, *_ = queued(client)
    monkeypatch.setattr(os, 'fsync', lambda _: (_ for _ in ()).throw(OSError('disk unavailable')))
    result = run_word_task(task['id'], task['revision'])
    assert result['status'] == 'failed' and result['error_code'] == 'storage_unavailable'
    assert not list((tmp_path / 'data').rglob('*.part'))


def test_stage_collision_never_deletes_existing_attempt_file(client, cloud, writer):
    from app.adapters.task_execution_store import TaskExecutionStore
    task, *_ = queued(client)
    store = TaskExecutionStore()
    lease = store.claim(task['id'], task['revision'])
    staged = store.stage(lease, b'owned-first-write')
    with pytest.raises(FileExistsError):
        store.stage(lease, b'conflicting-second-write')
    assert staged.read_bytes() == b'owned-first-write'


def test_claim_tolerates_small_clock_skew(client, cloud, writer):
    from app.adapters.task_execution_store import TaskExecutionStore
    task, *_ = queued(client)
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET created_at=clock_timestamp()+interval '2 seconds', updated_at=clock_timestamp()+interval '2 seconds' WHERE id=%s", (task['id'],))
    assert TaskExecutionStore().claim(task['id'], task['revision'])


def test_uncommitted_candidate_is_reused_without_stale_lease_overwrite(client, cloud, writer, monkeypatch, tmp_path):
    from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
    from app.domain.tasks.execution import run_word_task
    from app.adapters.report_docx import build_report
    from app.adapters.task_store import TaskStore
    task, *_ = queued(client)
    store = TaskExecutionStore()
    old = store.claim(task['id'], task['revision'])
    snapshot, report, png = store.load(old)
    content = build_report(snapshot, report, png)
    staged = store.stage(old, content)
    append = TaskStore.append_event
    def rejected(db, current, kind):
        if kind == 'succeeded':
            raise RuntimeError('commit not reached')
        return append(db, current, kind)
    with monkeypatch.context() as patch:
        patch.setattr(TaskStore, 'append_event', staticmethod(rejected))
        with pytest.raises(RuntimeError):
            store.complete(old, snapshot, report, staged, content)
    candidate = tmp_path / 'data' / 'reports' / (report['id'] + '.docx')
    assert candidate.read_bytes() == content
    with database_connection() as db:
        assert not db.execute('SELECT * FROM reports').fetchall()
    expired(old)
    store.recover_expired()
    with database_connection() as db:
        task = dict(db.execute('SELECT * FROM tasks').fetchone())
    done = run_word_task(task['id'], task['revision'])
    assert done['status'] == 'succeeded' and done['result_report_id'] == report['id']
    saved = candidate.read_bytes()
    stale_part = store.stage(old, b'old-worker-content')
    with pytest.raises(LeaseLost):
        store.complete(old, snapshot, report, stale_part, b'old-worker-content')
    stale_part.unlink()
    assert candidate.read_bytes() == saved
    assert len(list(candidate.parent.glob('*.docx'))) == 1
