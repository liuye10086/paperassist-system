"""A local numerical failure is terminal, without retrying cloud generation."""
from contextlib import contextmanager
from importlib import import_module
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def fail_node(*args, **kwargs):
    from app.domain.fixed_statistics_runtime import numeric_execution_scope
    from app.domain.regression.common import NumericError
    with numeric_execution_scope():
        raise NumericError('numeric_timeout', '统计节点期限已到。')


@pytest.mark.parametrize('module,entry', [
    ('app.domain.figure_workbench.execution', 'run_figure_workbench_task'),
    ('app.domain.figure_workbench.execution', 'run_figure_explanation_task'),
    ('app.domain.tasks.boxplot_execution', 'run_boxplot_task'),
    ('app.domain.tasks.explanation_execution', 'run_explanation_task'),
    ('app.domain.tasks.execution', 'run_word_task'),
])
def test_numeric_timeout_finishes_once_with_receipt(monkeypatch, module, entry):
    worker = import_module(module)
    failures = []
    class Repository:
        def __init__(self, **kwargs): pass
        def claim(self, *args, **kwargs): return SimpleNamespace(attempt_no=1)
        def fail(self, lease, code, *, execution_receipt=None):
            failures.append((code, execution_receipt))
            return {'status': 'failed', 'error_code': code}
        load = staticmethod(fail_node)
    monkeypatch.setattr(worker, 'TaskExecutionStore', Repository)
    if entry != 'run_word_task':
        monkeypatch.setattr(worker, '_execute', fail_node)
    result = getattr(worker, entry)('synthetic-task', 1)
    assert result == {'status': 'failed', 'error_code': 'numeric_timeout'}
    assert failures == [('numeric_timeout', dict(schema_version=1, status='failed',
                                               nodes=[], error_code='numeric_timeout'))]


def test_scope_keeps_only_actual_measured_nodes_on_failure():
    from app.domain.fixed_statistics_runtime import numeric_execution_scope, record_execution, scope_active
    from app.domain.regression.common import NumericError
    measured = {'elapsed_seconds': .01, 'child_cpu_seconds': None}
    with pytest.raises(NumericError) as caught:
        with numeric_execution_scope():
            record_execution(measured)
            fail_node()
    assert caught.value.execution_receipt['nodes'] == [measured]
    assert not scope_active()


def test_fail_persists_receipt_with_task_status(monkeypatch):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.adapters.task_store import TaskStore
    task = {'id': 'synthetic-task'}
    finished = []
    class Repository(TaskExecutionStore):
        def __init__(self): pass
        @contextmanager
        def connection(self, **kwargs): yield None
        def require_lease(self, db, lease): return task
        def _finish(self, db, row, status, code):
            assert row['execution_receipt']['status'] == 'failed'
            finished.append((status, code))
    monkeypatch.setattr(TaskStore, 'public_task', lambda row: row)
    receipt = dict(schema_version=1, status='failed', nodes=[], error_code='numeric_timeout')
    result = Repository().fail(None, 'numeric_timeout', execution_receipt=receipt)
    assert result['execution_receipt'] == receipt
    assert finished == [('failed', 'numeric_timeout')]
