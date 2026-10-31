"""CR-B04 controls must preserve accepted batch services and materials."""
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest


def runner():
    path = Path(__file__).resolve().parents[1] / 'dev' / 'cr_b04_runner.py'
    assert path.is_file(), 'CR-B04 owned runner missing'
    spec = importlib.util.spec_from_file_location('cr_b04_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state(module):
    return module.new_state('pa_test_' + uuid4().hex, 'pa_test_' + uuid4().hex)


def test_owned_state_separates_source_assets_and_browser_cookies():
    module = runner()
    value = state(module)
    assert module.validate_state(value) == value
    assert value['bind_host'] == '127.0.0.84'
    assert value['url'] == 'http://127.0.0.84:18084'
    assert value['schema'] in value['assets'] and value['source_schema'] not in value['assets']
    assert Path(value['assets']).parent == Path(value['staging']).parent
    assert value['runtime_manifest'] == str(module.GATE)


@pytest.mark.parametrize('field,value', [
    ('schema', 'public'), ('source_schema', 'public'), ('port', True),
    ('port', 18083), ('bind_host', '0.0.0.0'), ('url', 'http://127.0.0.83:18083'),
    ('assets', 'C:/Users/86182/Desktop/PaperAssist-System/backend/data'),
    ('staging', 'C:/unrelated'), ('workspace', 'C:/unrelated'),
    ('stack_project', 'pa-test-unrelated'), ('worker_image', 'paperassist-client-b03-worker:local'),
    ('runtime_manifest', 'C:/unrelated.json'), ('public_database_modified', True),
])
def test_foreign_paths_schemas_or_services_are_rejected(field, value):
    module = runner()
    record = state(module)
    record[field] = value
    with pytest.raises(ValueError):
        module.validate_state(record)


def test_source_schema_cannot_be_reused_as_target():
    module = runner()
    same = 'pa_test_' + uuid4().hex
    with pytest.raises(ValueError):
        module.new_state(same, same)


def test_stop_workers_rechecks_batch_identity_before_stop(monkeypatch):
    module = runner()
    value = state(module)
    value['stack_project'] = 'pa-test-foreign'
    monkeypatch.setattr(module, 'read_state', lambda: value)
    calls = []
    monkeypatch.setattr(module.worker_stack, 'stop', lambda stack: calls.append(stack))
    with pytest.raises(ValueError):
        module.stop_workers()
    assert calls == []


def test_standalone_probe_uses_owned_manifest_instead_of_ambient_environment(monkeypatch, tmp_path):
    module = runner()
    from app.domain.bio_insights import settings

    gate = tmp_path / 'runtime-gate.json'
    monkeypatch.setattr(module, 'GATE', gate)
    value = state(module)
    monkeypatch.setattr(module, 'read_state', lambda: value)
    monkeypatch.setattr(module.os, 'environ', {
        settings.RUNTIME_MANIFEST_ENV: str(tmp_path / 'foreign-gate.json'),
        'PAPERASSIST_DB_SCHEMA': 'public',
        'OPENAI_API_KEY': 'must-not-be-used',
    })
    report = dict(schema_version=1, status='passed', engine_version='bio_insights_v1.0.0',
        interpreter=settings.INTERPRETER, numeric_threads=1,
        lock_sha256=settings.engine_lock_digest(), code_digest=settings.engine_code_digest(),
        packages={'pydeseq2': '0.5.4', 'gseapy': '1.3.1'},
        isolation={'network': 'denied', 'file': 'denied', 'fork': 'denied', 'subprocess': 'denied'},
        checks={'aggregation': True, 'deseq2_fit': True, 'gsea': True},
        peak_rss_kib=1, limits=settings.BioInsightsLimits().model_dump(),
        python='test-fixture', native_libraries={})
    gate.write_text(module.json.dumps(report), encoding='utf-8')

    assert module.probe()['available'] is True
    assert module.os.environ[settings.RUNTIME_MANIFEST_ENV] == str(gate)
    assert module.os.environ['PAPERASSIST_DB_SCHEMA'] == value['schema']
    assert module.os.environ['OPENAI_API_KEY'] == ''

    report['checks']['gsea'] = False
    gate.write_text(module.json.dumps(report), encoding='utf-8')
    assert module.probe() == {
        'available': False, 'reason': 'bio_insights_environment_unavailable'}
