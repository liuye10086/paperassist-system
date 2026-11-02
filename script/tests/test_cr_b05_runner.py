"""B05 controls must never reuse an accepted batch's mutable resources."""
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.parametrize('wrong_gate', ['tabular','visium','missing'])
def test_workers_reject_different_proven_image_before_preparing_stack(monkeypatch,tmp_path,wrong_gate):
    module=runner();record=state(module);record['clone_status']='verified'
    monkeypatch.setattr(module,'read_state',lambda:record)
    monkeypatch.setattr(module,'configure',lambda _:None)
    monkeypatch.setattr(module,'probe',lambda:{'available':True})
    from app.domain.bioinformatics import analysis_settings
    monkeypatch.setattr(analysis_settings,'runtime_identity',lambda:{'available':True})
    from app.domain.bio_insights import settings
    monkeypatch.setattr(settings,'quantitative_runtime_identity',lambda:{'available':True})
    current='sha256:'+'a'*64;old='sha256:'+'b'*64
    for name,key,kind in [('GATE','image_digest','tabular'),('BIO_GATE','image_digest','visium')]:
        path=tmp_path/(name+'.json');path.write_text(json.dumps({key:old if wrong_gate==kind else current} if wrong_gate!='missing' else {}))
        monkeypatch.setattr(module,name,path)
    monkeypatch.setattr(module.worker_stack,'docker',lambda args,**_:current if args[0]=='image' else '8000000' if '64m' in args else 'same-source')
    monkeypatch.setattr(module,'source_digest',lambda:'same-source')
    called=[]
    monkeypatch.setattr(module.worker_stack,'prepare',lambda *a,**kw:called.append(True))
    with pytest.raises(ValueError,match='image'):
        module.workers()
    assert called==[]


def test_workers_require_quantitative_proof_before_preparing_stack(monkeypatch):
    module=runner();record=state(module);record['clone_status']='verified'
    monkeypatch.setattr(module,'read_state',lambda:record)
    monkeypatch.setattr(module,'configure',lambda _:None)
    monkeypatch.setattr(module,'probe',lambda:{'available':True})
    from app.domain.bio_insights import settings
    monkeypatch.setattr(settings,'quantitative_runtime_identity',lambda:{'available':False})
    calls=[];monkeypatch.setattr(module.worker_stack,'prepare',lambda *a,**k:calls.append(True))
    with pytest.raises(ValueError,match='quantitative'):module.workers()
    assert calls==[]


def runner():
    path = Path(__file__).resolve().parents[1] / 'dev' / 'cr_b05_runner.py'
    assert path.is_file(), 'CR-B05 owned runner missing'
    spec = importlib.util.spec_from_file_location('cr_b05_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state(module):
    return module.new_state('pa_test_' + uuid4().hex, 'pa_test_' + uuid4().hex)


def test_new_service_generation_keeps_same_schema_but_separate_container_identity():
    module=runner();record=state(module)
    original=module.worker_stack.Stack(module.ROOT, module.RUNTIME, record['stack_project'],
        {'PAPERASSIST_STACK_PROJECT':record['stack_project'],'PAPERASSIST_DB_SCHEMA':record['schema']})
    assert module.active_stack(record,original) is original
    record['service_generation']='r'+'a'*12
    selected=module.active_stack(record,original)
    assert selected.project==original.project+'-r'+'a'*12
    assert selected.environment['PAPERASSIST_STACK_PROJECT']==selected.project
    assert selected.environment['PAPERASSIST_DB_SCHEMA']==record['schema']
    assert original.environment['PAPERASSIST_STACK_PROJECT']==original.project
    record['service_generation']='foreign/project'
    with pytest.raises(ValueError):module.active_stack(record,original)


def test_generation_cannot_replace_retained_image_in_same_project():
    module=runner();record=state(module);old='sha256:'+'a'*64;new='sha256:'+'b'*64
    record['worker_image_id']=old
    module.validate_generation_image(record,old)
    with pytest.raises(ValueError):module.validate_generation_image(record,new)
    record['service_generation']='r'+'b'*12
    module.validate_generation_image(record,new)
    with pytest.raises(ValueError):module.validate_generation_image(record,old)


def test_separate_endpoint_assets_and_both_runtime_proofs():
    module = runner()
    record = state(module)
    assert module.validate_state(record) == record
    assert record['url'] == 'http://127.0.0.85:18085'
    assert record['schema'] in record['assets'] and record['source_schema'] not in record['assets']
    assert Path(record['assets']).is_relative_to(module.DATA_ROOT)
    assert record['runtime_manifest'] == str(module.GATE)
    assert record['bio_runtime_manifest'] == str(module.BIO_GATE)
    assert module.GATE.parent == module.BIO_GATE.parent == module.RUNTIME


@pytest.mark.parametrize('field,value', [
    ('schema', 'public'), ('source_schema', 'public'), ('port', True),
    ('port', 18084), ('bind_host', '0.0.0.0'), ('url', 'http://127.0.0.84:18084'),
    ('assets', 'C:/Users/86182/Desktop/PaperAssist-System/backend/data'),
    ('bio_staging', 'C:/unrelated'), ('workspace', 'C:/unrelated'),
    ('stack_project', 'pa-test-foreign'), ('worker_image', 'paperassist-client-b04-worker:local'),
    ('runtime_manifest', 'C:/b04/runtime-gate.json'), ('bio_runtime_manifest', 'C:/b02/runtime-gate.json'),
    ('public_database_modified', True),
])
def test_foreign_or_accepted_resources_rejected(field, value):
    module = runner()
    record = state(module)
    record[field] = value
    with pytest.raises(ValueError):
        module.validate_state(record)


def test_source_cannot_be_target_and_stop_revalidates(monkeypatch):
    module = runner()
    same = 'pa_test_' + uuid4().hex
    with pytest.raises(ValueError):
        module.new_state(same, same)
    record = state(module)
    record['stack_project'] = 'pa-test-foreign'
    monkeypatch.setattr(module, 'read_state', lambda: record)
    calls = []
    monkeypatch.setattr(module.worker_stack, 'stop', lambda stack: calls.append(stack))
    with pytest.raises(ValueError):
        module.stop_workers()
    assert calls == []


def test_configuration_clears_live_calls_and_uses_owned_proofs(monkeypatch):
    module = runner()
    monkeypatch.setattr(module.os, 'environ', {'OPENAI_API_KEY': 'must-not-be-used',
        'PAPERASSIST_DB_SCHEMA': 'public', 'PAPERASSIST_BIO_RUNTIME_MANIFEST': 'old'})
    record = state(module)
    module.configure(record)
    assert module.os.environ['OPENAI_API_KEY'] == ''
    assert module.os.environ['PAPERASSIST_NCBI_ENABLED'] == '0'
    assert module.os.environ['PAPERASSIST_WRITING_LIVE_ENABLED'] == '0'
    assert module.os.environ['PAPERASSIST_DB_SCHEMA'] == record['schema']
    assert module.os.environ['PAPERASSIST_BIO_RUNTIME_MANIFEST'] == str(module.BIO_GATE)
    assert module.os.environ['PAPERASSIST_BIO_INSIGHTS_RUNTIME_MANIFEST'] == str(module.GATE)


def test_clone_accepts_only_stopped_b04_with_exact_source_identity():
    module = runner()
    import sys
    sys.modules['cr_b05_runner'] = module
    path = Path(__file__).resolve().parents[1] / 'dev' / 'cr_b05_clone.py'
    assert path.is_file(), 'CR-B05 owned clone missing'
    spec = importlib.util.spec_from_file_location('cr_b05_clone', path)
    clone = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clone)
    schema = 'pa_test_' + uuid4().hex
    source = dict(schema=schema, status='user_accepted_and_services_stopped', workspace=str(module.ROOT),
        assets=str(module.ROOT / 'script/.runtime/client-requirements-b04/acceptance' / schema / 'assets'),
        migration_head='0061_bio_insights', bind_host='127.0.0.84', port=18084)
    clone.validate_source(source)
    for field, value in [('status', 'services_running'), ('migration_head', '0060_research_results_bridge'),
                         ('port', 18083), ('assets', 'C:/unrelated'), ('schema', 'public')]:
        with pytest.raises(ValueError):
            clone.validate_source({**source, field: value})
