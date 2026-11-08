"""Real database/task/storage; synthetic injected leaves, not scientific evidence."""
import hashlib,io,json
from uuid import uuid4
import numpy as np
import pytest
from tests.api.test_projects import client,create_project


@pytest.fixture
def ready_single_cell(client,monkeypatch,tmp_path):
    from app.domain.bioinformatics import single_cell_settings
    from app.domain.bioinformatics.execution import run_bio_import_task
    from app.domain.bioinformatics.analysis_execution import run_bio_analysis_task
    runtime=dict(available=True,blockers=[],engine_version='visium_explore_v1.0.0',environment_digest='b'*64,code_digest='a'*64)
    monkeypatch.setattr(single_cell_settings,'runtime_identity',lambda:runtime)
    stage=tmp_path/'science';monkeypatch.setenv('PAPERASSIST_BIO_STAGING_DIR',str(stage))
    base=f"/api/v1/projects/{create_project(client)['id']}"
    content=b'%%MatrixMarket matrix coordinate integer general\n2 2 3\n1 1 1\n1 2 2\n2 2 3\n';item=str(uuid4())
    batch=client.post(base+'/bio-upload-batches',json={'items':[dict(client_id=item,filename='matrix.mtx',size_bytes=len(content))]},headers={'Idempotency-Key':'upload'})
    assert batch.status_code==201,batch.text
    uploaded=client.post(base+f"/bio-upload-batches/{batch.json()['id']}/items/{item}",files={'file':('matrix.mtx',content)})
    assert uploaded.status_code==202,uploaded.text
    file_id=uploaded.json()['file_id']
    body=dict(workflow_version='bio_import_v4',assay='single_cell',file_ids=[file_id],name='cells',expected_dataset_revision=0,matrix_representation='mtx')
    created=client.post(base+'/bio-imports',json=body,headers={'Idempotency-Key':'cell-import'})
    assert created.status_code==202,created.text
    imported=created.json();assert imported['task']['input_version']['workflow_version']=='bio_import_v4'
    def parser(frozen,out,settings):
        outputs=[]
        def leaf(key,data,fmt):
            path=out/(key+'.'+fmt);path.write_bytes(data)
            outputs.append(dict(key=key,role=key,format=fmt,compression='none',verification_state='verified',path=str(path.resolve()),source_file_id=file_id,source_member_name='matrix.mtx',sha256=hashlib.sha256(data).hexdigest(),size_bytes=len(data)))
        for key,data,dtype in [('matrix_data',[1,2,3],'int64'),('matrix_indices',[0,0,1],'int32'),('matrix_indptr',[0,1,3],'int64')]:
            buffer=io.BytesIO();np.save(buffer,np.array(data,dtype=dtype),allow_pickle=False);leaf(key,buffer.getvalue(),'npy')
        leaf('features_index',json.dumps(dict(feature_ids=['g1','g2'],feature_symbols=['g1','g2'],feature_types=['Gene Expression']*2)).encode(),'json')
        leaf('barcodes_index',b'{"barcodes":["c1","c2"]}','json');leaf('source_000',content,'mtx')
        manifest=dict(schema_version=1,parser_version='single_cell_import_v1',assay='single_cell',observation_level='cell',input_shape={'features':2,'observations':2},stored_entries=3,storage_format='csr_npy_v1',matrix_orientation='observations_by_features',matrix_dtypes={'data':'int64','indices':'int32','indptr':'int64'},source_files=[{k:frozen['files'][0][k] for k in ('id','filename','size_bytes','sha256')}],members=[{k:v for k,v in o.items() if k!='path'} for o in outputs],checks={'structure':'checked'},verification={'structure':'checked'})
        return dict(parser_version='single_cell_import_v1',n_features=2,n_observations=2,entry_count=3,outputs=outputs,manifest=manifest,checks=manifest['checks'])
    def execute_import():
        task=imported['task'];wait=run_bio_import_task(task['id'],task['revision'],parser=parser,staging_directory=stage)
        assert wait['status']=='waiting_confirmation',wait
        d=client.get(base+'/bio-imports/'+imported['id']).json()
        c=client.post(base+'/bio-imports/'+imported['id']+'/confirm',headers={'Idempotency-Key':'confirm-import'},json=dict(task_revision=d['task']['revision'],checkpoint_id=d['checkpoint_id'],wait_id=d['wait_id'],candidate_sha256=d['candidate']['sha256'],expected_dataset_revision=d['expected_dataset_revision']))
        assert c.status_code==202,c.text
        done=run_bio_import_task(task['id'],c.json()['revision'],parser=parser,staging_directory=stage)
        assert done['status']=='succeeded',done
        return client.get(base+'/bio-imports/'+imported['id']).json()['result_source']
    source=execute_import()
    return dict(base=base,source=source,runtime=runtime,stage=stage)


def synthetic_engine(source,runtime,modes):
    """Contract-only output leaves: no claim of real Scanpy or biological validation."""
    def engine(payload,out,mode,*,cancel_event=None):
        modes.append(mode)
        body=b'barcode\tkept\tcluster\tcell_label\nc1\tTrue\t0\tunknown\n'
        path=out/'observations.tsv';path.write_bytes(body)
        artifact=dict(key='observations',role='table',format='tsv',path=str(path.resolve()),size_bytes=len(body),sha256=hashlib.sha256(body).hexdigest())
        summary=dict(shape=[2,2],raw_observations=2,retained_observations=2,excluded_observations=0,raw_features=2,retained_features=2,excluded_features=0,statistical_unit='cell_exploratory')
        steps=[dict(key='raw_qc',status='completed',reason=None,params={})]
        manifest=dict(schema_version=1,engine_version=runtime['engine_version'],identity=payload['identity'],raw_source=source,summary=summary,params=payload['config'],steps=steps,tables=[dict(key='observations',label='observations',status='completed',reason=None)],assay='single_cell',observation_level='cell',code_digest=runtime['code_digest'],environment_digest=runtime['environment_digest'])
        return dict(outputs=[artifact],manifest=manifest,summary=summary,steps=steps,checks={},effective_params=payload['config'])
    return engine


def test_direct_start_unified_worker_has_no_manual_qc_wait_and_replays(client,ready_single_cell,monkeypatch):
    from app.domain.tasks.execution import run_task
    from app.domain.bioinformatics import analysis_execution
    from app.db.database import database_connection
    fixture=ready_single_cell;base=fixture['base'];source=fixture['source']
    body=dict(name='One-click cells',raw_source=source,params={'min_spots':1})
    response=client.post(base+'/single-cell-analysis-runs',json=body,headers={'Idempotency-Key':'direct-run'})
    assert response.status_code==202,response.text
    created=response.json();task=created['task'];modes=[]
    monkeypatch.setattr(analysis_execution,'execute_bio_analysis',synthetic_engine(source,fixture['runtime'],modes))
    replay=client.post(base+'/single-cell-analysis-runs',json=body,headers={'Idempotency-Key':'direct-run'})
    assert replay.status_code==202 and replay.json()['id']==created['id']
    changed=client.post(base+'/single-cell-analysis-runs',json={**body,'name':'Changed'},headers={'Idempotency-Key':'direct-run'})
    assert changed.status_code==409,changed.text
    done=run_task(task['id'],task['revision'])
    assert done['status']=='succeeded',done
    assert modes==['compute']
    lookup=client.get(base+'/bio-requests/direct-run?kind=run')
    assert lookup.status_code==200 and lookup.json()['id']==created['id']
    from app.domain.bioinformatics import single_cell_settings
    monkeypatch.setattr(single_cell_settings,'runtime_identity',lambda:{'available':False})
    replay=client.post(base+'/single-cell-analysis-runs',json=body,headers={'Idempotency-Key':'direct-run'})
    assert replay.status_code==202 and replay.json()['task']['status']=='succeeded'
    read=client.get(base+'/bio-analysis-runs/'+created['id']).json()
    assert read['wait_id'] is None and read['result_source']
    with database_connection() as db:
        stored=db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone()
        assert stored['input_snapshot']['execution_mode']=='direct'
        assert db.execute('SELECT count(*) AS n FROM task_waits WHERE task_id=%s',(task['id'],)).fetchone()['n']==0
        checkpoints=db.execute('SELECT state_json FROM task_checkpoints WHERE task_id=%s',(task['id'],)).fetchall()
        assert all(not cp['state_json'].get('decision') for cp in checkpoints)


def test_direct_failed_task_is_found_by_original_request(client,ready_single_cell,monkeypatch):
    from app.domain.tasks.execution import run_task
    from app.domain.bioinformatics import analysis_execution
    fixture=ready_single_cell;base=fixture['base']
    body=dict(name='Fails visibly',raw_source=fixture['source'],params={})
    response=client.post(base+'/single-cell-analysis-runs',json=body,headers={'Idempotency-Key':'direct-failure'})
    assert response.status_code==202,response.text
    task=response.json()['task']
    def broken(*args,**kwargs):raise RuntimeError('synthetic science failure')
    monkeypatch.setattr(analysis_execution,'execute_bio_analysis',broken)
    done=run_task(task['id'],task['revision'])
    assert done['status']=='failed' and done['error_code']=='task_execution_failed'
    replay=client.post(base+'/single-cell-analysis-runs',json=body,headers={'Idempotency-Key':'direct-failure'})
    assert replay.status_code==202 and replay.json()['task']['id']==task['id']
    assert replay.json()['task']['status']=='failed'
    assert client.get(base+'/bio-requests/direct-failure?kind=run').json()['task_id']==task['id']


def test_single_cell_capabilities_explain_saved_matrix_and_limits(client,ready_single_cell):
    fixture=ready_single_cell;source=fixture['source']
    response=client.get(fixture['base']+f"/bio-analysis-capabilities?dataset_id={source['dataset_id']}&version_id={source['dataset_version_id']}")
    assert response.status_code==200,response.text
    estimate=response.json()['resource_estimate']
    assert estimate['matrix']==dict(observations=2,features=2,nnz=3)
    assert estimate['sparse_bytes']==60 and estimate['dense_hvg_bytes']==16
    assert estimate['configured_limits']['max_entries']==10000000
    assert estimate['blockers']==[] and estimate['estimate_only'] is True


def test_direct_start_checks_requested_hvg_before_writing_a_setup(client,ready_single_cell,monkeypatch):
    from app.adapters.bio_analysis_store import BioAnalysisStore
    from app.db.database import database_connection
    fixture=ready_single_cell;original=BioAnalysisStore.axes
    def large_axes(self,*args,**kwargs):
        row,manifest,members,barcodes,features=original(self,*args,**kwargs)
        return row,{**manifest,'input_shape':dict(observations=15000,features=3000)},members,barcodes,features
    monkeypatch.setattr(BioAnalysisStore,'axes',large_axes)
    body=dict(name='Bounded cells',raw_source=fixture['source'],params={'hvg_count':2000})
    blocked=client.post(fixture['base']+'/single-cell-analysis-runs',json=body,headers={'Idempotency-Key':'resource-block'})
    assert blocked.status_code==422 and blocked.json()['detail']['code']=='bio_resource_exceeded',blocked.text
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM bio_analysis_setups').fetchone()['n']==0
    accepted=client.post(fixture['base']+'/single-cell-analysis-runs',json={**body,'params':{'hvg_count':1000}},headers={'Idempotency-Key':'resource-allowed'})
    assert accepted.status_code==202,accepted.text
