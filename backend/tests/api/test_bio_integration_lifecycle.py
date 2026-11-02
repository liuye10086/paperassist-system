"""New formal integration lifecycle; numeric execution stays in the fixed Docker image."""
import copy,csv,io,json,os,subprocess
from pathlib import Path
from uuid import uuid4
import pytest
from tests.api.test_projects import client,create_project

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
    marker=Path(__file__).resolve().parents[3]/'script/.runtime/client-requirements-b05-sub4/task-b-lifecycle-schemas.jsonl'
    marker.parent.mkdir(parents=True,exist_ok=True)
    with marker.open('a',encoding='utf-8') as f:f.write(json.dumps(dict(schema=schema,directory=str(tmp_path),head='0067_bio_integration'))+'\n')
    yield config


def test_integration_formal_resources_confirmation_publication_and_research(client,monkeypatch,tmp_path):
    from app.domain.bio_insights.service import BioInsightsService
    from app.domain.bio_insights.execution import run_bio_insight_task
    from app.domain.bio_insights.contracts import ResourceImportRequest,ResultImportConfig
    from app.domain.bio_insights.integration_contracts import IntegrationConfig,SAMPLE_COLUMNS,OBJECT_COLUMNS
    runtime=dict(engine_version='bio_insights_v1.0.0',code_digest='c'*64,environment_digest='e'*64,lock_sha256='f'*64)
    monkeypatch.setattr(BioInsightsService,'_runtime',lambda self:runtime)
    monkeypatch.setattr(BioInsightsService,'_runtime_for',lambda self,config:runtime)
    root=Path(__file__).resolve().parents[3];app=root/'backend/app';attempt=[0]
    def engine(payload,output):
        attempt[0]+=1
        def linux(value):
            if isinstance(value,dict):return {k:linux(v) for k,v in value.items()}
            if isinstance(value,list):return [linux(v) for v in value]
            if isinstance(value,str) and value.replace('\\','/').startswith(tmp_path.as_posix()):return '/work'+value.replace('\\','/')[len(tmp_path.as_posix()):]
            return value
        request=tmp_path/f'payload-{attempt[0]}.json';answer=tmp_path/f'answer-{attempt[0]}.json'
        request.write_text(json.dumps(linux({**payload,'output_directory':str(output)})),encoding='utf-8')
        script="import json;from pathlib import Path;from app.adapters.bio_insights_engine.pipeline import run;p=json.loads(Path('/work/"+request.name+"').read_bytes());r=run(p);Path('/work/"+answer.name+"').write_text(json.dumps(r))"
        command=['docker','run','--rm','--network','none','--memory','2g','--cpus','2','-e','OPENBLAS_NUM_THREADS=1','-e','OMP_NUM_THREADS=1','-e','MKL_NUM_THREADS=1','-v',str(app)+':/app/app:ro','-v',str(tmp_path)+':/work','-w','/app','paperassist-client-b05-sub4-deps:local','/opt/paperassist-bio-insights/bin/python','-c',script]
        done=subprocess.run(command,capture_output=True,text=True,timeout=120);assert done.returncode==0,done.stderr
        def windows(value):
            if isinstance(value,dict):return {k:windows(v) for k,v in value.items()}
            if isinstance(value,list):return [windows(v) for v in value]
            if isinstance(value,str) and value.startswith('/work/'):return str(tmp_path/Path(value[6:]))
            return value
        return windows(json.loads(answer.read_bytes()))
    from app.domain.storage_governance import service as storage_governance
    monkeypatch.setattr(storage_governance.shutil,'disk_usage',lambda _:type('Disk',(),dict(total=100*1024**3,free=80*1024**3,used=20*1024**3))())
    project=create_project(client)['id'];base='/api/v1/projects/'+project
    def upload(name,content):
        response=client.post(base+'/bio-resource-files',headers={'Idempotency-Key':name},files={'file':(name,content)})
        assert response.status_code==201,response.text
        return response.json()
    def publish(config,sources,name):
        body=dict(name=name,kind=config['kind'],decision='confirmed',expected_revision=0,config=config,sources=sources)
        preview=client.post(base+'/bio-insight-plans/preview',json=body)
        assert preview.status_code==200 and preview.json()['executable'],preview.text
        plan=client.post(base+'/bio-insight-plans',json=body,headers={'Idempotency-Key':name+'-plan'})
        assert plan.status_code==201,plan.text
        plan=plan.json();request=dict(plan_version_id=plan['id'],expected_plan_revision=1,source_digest=plan['source_digest'])
        created=client.post(base+'/bio-insight-runs',json=request,headers={'Idempotency-Key':name+'-run'})
        assert created.status_code==202,created.text
        run=created.json()
        assert client.post(base+'/bio-insight-runs',json=request,headers={'Idempotency-Key':name+'-run'}).json()['id']==run['id']
        task_type='bio_integration' if config['kind']=='integration' else 'bio_result_import'
        done=run_bio_insight_task(run['task_id'],run['task_revision'],task_type=task_type,engine=engine,staging_directory=tmp_path/'stage')
        assert done['status']=='succeeded',done
        result=client.get(base+'/bio-insight-results/'+done['result_bio_insight_result_version_id']).json()
        assert client.get('/api/v1/tasks/'+run['task_id']+'/workspace').status_code==200
        return result,body
    results=[]
    for i,effect in enumerate((2,-3)):
        uploaded=upload(f'comparison{i}.csv',f'gene,effect,q\ng,{effect},0.01\n'.encode())
        config=ResultImportConfig(file_source_id=uploaded['file_id'],parse_version_id=uploaded['parse_version_id'],species_taxon_id=9606,namespace='symbol',reference_version='fixture1',columns={'feature_id':'gene','effect':'effect','q_value':'q'},contrast_id='c',numerator='A',denominator='B',original_method='saved complete fixture',original_correction_scope='all declared fixture objects',complete_tested_universe=True).model_dump(mode='json')
        result,_=publish(config,[dict(source_kind='original_file',source_id=uploaded['file_id'],sha256=uploaded['sha256'],role='table')],f'comparison{i}');results.append(result)
    sample=dict(dataset_version='declared-fixed-version',observation_id='s1',donor_id='',tissue='',time='',match_group='s1',relationship='author_declared_matched_sample',basis='author declared; donor unverified',independent_unit_verified='false')
    obj=dict(source_dataset_version='left',source_id='g',source_namespace='symbol',source_species=9606,source_version='unknown',target_dataset_version='right',target_id='g',target_namespace='symbol',target_species=9606,target_version='unknown',relationship='manual_source_label_correspondence',basis='source labels only',ambiguity='none',decision='include')
    for kind,cols,row in [('sample_correspondence',SAMPLE_COLUMNS,sample),('object_correspondence',OBJECT_COLUMNS,obj)]:
        buffer=io.StringIO();writer=csv.DictWriter(buffer,fieldnames=cols,delimiter='\t',lineterminator='\n');writer.writeheader();writer.writerow(row)
        uploaded=upload(kind+'.tsv',buffer.getvalue().encode())
        config=ResourceImportRequest(kind=kind,title=kind,species_taxon_id=9606,namespace='symbol',release='unknown',source=dict(institution='fixture',name='source labels',description='synthetic declarations'),usage=dict(basis='fixture',redistribution_allowed=True,scope='project'),files=[dict(file_id=uploaded['file_id'],sha256=uploaded['sha256'],parse_version_id=uploaded['parse_version_id'],role=kind,format='tsv')])
        created=client.post(base+'/bio-resources',json=config.model_dump(mode='json'),headers={'Idempotency-Key':kind})
        assert created.status_code==202,created.text
        resource=created.json();task=resource['task'];done=run_bio_insight_task(task['id'],task['revision'],task_type='bio_resource_import',engine=engine,staging_directory=tmp_path/'stage')
        assert done['status']=='succeeded',done
    sources=[dict(source_kind='bio_insight_result_version',source_id=r['id'],sha256=r['manifest_sha256'],role='result') for r in results]
    config=IntegrationConfig(mapping_confirmed=True,concordances=[dict(concordance_id='c',left_result_source_id=results[0]['id'],right_result_source_id=results[1]['id'],left_contrast_id='c',right_contrast_id='c',object_ids=['g','untested'],direction_alignment='reverse',comparison_basis='frozen reversed comparison labels',q_column='original_q')]).model_dump(mode='json')
    result,body=publish(config,sources,'integration');assert result['kind']=='integration'
    rows=client.get(base+'/bio-insight-results/'+result['id']+'/tables/integration_concordance').json()['items']
    assert [r['status'] for r in rows]==['support','unknown']
    assert all(r['independent_support']=='False' for r in rows)
    wrong=copy.deepcopy(body);wrong['sources'][0]['sha256']='0'*64
    assert client.post(base+'/bio-insight-plans/preview',json=wrong).status_code==409
    other=create_project(client)['id'];assert client.post('/api/v1/projects/'+other+'/bio-insight-plans/preview',json=body).status_code==404
    member=next(m for m in result['members'] if m['key']=='integration_concordance')
    selection=dict(source_kind='bio_insight_result_member',source_id=member['id'],sha256=member['sha256'],locator=dict(kind='row',table='integration_concordance',row_key={'row_key':rows[0]['row_key']},column='left_effect'))
    preview=client.post(base+'/research-results/preview',json={'sources':[selection]});assert preview.status_code==200,preview.text
    catalog=preview.json()['catalogs'][0];assert any('matched observation' in text for text in catalog['limitations'])
    finding=client.post(base+'/research-findings',headers={'Idempotency-Key':'integration-finding'},json=dict(title='Frozen cross-layer agreement',sources=[selection],selected_fact_ids=[catalog['facts'][0]['id']],expected_revision=0));assert finding.status_code==201,finding.text
    assert attempt[0]==5
