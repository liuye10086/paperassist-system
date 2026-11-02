"""W1 cannot target accepted schemas/assets or enable external work."""
import importlib.util
from pathlib import Path
from uuid import uuid4
import pytest


def control():
    spec = importlib.util.spec_from_file_location('b06_w1_controls', Path(__file__).parents[1] / 'dev/cr_b06_w1_runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_w1_rejects_source_schema_and_accepted_asset_directory():
    module = control()
    source = 'pa_test_' + uuid4().hex
    with pytest.raises(ValueError):
        module.new_state(source, source)
    state = module.new_state('pa_test_' + uuid4().hex, source)
    with pytest.raises(ValueError):
        module.validate_state(dict(state, assets=str(module.ROOT / 'script/.runtime/client-requirements-b04/acceptance' / source / 'assets')))
    with pytest.raises(ValueError):
        module.validate_state(dict(state, port=18084))


def test_w1_disables_inherited_real_calls(monkeypatch):
    module = control()
    monkeypatch.setenv('PAPERASSIST_WRITING_LIVE_ENABLED', '1')
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-never-used')
    monkeypatch.setenv('PAPERASSIST_NCBI_ENABLED', '1')
    state = module.new_state('pa_test_' + uuid4().hex, 'pa_test_' + uuid4().hex)
    module.configure(state)
    assert module.os.environ['PAPERASSIST_WRITING_LIVE_ENABLED'] == '0'
    assert module.os.environ['OPENAI_API_KEY'] == ''
    assert module.os.environ['PAPERASSIST_NCBI_ENABLED'] == '0'
    assert module.os.environ['PAPERASSIST_DB_SCHEMA'] == state['schema']
    assert module.os.environ['PAPERASSIST_DATA_DIR'] == state['assets']
