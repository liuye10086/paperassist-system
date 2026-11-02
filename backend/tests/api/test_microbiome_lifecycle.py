"""Scoped micro intake/analysis/plan API; synthetic local parser, no actual gate claim."""
from uuid import uuid4
from tests.api.test_projects import client,create_project
from tests.domain.test_bio_tabular_contracts import request_body
def microbiome_processed_fixture(client,monkeypatch,tmp_path):
    # Synthetic API fixture isolates capacity from this host; product disk guard is unchanged.
    from app.domain.storage_governance import service as storage_governance
    monkeypatch.setattr(storage_governance.shutil,'disk_usage',lambda _:type('Disk',(),dict(total=100*1024**3,free=80*1024**3,used=20*1024**3))())
    from app.domain.bioinformatics import tabular_settings
    from app.domain.bioinformatics.execution import run_bio_import_task
    from app.domain.bioinformatics.analysis_execution import run_bio_analysis_task
    from app.adapters.bio_engine.tabular_assays import import_tabular,run_tabular
    runtime=dict(available=True,blockers=[],engine_version='tabular_quantitative_v1.0.0',code_digest='a'*64,environment_digest='b'*64)
    monkeypatch.setattr(tabular_settings,'runtime_identity',lambda:runtime)
    staging=tmp_path/'science';monkeypatch.setenv('PAPERASSIST_BIO_STAGING_DIR',str(staging))
    project=create_project(client);base=f"/api/v1/projects/{project['id']}";files=[]
    for name,content in [('matrix.csv',b'feature_id,B0,B1,B2,A0,A1,A2\nf1,6,8,13,1,2,5\nf2,10,11,15,1,3,7\nf3,1,1,1,1,1,1\n'),('taxonomy.csv',b'feature_id,Kingdom,Genus\nf1,Bacteria,G1\nf2,Bacteria,G2\nf3,Bacteria,NA\n'),('samples.csv',b'sample_id,condition,biological_unit_id,sample_role\nB0,B,B0,biological\nB1,B,B1,biological\nB2,B,B2,biological\nA0,A,A0,biological\nA1,A,A1,biological\nA2,A,A2,biological\n')]:
        item=str(uuid4());batch=client.post(base+'/bio-upload-batches',json={'items':[dict(client_id=item,filename=name,size_bytes=len(content))]},headers={'Idempotency-Key':str(uuid4())})
        assert batch.status_code==201,batch.text
        file=client.post(base+f"/bio-upload-batches/{batch.json()['id']}/items/{item}",files={'file':(name,content)})
        assert file.status_code==202,file.text
        files.append(file.json()['file_id'])
    body=request_body('proteomics','intensity');body['assay']='microbiome';body['scale']['kind']='raw_counts';body['scale']['unit']='counts';body['file_ids']=files;body['sample_columns']=['B0','B1','B2','A0','A1','A2'];body['scale'].update(namespace='protein_label',reference_version='fixed')
    body['tables']=[dict(file_id=files[0],role='quantitative_matrix',format='csv'),dict(file_id=files[1],role='feature_metadata',format='csv'),dict(file_id=files[2],role='sample_metadata',format='csv')]
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


def test_microbiome_plan_intake_and_owner_scope(client,monkeypatch,tmp_path):
    from app.domain.bio_insights.microbiome_contracts import MicrobiomeConfig
    base,pid=microbiome_processed_fixture(client,monkeypatch,tmp_path)
    detail=client.get(base+'/bio-processed-datasets/'+pid).json()
    config=MicrobiomeConfig(processed_source_id=pid,abundance_scale='counts',measurement_pipeline='synthetic counts',classification_database='synthetic',classification_version='1',host_identity='synthetic host',feature_identity='taxa',taxonomy_columns=['Kingdom','Genus'],aggregate_rank='Genus').model_dump(mode='json')
    body=dict(name='Microbiome frozen',kind='comparison',expected_revision=0,decision='draft',config=config,sources=[dict(source_kind='bio_processed_dataset_version',source_id=pid,role='processed',sha256=detail['manifest_sha256'])])
    preview=client.post(base+'/bio-insight-plans/preview',json=body);assert preview.status_code==200,preview.text
    assert preview.json()['executable'],preview.text
    created=client.post(base+'/bio-insight-plans',json=body,headers={'Idempotency-Key':'micro-plan'});assert created.status_code==201,created.text
    assert created.json()['config']['permdisp_dimensions']==0
    other=create_project(client);response=client.post('/api/v1/projects/'+other['id']+'/bio-insight-plans/preview',json=body)
    assert response.status_code==404,response.text
