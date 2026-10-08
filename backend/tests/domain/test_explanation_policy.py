"""Explanation policy and receipt boundaries use synthetic data only."""
import importlib
import json
from pathlib import Path

import pytest

from app.core.exceptions import PlotError, StorageError
from app.domain.explanation_content import VERSION
from tests.domain.test_model_pricing import policy


def module(name):
    assert (Path(__file__).parents[2] / 'app/domain' / (name + '.py')).exists(), name + ' is not implemented'
    return importlib.import_module('app.domain.' + name)


def execution_policy():
    values = policy().model_dump()
    values.update(prompt_version=VERSION, output_format='analysis_explanation_v1')
    return {'policy': values, 'input_token_allowance': 20000, 'task_limit_micro_usd': 50000}


def configured(monkeypatch, tmp_path, **changes):
    target = module('explanation_policy')
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(execution_policy()), encoding='utf-8')
    values = {'PAPERASSIST_EXPLANATION_POLICY_FILE': str(path), 'OPENAI_API_KEY': 'synthetic-test-key'}
    values.update(changes)
    monkeypatch.setattr(target, 'local_config', lambda: values)
    return target, path, values


def test_policy_is_explicit_strict_and_configuration_is_public(monkeypatch, tmp_path):
    target, _, _ = configured(monkeypatch, tmp_path)
    assert target.get_execution_policy({'facts': 'synthetic'}) == execution_policy()
    public = target.configuration()
    assert public['configured'] and public['model'] == execution_policy()['policy']['model']
    assert not {'policy', 'price', 'api_key', 'path', 'task_limit_micro_usd'} & public.keys()
    assert 'synthetic-test-key' not in json.dumps(public)


@pytest.mark.parametrize('change', [
    {'unexpected': 1}, {'task_limit_micro_usd': True}, {'input_token_allowance': 0},
    {'input_token_allowance': '20000'}, {'task_limit_micro_usd': -1},
])
def test_invalid_policy_is_safe_not_configured(monkeypatch, tmp_path, change):
    target, path, _ = configured(monkeypatch, tmp_path)
    path.write_text(json.dumps({**execution_policy(), **change}), encoding='utf-8')
    with pytest.raises(StorageError) as error:
        target.get_execution_policy({})
    assert (error.value.code, error.value.status) == ('explanation_not_configured', 503)
    assert str(path) not in str(error.value)
    assert not target.configuration()['configured']


@pytest.mark.parametrize('change', [
    {'output_format': 'text'}, {'prompt_version': 'future-v99'}, {'tools': ['code_interpreter']},
])
def test_explanation_policy_cannot_select_other_schema_or_tools(monkeypatch, tmp_path, change):
    target, path, _ = configured(monkeypatch, tmp_path)
    data = execution_policy()
    data['policy'].update(change)
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(StorageError) as error:
        target.get_execution_policy({})
    assert error.value.code == 'explanation_not_configured'


def test_missing_files_and_key_never_get_default_prices(monkeypatch, tmp_path):
    target, path, values = configured(monkeypatch, tmp_path, OPENAI_API_KEY='')
    with pytest.raises(StorageError):
        target.get_execution_policy({})
    values['OPENAI_API_KEY'] = 'synthetic-key'
    path.unlink()
    with pytest.raises(StorageError):
        target.get_execution_policy({})
    assert target.configuration()['configured'] is False


def test_key_file_is_read_lazily_bounded_and_overrides_local_key(monkeypatch, tmp_path):
    path = tmp_path / 'key.txt'
    target, _, _ = configured(monkeypatch, tmp_path, OPENAI_API_KEY_FILE=str(path))
    with pytest.raises(StorageError):
        target.explanation_api_key()
    path.write_text('synthetic-file-key\n', encoding='utf-8')
    assert target.explanation_api_key() == 'synthetic-file-key'
    path.write_text('x' * 9000, encoding='utf-8')
    with pytest.raises(StorageError):
        target.explanation_api_key()


def test_allowance_checks_canonical_utf8_size_without_changing_model_tokens(monkeypatch, tmp_path):
    from app.adapters.openai_explanation import INSTRUCTIONS
    from app.adapters.models.openai_responses import canonical_payload
    target, path, _ = configured(monkeypatch, tmp_path)
    payload = {'facts': '中文'}
    minimum = len(INSTRUCTIONS.encode()) + len(canonical_payload(payload).encode()) + 4096
    data = execution_policy()
    data['input_token_allowance'] = minimum
    path.write_text(json.dumps(data), encoding='utf-8')
    assert target.get_execution_policy(payload)['input_token_allowance'] == minimum
    with pytest.raises(StorageError) as error:
        target.get_execution_policy({'facts': '中文更多'})
    assert error.value.code == 'explanation_input_limit'


def response(**changes):
    return {'id': 'resp_synthetic', 'status': 'completed', 'model': 'test-model', 'usage': None,
            'output': [{'content': [{'type': 'output_text', 'text': '{"purpose":'},
                                    {'type': 'output_text', 'text': '"synthetic"}'}]}], **changes}


def test_parser_combines_only_output_text_and_preserves_provenance():
    target = module('explanation_response')
    parsed = target.parse_explanation_response(response())
    assert parsed == {'draft': {'purpose': 'synthetic'}, 'provenance': {
        'response_id': 'resp_synthetic', 'model': 'test-model', 'usage': None, 'prompt_version': VERSION}}


@pytest.mark.parametrize('status', ['queued', 'in_progress'])
def test_parser_pending_is_none(status):
    assert module('explanation_response').parse_explanation_response(response(status=status)) is None


@pytest.mark.parametrize(('changes', 'code'), [
    ({'status': 'failed'}, 'explanation_incomplete'),
    ({'output': [{'content': [{'type': 'refusal'}]}]}, 'explanation_refused'),
    ({'output': [{'content': [{'type': 'output_text', 'text': 'x' * (96 * 1024 + 1)}]}]}, 'explanation_output_limit'),
    ({'output': [{'content': [{'type': 'output_text', 'text': 'not JSON'}]}]}, 'explanation_invalid_json'),
    ({'output': [{'content': [{'type': 'output_text', 'text': '[]'}]}]}, 'explanation_invalid_json'),
])
def test_parser_rejects_incomplete_refusal_large_or_nonobject_json(changes, code):
    with pytest.raises(PlotError) as error:
        module('explanation_response').parse_explanation_response(response(**changes))
    assert error.value.code == code
