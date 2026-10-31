"""Offline verification and comparison; fixtures are not scientific runs."""
import importlib.util
import hashlib
import json
from pathlib import Path
import pytest


def module():
    path=Path(__file__).resolve().parents[1]/'cr_b04_reproduce.py'
    assert path.exists(),'B04 standalone reproduction entry is missing'
    spec=importlib.util.spec_from_file_location('b04_reproduce',path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def fixture(tmp_path,external=False):
    raw=b'row_key\tfeature_id\tp_value\teffect_value\treason\na\tg1\t0\t2\t\nb\tg2\t\t\tconstant\n'
    path=tmp_path/'result.tsv';path.write_bytes(raw)
    record=dict(path='result.tsv',sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw),table={'format':'tsv','columns':['row_key','feature_id','p_value','effect_value','reason'],'rows':2})
    required=[]
    if external:required=[dict(path='required-resources/'+'a'*64+'.bin',sha256='a'*64,size_bytes=3,roles=['gene_sets'])]
    code=tmp_path/'code.py';code.write_bytes(b'# explicit test fixture; no scientific run\n');lock=tmp_path/'lock.txt';lock.write_bytes(b'test-fixture==1\n')
    environment={'python':'test-fixture-only','packages':{},'native_libraries':[],'lock_sha256':hashlib.sha256(lock.read_bytes()).hexdigest(),'limits':{}}
    code_digest=hashlib.sha256(b'app/adapters/bio_insights_engine/fixture.py\0'+code.read_bytes()+b'\0').hexdigest()
    dump=lambda value:json.dumps(value,sort_keys=True,separators=(',',':')).encode()
    identity={'code_digest':code_digest,'environment_digest':hashlib.sha256(dump(environment)).hexdigest(),'lock_sha256':environment['lock_sha256'],
              'project_id':'fixture','task_id':'fixture-task','source_digest':hashlib.sha256(dump([])).hexdigest()}
    config={'kind':'result_import'};identity['config_sha256']=hashlib.sha256(dump(config)).hexdigest()
    payload={'kind':'bio_result_import','identity':identity,'config':config,'sources':[]}
    (tmp_path/'input').mkdir();(tmp_path/'provenance').mkdir()
    (tmp_path/'input/payload.json').write_bytes(dump(payload));snapshot={'kind':'bio_result_import','project_id':'fixture'}
    (tmp_path/'provenance/task-input.json').write_bytes(dump(snapshot))
    (tmp_path/'provenance/formal-manifest.json').write_bytes(dump({'identity':identity}))
    material=(code,lock,tmp_path/'input/payload.json',tmp_path/'provenance/task-input.json',tmp_path/'provenance/formal-manifest.json')
    records=[record]+[dict(path=p.relative_to(tmp_path).as_posix(),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),size_bytes=p.stat().st_size) for p in material]
    package=dict(schema_version=1,kind='bio_insights_reproduction',files=records,required_resources=required,fully_self_contained=False,
                 identity=identity,baseline=[],source_proofs=[],task_input_sha256=hashlib.sha256(dump(snapshot)).hexdigest(),frozen_config_sha256=identity['config_sha256'],
                 formal_manifest_sha256=hashlib.sha256((tmp_path/'provenance/formal-manifest.json').read_bytes()).hexdigest(),
                 environment_proof={'environment':environment},engine_code_files=[{'relative_name':'app/adapters/bio_insights_engine/fixture.py','path':'code.py'}],lock_path='lock.txt')
    (tmp_path/'package.json').write_text(json.dumps(package),encoding='utf-8')
    return package


def test_verify_checks_raw_zero_na_table_counts_and_does_not_execute(tmp_path,monkeypatch):
    m=module();fixture(tmp_path)
    monkeypatch.setattr(m.subprocess,'Popen',lambda *a,**k:(_ for _ in ()).throw(AssertionError('verify cannot execute')))
    assert m.verify_package(tmp_path)['status']=='verified'
    package=json.loads((tmp_path/'package.json').read_bytes());package['files'][0]['table']['rows']=1
    (tmp_path/'package.json').write_text(json.dumps(package),encoding='utf-8')
    with pytest.raises(ValueError,match='row'):m.verify_package(tmp_path)


def test_missing_external_resources_fail_and_matching_explicit_file_is_required(tmp_path):
    m=module();package=fixture(tmp_path,external=True)
    with pytest.raises(ValueError,match='Missing required resource'):m.verify_package(tmp_path)
    resource=tmp_path.parent/(tmp_path.name+'-provided.gmt');resource.write_bytes(b'gmt')
    sha=hashlib.sha256(b'gmt').hexdigest();package['required_resources'][0].update(sha256=sha,path='required-resources/'+sha+'.bin')
    (tmp_path/'package.json').write_text(json.dumps(package),encoding='utf-8')
    result=m.verify_package(tmp_path,resources={sha:str(resource)})
    assert result['status']=='verified' and result['fully_self_contained'] is False
    resource.write_bytes(b'bad')
    with pytest.raises(ValueError):m.verify_package(tmp_path,resources={sha:str(resource)})


def test_paths_manifest_anchor_and_unlisted_files_are_rejected(tmp_path):
    m=module();fixture(tmp_path)
    for path in ('../private','/private','C:/private','a\\b'):
        with pytest.raises(ValueError):m.relative_file(tmp_path,path)
    with pytest.raises(ValueError,match='anchor'):m.verify_package(tmp_path,manifest_sha256='a'*64)
    (tmp_path/'unexpected.py').write_text('raise RuntimeError()',encoding='utf-8')
    with pytest.raises(ValueError,match='Unlisted'):m.verify_package(tmp_path)


def test_numeric_tolerances_keep_na_direction_and_original_text_exact(tmp_path):
    m=module();left=tmp_path/'baseline.tsv';right=tmp_path/'actual.tsv'
    left.write_text('row_key\tp_value\teffect_value\toriginal_p_value\treason\na\t0.1\t2\t1e-400\t\n',encoding='utf-8')
    right.write_text('row_key\tp_value\teffect_value\toriginal_p_value\treason\na\t0.10000000001\t2.000000001\t1e-400\t\n',encoding='utf-8')
    result=m.compare_table(left,right)
    assert result['passed'] and result['numeric_differences']
    right.write_text(right.read_text().replace('1e-400','0'),encoding='utf-8')
    assert m.compare_table(left,right)['passed'] is False


def test_effect_sign_change_is_not_hidden_inside_absolute_tolerance(tmp_path):
    m=module();a=tmp_path/'a.tsv';b=tmp_path/'b.tsv'
    a.write_text('row_key\teffect_value\na\t1e-9\n',encoding='utf-8')
    b.write_text('row_key\teffect_value\na\t-1e-9\n',encoding='utf-8')
    assert m.compare_table(a,b)['passed'] is False


def test_transport_uses_a_real_independent_child_and_retains_exact_logs(tmp_path):
    import os,sys
    m=module();worker=tmp_path/'protocol_fixture.py'
    worker.write_text("import sys,struct,json,os\nheader=sys.stdin.buffer.read(4)\nbody=sys.stdin.buffer.read(struct.unpack('!I',header)[0])\n"
        "sys.stdout.buffer.write(b'READY\\n'+json.dumps({'result':{'child_pid':os.getpid(),'payload':json.loads(body)}}).encode())\n",encoding='utf-8')
    output=tmp_path/'new-attempt';output.mkdir()
    result,receipt=m.execute_child([sys.executable,'-I','-B',str(worker)],{'literal':'no scientific computation'},output)
    assert result['child_pid']!=os.getpid() and result['payload']=={'literal':'no scientific computation'}
    assert receipt['exit_code']==0 and (output/'worker.stdout.bin').read_bytes().startswith(b'READY\n')
    assert (output/'execution.json').is_file()


def test_acceptance_wrapper_does_not_replace_missing_state_with_examples(tmp_path):
    path=Path(__file__).resolve().parents[1]/'verify_cr_b04_reproducibility.py'
    assert path.is_file()
    spec=importlib.util.spec_from_file_location('verify_b04',path);wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)
    state=tmp_path/'state.json';state.write_text(json.dumps({'schema':'pa_test_'+'a'*32,'workspace':str(wrapper.ROOT)}),encoding='utf-8')
    with pytest.raises(ValueError,match='no actual exported'):wrapper.state_packages(state)


def test_pdf_comparison_uses_page_and_decompressed_vector_content(tmp_path):
    import zlib
    m=module()
    def pdf(name,date,commands):
        stream=zlib.compress(commands);content=b'%PDF-1.4\n1 0 obj << /Type /Page /MediaBox [0 0 10 10] >> endobj\n'
        content+=b'2 0 obj << /Filter /FlateDecode >>\nstream\n'+stream+b'\nendstream\nendobj\n/CreationDate ('+date+b')\n%%EOF'
        path=tmp_path/name;path.write_bytes(content);return path
    first=pdf('a.pdf',b'D:20260101',b'0 0 m 10 10 l S')
    second=pdf('b.pdf',b'D:20260201',b'0 0 m 10 10 l S')
    assert m.pdf_content(first)==m.pdf_content(second)
    third=pdf('c.pdf',b'D:20260101',b'0 0 m 5 5 l S')
    assert m.pdf_content(first)!=m.pdf_content(third)


def test_pipe_projection_is_the_exported_scientific_function_and_preserves_snapshot(tmp_path):
    import copy
    m=module();repository=Path(__file__).resolve().parents[2]
    source=repository/'backend/app/adapters/bio_insights_engine/transport.py'
    target=tmp_path/'code/app/adapters/bio_insights_engine/transport.py';target.parent.mkdir(parents=True);target.write_bytes(source.read_bytes())
    full={'identity':{'source_digest':'a'*64},'config':{'kind':'comparison'},'sources':[{'source_kind':'bio_processed_dataset_version','source_id':'p','sha256':'b'*64,
        'metadata':{'feature_ids':['g1']*100000,'manifest':{'redundant':True},'shape':{},'observations':[{'barcode':'b','donor':'d'}]},
        'members':{'counts':{'path':'/controlled/c','sha256':'c'*64}},'raw':{'manifest':{'input_shape':{'features':1,'observations':1},'redundant':True},'members':{}}}]}
    original=copy.deepcopy(full);projected=m.project_for_pipe(tmp_path,full)
    assert full==original and projected['sources'][0]['metadata']['observations']==original['sources'][0]['metadata']['observations']
    assert 'feature_ids' not in projected['sources'][0]['metadata']
    assert projected['sources'][0]['members']==original['sources'][0]['members']


def test_svg_comparison_ignores_generation_date_but_preserves_visible_content(tmp_path):
    m=module();output=tmp_path/'output';output.mkdir()
    baseline=tmp_path/'before.svg';actual=output/'after.svg'
    svg='<svg xmlns="http://www.w3.org/2000/svg" xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:date>{date}</dc:date></metadata><defs><clipPath id="{identifier}"/></defs><path clip-path="url(#{identifier})" d="{shape}"/></svg>'
    baseline.write_text(svg.format(date='2026-10-30T01:00:00',identifier='pabc',shape='M 0 0 L 1 1'))
    actual.write_text(svg.format(date='2026-10-30T02:00:00',identifier='pxyz',shape='M 0 0 L 1 1'))
    package={'baseline':[{'key':'svg','path':'before.svg','format':'svg','sha256':m.sha256(baseline),'size_bytes':baseline.stat().st_size}]}
    def result():return {'outputs':[{'key':'svg','path':str(actual),'sha256':m.sha256(actual),'size_bytes':actual.stat().st_size}]}
    assert m.compare_outputs(package,tmp_path,result(),output)['passed']
    actual.write_text(svg.format(date='2026-10-30T02:00:00',identifier='pxyz',shape='M 0 0 L 2 1'))
    assert not m.compare_outputs(package,tmp_path,result(),output)['passed']


def test_verify_cross_checks_frozen_input_member_hash_against_packaged_bytes(tmp_path):
    m=module();package=fixture(tmp_path);member=package['files'][0]
    payload_path=tmp_path/'input/payload.json';payload=m.strict_json(payload_path.read_bytes())
    source={'source_kind':'original_file','source_id':'fixed-file','role':'external_table','sha256':member['sha256'],
            'project_id':'fixture','locator':{},'metadata':{},'members':{'original_file':{**member,'sha256':'f'*64}}}
    payload['sources']=[source]
    package['identity']['source_digest']=hashlib.sha256(m.canonical([{key:source[key] for key in ('source_kind','source_id','role','sha256','project_id','locator')}])).hexdigest()
    payload['identity']['source_digest']=package['identity']['source_digest'];payload_path.write_bytes(m.canonical(payload))
    for record in package['files']:
        if record['path']=='input/payload.json':record.update(sha256=m.sha256(payload_path),size_bytes=payload_path.stat().st_size)
    package['source_proofs']=[{key:source[key] for key in ('source_kind','source_id','sha256')}|{'path':'result.tsv','proof':'original_bytes'}]
    (tmp_path/'package.json').write_bytes(m.canonical(package))
    with pytest.raises(ValueError,match='Frozen input member'):m.verify_package(tmp_path)


def test_verify_raw_delimited_records_does_not_assume_first_record_is_header(tmp_path):
    m=module();package=fixture(tmp_path)
    package['files'][0]['table']=dict(format='tsv',header='uninterpreted',column_count=5,records=3)
    (tmp_path/'package.json').write_bytes(m.canonical(package))
    assert m.verify_package(tmp_path)['status']=='verified'
    package['files'][0]['table']['records']=2
    (tmp_path/'package.json').write_bytes(m.canonical(package))
    with pytest.raises(ValueError,match='row count'):m.verify_package(tmp_path)


def test_acceptance_wrapper_checks_external_anchor_before_loading_package_code(tmp_path):
    path=Path(__file__).resolve().parents[1]/'verify_cr_b04_reproducibility.py'
    spec=importlib.util.spec_from_file_location('verify_b04_preimport',path);wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)
    (tmp_path/'reproduce.py').write_text("raise AssertionError('package code executed before external anchor')",encoding='utf-8')
    (tmp_path/'package.json').write_text(json.dumps({'identity':{},'files':[]}),encoding='utf-8')
    receipt=tmp_path.parent/(tmp_path.name+'-receipt.json')
    with pytest.raises(RuntimeError):wrapper.main(['--package',str(tmp_path),'--manifest-sha256','f'*64,'--receipt',str(receipt)])
    assert json.loads(receipt.read_text(encoding='utf-8'))['error']=='Package manifest anchor differs'


def test_processed_source_proof_preserves_distinct_formal_and_inner_manifest_bytes(tmp_path):
    m=module();package=fixture(tmp_path)
    formal=tmp_path/'provenance/processed-formal.json';formal.write_text('{"parent_resources":[],"kind":"formal"}',encoding='utf-8')
    inner=tmp_path/'provenance/processed-inner.json';inner.write_text('{"kind":"engine-artifact"}',encoding='utf-8')
    record=lambda p:dict(path=p.relative_to(tmp_path).as_posix(),sha256=m.sha256(p),size_bytes=p.stat().st_size)
    outer_record,inner_record=record(formal),record(inner)
    source=dict(source_kind='bio_processed_dataset_version',source_id='processed',role='expression',sha256=outer_record['sha256'],
        project_id='fixture',locator={},metadata={},members={'manifest':inner_record})
    payload_path=tmp_path/'input/payload.json';payload=m.strict_json(payload_path.read_bytes());payload['sources']=[source]
    source_digest=hashlib.sha256(m.canonical([{key:source[key] for key in ('source_kind','source_id','role','sha256','project_id','locator')}])).hexdigest()
    payload['identity']['source_digest']=package['identity']['source_digest']=source_digest;payload_path.write_bytes(m.canonical(payload))
    for item in package['files']:
        if item['path']=='input/payload.json':item.update(sha256=m.sha256(payload_path),size_bytes=payload_path.stat().st_size)
    package['files'].extend([outer_record,inner_record])
    package['source_proofs']=[{key:source[key] for key in ('source_kind','source_id','sha256')}|
        dict(path=outer_record['path'],proof='formal_manifest_bytes')]
    (tmp_path/'package.json').write_bytes(m.canonical(package));assert m.verify_package(tmp_path)['status']=='verified'
    package['source_proofs'][0]['path']=inner_record['path'];(tmp_path/'package.json').write_bytes(m.canonical(package))
    with pytest.raises(ValueError,match='Frozen source SHA'):m.verify_package(tmp_path)

def test_cold_render_child_preloads_lazy_table_reader_before_isolation(tmp_path):
    """Protocol regression only; no scientific environment/compute claim."""
    import struct,subprocess,sys
    worker=Path(__file__).resolve().parents[2]/'backend/app/reproduction_assets/bio_insights/render_worker.py'
    setup=tmp_path/'cold_render_fixture.py'
    setup.write_text(r'''
import sys,types,json,runpy,importlib.abc,importlib.util,signal
signal.SIGALRM=14;signal.signal=lambda *args:None;signal.alarm=lambda *args:None
from pathlib import Path
isolated=False
name='app.adapters.bio_insights_engine.tables'
class TableLoader(importlib.abc.Loader):
    def create_module(self,spec):return None
    def exec_module(self,module):module.read=lambda:'bounded fixture table'
class TableFinder(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname==name:
            if isolated:raise PermissionError('table reader imported after isolation')
            return importlib.util.spec_from_loader(fullname,TableLoader())
sys.meta_path.insert(0,TableFinder())
def module(name,**attrs):
    obj=types.ModuleType(name);obj.__dict__.update(attrs);sys.modules[name]=obj;return obj
for pkg in ['app','app.adapters','app.adapters.bio_insights_engine','app.adapters.bio_engine','app.domain','app.domain.bio_insights']:
    module(pkg,__path__=[])
identity={'engine_version':'fixture','code_digest':'fixture','environment_digest':'fixture','lock_sha256':'fixture'}
def enter(*args):
    global isolated
    isolated=True
    return []
def figure(payload,writer):
    import importlib
    assert importlib.import_module(name).read()=='bounded fixture table'
    return {'methods':{},'summary':{}}
module('app.adapters.bio_insights_engine.worker',actual_identity=lambda:identity,warm_render_environment=lambda _:None,records=lambda _:[])
module('app.adapters.bio_insights_engine.sandbox',enter=enter)
module('app.adapters.bio_insights_engine.figures',run_figure=figure)
class Writer:
    def __init__(self,*args):self.artifacts=[]
    def json(self,*args):pass
module('app.adapters.bio_engine.manifest',Writer=Writer,canonical=lambda value:json.dumps(value).encode())
module('app.domain.bio_insights.contracts',FigureConfig=type('Config',(),{'model_validate':staticmethod(lambda _:None)}))
module('app.domain.bio_insights.settings',BioInsightsLimits=type('Limits',(),{'warmup_seconds':30,'compute_wall_seconds':30}))
module('PIL',Image=type('Image',(),{'init':staticmethod(lambda:None)}))
target=sys.argv[1];sys.argv=[target,'1'];runpy.run_path(target,run_name='__main__')
''',encoding='utf-8')
    output=tmp_path/'output';output.mkdir()
    identity=dict(engine_version='fixture',code_digest='fixture',environment_digest='fixture',lock_sha256='fixture')
    body=json.dumps(dict(kind='bio_insight_figure',config={},identity=identity,_runtime_identity=identity,output_directory=str(output))).encode()
    child=subprocess.run([sys.executable,'-I','-B',str(setup),str(worker)],input=struct.pack('!I',len(body))+body,capture_output=True,timeout=30)
    assert child.returncode==0,child.stderr.decode()
    assert child.stdout.startswith(b'READY\n')
    answer=json.loads(child.stdout[6:])
    assert 'result' in answer,answer
    assert answer['result']['status']=='completed'
