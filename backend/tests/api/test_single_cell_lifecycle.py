"""Real database/task/storage; synthetic injected leaves, not scientific evidence."""
import hashlib,io,json
from uuid import uuid4
import numpy as np
from tests.api.test_projects import client,create_project


def test_single_cell_api_worker_freeze_and_research(client,monkeypatch,tmp_path):
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
    evidence_content=b'Synthetic cell label review';evidence_item=str(uuid4())
    evidence_batch=client.post(base+'/bio-upload-batches',json={'items':[dict(client_id=evidence_item,filename='label-review.txt',size_bytes=len(evidence_content))]},headers={'Idempotency-Key':'evidence-upload'})
    evidence_upload=client.post(base+f"/bio-upload-batches/{evidence_batch.json()['id']}/items/{evidence_item}",files={'file':('label-review.txt',evidence_content)})
    assert evidence_upload.status_code==202,evidence_upload.text
    evidence_id=evidence_upload.json()['file_id']
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
    cap=client.get(base+'/bio-analysis-capabilities',params=dict(dataset_id=source['dataset_id'],version_id=source['dataset_version_id']))
    assert cap.status_code==200,cap.text
    assert cap.json()['observation_level']=='cell' and cap.json()['recipes']==['single_cell_explore_v1']
    request=dict(recipe_code='single_cell_explore_v1',name='cells',raw_source=source,expected_revision=0,params={'min_spots':1,'cell_labels':[dict(cluster='0',label='reviewed cell group',marker_ids=['g1'],evidence_file_ids=[evidence_id],basis='synthetic marker evidence',decided_by='fixture reviewer')]})
    recipe=client.post(base+'/bio-analysis-setups',json=request,headers={'Idempotency-Key':'setup'})
    assert recipe.status_code==201,recipe.text
    assert recipe.json()['params']['cell_labels'][0]['evidence_file_sha256']=={evidence_id:hashlib.sha256(evidence_content).hexdigest()}
    from app.db.database import database_connection
    from app.domain.file_lifecycle.bio_analysis_references import read_groups
    with database_connection() as db:
        file=db.execute('SELECT * FROM files WHERE id=%s',(evidence_id,)).fetchone()
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(file['project_id'],)).fetchone()['owner_id']
        references=read_groups(db,file,owner)
        assert recipe.json()['id'] in {r['id'] for r in references['bio_analysis_recipe_versions']}
    assert client.post(base+'/bio-analysis-setups',json={**request,'params':{'in_tissue_only':True}},headers={'Idempotency-Key':'bad'}).status_code==422
    run=client.post(base+'/bio-analysis-runs',json=dict(raw_source=source,recipe_version_id=recipe.json()['id'],expected_setup_revision=1),headers={'Idempotency-Key':'run'})
    assert run.status_code==202,run.text
    run=run.json();task=run['task'];assert task['input_version']['workflow_version']=='bio_analysis_v3'
    def engine(payload,out,mode):
        assert payload['raw']['manifest']['assay']=='single_cell' and not payload['config']['in_tissue_only']
        body=b'barcode\tkept\tcluster\tcell_label\nc1\tTrue\t0\tunknown\n';path=out/'observations.tsv';path.write_bytes(body)
        artifact=dict(key='observations',role='table',format='tsv',path=str(path.resolve()),size_bytes=len(body),sha256=hashlib.sha256(body).hexdigest())
        summary=dict(shape=[2,2],raw_observations=2,retained_observations=2,excluded_observations=0,raw_features=2,retained_features=2,excluded_features=0,statistical_unit='cell_exploratory')
        steps=[dict(key='raw_qc',status='completed',reason=None,params={})]
        manifest=dict(schema_version=1,engine_version=runtime['engine_version'],identity=payload['identity'],raw_source=source,summary=summary,params=payload['config'],steps=steps,tables=[dict(key='observations',label='observations',status='completed',reason=None)],assay='single_cell',observation_level='cell',code_digest=runtime['code_digest'],environment_digest=runtime['environment_digest'])
        return dict(outputs=[artifact],manifest=manifest,summary=summary,steps=steps,checks={},effective_params=payload['config'])
    wait=run_bio_analysis_task(task['id'],task['revision'],engine=engine,staging_directory=stage)
    assert wait['status']=='waiting_confirmation',wait
    d=client.get(base+'/bio-analysis-runs/'+run['id']).json()
    c=client.post(base+'/bio-analysis-runs/'+run['id']+'/confirm',headers={'Idempotency-Key':'confirm-analysis'},json=dict(task_revision=d['task']['revision'],checkpoint_id=d['checkpoint_id'],wait_id=d['wait_id'],candidate_sha256=d['candidate']['sha256'],expected_setup_revision=1))
    assert c.status_code==202,c.text
    done=run_bio_analysis_task(task['id'],c.json()['revision'],engine=engine,staging_directory=stage)
    assert done['status']=='succeeded',done
    pid=done['result_bio_processed_dataset_version_id'];result=client.get(base+'/bio-processed-datasets/'+pid)
    assert result.status_code==200,result.text
    result=result.json();assert result['manifest']['observation_level']=='cell'
    preview=client.post(base+'/research-results/preview',json={'sources':[dict(source_kind='bio_processed_dataset_version',source_id=pid,sha256=result['manifest_sha256'])]})
    assert preview.status_code==200,preview.text
    assert 'cells' in preview.text
