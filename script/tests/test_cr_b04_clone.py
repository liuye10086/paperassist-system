"""Only the accepted, stopped B03 snapshot can seed B04."""
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest


def module():
    path = Path(__file__).resolve().parents[1] / 'dev' / 'cr_b04_clone.py'
    assert path.is_file(), 'CR-B04 retention clone missing'
    spec = importlib.util.spec_from_file_location('cr_b04_clone', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def source(m):
    schema = 'pa_test_' + uuid4().hex
    return dict(schema=schema, status='user_accepted_and_services_stopped',
                workspace=str(m.ROOT), assets=str(m.ROOT / 'script/.runtime/client-requirements-b03/acceptance' / schema / 'assets'),
                migration_head='0060_research_results_bridge', bind_host='127.0.0.83', port=18083)


def test_accepts_exact_b03_source_identity():
    m = module()
    m.validate_source(source(m))


@pytest.mark.parametrize('key,value', [('status', 'services_running'), ('schema', 'public'),
    ('workspace', 'C:/elsewhere'), ('assets', 'C:/protected'), ('migration_head', '0059_bio_spatial_analysis'),
    ('bind_host', '127.0.0.1'), ('port', 18082)])
def test_rejects_other_batches_and_unaccepted_sources(key, value):
    m = module()
    record = source(m)
    record[key] = value
    with pytest.raises(ValueError):
        m.validate_source(record)
