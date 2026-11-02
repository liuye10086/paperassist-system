"""Real database, storage and task publication; numerical child injected locally."""
from uuid import uuid4
import pytest
from tests.api.test_projects import client,create_project
from tests.domain.test_bio_tabular_contracts import request_body


@pytest.mark.parametrize('assay,scale',[('bulk_rna_counts','raw_counts'),('normalized_expression','tpm'),('proteomics','intensity'),('metabolomics','concentration')])
def test_tabular_raw_and_processed_publish_through_existing_tasks(client,monkeypatch,tmp_path,assay,scale):
    from app.domain.bioinformatics import tabular_settings
    from app.domain.bioinformatics.execution import run_bio_import_task
    from app.domain.bioinformatics.analysis_execution import run_bio_analysis_task
    from app.adapters.bio_engine.tabular_assays import import_tabular,run_tabular
    runtime=dict(available=True,blockers=[],engine_version='tabular_quantitative_v1.0.0',code_digest='a'*64,environment_digest='b'*64)
    monkeypatch.setattr(tabular_settings,'runtime_identity',lambda:runtime)
    staging=tmp_path/'science';monkeypatch.setenv('PAPERASSIST_BIO_STAGING_DIR',str(staging))
    project=create_project(client);base=f"/api/v1/projects/{project['id']}";files=[]
    for name,content in [('matrix.csv',b'feature_id,s1,s2,s3\na,1,2,4\nb,2,5,8\nc,3,6,12\n'),('samples.csv',b'sample_id,condition,biological_unit_id\ns1,A,u1\ns2,A,u2\ns3,B,u3\n')]:
        item=str(uuid4());batch=client.post(base+'/bio-upload-batches',json={'items':[dict(client_id=item,filename=name,size_bytes=len(content))]},headers={'Idempotency-Key':str(uuid4())})
        assert batch.status_code==201,batch.text
        file=client.post(base+f"/bio-upload-batches/{batch.json()['id']}/items/{item}",files={'file':(name,content)})
        assert file.status_code==202,file.text
        files.append(file.json()['file_id'])
    body=request_body(assay,scale);body['file_ids']=files
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
    preview=client.get(base+f"/bio-datasets/{source['dataset_id']}/versions/{source['dataset_version_id']}/matrix-preview")
    assert preview.status_code==200,preview.text
    assert preview.json()['observations']==['s1','s2','s3']
    assert preview.json()['values'][0]==[1,2,3]
    capabilities=client.get(base+'/bio-analysis-capabilities',params=dict(dataset_id=source['dataset_id'],version_id=source['dataset_version_id']))
    assert capabilities.status_code==200,capabilities.text
    assert capabilities.json()['assay']==assay and capabilities.json()['scale']['kind']==scale
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
    assert result['schema_version']==2
    processed=client.get(base+'/bio-processed-datasets/'+result['processed_dataset_version_id'])
    assert processed.status_code==200,processed.text
    assert processed.json()['manifest']['observation_level']=='sample'
    assert len(processed.json()['figures'])>=2
    pid=result['processed_dataset_version_id']
    matrix=client.get(base+f'/bio-processed-datasets/{pid}/matrix-preview?layer=analysis')
    assert matrix.status_code==200 and matrix.json()['values'][0]==[1,2,3]
    assert client.get(base+f'/bio-processed-datasets/{pid}/coordinates').status_code==422
    table=client.get(base+f'/bio-processed-datasets/{pid}/tables/sample_qc')
    assert table.status_code==200,table.text
    for figure in processed.json()['figures']:
        assert {'png','tiff','svg','pdf'} <= {m['format'] for m in figure['members']}
        image=next(m for m in figure['members'] if m['format']=='png')
        assert client.get(image['download_url']).content.startswith(b'\x89PNG')
    # Every later read must still verify the original bytes, not just derived leaves.
    from app.db.database import database_connection
    with database_connection() as db:
        original=db.execute('SELECT object_key FROM files WHERE id=%s',(files[0],)).fetchone()
    (tmp_path/'data'/original['object_key']).write_bytes(b'changed synthetic original')
    assert client.get(base+f'/bio-processed-datasets/{pid}/matrix-preview?layer=analysis').status_code==409
