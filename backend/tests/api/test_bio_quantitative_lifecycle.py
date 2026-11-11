"""Real DB/storage/API lifecycle; local numeric fixture, not Linux gate evidence."""
from uuid import uuid4
from tests.api.test_projects import client,create_project
from tests.domain.test_bio_tabular_contracts import request_body


def processed_fixture(client,monkeypatch,tmp_path,assay='proteomics'):
    from app.domain.bioinformatics import tabular_settings
    from app.domain.bioinformatics.execution import run_bio_import_task
    from app.domain.bioinformatics.analysis_execution import run_bio_analysis_task
    from app.adapters.bio_engine.tabular_assays import import_tabular,run_tabular
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
    counts=assay=='bulk_rna_counts'
    body=request_body(assay,'raw_counts' if counts else 'intensity');body['file_ids']=files;body['sample_columns']=['B0','B1','B2','A0','A1','A2']
    body['scale'].update(namespace='ensembl' if counts else 'protein_label',reference_version='fixed')
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


def test_bulk_requires_matching_review_and_rejects_superseded_confirmation(client,monkeypatch,tmp_path):
    from app.domain.bio_insights.service import BioInsightsService
    from tests.api.test_bio_insight_reproducibility import fixed_fixture_runtime

    base,pid=processed_fixture(client,monkeypatch,tmp_path,assay='bulk_rna_counts')
    runtime=fixed_fixture_runtime(monkeypatch)
    monkeypatch.setattr(BioInsightsService,'_runtime_for',lambda self,config:runtime)
    plans=base+'/bio-insight-plans'
    runs=base+'/bio-insight-runs'
    detail=client.get(base+'/bio-processed-datasets/'+pid).json()
    source=dict(source_kind='bio_processed_dataset_version',source_id=pid,sha256=detail['manifest_sha256'],role='processed')
    config=dict(schema_version=2,kind='comparison',mode='bulk_counts',design='independent',method='deseq2_wald',
        analysis_layer='raw_counts',bulk_model='shared_wald_v1',contrasts=[dict(contrast_id='B_A',name='B/A',
            groups=[dict(label=g,sample_keys=[dict(processed_version_id=pid,sample_id=g+str(i)) for i in range(2)])
                    for g in ('B','A')])],family_contrast_ids=['B_A'],namespace='ensembl',reference_version='fixed',
        data_driven_grouping=False,design_basis='Synthetic frozen design',independence_confirmed=True,
        independence_basis='Synthetic independent units',inference_goal='inference',inference_unit='biological')
    body=dict(name='Bulk lifecycle',kind='comparison',decision='draft',expected_revision=0,sources=[source],config=config)

    def post(url,payload,key):
        return client.post(url,json=payload,headers={'Idempotency-Key':key})

    preview=client.post(plans+'/preview',json=body)
    assert preview.status_code==200,preview.text
    design=preview.json()
    assert design['executable'] and len(design['bulk_model']['samples'])==4
    assert len(design['exclusions'])==2
    assert client.get(runs).json()['total']==0
    token=design['reviewed_design_sha256']
    confirmed={**body,'decision':'confirmed'}
    assert post(plans,confirmed,'missing-review').status_code==422
    reversed_config={**config,'contrasts':[{**config['contrasts'][0],'groups':config['contrasts'][0]['groups'][::-1]}]}
    assert post(plans,{**confirmed,'config':reversed_config,'reviewed_design_sha256':token},'stale-review').status_code==409
    confirmed['reviewed_design_sha256']=token
    response=post(plans,confirmed,'confirmed-model')
    assert response.status_code==201,response.text
    plan=response.json()
    assert client.get(runs).json()['total']==0
    request=dict(plan_version_id=plan['id'],expected_plan_revision=1,source_digest=plan['source_digest'])
    assert post(runs,request,'confirmed-run').status_code==202
    versions=plans+'/'+plan['plan_id']+'/versions'
    response=post(versions,{**body,'expected_revision':1,'config':reversed_config},'reverse-draft')
    assert response.status_code==201,response.text
    assert post(runs,{**request,'expected_plan_revision':2},'stale-plan-run').status_code==409
    assert client.get(versions+'/'+plan['id']).json()['design']['bulk_model']['contrasts'][0]['numerator']=='B'


def test_v2_comparison_candidates_research_and_portable_full_export(client,monkeypatch,tmp_path):
    import io,json,zipfile
    from app.domain.bio_insights.execution import run_bio_insight_task
    from app.adapters.bio_insights_engine.pipeline import run as pipeline
    from app.domain.bio_insights.service import BioInsightsService
    from tests.api.test_bio_insight_reproducibility import fixed_fixture_runtime,verify_module
    base,pid=processed_fixture(client,monkeypatch,tmp_path)
    runtime=fixed_fixture_runtime(monkeypatch)
    monkeypatch.setattr(BioInsightsService,'_runtime_for',lambda self,config:runtime)
    observations=client.get(base+f'/bio-insights/sources/bio_processed_dataset_version/{pid}/observations')
    assert observations.status_code==200,observations.text
    assert observations.json()['observation_level']=='sample'
    detail=client.get(base+'/bio-processed-datasets/'+pid).json()
    source=dict(source_kind='bio_processed_dataset_version',source_id=pid,sha256=detail['manifest_sha256'],role='processed')
    config=dict(schema_version=2,kind='comparison',mode='continuous',design='independent',method='welch_t',analysis_layer='analysis',
        contrasts=[dict(contrast_id='B_A',name='B/A',groups=[dict(label=g,sample_keys=[dict(processed_version_id=pid,sample_id=g+str(i)) for i in range(3)]) for g in ('B','A')])],
        family_contrast_ids=['B_A'],namespace='protein_label',reference_version='fixed',data_driven_grouping=False,design_basis='synthetic local lifecycle fixture',
        independence_confirmed=True,independence_basis='synthetic independent units',inference_goal='inference',inference_unit='biological')
    def publish(kind,config,sources,key):
        body=dict(kind=kind,name=key,decision='confirmed',expected_revision=0,sources=sources,config=config)
        response=client.post(base+'/bio-insight-plans',json=body,headers={'Idempotency-Key':key+'-plan'})
        assert response.status_code==201,response.text
        plan=response.json();assert plan['design']['executable'],plan
        request=dict(plan_version_id=plan['id'],expected_plan_revision=1,source_digest=plan['source_digest'])
        response=client.post(base+'/bio-insight-runs',json=request,headers={'Idempotency-Key':key+'-run'})
        assert response.status_code==202,response.text
        run=response.json()
        assert client.post(base+'/bio-insight-runs',json=request,headers={'Idempotency-Key':key+'-run'}).json()==run
        done=run_bio_insight_task(run['task_id'],run['task_revision'],task_type=run['task']['task_type'],engine=lambda p,out:pipeline({**p,'output_directory':str(out)}),staging_directory=tmp_path/(key+'-stage'))
        assert done['status']=='succeeded',done
        return client.get(base+'/bio-insight-results/'+done['result_bio_insight_result_version_id']).json(),run
    result,run=publish('comparison',config,[source],'comparison')
    from app.db.database import database_connection
    with database_connection() as db:assert db.execute('SELECT workflow_version FROM tasks WHERE id=%s',(run['task_id'],)).fetchone()['workflow_version']=='bio_comparison_v2'
    assert result['inference_scope']=='sample_inference'
    table=client.get(base+'/bio-insight-results/'+result['id']+'/tables/comparison_results').json()
    assert table['total']==3 and table['items'][0]['n_numerator']=='3'
    assert 'spots_numerator' not in table['items'][0]
    candidate,_=publish('candidate',dict(kind='candidate',result_source_ids=[result['id']],primary_result_source_id=result['id'],source_contrasts={result['id']:'B_A'},
        steps=[dict(operation='threshold',source_ids=[result['id']],q_column='q_within_contrast',q_threshold=1.,minimum_absolute_effect=0.)]),
        [dict(source_kind='bio_insight_result_version',source_id=result['id'],sha256=result['manifest_sha256'],role='result')],'candidate')
    assert candidate['summary']['candidate_count']==2
    member=next(m for m in result['members'] if m['key']=='comparison_results')
    selected=dict(source_kind='bio_insight_result_member',source_id=member['id'],sha256=member['sha256'],locator=dict(kind='row',table='comparison_results',row_key={'row_key':table['items'][0]['row_key']},column='effect_value'))
    preview=client.post(base+'/research-results/preview',json={'sources':[selected]})
    assert preview.status_code==200,preview.text
    facts=preview.json()['catalogs'][0]['facts'];assert facts and facts[0]['observation_level']=='sample'
    finding=client.post(base+'/research-findings',json=dict(title='Sample result',sources=[selected],selected_fact_ids=[facts[0]['id']]),headers={'Idempotency-Key':'sample-finding'})
    assert finding.status_code==201,finding.text
    from app.domain.research_results.execution import run_research_task
    from app.adapters.research_report_render import render_report
    report=client.post(base+'/research-reports',json=dict(title='Sample measurements report',finding_version_id=finding.json()['id'],language='en'),headers={'Idempotency-Key':'sample-report'})
    assert report.status_code==201,report.text
    report=report.json()
    done=run_research_task(report['task_id'],report['task']['revision'],task_type='research_report',engine=render_report,staging_directory=tmp_path/'report-stage')
    assert done['status']=='succeeded',done
    saved=client.get(base+'/research-reports/'+report['id']).json()
    assert {'docx','xlsx','zip'}<={m['format'] for m in saved['members']}
    docx=next(m for m in saved['members'] if m['format']=='docx')
    from docx import Document
    document=Document(io.BytesIO(client.get(docx['download_url']).content));body='\n'.join(p.text for p in document.paragraphs)
    assert 'n_numerator' in body and 'selected_samples' in body and 'spots_numerator' not in body
    pdf=client.post(base+'/pdf-exports',json=dict(source_kind='research_report',source_id=docx['id'],request_key='sample-report-pdf'))
    assert pdf.status_code==405,pdf.text
    zipped=next(m for m in saved['members'] if m['format']=='zip')
    with zipfile.ZipFile(io.BytesIO(client.get(zipped['download_url']).content)) as package:
        assert b'def _sample_groups' in package.read('rebuild_support/research_method_text.py')
    from openpyxl import load_workbook
    xlsx=next(m for m in saved['members'] if m['format']=='xlsx')
    workbook=load_workbook(io.BytesIO(client.get(xlsx['download_url']).content),read_only=True,data_only=False)
    try:
        tables=[list(sheet.values) for sheet in workbook.worksheets]
        full=next(rows for rows in tables if rows and rows[0][:2]==('row_key','feature_id'))
        assert len(full)==4 and full[-1][1]=='f3'
    finally:workbook.close()
    export=client.get(base+'/bio-insight-results/'+result['id']+'/reproducibility-package')
    assert export.status_code==200,export.text
    directory=tmp_path/'export';directory.mkdir()
    with zipfile.ZipFile(io.BytesIO(export.content)) as package:package.extractall(directory)
    originals=json.loads((directory/'input/tabular-originals.json').read_bytes());assert len(originals)==2
    assert all((directory/r['path']).is_file() for r in originals)
    assert (directory/'code/app/adapters/bio_insights_engine/quantitative.py').is_file()
    assert verify_module(directory).verify_package(directory,manifest_sha256=export.headers['X-Reproducibility-Manifest-SHA256'])['status']=='verified'
    other=create_project(client)['id']
    assert client.get(f'/api/v1/projects/{other}/bio-insight-results/'+result['id']).status_code==404
    assert client.post(f'/api/v1/projects/{other}/research-results/preview',json={'sources':[selected]}).status_code==404
