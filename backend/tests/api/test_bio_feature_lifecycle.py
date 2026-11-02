"""Feature API/task/publication/finding slice; science runs only in Docker."""
import copy,json,os,subprocess
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
    marker=Path(__file__).resolve().parents[3]/'script/.runtime/client-requirements-b05-sub4/task-a-lifecycle-schemas.jsonl'
    marker.parent.mkdir(parents=True,exist_ok=True)
    with marker.open('a',encoding='utf-8') as f:f.write(json.dumps(dict(schema=schema,directory=str(tmp_path),head='0066_bio_feature_extraction'))+'\n')
    yield config


def test_feature_native_lifecycle_freezes_source_recovers_and_projects(client,monkeypatch,tmp_path):
    from app.domain.bio_insights.service import BioInsightsService
    from app.domain.bio_insights.execution import run_bio_insight_task
    from app.domain.bio_insights.contracts import ResourceImportRequest
    from app.domain.bio_insights.feature_contracts import FeatureExtractConfig
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
    upload=client.post(base+'/bio-resource-files',headers={'Idempotency-Key':'feature-upload'},files={'file':('rna.fasta',b'>x\nACGTNN\n>y\nNN\n')})
    assert upload.status_code==201,upload.text
    uploaded=upload.json();assert client.get(base+'/bio-resource-files/requests/feature-upload').json()==uploaded
    cfg=ResourceImportRequest(kind='sequence',title='T encoded RNA',sequence_type='rna',nucleotide_encoding='T',species_taxon_id=9606,namespace='refseq',release='fixture1',source=dict(institution='synthetic',name='RNA fixture',description='engineering only'),usage=dict(basis='fixture',redistribution_allowed=True,scope='project'),files=[dict(file_id=uploaded['file_id'],sha256=uploaded['sha256'],role='fasta',format='fasta')])
    response=client.post(base+'/bio-resources',json=cfg.model_dump(mode='json'),headers={'Idempotency-Key':'feature-resource'})
    assert response.status_code==202,response.text
    resource=response.json();task=resource['task']
    done=run_bio_insight_task(task['id'],task['revision'],task_type='bio_resource_import',engine=engine,staging_directory=tmp_path/'stage')
    assert done['status']=='succeeded',done
    resource=client.get(base+'/bio-resources/'+resource['id']).json()
    config=FeatureExtractConfig(resource_source_ids=[resource['id']],steps=[dict(operation='annotation',annotation_field='gc_fraction',annotation_operator='known')]).model_dump(mode='json')
    body=dict(name='Feature extraction',kind='feature_extract',decision='confirmed',expected_revision=0,config=config,sources=[dict(source_kind='bio_resource_version',source_id=resource['id'],sha256=resource['manifest_sha256'],role='feature_input')])
    preview=client.post(base+'/bio-insight-plans/preview',json=body);assert preview.status_code==200 and preview.json()['executable'],preview.text
    wrong=copy.deepcopy(body);wrong['sources'][0]['sha256']='0'*64
    assert client.post(base+'/bio-insight-plans/preview',json=wrong).status_code==409
    other=create_project(client)['id'];assert client.post('/api/v1/projects/'+other+'/bio-insight-plans/preview',json=body).status_code==404
    plan=client.post(base+'/bio-insight-plans',json=body,headers={'Idempotency-Key':'feature-plan'});assert plan.status_code==201,plan.text
    plan=plan.json();run_body=dict(plan_version_id=plan['id'],expected_plan_revision=1,source_digest=plan['source_digest'])
    response=client.post(base+'/bio-insight-runs',json=run_body,headers={'Idempotency-Key':'feature-run'});assert response.status_code==202,response.text
    run=response.json();replay=client.post(base+'/bio-insight-runs',json=run_body,headers={'Idempotency-Key':'feature-run'})
    assert replay.json()['id']==run['id']
    done=run_bio_insight_task(run['task_id'],run['task_revision'],task_type='bio_feature_extract',engine=engine,staging_directory=tmp_path/'stage');assert done['status']=='succeeded',done
    result=client.get(base+'/bio-insight-results/'+done['result_bio_insight_result_version_id']).json()
    assert result['kind']=='feature_extract' and result['summary']['selected_count']==1
    assert client.get('/api/v1/tasks/'+run['task_id']+'/workspace').status_code==200
    rows=client.get(base+'/bio-insight-results/'+result['id']+'/tables/feature_results').json()['items'];assert len(rows)==2
    member=next(m for m in result['members'] if m['key']=='feature_results')
    source=dict(source_kind='bio_insight_result_member',source_id=member['id'],sha256=member['sha256'],locator=dict(kind='row',table='feature_results',row_key={'row_key':rows[0]['row_key']},column='gc_fraction'))
    preview=client.post(base+'/research-results/preview',json={'sources':[source]});assert preview.status_code==200,preview.text
    catalog=preview.json()['catalogs'][0];assert catalog['facts'][0]['origin']=='system_computed' and any('Cα' in s for s in catalog['limitations'])
    finding=client.post(base+'/research-findings',headers={'Idempotency-Key':'feature-finding'},json=dict(title='Extracted RNA features',sources=[source],selected_fact_ids=[catalog['facts'][0]['id']],expected_revision=0));assert finding.status_code==201,finding.text
    assert attempt[0]==2
