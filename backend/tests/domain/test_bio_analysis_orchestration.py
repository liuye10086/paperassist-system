"""Finite leased slices retain recovery bytes and never recompute publication."""
import importlib
from types import SimpleNamespace
from pathlib import Path

import pytest
from app.core.exceptions import StorageError


def harness(monkeypatch, tmp_path, *, stage='qc', node='check', kind='bio_analysis', engine_error=False):
    module = importlib.import_module('app.domain.bioinformatics.analysis_execution')
    calls = []
    task = {'id': 'a0158bba-a325-46aa-9b0a-0d0959831ca6', 'task_type': kind}
    checkpoint = {'next_node': node, 'state_json': {'stage': stage}}
    class Repository:
        assets = SimpleNamespace(directory=tmp_path / 'assets')
        def __init__(self, **kwargs): pass
        def claim(self, *args, **kwargs): return SimpleNamespace(task_id=task['id'], attempt_no=1)
        def heartbeat(self, lease): return True
        def fail(self, lease, code): calls.append(('failed', code)); return {'status': 'failed', 'error_code': code}
    class Execution:
        def __init__(self, repo): pass
        def load(self, lease): return task, checkpoint, {'raw': {}, 'config': {}, 'identity': {}}
        def publish_existing(self, lease, current): calls.append(('restore', None)); return {'status': 'succeeded'}
        def wait(self, lease, current, result): calls.append(('wait', result)); return {'status': 'waiting_confirmation'}
        def publish_result(self, lease, current, result): calls.append(('publish', result)); return {'status': 'succeeded'}
    def engine(payload, output, *, mode, **kwargs):
        (output / 'recovery.bin').write_bytes(b'preserved')
        calls.append(('engine', mode))
        if engine_error: raise StorageError('bio_resource_exceeded', 'fixture')
        return {'fixture': 'verified'}
    monkeypatch.setattr(module, 'TaskExecutionStore', Repository)
    monkeypatch.setattr(module, 'execution_store', Execution)
    result = module.run_bio_analysis_task(task['id'], 1, engine=engine,
                staging_directory=tmp_path / 'private-staging', task_type=kind)
    return result, calls


def test_restore_publication_does_not_call_science_engine(monkeypatch, tmp_path):
    result, calls = harness(monkeypatch, tmp_path, node='publish')
    assert result['status'] == 'succeeded'
    assert calls == [('restore', None)]
    assert not (tmp_path / 'private-staging').exists()


@pytest.mark.parametrize('stage,kind,expected', [('qc', 'bio_analysis', 'waiting_confirmation'),
                                                ('compute', 'bio_analysis', 'succeeded'),
                                                ('figure', 'bio_figure', 'succeeded')])
def test_run_uses_confirmed_stage_and_retains_runtime_bytes(monkeypatch, tmp_path, stage, kind, expected):
    result, calls = harness(monkeypatch, tmp_path, stage=stage, kind=kind)
    assert result['status'] == expected
    assert ('engine', stage) in calls
    assert len(list((tmp_path / 'private-staging').rglob('recovery.bin'))) == 1


def test_failed_science_does_not_discard_recovery_material(monkeypatch, tmp_path):
    result, calls = harness(monkeypatch, tmp_path, stage='compute', engine_error=True)
    assert result == {'status': 'failed', 'error_code': 'bio_resource_exceeded'}
    assert not any(name == 'publish' for name, _ in calls)
    assert next((tmp_path / 'private-staging').rglob('recovery.bin')).read_bytes() == b'preserved'


def test_receipt_failure_after_publication_cannot_turn_success_into_failure(monkeypatch, tmp_path):
    module = importlib.import_module('app.domain.bioinformatics.analysis_execution')
    receipt = module._receipt
    def write(attempt, lease, status):
        if status == 'succeeded':
            raise OSError('synthetic final receipt failure')
        return receipt(attempt, lease, status)
    monkeypatch.setattr(module, '_receipt', write)
    result, calls = harness(monkeypatch, tmp_path, stage='compute')
    assert result['status'] == 'succeeded'
    assert not any(name == 'failed' for name, _ in calls)
