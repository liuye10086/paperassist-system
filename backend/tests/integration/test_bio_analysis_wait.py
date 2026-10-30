"""Synthetic worker payloads test durable SQL wait/publication, not scientific validity."""
import hashlib
import json
from pathlib import Path
import pytest
from tests.api.test_projects import client
from tests.integration.test_bio_analysis_setup import raw_source
from app.db.database import database_connection,migration_connection


def frozen_runtime(monkeypatch):
    value=dict(available=True,blockers=[],engine_version='visium_explore_v1.0.0',environment_digest='b'*64,code_digest='c'*64)
    monkeypatch.setattr('app.domain.bioinformatics.analysis_service.runtime_identity',lambda:value)
    monkeypatch.setattr('app.adapters.bio_figure_store.runtime_identity',lambda:value)


def create(client,monkeypatch,tmp_path,run_key='run',with_mapping=False):
    frozen_runtime(monkeypatch);base,source=raw_source(client)
    mapping={}
    if with_mapping:
        response=client.post(base+'/bio-observation-maps',json=dict(name='frozen mapping',raw_source=source,expected_revision=0,
            rows=[dict(barcode='AA-1',section=dict(status='known',value='S1'))]),headers={'Idempotency-Key':'payload-map'})
        assert response.status_code==201,response.text
        mapping['observation_map_version_id']=response.json()['id']
    recipe=client.post(base+'/bio-analysis-setups',json=dict(name='transaction fixture',raw_source=source,expected_revision=0,params={'min_spots':1},**mapping),headers={'Idempotency-Key':'recipe'})
    assert recipe.status_code==201,recipe.text
    request=dict(raw_source=source,recipe_version_id=recipe.json()['id'],expected_setup_revision=1)
    response=client.post(base+'/bio-analysis-runs',json=request,headers={'Idempotency-Key':run_key})
    assert response.status_code==202,response.text
    staging=tmp_path/'bio-staging';monkeypatch.setenv('PAPERASSIST_BIO_STAGING_DIR',str(staging))
    return base,response.json(),staging,request


def payload_engine(payload,output,mode):
    json.dumps(payload,allow_nan=False)
    contents={'observations':('tsv',b'barcode\traw_index\tx\ty\tkept\texclusion_reasons\tcluster\nAA-1\t0\t2\t2\tTrue\t\t0\nBB-1\t1\t4\t4\tTrue\t\t0\n'),
              'features':('tsv',b'feature_id\tsymbol\tkept\nENSG_TEST_1\tG1\tTrue\n'),
              'methods':('txt',b'Synthetic persistence fixture only; not numerical evidence.\n')}
    members=[]
    for key,(fmt,content) in contents.items():
        path=Path(output)/(key+'.'+fmt);path.write_bytes(content)
        members.append(dict(key=key,path=str(path),role='table' if fmt=='tsv' else 'methods',format=fmt,size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest()))
    manifest=dict(schema_version=1,identity=payload['identity'],raw_source=payload['identity']['raw_source'],params=payload['config'],
        tables=[dict(key=k,label=k,status='completed',reason=None) for k in ('observations','features')],layers={})
    return dict(engine_version='visium_explore_v1.0.0',status='completed',outputs=members,manifest=manifest,summary={'observations':2,'features':1},steps=[dict(key='fixture',status='completed',reason=None,params={})],checks={},effective_params=payload['config'])


def test_engine_payload_excludes_database_timestamps_for_mapping_processed_and_annotation(client,monkeypatch,tmp_path):
    from datetime import datetime
    from app.domain.bioinformatics.analysis_execution import run_bio_figure_task
    base,created,staging,request=create(client,monkeypatch,tmp_path,with_mapping=True)
    with database_connection() as db:
        row=db.execute('SELECT o.scanned_at FROM storage_objects o JOIN bio_observation_map_versions v ON v.mapping_object_id=o.id').fetchone()
        assert isinstance(row['scanned_at'],datetime), 'Exercise the actual ledger timestamp, not a JSON mock'
    seen=[]
    def transport(payload,output,mode):
        json.dumps(payload,allow_nan=False)
        allowed={'path','sha256','size_bytes','role','format','source_file_id','source_member_name','compression','verification_state'}
        for group in ('raw','processed','annotation'):
            if group not in payload:continue
            seen.append(group)
            for member in payload[group]['members'].values():
                assert set(member)<=allowed
                assert {'path','sha256','size_bytes','role','format'}<=set(member)
        return payload_engine(payload,output,mode)
    waiting=run(created['task'],staging,transport)
    assert waiting['status']=='waiting_confirmation',waiting
    queued=confirm(client,base,created,client.get(base+'/bio-analysis-runs/'+created['id']).json())
    assert queued.status_code==202,queued.text
    done=run(queued.json(),staging,transport);assert done['status']=='succeeded',done
    result=client.get(base+'/bio-processed-datasets/'+done['result_bio_processed_dataset_version_id']).json()
    annotation=client.post(base+'/bio-annotation-sets',json=dict(name='mapped region',raw_source=request['raw_source'],
        processed_dataset_version_id=result['id'],expected_revision=0,labels=[dict(id='label',name='region')],
        regions=[dict(id='region',label_id='label',points=[[1,1],[3,1],[3,3],[1,3]])]),headers={'Idempotency-Key':'payload-annotation'})
    assert annotation.status_code==201,annotation.text
    figure=client.post(base+'/bio-figures',json=dict(processed_source=result['source'],annotation_version_id=annotation.json()['id'],
        expected_version=0,config={'kind':'annotation'}),headers={'Idempotency-Key':'payload-figure'})
    assert figure.status_code==202,figure.text
    task=figure.json()['task']
    done=run_bio_figure_task(task['id'],task['revision'],engine=transport,staging_directory=staging)
    assert done['status']=='succeeded',done
    assert {'raw','processed','annotation'}<=set(seen)


def run(task,staging,engine=payload_engine):
    from app.domain.bioinformatics.analysis_execution import run_bio_analysis_task
    return run_bio_analysis_task(task['id'],task['revision'],engine=engine,staging_directory=staging)


def confirm(client,base,created,view,key='confirm'):
    body={k:view[k] for k in ('checkpoint_id','wait_id','expected_setup_revision')}
    body.update(task_revision=view['task']['revision'],candidate_sha256=view['candidate']['sha256'])
    return client.post(base+'/bio-analysis-runs/'+created['id']+'/confirm',json=body,headers={'Idempotency-Key':key})


def test_qc_wait_confirmation_and_atomic_result_pointers(client,monkeypatch,tmp_path):
    base,created,staging,request=create(client,monkeypatch,tmp_path,run_key='r'*128)
    assert client.post(base+'/bio-analysis-runs',json=request,headers={'Idempotency-Key':'r'*128}).json()==created
    waiting=run(created['task'],staging)
    assert waiting['status']=='waiting_confirmation',waiting
    view=client.get(base+'/bio-analysis-runs/'+created['id']).json()
    with database_connection() as db:
        wait=db.execute('SELECT * FROM task_waits WHERE task_id=%s',(waiting['id'],)).fetchone()
        attempt=db.execute('SELECT * FROM task_attempts WHERE task_id=%s',(waiting['id'],)).fetchone()
        assert wait['kind']=='bio_analysis_confirmation' and attempt['finished_at'] and attempt['lease_owner'] is None
        assert db.execute('SELECT count(*) AS n FROM bio_processed_dataset_versions').fetchone()['n']==0
    queued=confirm(client,base,created,view)
    assert queued.status_code==202,queued.text
    assert confirm(client,base,created,view).json()==queued.json()
    assert confirm(client,base,created,view,'stale-other-key').status_code==409
    done=run(queued.json(),staging)
    assert done['status']=='succeeded',done
    result=client.get(base+'/bio-processed-datasets/'+done['result_bio_processed_dataset_version_id'])
    assert result.status_code==200,result.text
    assert result.json()['source']['raw_source']==request['raw_source']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM bio_processed_dataset_versions').fetchone()['n']==1
        assert db.execute("SELECT count(*) AS n FROM storage_reservations WHERE task_id=%s AND state<>'settled'",(done['id'],)).fetchone()['n']==0
        row=db.execute('SELECT * FROM bio_analysis_runs WHERE id=%s',(created['id'],)).fetchone()
        assert row['processed_dataset_version_id']==done['result_bio_processed_dataset_version_id']
    lookup=client.get(base+'/bio-requests/confirm?kind=confirmation')
    assert lookup.status_code==200 and lookup.json()['id']==created['id']
    other=client.post(base+'/bio-analysis-runs',json=request,headers={'Idempotency-Key':'second-run'})
    assert other.status_code==202,other.text
    assert run(other.json()['task'],staging)['status']=='waiting_confirmation'
    other_view=client.get(base+'/bio-analysis-runs/'+other.json()['id']).json()
    assert confirm(client,base,other.json(),other_view).status_code==202
    ambiguous=client.get(base+'/bio-requests/confirm?kind=confirmation')
    assert ambiguous.status_code==409,ambiguous.text


def test_interrupted_publish_reuses_exact_prepared_outputs_without_second_compute(client,monkeypatch,tmp_path):
    from app.adapters.bio_objects import BioAnalysisObjects
    from app.core.exceptions import StorageError
    base,created,staging,_=create(client,monkeypatch,tmp_path)
    waiting=run(created['task'],staging);assert waiting['status']=='waiting_confirmation',waiting
    view=client.get(base+'/bio-analysis-runs/'+created['id']).json();queued=confirm(client,base,created,view);assert queued.status_code==202,queued.text
    original=BioAnalysisObjects.write
    def fail(*args):raise StorageError('storage_unavailable','Synthetic interrupted write')
    monkeypatch.setattr(BioAnalysisObjects,'write',fail)
    failed=run(queued.json(),staging);assert failed['status']=='failed' and failed['error_code']=='storage_unavailable',failed
    with database_connection() as db:
        cp=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(failed['id'],)).fetchone()
        assert cp['next_node']=='publish' and cp['state_json']['prepared']['stage']=='compute'
        assert db.execute('SELECT count(*) AS n FROM bio_processed_dataset_versions').fetchone()['n']==0
        reserved=[dict(r) for r in db.execute('SELECT operation_key,sha256,size_bytes FROM storage_reservations WHERE task_id=%s ORDER BY operation_key',(failed['id'],))]
    monkeypatch.setattr(BioAnalysisObjects,'write',original)
    retried=client.post('/api/v1/tasks/'+failed['id']+'/retry',json={'expected_revision':failed['revision']})
    assert retried.status_code==202,retried.text
    def forbid(*args,**kwargs):pytest.fail('Prepared publication must never recompute')
    done=run(retried.json(),staging,forbid);assert done['status']=='succeeded',done
    with database_connection() as db:
        assert [dict(r) for r in db.execute('SELECT operation_key,sha256,size_bytes FROM storage_reservations WHERE task_id=%s ORDER BY operation_key',(failed['id'],))]==reserved


def test_expired_qc_confirmation_closes_wait_without_requeue(client,monkeypatch,tmp_path):
    base,created,staging,_=create(client,monkeypatch,tmp_path)
    assert run(created['task'],staging)['status']=='waiting_confirmation'
    view=client.get(base+'/bio-analysis-runs/'+created['id']).json()
    with migration_connection() as db:
        db.execute("UPDATE task_waits SET created_at=created_at-interval '25 hours' WHERE task_id=%s",(created['task']['id'],))
    response=confirm(client,base,created,view)
    assert response.status_code==409,response.text
    current=client.get(base+'/bio-analysis-runs/'+created['id']).json()
    assert current['task']['status']=='failed' and current['task']['error_code']=='bio_confirmation_stale'
    assert current['candidate']['sha256']==view['candidate']['sha256']
    with database_connection() as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(created['task']['id'],)).fetchone()
        from app.domain.bioinformatics.analysis_service import recovery_actions
        assert recovery_actions(db,dict(task))==[]
        assert db.execute('SELECT status FROM task_waits WHERE id=%s',(view['wait_id'],)).fetchone()['status']=='superseded'
        assert db.execute('SELECT count(*) AS n FROM bio_analysis_runs').fetchone()['n']==1


def test_published_default_figure_keeps_gene_configuration_and_annotations_use_clusters(client,monkeypatch,tmp_path):
    base,created,staging,_=create(client,monkeypatch,tmp_path)
    assert run(created['task'],staging)['status']=='waiting_confirmation'
    view=client.get(base+'/bio-analysis-runs/'+created['id']).json()
    queued=confirm(client,base,created,view);assert queued.status_code==202
    def engine(payload,output,mode):
        result=payload_engine(payload,output,mode)
        config=dict(gene_ids=['ENSG_TEST_1'],layer='normalized',cmap='magma',vmin=0.0,vmax=7.0,title='fixed gene',output_language='zh-CN')
        for suffix,fmt,content in [('png','png',b'synthetic PNG fixture'),('pdf','pdf',b'synthetic PDF fixture'),('data','json',b'{}'),
            ('manifest','json',json.dumps(dict(config=config,dpi=150,width_inches=8.0,height_inches=6.0)).encode())]:
            key='spatial_gene_0_'+suffix;path=Path(output)/(key+'.'+fmt);path.write_bytes(content)
            result['outputs'].append(dict(key=key,path=str(path),role='figure_'+suffix,format=fmt,size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest()))
        return result
    done=run(queued.json(),staging,engine);assert done['status']=='succeeded',done
    result=client.get(base+'/bio-processed-datasets/'+done['result_bio_processed_dataset_version_id']).json()
    figure=result['figures'][0]
    assert figure['config']['gene_ids']==['ENSG_TEST_1']
    assert {k:figure['config'][k] for k in ('palette','layer','dpi','width','height')}==dict(palette='magma',layer='normalized',dpi=150,width=1200,height=900)
    old_member=next(m for m in figure['members'] if m['format']=='png')
    old_bytes=client.get(old_member['download_url']).content
    redraw=dict(processed_source=result['source'],expected_version=1,config={**figure['config'],'palette':'viridis'})
    endpoint=base+'/bio-figures/'+figure['root_id']+'/versions'
    requested=client.post(endpoint,json=redraw,headers={'Idempotency-Key':'f'*128})
    assert requested.status_code==202,requested.text
    assert client.post(endpoint,json=redraw,headers={'Idempotency-Key':'f'*128}).json()==requested.json()
    from app.domain.bioinformatics.analysis_execution import run_bio_figure_task
    figure_done=run_bio_figure_task(requested.json()['task']['id'],requested.json()['task']['revision'],engine=payload_engine,staging_directory=staging)
    assert figure_done['status']=='succeeded',figure_done
    saved=client.get(base+'/bio-figures/'+requested.json()['id']).json()
    assert saved['version']==2 and saved['config']['gene_ids']==['ENSG_TEST_1']
    assert client.get(old_member['download_url']).content==old_bytes
    annotation=dict(name='cluster label',raw_source=result['source']['raw_source'],processed_dataset_version_id=result['id'],expected_revision=0,
        labels=[dict(id='l',name='enriched',cluster_ids=['0'])])
    response=client.post(base+'/bio-annotation-sets',json=annotation,headers={'Idempotency-Key':'cluster-label'})
    assert response.status_code==201,response.text
    assert all(row['label_id']=='l' for row in response.json()['assignments'])
    bad=client.post(base+'/bio-annotation-sets',json={**annotation,'labels':[dict(id='l',name='bad',cluster_ids=['missing'])]},headers={'Idempotency-Key':'bad-cluster'})
    assert bad.status_code==422,bad.text
    from app.maintenance.bio_analysis_audit import audit_bio_analysis
    from app.domain.file_lifecycle.bio_analysis_references import read_groups
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM bio_processed_dataset_versions').fetchone()['n']==1
        assert all(check['invalid']==0 for check in audit_bio_analysis(db))
        source=result['source']['raw_source'];file=db.execute('SELECT * FROM files WHERE id=%s',(source['source_file_ids'][0],)).fetchone()
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(source['project_id'],)).fetchone()['owner_id']
        groups=read_groups(db,dict(file),owner)
        assert groups['bio_processed_dataset_versions'] and groups['bio_figure_versions'] and groups['bio_annotation_versions']
        assert all(row['_integrity_valid'] for rows in groups.values() for row in rows)
    assessment=client.get(base+'/files/'+result['source']['raw_source']['source_file_ids'][0]+'/lifecycle/assessment')
    assert assessment.status_code==200,assessment.text
    assert 'bio_history_retained' in [r['code'] for r in assessment.json()['reasons']]
    assert 'integrity_unknown' not in [r['code'] for r in assessment.json()['reasons']]
    from sqlalchemy.exc import DBAPIError
    with pytest.raises(DBAPIError,match='Immutable bio analysis snapshot'):
        with migration_connection() as db:
            db.execute("UPDATE bio_processed_dataset_versions SET engine_version='tampered' WHERE id=%s",(result['id'],))


def test_database_publication_failure_rolls_back_all_results_and_retry_reuses_outputs(client,monkeypatch,tmp_path):
    from app.domain.bioinformatics import analysis_service
    from app.core.exceptions import StorageError
    base,created,staging,_=create(client,monkeypatch,tmp_path)
    assert run(created['task'],staging)['status']=='waiting_confirmation'
    queued=confirm(client,base,created,client.get(base+'/bio-analysis-runs/'+created['id']).json())
    original=analysis_service.insert
    def fail_after_processed_insert(db,table,row):
        original(db,table,row)
        if table=='bio_processed_dataset_versions':raise StorageError('storage_unavailable','Synthetic transaction interruption')
    monkeypatch.setattr(analysis_service,'insert',fail_after_processed_insert)
    failed=run(queued.json(),staging)
    assert failed['status']=='failed' and failed['error_code']=='storage_unavailable',failed
    with database_connection() as db:
        for table in ('bio_processed_dataset_versions','bio_analysis_artifacts','bio_figure_versions','bio_figure_members'):
            assert db.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n']==0
        assert db.execute('SELECT processed_dataset_version_id FROM bio_analysis_runs WHERE id=%s',(created['id'],)).fetchone()['processed_dataset_version_id'] is None
        assert db.execute('SELECT result_bio_processed_dataset_version_id FROM tasks WHERE id=%s',(failed['id'],)).fetchone()['result_bio_processed_dataset_version_id'] is None
    monkeypatch.setattr(analysis_service,'insert',original)
    response=client.post('/api/v1/tasks/'+failed['id']+'/retry',json={'expected_revision':failed['revision']})
    assert response.status_code==202,response.text
    def forbid(*args,**kwargs):pytest.fail('Rolled back publication must reuse the prepared result')
    assert run(response.json(),staging,forbid)['status']=='succeeded'
