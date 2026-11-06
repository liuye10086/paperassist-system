"""Real isolated DB/task/storage; injected tiny outputs, no real SingleR evidence."""
import hashlib
import io
import json
import numpy as np
import pytest
from tests.api.test_projects import client,create_project
from tests.api.test_single_cell_direct_start import ready_single_cell,synthetic_engine


@pytest.fixture
def parent_result(client,monkeypatch,tmp_path):
    from app.domain.bioinformatics import execution,analysis_execution
    original=execution.run_bio_import_task
    def imported(*args,**kwargs):
        parser=kwargs.get('parser')
        if parser:
            def with_species(frozen,out,settings):
                result=parser(frozen,out,settings)
                result['manifest']['samples']=[dict(library_id='L1',sample_id='S1',species_taxon_id=9606)]
                return result
            kwargs['parser']=with_species
        return original(*args,**kwargs)
    monkeypatch.setattr(execution,'run_bio_import_task',imported)
    fixture=ready_single_cell.__wrapped__(client,monkeypatch,tmp_path)
    from app.adapters import bio_figure_store
    from app.domain.bioinformatics import analysis_service
    monkeypatch.setattr(bio_figure_store,'runtime_identity',lambda:fixture['runtime'])
    monkeypatch.setattr(analysis_service,'runtime_identity',lambda:fixture['runtime'])
    base=fixture['base'];modes=[];engine=synthetic_engine(fixture['source'],fixture['runtime'],modes)
    def base_engine(payload,out,mode):
        result=engine(payload,out,mode)
        def leaf(key,content,fmt):
            path=out/(key+'.'+fmt);path.write_bytes(content)
            result['outputs'].append(dict(key=key,role='axis',format=fmt,path=str(path.resolve()),size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest()))
        leaf('raw_axes',b'{"barcodes":["c1","c2"],"feature_ids":["g1","g2"]}','json')
        buffer=io.BytesIO();np.save(buffer,np.array([True,False]),allow_pickle=False);leaf('observation_mask',buffer.getvalue(),'npy')
        return result
    created=client.post(base+'/single-cell-analysis-runs',json=dict(name='Parent',raw_source=fixture['source'],params={'min_spots':1}),headers={'Idempotency-Key':'parent'})
    assert created.status_code==202,created.text
    monkeypatch.setattr(analysis_execution,'execute_bio_analysis',base_engine)
    from app.domain.tasks.execution import run_task
    task=created.json()['task'];done=run_task(task['id'],task['revision'])
    assert done['status']=='succeeded',done
    run=client.get(base+'/bio-analysis-runs/'+created.json()['id']).json()
    fixture.update(source=run['result_source'],modes=modes,run_id=created.json()['id'])
    return fixture


def test_manual_label_versions_are_independent_and_sc_figure_can_use_them(client,parent_result,monkeypatch):
    from app.db.database import database_connection
    f=parent_result;base=f['base'];parent=f['source']
    body=dict(name='Reviewed',raw_source=parent['raw_source'],processed_dataset_version_id=parent['processed_dataset_version_id'],expected_revision=0,
        labels=[dict(id='T',name='T candidate',status='uncertain',cluster_ids=['0'])],evidence=[dict(label_id='T',kind='manual',note='Marker review'),dict(label_id='T',kind='reference',note='Reference release 1')])
    created=client.post(base+'/bio-annotation-sets',json=body,headers={'Idempotency-Key':'labels'})
    assert created.status_code==201,created.text
    label=created.json();assert label['assignments'][0]['status']=='uncertain'
    assert client.post(base+'/bio-annotation-sets',json=body,headers={'Idempotency-Key':'labels'}).json()['id']==label['id']
    listed=client.get(base+f"/bio-processed-datasets/{parent['processed_dataset_version_id']}/annotations")
    assert listed.status_code==200 and listed.json()['items'][0]['id']==label['id']
    figure=client.post(base+'/bio-figures',json=dict(processed_source=parent,annotation_version_id=label['id'],config=dict(kind='annotation')),headers={'Idempotency-Key':'label-figure'})
    assert figure.status_code==202,figure.text
    from app.domain.bioinformatics import analysis_execution
    from app.domain.tasks.execution import run_task
    def figure_engine(payload,out,mode):
        assert mode=='figure'
        from PIL import Image
        buffer=io.BytesIO();Image.new('RGB',(4,4),'white').save(buffer,format='PNG');content=buffer.getvalue()
        path=out/'annotation_png.png';path.write_bytes(content)
        return dict(outputs=[dict(key='annotation_png',role='figure',format='png',path=str(path.resolve()),size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest())],
            manifest=dict(config=payload['config']),summary={},steps=[],checks={})
    monkeypatch.setattr(analysis_execution,'execute_bio_analysis',figure_engine)
    figure_task=figure.json()['task'];assert run_task(figure_task['id'],figure_task['revision'])['status']=='succeeded'
    figure_view=client.get(base+'/bio-figures/'+figure.json()['id']).json()
    selection=dict(source_kind='bio_figure_version',source_id=figure_view['id'],sha256=figure_view['manifest_sha256'])
    finding=client.post(base+'/research-findings',json=dict(title='Annotated cell projection',sources=[selection]),headers={'Idempotency-Key':'label-finding'})
    assert finding.status_code==201,finding.text
    report_body=dict(title='Label-dependent report',finding_version_id=finding.json()['id'])
    report=client.post(base+'/research-reports',json=report_body,headers={'Idempotency-Key':'label-report'})
    assert report.status_code==201,report.text
    from app.domain.research_results.execution import run_research_report_task
    def history_report_engine(payload,out):
        content=b'Synthetic history download fixture; no model or document render.'
        path=out/'history_fixture.txt';path.write_bytes(content)
        return dict(outputs=[dict(key='history_fixture',role='evidence',format='txt',path=str(path.resolve()),size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest())],manifest=dict(schema_version=1))
    report_task=report.json()['task']
    finished=run_research_report_task(report_task['id'],report_task['revision'],engine=history_report_engine,staging_directory=f['stage'])
    assert finished['status']=='succeeded',finished
    historical_report=client.get(base+'/research-reports/'+report.json()['id'])
    assert historical_report.status_code==200,historical_report.text
    historical_download=historical_report.json()['members'][0]['download_url']
    from app.domain.research_results.execution import source_current as research_current
    with database_connection() as db:
        report_task=db.execute('SELECT * FROM tasks WHERE id=%s',(report.json()['task']['id'],)).fetchone()
        assert research_current(db,report_task)
    edit={**body,'expected_revision':1,'labels':[dict(id='T',name='T cell',status='confirmed',cell_ids=['c1'])]}
    changed=client.post(base+f"/bio-annotation-sets/{label['set_id']}/versions",json=edit,headers={'Idempotency-Key':'edited'})
    assert changed.status_code==201,changed.text
    assert changed.json()['id']!=label['id']
    assert client.get(base+f"/bio-annotation-sets/{label['set_id']}/versions/{label['id']}").json()['is_current'] is False
    taskview=client.get(f"/api/v1/tasks/{figure.json()['task']['id']}/workspace")
    assert taskview.status_code==200,taskview.text
    assert taskview.json()['source']['is_current'] is False
    with database_connection() as db:
        report_task=db.execute('SELECT * FROM tasks WHERE id=%s',(report.json()['task']['id'],)).fetchone()
        assert research_current(db,report_task) is False
    new_report=client.post(base+'/research-reports',json=report_body,headers={'Idempotency-Key':'stale-label-report'})
    assert new_report.status_code==409,new_report.text
    assert new_report.json()['detail']['code']=='research_source_conflict'
    assert client.get(figure_view['members'][0]['download_url']).status_code==200
    assert client.get(historical_download).status_code==200
    assert client.get(base+'/research-reports/'+report.json()['id']).status_code==200
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE project_id=%s AND task_type='bio_analysis'",(parent['project_id'],)).fetchone()['n']==1
        from app.adapters.task_store import DatasetTaskAssets
        from app.domain.bio_insights.sources import InsightSourceReader
        from app.domain.bioinformatics.contracts import digest
        from app.core.config import get_data_dir
        from app.core.exceptions import StorageError
        version=db.execute('SELECT * FROM bio_annotation_versions WHERE id=%s',(label['id'],)).fetchone()
        reader=InsightSourceReader(DatasetTaskAssets(version['created_by'],db.config,get_data_dir()))
        with pytest.raises(StorageError) as exc:
            reader.resolve(db,parent['project_id'],dict(source_kind='bio_annotation_version',source_id=label['id'],sha256=digest({k:version[k] for k in ('geometry_sha256','assignments_sha256')})))
        assert exc.value.code=='bio_insight_source_conflict'
    assert f['modes']==['compute']
    foreign=f"/api/v1/projects/{create_project(client)['id']}"
    assert client.get(foreign+f"/bio-annotation-sets/{label['set_id']}/versions/{label['id']}").status_code==404


def test_single_r_task_publishes_downloadable_candidates_and_replays(client,parent_result,monkeypatch):
    from app.domain.bioinformatics import annotation_service,analysis_execution
    from app.domain.bioinformatics.contracts import digest
    from app.domain.tasks.execution import run_task
    f=parent_result;base=f['base'];parent=f['source']
    reference=dict(reference_id='monaco_immune_1.0.0',species='Homo sapiens',species_taxon_id=9606,gene_id_type='ensembl_gene_id',version='1.0.0',source='official fixture',license='fixture',available=True,reason=None)
    monkeypatch.setattr(annotation_service,'reference_catalog',lambda:[reference])
    def engine(payload,out,mode):
        assert mode=='annotation';assert payload['identity']['processed_source']==parent
        outputs=[]
        def leaf(key,content,fmt):
            path=out/(key+'.'+fmt);path.write_bytes(content)
            outputs.append(dict(key=key,role='table' if fmt=='tsv' else 'evidence',format=fmt,path=str(path.resolve()),size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest()))
        leaf('annotation_candidates',b'barcode\tcandidate_label\tpruned_label\tdelta_next\tdelta_median\nc1\tT cells\tunknown\t0.1\t0.3\n','tsv')
        leaf('annotation_scores',b'barcode\tT cells\tB cells\nc1\t0.5\t0.4\n','tsv')
        leaf('annotation_reference',json.dumps(dict(reference=reference,matching={'common_genes':2})).encode(),'json')
        leaf('annotation_tool_logs',b'Synthetic fixture; no real model\n','txt')
        return dict(outputs=outputs,manifest=dict(algorithm='SingleR',tool_version='fixture',reference=reference,matching=dict(common_genes=2)),summary=dict(cells=1,score_labels=['T cells','B cells']),steps=[],checks={})
    monkeypatch.setattr(analysis_execution,'execute_bio_analysis',engine)
    body=dict(name='SingleR candidates',parent_processed_source=parent,reference_id=reference['reference_id'])
    made=client.post(base+'/bio-single-cell-annotation-runs',json=body,headers={'Idempotency-Key':'single-r'})
    assert made.status_code==202,made.text
    created=made.json();task=created['task'];assert task['task_type']=='bio_annotation'
    done=run_task(task['id'],task['revision']);assert done['status']=='succeeded',done
    run=client.get(base+'/bio-single-cell-annotation-runs/'+created['id']).json();assert run['result']
    assert client.post(base+'/bio-single-cell-annotation-runs',json=body,headers={'Idempotency-Key':'single-r'}).json()['id']==created['id']
    changed=client.post(base+'/bio-single-cell-annotation-runs',json={**body,'name':'changed'},headers={'Idempotency-Key':'single-r'})
    assert changed.status_code==409
    result=run['result'];view=client.get(base+f"/bio-annotation-sets/{result['set_id']}/versions/{result['version_id']}")
    assert view.status_code==200,view.text
    view=view.json();assert view['origin']=='SingleR' and view['algorithm']['candidate_only']
    assert view['assignments'][0]['status']=='uncertain' and view['labels'][0]['status']=='proposed'
    assert client.get(view['members'][0]['download_url']).status_code==200
    assert len(client.get(base+f"/bio-processed-datasets/{parent['processed_dataset_version_id']}/annotation-runs").json()['items'])==1
    receipt=client.get(base+'/bio-requests/single-r?kind=annotation_run')
    assert receipt.status_code==200,receipt.text
    assert receipt.json()==dict(kind='annotation_run',id=created['id'],root_id=None,
        request_digest=digest({**body,'seed':0}),task_id=task['id'])
    workspace=client.get(f"/api/v1/tasks/{task['id']}/workspace");assert workspace.status_code==200,workspace.text
    assert workspace.json()['artifacts']['bioinformatics']['annotation_version_id']==result['version_id']
    # Suggestions remain their own immutable set; human adoption creates a new set.
    assert client.post(base+f"/bio-annotation-sets/{result['set_id']}/versions",json=dict(name='Human',raw_source=parent['raw_source'],processed_dataset_version_id=parent['processed_dataset_version_id'],expected_revision=1),headers={'Idempotency-Key':'no-machine-overwrite'}).status_code==422
    retry_run=client.post(base+'/bio-single-cell-annotation-runs',json=body,headers={'Idempotency-Key':'single-r-retry'}).json()
    from app.core.exceptions import StorageError
    def unavailable(*args,**kwargs):raise StorageError('bio_environment_unavailable','Fixture unavailable',409)
    monkeypatch.setattr(analysis_execution,'execute_bio_analysis',unavailable)
    failed=run_task(retry_run['task']['id'],retry_run['task']['revision']);assert failed['status']=='failed'
    retried=client.post(f"/api/v1/tasks/{failed['id']}/retry",json=dict(expected_revision=failed['revision']))
    assert retried.status_code==202,retried.text
    monkeypatch.setattr(analysis_execution,'execute_bio_analysis',engine)
    assert run_task(failed['id'],retried.json()['revision'])['status']=='succeeded'
    assert f['modes']==['compute']


def test_subset_task_freezes_parent_and_never_reuses_old_labels(client,parent_result,monkeypatch):
    from app.domain.bioinformatics import analysis_execution
    from app.domain.tasks.execution import run_task
    from app.db.database import database_connection
    f=parent_result;base=f['base'];parent=f['source']
    body=dict(name='T subset',parent_processed_source=parent,cluster_ids=['0'],params=dict(min_spots=1,doublet=dict(enabled=True,exclude_predicted=True)))
    created=client.post(base+'/bio-single-cell-subsets',json=body,headers={'Idempotency-Key':'subset'})
    assert created.status_code==202,created.text
    task=created.json()['task']
    with database_connection() as db:
        row=db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()['input_snapshot']
        assert row['subset']['resolved_cell_ids']==['c1']
        assert row['subset']['parent_processed_source']==parent
        assert not row['params']['doublet']['enabled'] and not row['params']['doublet']['exclude_predicted']
        assert not row['params']['decontx']['enabled'] and row['params']['cell_labels']==[]
    assert client.post(base+'/bio-single-cell-subsets',json={**body,'cell_ids':['c2']},headers={'Idempotency-Key':'bad'}).status_code==422
    replay=client.post(base+'/bio-single-cell-subsets',json=body,headers={'Idempotency-Key':'subset'})
    assert replay.status_code==202 and replay.json()['id']==created.json()['id']
    assert client.post(base+'/bio-single-cell-subsets',json={**body,'cell_ids':['c2']},headers={'Idempotency-Key':'subset'}).status_code==409
