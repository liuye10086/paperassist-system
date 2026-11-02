"""Only the new wrapper's retained-attempt recovery; no Docker execution."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture
def case(tmp_path, monkeypatch):
    script = Path(__file__).parents[1] / 'verify_cr_b05_sub4_reproduction.py'
    spec = importlib.util.spec_from_file_location('sub4_reproduction', script)
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    acceptance = SimpleNamespace(output=tmp_path, state={'worker_image_id': 'sha256:current'},
        record={'results': {'sequence-structure-features': {
            'id': 'result-current', 'project_id': 'project-current', 'manifest_sha256': 'formal-current'}}}, save=Mock())
    root = tmp_path / 'reproduction/sequence-structure-features'
    package = root / 'package'
    package.mkdir(parents=True)
    code = b'# fixture only\n'
    (package / 'reproduce.py').write_bytes(code)
    write(package / 'package.json', {'identity': {'result_version_id': 'result-current', 'project_id': 'project-current'},
        'formal_manifest_sha256': 'formal-current', 'analysis_inputs_self_contained': True,
        'files': [{'path': 'reproduce.py', 'size_bytes': len(code), 'sha256': hashlib.sha256(code).hexdigest()}]})
    receipt = {'result_id': 'result-current', 'manifest_sha256': hashlib.sha256((package / 'package.json').read_bytes()).hexdigest()}
    write(root / 'acquisition.json', receipt)
    write(root / 'verification.json', {'status': 'passed'})
    execute = Mock(return_value={'status': 'passed', 'operation': 'recompute', 'evidence': 'fresh-attempt'})
    monkeypatch.setattr(wrapper.shared, 'execute', execute)
    return wrapper, acceptance, root, receipt, execute


def retained(case):
    wrapper, acceptance, root, receipt, execute = case
    attempt = root / 'attempt-recompute-retained'
    write(attempt / 'request.json', {'image': 'sha256:current', 'container': 'retained', 'command': [
        'docker', 'run', '--mount', 'type=bind,source=' + str(root / 'package') + ',target=/package,readonly',
        '--entrypoint', '/opt/paperassist-bio-insights/bin/python', 'sha256:current', '-B', '/package/reproduce.py',
        'recompute', '--output', '/attempt/output', '--manifest-sha256', receipt['manifest_sha256']]})
    return attempt


def test_success_without_outer_marker_recovers_without_execute(case):
    wrapper, acceptance, root, receipt, execute = case
    attempt = retained(case)
    write(attempt / 'completion.json', {'exit_code': 0, 'container_retained': True})
    write(attempt / 'output/operation.json', {'operation': 'recompute', 'status': 'completed',
        'comparison': {'passed': True}, 'execution': {'child_peak_rss_bytes': 1234, 'violation': None}})
    result = wrapper.execute(acceptance, 'features', 'recompute')
    assert result['reused'] is True and result['evidence'] == str(attempt)
    assert json.loads((root / 'recompute-completed.json').read_bytes())['result_id'] == 'result-current'
    assert acceptance.record['reproductions']['sequence-structure-features']['manifest_sha256'] == receipt['manifest_sha256']
    acceptance.save.assert_called_once()
    execute.assert_not_called()


@pytest.mark.parametrize('state', ['unknown', 'running', 'failed', 'wrong-image', 'wrong-manifest'])
def test_submitted_attempt_blocks_new_execute(case, state):
    wrapper, acceptance, root, receipt, execute = case
    attempt = retained(case)
    if state == 'running':
        write(attempt / 'output/operation.json', {'operation': 'recompute', 'status': 'running'})
    elif state == 'failed':
        write(attempt / 'completion.json', {'exit_code': 1})
    elif state in ('wrong-image', 'wrong-manifest'):
        request = json.loads((attempt / 'request.json').read_bytes())
        if state == 'wrong-image':
            request['image'] = 'sha256:other'
        else:
            request['command'][-1] = 'other-manifest'
        write(attempt / 'request.json', request)
    with pytest.raises(RuntimeError, match='Retained'):
        wrapper.execute(acceptance, 'features', 'recompute')
    execute.assert_not_called()
    assert attempt.exists() and not (root / 'recompute-completed.json').exists()


def test_no_attempt_executes_normally(case):
    wrapper, acceptance, root, receipt, execute = case
    result = wrapper.execute(acceptance, 'features', 'recompute')
    execute.assert_called_once_with(acceptance, 'sequence-structure', 'features', 'recompute',
        acquired=(root, root / 'package', receipt))
    assert result['status'] == 'passed'
    assert (root / 'recompute-completed.json').exists()
