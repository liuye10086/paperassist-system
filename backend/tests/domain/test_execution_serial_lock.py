"""Host lock checks use tiny Python processes, with no DB, broker or model."""
from pathlib import Path
from contextlib import contextmanager
import subprocess
import sys
import time

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def child(lock_path, *, mode='normal'):
    code = '''
import sys, time
from app.domain.tasks.serial_execution import file_lock
with file_lock(sys.argv[1]) as acquired:
    print('entered', flush=True)
    if sys.argv[2] == 'wait':
        sys.stdin.readline()
    elif sys.argv[2] == 'error':
        raise RuntimeError('test unwind')
    elif sys.argv[2] == 'cancel':
        raise SystemExit(0)
    print('leaving', flush=True)
'''
    return subprocess.Popen([sys.executable, '-c', code, str(lock_path), mode],
        cwd=Path(__file__).resolve().parents[2], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_processes_never_enter_shared_execution_slot_together(tmp_path):
    from app.domain.tasks.serial_execution import file_lock
    path = tmp_path / 'shared.lock'
    first = child(path, mode='wait')
    second = None
    try:
        assert first.stdout.readline().strip() == 'entered'
        with file_lock(path, blocking=False) as acquired:
            assert not acquired
        second = child(path)
        time.sleep(.15)
        assert second.poll() is None
        first.communicate('\n', timeout=10)
        output, error = second.communicate(timeout=10)
        assert second.returncode == 0, error
        assert output.splitlines() == ['entered', 'leaving']
    finally:
        for process in (first, second):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=10)


@pytest.mark.parametrize('mode', ['error', 'cancel', 'killed'])
def test_exception_cancel_and_process_exit_release_slot(tmp_path, mode):
    from app.domain.tasks.serial_execution import file_lock
    path = tmp_path / 'worker.lock'
    process = child(path, mode='wait' if mode == 'killed' else mode)
    try:
        assert process.stdout.readline().strip() == 'entered'
        if mode == 'killed':
            process.kill()
        process.communicate(timeout=10)
        with file_lock(path, blocking=False) as acquired:
            assert acquired
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


def test_execution_path_shares_explicit_host_override(monkeypatch, tmp_path):
    from app.domain.tasks.serial_execution import execution_lock_path
    shared = tmp_path / 'host' / 'worker.lock'
    monkeypatch.setenv('PAPERASSIST_EXECUTION_LOCK_FILE', str(shared))
    assert execution_lock_path(tmp_path / 'one') == shared
    assert execution_lock_path(tmp_path / 'two') == shared
    monkeypatch.delenv('PAPERASSIST_EXECUTION_LOCK_FILE')
    assert execution_lock_path(tmp_path / 'one') == tmp_path / 'one' / '.worker-execution.lock'


def test_run_task_keeps_slot_through_executor_unwind(monkeypatch, tmp_path):
    from app.domain.tasks import execution
    from app.domain.tasks.serial_execution import file_lock, execution_lock_path
    path = execution_lock_path(tmp_path)
    observed = []
    def dispatch(*args, **kwargs):
        with file_lock(path, blocking=False) as acquired:
            observed.append(acquired)
        raise RuntimeError('executor stopped after cancellation')
    class EmptyRepository:
        def __init__(self, **kwargs):
            pass
        @contextmanager
        def connection(self):
            yield self
        def execute(self, *args):
            return self
        def fetchone(self):
            return None
    monkeypatch.setattr(execution, 'TaskExecutionStore', EmptyRepository)
    monkeypatch.setattr(execution, '_run_task_in_slot', dispatch, raising=False)
    with pytest.raises(RuntimeError, match='executor stopped after cancellation'):
        execution.run_task('task', 1, directory=tmp_path, config=object())
    assert observed == [False]
    with file_lock(path, blocking=False) as acquired:
        assert acquired
