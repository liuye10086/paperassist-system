"""Typed external evidence API and actual isolated worker publication slice."""
import copy,json,subprocess
from pathlib import Path
from uuid import uuid4
import pytest
from tests.api.test_projects import client,create_project
from tests.domain.test_bio_tabular_contracts import request_body
from tests.domain.test_bio_evidence_independence import typed


def docker_call(tmp_path,module,function,payload):
    def convert(value,to_linux):
        if isinstance(value,dict):return {k:convert(v,to_linux) for k,v in value.items()}
        if isinstance(value,list):return [convert(v,to_linux) for v in value]
        if isinstance(value,str):
            normalized=value.replace('\\','/')
            if to_linux and normalized.startswith(tmp_path.as_posix()):return '/work'+normalized[len(tmp_path.as_posix()):]
            if not to_linux and value.startswith('/work/'):return str(tmp_path/Path(value[6:]))
        return value
    identity=uuid4().hex;request=tmp_path/(identity+'.json');answer=tmp_path/(identity+'-answer.json')
    request.write_text(json.dumps(convert(payload,True)),encoding='utf-8')
    script="import json;from pathlib import Path;from "+module+" import "+function+";r="+function+"(json.loads(Path('/work/"+request.name+"').read_bytes()));Path('/work/"+answer.name+"').write_text(json.dumps(r))"
    app=Path(__file__).resolve().parents[2]/'app'
    command=['docker','run','--rm','--network','none','--memory','2g','--cpus','2','-e','OPENBLAS_NUM_THREADS=1','-e','OMP_NUM_THREADS=1','-e','MKL_NUM_THREADS=1','-v',str(app)+':/app/app:ro','-v',str(tmp_path)+':/work','-w','/app','paperassist-client-b05-sub4-deps:local','/opt/paperassist-bio-insights/bin/python','-c',script]
    done=subprocess.run(command,capture_output=True,text=True,timeout=120);assert done.returncode==0,done.stderr
    return convert(json.loads(answer.read_bytes()),False)

@pytest.fixture(autouse=True)
def postgres_schema(monkeypatch,tmp_path):
    # Retain this isolated migrated schema: DROP of the full project schema can
    # exceed shared PostgreSQL max_locks_per_transaction. No shared mutation.
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    from app.core.config import local_config
    from app.db.database import DatabaseConfig,get_migration_database_config,migrate_database
    url=local_config().get('PAPERASSIST_TEST_DATABASE_URL')
    assert url,'PAPERASSIST_TEST_DATABASE_URL required'
    schema='pa_test_'+uuid4().hex
    monkeypatch.setenv('PAPERASSIST_ENV','test');monkeypatch.setenv('PAPERASSIST_DB_SCHEMA',schema)
    monkeypatch.setenv('PAPERASSIST_DATA_DIR',str(tmp_path/'data'))
    config=DatabaseConfig('test',url,schema);migration=get_migration_database_config()
    engine=create_engine(migration.url,poolclass=NullPool)
    with engine.begin() as db:
        assert db.exec_driver_sql('SELECT current_database()').scalar_one()=='paperassist_system_test'
        db.exec_driver_sql('CREATE SCHEMA '+engine.dialect.identifier_preparer.quote(schema))
    engine.dispose();migrate_database(migration)
    marker=Path(__file__).resolve().parents[3]/'script/.runtime/client-requirements-b05-sub4/task-c-lifecycle-schemas.jsonl'
    marker.parent.mkdir(parents=True,exist_ok=True)
    with marker.open('a',encoding='utf-8') as f:f.write(json.dumps(dict(schema=schema,directory=str(tmp_path),head='0068_bio_external_evidence'))+'\n')
    yield config


def processed_fixture(client,monkeypatch,tmp_path):
    from app.domain.bioinformatics import tabular_settings
    from app.domain.bioinformatics.execution import run_bio_import_task
    from app.domain.bioinformatics.analysis_execution import run_bio_analysis_task
    import_tabular=lambda payload:docker_call(tmp_path,'app.adapters.bio_engine.tabular_assays','import_tabular',payload)
    run_tabular=lambda payload:docker_call(tmp_path,'app.adapters.bio_engine.tabular_assays','run_tabular',payload)
    runtime=dict(available=True,blockers=[],engine_version='tabular_quantitative_v1.0.0',code_digest='a'*64,environment_digest='b'*64)
    monkeypatch.setattr(tabular_settings,'runtime_identity',lambda:runtime)
    staging=tmp_path/'science';monkeypatch.setenv('PAPERASSIST_BIO_STAGING_DIR',str(staging))
    project=create_project(client);base=f"/api/v1/projects/{project['id']}";files=[]
    for name,content in [('matrix.csv',b'feature_id,B0,B1,B2,A0,A1,A2\nf1,6,8,13,1,2,5\nf2,10,11,15,1,3,7\nf3,1,1,1,1,1,1\n'),('samples.csv',b'sample_id,condition,biological_unit_id,sample_role\nB0,B,B0,biological\nB1,B,B1,biological\nB2,B,B2,biological\nA0,A,A0,biological\nA1,A,A1,biological\nA2,A,A2,biological\n')]:
        item=str(uuid4());batch=client.post(base+'/bio-upload-batches',json={'items':[dict(client_id=item,filename=name,size_bytes=len(content))]},headers={'Idempotency-Key':str(uuid4())})
        assert batch.status_code==201,batch.text
        file=client.post(base+f"/bio-upload-batches/{batch.json()['id']}/items/{item}",files={'file':(name,content)})
        assert file.status_code==202,file.text
        files.append(file.json()['file_id'])
    body=request_body('proteomics','intensity');body['file_ids']=files;body['sample_columns']=['B0','B1','B2','A0','A1','A2'];body['scale'].update(namespace='protein_label',reference_version='fixed')
    for spec,file in zip(body['tables'],files):spec['file_id']=file
    created=client.post(base+'/bio-imports',json=body,headers={'Idempotency-Key':'new-import'})
    assert created.status_code==202,created.text
    value=created.json();task=value['task']
    assert client.post(base+'/bio-imports',json=body,headers={'Idempotency-Key':'new-import'}).json()==value
    assert client.post(base+'/bio-imports',json={**body,'name':'changed'},headers={'Idempotency-Key':'new-import'}).status_code==409
    def parser(frozen,out,settings):
        return import_tabular(dict(files=frozen['files'],config=frozen['tabular_config'],identity=runtime,output_directory=str(out)))
    wait=run_bio_import_task(task['id'],task['revision'],parser=parser,staging_directory=staging)
    assert wait['status']=='waiting_confirmation',wait
    detail=client.get(base+'/bio-imports/'+value['id']).json()
    confirm=client.post(base+'/bio-imports/'+value['id']+'/confirm',headers={'Idempotency-Key':'import-confirm'},json=dict(task_revision=detail['task']['revision'],checkpoint_id=detail['checkpoint_id'],wait_id=detail['wait_id'],candidate_sha256=detail['candidate']['sha256'],expected_dataset_revision=detail['expected_dataset_revision']))
    assert confirm.status_code==202,confirm.text
    done=run_bio_import_task(task['id'],confirm.json()['revision'],parser=parser,staging_directory=staging)
    assert done['status']=='succeeded',done
    source=client.get(base+'/bio-imports/'+value['id']).json()['result_source']
    setup=client.post(base+'/bio-analysis-setups',headers={'Idempotency-Key':'setup'},json=dict(recipe_code='tabular_quantitative_v1',name='samples',raw_source=source,expected_revision=0,params={}))
    assert setup.status_code==201,setup.text
    recipe=setup.json()
    run=client.post(base+'/bio-analysis-runs',headers={'Idempotency-Key':'run'},json=dict(raw_source=source,recipe_version_id=recipe['id'],expected_setup_revision=1))
    assert run.status_code==202,run.text
    run=run.json();task=run['task']
    def engine(payload,out,mode):return run_tabular({**payload,'output_directory':str(out),'mode':mode})
    wait=run_bio_analysis_task(task['id'],task['revision'],engine=engine,staging_directory=staging)
    assert wait['status']=='waiting_confirmation',wait
    detail=client.get(base+'/bio-analysis-runs/'+run['id']).json()
    confirmation=client.post(base+'/bio-analysis-runs/'+run['id']+'/confirm',headers={'Idempotency-Key':'analysis-confirm'},json=dict(task_revision=detail['task']['revision'],checkpoint_id=detail['checkpoint_id'],wait_id=detail['wait_id'],candidate_sha256=detail['candidate']['sha256'],expected_setup_revision=1))
    assert confirmation.status_code==202,confirmation.text
    done=run_bio_analysis_task(task['id'],confirmation.json()['revision'],engine=engine,staging_directory=staging)
    assert done['status']=='succeeded',done
    result=client.get(base+'/bio-analysis-runs/'+run['id']).json()['result_source']
    return base,result['processed_dataset_version_id']


def test_typed_evidence_formal_lifecycle_and_source_fence(client,monkeypatch,tmp_path):
    from app.domain.bio_insights.service import BioInsightsService
    from app.domain.bio_insights.execution import run_bio_insight_task
    from app.domain.storage_governance import service as governance
    monkeypatch.setattr(governance.shutil,'disk_usage',lambda _:type('Disk',(),dict(total=100*1024**3,free=80*1024**3,used=20*1024**3))())
    runtime=dict(engine_version='bio_insights_v1.0.0',code_digest='c'*64,environment_digest='e'*64,lock_sha256='f'*64)
    monkeypatch.setattr(BioInsightsService,'_runtime_for',lambda self,config:runtime)
    base,pid=processed_fixture(client,monkeypatch,tmp_path)
    original=b'<article><p id="Par6">ERBB2 HER2 V777L 13/105</p><p id="Alias">f1 also known as ERBB2</p></article>'
    uploaded=client.post(base+'/bio-resource-files',headers={'Idempotency-Key':'original'},files={'file':('study.xml',original)})
    assert uploaded.status_code==201,uploaded.text
    body=dict(file_id=uploaded.json()['file_id'],source_kind='original',title='typed original',intended_use='reference',original_data='unknown',typed_evidence=typed())
    saved=client.post(base+'/external-evidence',json=body,headers={'Idempotency-Key':'evidence'})
    assert saved.status_code==201,saved.text
    evidence=saved.json();assert evidence['verification_status']=='external_not_recomputed' and evidence['locator_verification']['locator_verified']
    assert client.get(base+'/external-evidence/requests/evidence').json()==evidence
    bad=copy.deepcopy(body);bad['typed_evidence']['locators'][0]['value']='absent'
    assert client.post(base+'/external-evidence',json=bad,headers={'Idempotency-Key':'wrong-locator'}).status_code==422
    metadata=client.get(base+'/bio-insights/sources/bio_processed_dataset_version/'+pid+'/observations').json()
    processed=client.get(base+'/bio-processed-datasets/'+pid).json()
    config=dict(kind='candidate',schema_version=2,candidates=[dict(object_id='ERBB2',source_id=pid,feature_id='f1',namespace='protein_label',species_taxon_id=None,reference_version='fixed',condition='primary tumor',mapping_evidence_source_id=evidence['id'],mapping_locator='Alias',mapping_quote='f1 also known as ERBB2')],evidence_source_ids=[evidence['id']])
    sources=[dict(source_kind='bio_processed_dataset_version',source_id=pid,sha256=processed['manifest_sha256'],role='processed'),dict(source_kind='external_evidence_version',source_id=evidence['id'],sha256=evidence['sha256'],role='external_evidence')]
    request=dict(kind='candidate',name='External matrix',decision='confirmed',expected_revision=0,config=config,sources=sources)
    preview=client.post(base+'/bio-insight-plans/preview',json=request);assert preview.status_code==200 and preview.json()['executable'],preview.text
    wrong=copy.deepcopy(request);wrong['sources'][1]['sha256']='0'*64;assert client.post(base+'/bio-insight-plans/preview',json=wrong).status_code==409
    foreign=create_project(client)['id'];assert client.get('/api/v1/projects/'+foreign+'/external-evidence/'+evidence['id']).status_code==404
    plan=client.post(base+'/bio-insight-plans',json=request,headers={'Idempotency-Key':'matrix-plan'});assert plan.status_code==201,plan.text
    plan=plan.json();run=client.post(base+'/bio-insight-runs',json=dict(plan_version_id=plan['id'],expected_plan_revision=1,source_digest=plan['source_digest']),headers={'Idempotency-Key':'matrix-run'});assert run.status_code==202,run.text
    run=run.json();engine=lambda payload,out:docker_call(tmp_path,'app.adapters.bio_insights_engine.pipeline','run',{**payload,'output_directory':str(out)})
    done=run_bio_insight_task(run['task_id'],run['task_revision'],task_type='bio_candidate',engine=engine,staging_directory=tmp_path/'stage');assert done['status']=='succeeded',done
    result=client.get(base+'/bio-insight-results/'+done['result_bio_insight_result_version_id']).json();assert result['summary']['matrix_row_count']==1 and result['summary']['independent_support_count']==0
    table=client.get(base+'/bio-insight-results/'+result['id']+'/tables/candidate_evidence').json();member=next(m for m in result['members'] if m['key']=='candidate_evidence')
    source=dict(source_kind='bio_insight_result_member',source_id=member['id'],sha256=member['sha256'],locator=dict(kind='row',table='candidate_evidence',row_key={'row_key':table['items'][0]['row_key']},column='source_statement'))
    projected=client.post(base+'/research-results/preview',json={'sources':[source]});assert projected.status_code==200,projected.text
    fact=projected.json()['catalogs'][0]['facts'][0];assert fact['origin']=='external_result' and fact['verification_status']=='unverified'
    finding=client.post(base+'/research-findings',json=dict(title='External statements',sources=[source],selected_fact_ids=[fact['id']],expected_revision=0),headers={'Idempotency-Key':'finding'});assert finding.status_code==201,finding.text

def test_finite_support_originals_and_html_are_inert(client,monkeypatch):
    from app.domain.storage_governance import service as governance
    monkeypatch.setattr(governance.shutil,'disk_usage',lambda _:type('Disk',(),dict(total=100*1024**3,free=80*1024**3,used=20*1024**3))())
    project=create_project(client);base='/api/v1/projects/'+project['id']
    payload=dict(schema='independent_validation_design_v1',material_source_ids=['fixed-material'],object_id='ERBB2',species_taxon_id=9606,condition='tumor',numerator='tumor',denominator='normal')
    raw=json.dumps(payload).encode();response=client.post(base+'/bio-resource-files',headers={'Idempotency-Key':'support-json'},files={'file':('design.json',raw)})
    assert response.status_code==201,response.text
    saved=response.json();assert client.get(base+'/files/'+saved['file_id']+'/download').content==raw
    invalid=client.post(base+'/bio-resource-files',headers={'Idempotency-Key':'arbitrary-json'},files={'file':('arbitrary.json',b'{"schema":"generic"}')});assert invalid.status_code==422
    html=b'<html><script>never_execute()</script><p>ERBB2 category Medium</p></html>'
    response=client.post(base+'/bio-resource-files',headers={'Idempotency-Key':'html-original'},files={'file':('atlas.html',html)});assert response.status_code==201,response.text
    body=dict(file_id=response.json()['file_id'],source_kind='original',title='atlas source',intended_use='reference',original_data='unknown',typed_evidence={**typed(),'evidence_type':'expression_atlas','locators':[dict(kind='text',value='ERBB2 category Medium',quote='category Medium')]})
    source=client.post(base+'/external-evidence',json=body,headers={'Idempotency-Key':'html-evidence'});assert source.status_code==201,source.text
    assert source.json()['locator_verification']['biological_claim_status']=='source_reported' and source.json()['computed_by_system'] is False
