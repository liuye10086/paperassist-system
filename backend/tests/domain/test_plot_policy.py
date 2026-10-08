"""Explicit synthetic plot configuration, never a paid provider call."""
import importlib
import json
from pathlib import Path

import pytest

from app.adapters.models.openai_responses import canonical_payload
from app.adapters.openai_plot import INSTRUCTIONS, PROMPT_VERSION
from app.core.exceptions import StorageError
from tests.domain.test_model_pricing import policy


def target():
    assert (Path(__file__).parents[2] / 'app/domain/plot_policy.py').exists(), 'Plot policy is not implemented'
    return importlib.import_module('app.domain.plot_policy')


def execution_policy():
    selected = policy(tools=['code_interpreter']).model_dump()
    selected['prompt_version'] = PROMPT_VERSION
    return dict(policy=selected, input_token_allowance=20000, task_limit_micro_usd=50000,
                tool_reserve_micro_usd=300, tool_reserve_version='synthetic-tool-v1')


def configure(monkeypatch, tmp_path):
    module = target()
    path = tmp_path / 'plot-policy.json'
    path.write_text(json.dumps(execution_policy()), encoding='utf-8')
    values = {'PAPERASSIST_PLOT_POLICY_FILE': str(path), 'OPENAI_API_KEY': 'synthetic-key'}
    monkeypatch.setattr(module, 'local_config', lambda: values)
    return module, path, values


def test_policy_requires_explicit_tool_reserve_and_public_configuration_hides_secrets(monkeypatch, tmp_path):
    module, _, _ = configure(monkeypatch, tmp_path)
    assert module.get_execution_policy(None) == execution_policy()
    public = module.configuration()
    assert public['configured'] and public['model'] == 'test-model'
    assert not {'policy', 'price', 'task_limit_micro_usd', 'tool_reserve_micro_usd', 'path', 'api_key'} & public.keys()
    assert 'synthetic-key' not in json.dumps(public)


@pytest.mark.parametrize('change', [
    {'tool_reserve_micro_usd': 0}, {'tool_reserve_micro_usd': True},
    {'tool_reserve_micro_usd': -1}, {'tool_reserve_version': ''}, {'input_token_allowance': 0},
    {'task_limit_micro_usd': '50000'}, {'unexpected': 'ignored'},
])
def test_invalid_policy_has_no_fallback_or_private_error(monkeypatch, tmp_path, change):
    module, path, _ = configure(monkeypatch, tmp_path)
    path.write_text(json.dumps(execution_policy() | change), encoding='utf-8')
    with pytest.raises(StorageError) as error:
        module.get_execution_policy(None)
    assert (error.value.code, error.value.status) == ('plot_not_configured', 503)
    assert str(path) not in str(error.value)
    assert not module.configuration()['configured']


@pytest.mark.parametrize('change', [{'tools': []}, {'output_format': 'analysis_explanation_v1'},
                                    {'prompt_version': 'future-v99'}])
def test_plot_policy_only_uses_fixed_plot_contract(monkeypatch, tmp_path, change):
    module, path, _ = configure(monkeypatch, tmp_path)
    selected = execution_policy()
    selected['policy'].update(change)
    path.write_text(json.dumps(selected), encoding='utf-8')
    with pytest.raises(StorageError, match='策略'):
        module.get_execution_policy(None)


def test_worker_validates_snapshot_without_live_configuration_and_checks_real_material(monkeypatch, tmp_path):
    module, _, values = configure(monkeypatch, tmp_path)
    payload = {'values': [1, 2], 'labels': {'caption': '中文'}}
    frozen = execution_policy()
    frozen['input_token_allowance'] = len(INSTRUCTIONS.encode()) + len(canonical_payload(payload).encode()) + 4096
    values.clear()
    assert module.validate_execution_policy(frozen, payload) == frozen
    with pytest.raises(StorageError) as error:
        module.validate_execution_policy(frozen, {'values': [1, 2], 'labels': {'caption': '更多中文'}})
    assert error.value.code == 'plot_input_limit'


def test_key_file_rotation_missing_and_bounded_bytes(monkeypatch, tmp_path):
    module, path, values = configure(monkeypatch, tmp_path)
    key_file = tmp_path / 'key'
    values['OPENAI_API_KEY_FILE'] = str(key_file)
    with pytest.raises(StorageError) as error:
        module.plot_api_key()
    assert error.value.code == 'plot_not_configured'
    key_file.write_text('synthetic-one\n', encoding='utf-8')
    assert module.plot_api_key() == 'synthetic-one'
    key_file.write_text('synthetic-two', encoding='utf-8')
    assert module.plot_api_key() == 'synthetic-two'
    key_file.write_text('中' * 3000, encoding='utf-8')
    with pytest.raises(StorageError):
        module.plot_api_key()
    key_file.unlink()
    path.unlink()
    assert not module.configuration()['configured']
