"""Control commands may only address this batch's owned schema and paths."""
import importlib.util
from pathlib import Path
from uuid import uuid4
import pytest


def runner():
    path = Path(__file__).resolve().parents[1] / 'dev' / 'cr_b02_runner.py'
    spec = importlib.util.spec_from_file_location('cr_b02_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acceptance_state_is_bound_to_this_batch():
    module = runner()
    state = module.new_state('pa_test_' + uuid4().hex)
    assert module.validate_state(state) == state


@pytest.mark.parametrize('field,value', [('schema','public'),('assets','C:/Users/86182/Desktop/PaperAssist-System/backend/data'),
    ('workspace','C:/Users/86182/Desktop/PaperAssist-System'),('url','https://example.com'),('port',18081)])
def test_other_workspaces_and_first_batch_cannot_be_targeted(field, value):
    module = runner()
    state = module.new_state('pa_test_' + uuid4().hex)
    state[field] = value
    with pytest.raises(ValueError):
        module.validate_state(state)


def test_reprepared_schema_does_not_share_assets_or_recovery_material():
    module = runner()
    first, second = (module.new_state('pa_test_' + uuid4().hex) for _ in range(2))
    assert first['assets'] != second['assets']
    assert first['staging'] != second['staging']


def test_dedicated_loopback_host_separates_browser_cookies_from_other_batches():
    module = runner()
    state = module.new_state('pa_test_' + uuid4().hex)
    assert state['bind_host'] == '127.0.0.82'
    assert state['url'].startswith('http://127.0.0.82:')
