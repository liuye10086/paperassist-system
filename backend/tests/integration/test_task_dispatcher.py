from app.db.database import database_connection
from tests.integration.test_task_execution import queued
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
import pytest


def test_dispatch_failure_keeps_outbox_and_later_confirmation_marks_it(client, cloud, writer):
    from app.workers.dispatcher import dispatch_once
    task, *_ = queued(client)
    calls = []
    def offline(message):
        calls.append(message)
        raise OSError('broker down with private information')
    assert dispatch_once(publish=offline) == 0
    with database_connection(write=True) as db:
        row = db.execute('SELECT * FROM task_outbox').fetchone()
        assert row['published_at'] is None and row['publish_attempts'] == 1
        db.execute("UPDATE task_outbox SET available_at=clock_timestamp()-interval '1 second'")
    assert dispatch_once(publish=lambda message: calls.append(message)) == 1
    assert all(set(call) == {'id', 'task_id', 'task_revision'} for call in calls)
    assert calls[0]['task_id'] == task['id']
    with database_connection() as db:
        row = db.execute('SELECT * FROM task_outbox').fetchone()
        assert row['published_at'] is not None and row['publish_attempts'] == 2
        assert db.execute('SELECT status FROM tasks').fetchone()['status'] == 'queued'


def test_confirmed_message_before_database_mark_can_be_replayed_safely(client, cloud, writer, monkeypatch):
    from app.workers.dispatcher import dispatch_once
    from app.db.database import DatabaseConnection
    from app.domain.tasks.execution import run_word_task
    task, *_ = queued(client)
    calls = []
    execute = DatabaseConnection.execute
    def fail_mark(self, sql, parameters=()):
        if sql.startswith('UPDATE task_outbox SET published_at='):
            raise RuntimeError('lost connection after confirm')
        return execute(self, sql, parameters)
    with monkeypatch.context() as patch:
        patch.setattr(DatabaseConnection, 'execute', fail_mark)
        with pytest.raises(RuntimeError):
            dispatch_once(publish=lambda message: calls.append(message))
    assert len(calls) == 1
    with database_connection(write=True) as db:
        assert db.execute('SELECT published_at FROM task_outbox').fetchone()['published_at'] is None
        db.execute("UPDATE task_outbox SET available_at=clock_timestamp()-interval '1 second'")
    assert dispatch_once(publish=lambda message: calls.append(message)) == 1
    assert calls[0] == calls[1]
    results = [run_word_task(call['task_id'], call['task_revision']) for call in calls]
    assert results[0]['status'] == 'succeeded' and results[1] is None
