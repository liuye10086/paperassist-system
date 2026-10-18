"""Collection failure receipts and publication fences without a database or kernel."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_collection_numeric_failure_keeps_code_and_receipt(monkeypatch, tmp_path):
    from app.domain.report_collections import execution
    from app.domain.regression.common import NumericError
    from app.domain.fixed_statistics_runtime import scope_active

    task = {'id': 'synthetic-task', 'user_id': 'synthetic-owner', 'status': 'running'}
    updates, finished = [], []

    class Repository:
        config = None
        assets = SimpleNamespace(directory=tmp_path)

        def __init__(self, **kwargs): pass
        def claim(self, *args, **kwargs): return SimpleNamespace(lease_owner='synthetic-lease')
        def require_lease(self, db, lease): return task
        def require_owner(self, db, row): pass

        @contextmanager
        def connection(self, **kwargs):
            yield SimpleNamespace(execute=lambda sql, args: updates.append((sql, args)))

        def _finish(self, db, row, status, code):
            assert not scope_active(), 'Persist failure after the expired numeric scope ends.'
            finished.append((status, code, deepcopy(row.get('execution_receipt'))))
            row.update(status=status, error_code=code)

    def fail_verification(*args):
        raise NumericError('numeric_timeout', 'synthetic deadline')

    monkeypatch.setattr(execution, 'TaskExecutionStore', Repository)
    monkeypatch.setattr(execution, 'scoped_store', lambda *args: None)
    monkeypatch.setattr(execution, 'CollectionStore', lambda store:
                        SimpleNamespace(verify_task_snapshot=fail_verification))
    monkeypatch.setattr(execution.TaskStore, 'public_task', lambda row: deepcopy(row))
    result = execution.run_collection_word_task(task['id'], 1)

    receipt = dict(schema_version=1, status='failed', nodes=[], error_code='numeric_timeout')
    assert result['status'] == 'failed'
    assert result['error_code'] == 'numeric_timeout'
    assert result['execution_receipt'] == receipt
    assert finished == [('failed', 'numeric_timeout', receipt)]
    assert len(updates) == 1
    assert updates[0][1] == ('numeric_timeout', task['id'])
    assert not list(tmp_path.iterdir())


def test_collection_rechecks_lease_after_report_insert_before_success(monkeypatch, tmp_path):
    from app.domain.report_collections import execution
    from app.adapters.task_execution_store import LeaseLost

    task = {'id': 'synthetic-task', 'user_id': 'synthetic-owner', 'status': 'running'}
    snapshot = dict(build_request_id='synthetic-build', collection_id='synthetic-collection',
                    collection_version_id='synthetic-version', export_revision=1, language='en', items=[])
    lease_checks, writes, finished, transactions = [], [], [], []

    class Repository:
        config = None
        assets = SimpleNamespace(directory=tmp_path)

        def __init__(self, **kwargs): pass
        def claim(self, *args, **kwargs): return SimpleNamespace(lease_owner='synthetic-lease')
        def require_owner(self, db, row): pass

        def require_lease(self, db, lease):
            lease_checks.append(True)
            if any(sql.startswith('INSERT INTO collection_reports') for sql in writes):
                raise LeaseLost()
            return task

        @contextmanager
        def connection(self, *, write=False):
            def execute(sql, args):
                if write: writes.append(sql)
                return SimpleNamespace(fetchone=lambda: None)
            try:
                yield SimpleNamespace(execute=execute)
            except Exception:
                if write: transactions.append('rolled_back')
                raise
            else:
                if write: transactions.append('committed')

        def _finish(self, db, row, status, code):
            finished.append((status, code))
            row.update(status=status)

    collection = SimpleNamespace(directory=tmp_path / 'reports', store=SimpleNamespace(),
                                 verify_task_snapshot=lambda *args: deepcopy(snapshot))
    monkeypatch.setattr(execution, 'TaskExecutionStore', Repository)
    monkeypatch.setattr(execution, 'scoped_store', lambda *args: None)
    monkeypatch.setattr(execution, 'CollectionStore', lambda store: collection)
    monkeypatch.setattr(execution, 'build_collection_report', lambda *args: b'synthetic-docx')
    monkeypatch.setattr(execution.TaskStore, 'public_task', lambda row: deepcopy(row))

    assert execution.run_collection_word_task(task['id'], 1) is None
    assert len(lease_checks) == 3
    assert any(sql.startswith('INSERT INTO collection_reports') for sql in writes)
    assert transactions == ['rolled_back']
    assert finished == []
    assert task['status'] == 'running'
    assert not list(collection.directory.glob('*.part'))


def test_word_render_numeric_timeout_is_not_reclassified_as_format_error(monkeypatch):
    from app.domain.tasks import execution
    from app.domain.regression.common import NumericError

    failures = []

    class Repository:
        def __init__(self, **kwargs): pass
        def claim(self, *args, **kwargs): return SimpleNamespace(attempt_no=1)
        def load(self, lease): return {}, {}, b'synthetic-png'
        def fail(self, lease, code, *, execution_receipt=None):
            failures.append((code, execution_receipt))
            return {'status': 'failed', 'error_code': code}

    def render(*args):
        raise NumericError('numeric_timeout', 'synthetic render deadline')

    monkeypatch.setattr(execution, 'TaskExecutionStore', Repository)
    monkeypatch.setattr(execution, 'build_report', render)
    assert execution.run_word_task('synthetic-task', 1) == {
        'status': 'failed', 'error_code': 'numeric_timeout'}
    assert failures == [('numeric_timeout', dict(schema_version=1, status='failed',
                                               nodes=[], error_code='numeric_timeout'))]
