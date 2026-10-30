"""New version integration. Providers and white PNGs are explicitly synthetic.

Real isolated PostgreSQL, numerical worker, public authenticated API, persisted
tasks and Word export run locally; these tests never establish paid evidence.
"""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import json
import pytest
from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_execution import queued_figure, FigureExplanationProvider
from tests.integration.test_batch06_pipeline import IndependentV2LineProvider, checked_policy
from tests.integration.test_batch08_recovery import finish
from app.adapters.figure_workbench_store import read_bundle
from app.adapters.collection_store import CollectionStore
from app.domain.figure_workbench.execution import run_figure_workbench_task, run_figure_explanation_task
from app.domain.figure_workbench.explanations import build_payload
from app.domain.figure_workbench.explanation_v5 import sentence_draft_v5
from app.domain.report_collections.contracts import CollectionRequest
from app.domain.report_collections.execution import run_collection_word_task
from app.domain.report_collections.service import advance_pending


class SyntheticSentenceProvider(FigureExplanationProvider):
    def create(self, **kwargs):
        receipt=super().create(**kwargs)
        payload=kwargs['payload']
        receipt['response']['output'][0]['content'][0]['text']=json.dumps(sentence_draft_v5(payload))
        return receipt


def authenticated_v5_explanation(client,workbench,project,result,figure,key):
    """Exercise preview approval and frozen persisted task with a synthetic v5 reply."""
    base=f'/api/v1/projects/{project}/files/{result["file_id"]}/analysis-runs/{result["id"]}/figure-workbench/figures/{figure["id"]}'
    preview=client.post(base+'/explanation-preview')
    assert preview.status_code==200,preview.text
    assert preview.json()['payload']['figure_explanation_contract']==5
    body={'idempotency_key':key,'external_processing':{'confirmed':True,'payload_sha256':preview.json()['payload_sha256']}}
    response=client.post(base+'/explanations',json=body)
    assert response.status_code==202,response.text
    task=response.json()['task']
    assert client.post(base+'/explanations',json=body).json()['task']['id']==task['id']
    with workbench.tasks.connection() as db:
        frozen=deepcopy(db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()['input_snapshot'])
    prose=SyntheticSentenceProvider()
    done=finish(task,prose,run_figure_explanation_task)
    assert done['status']=='succeeded',done
    with workbench.tasks.connection() as db:
        assert db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()['input_snapshot']==frozen
    assert len(prose.posts)==1
    return done


def frozen_collection_versions(repository,version_ids):
    with repository.store.connection() as db:
        return {version_id:{
            'version':dict(db.execute('SELECT * FROM report_collection_versions WHERE id=%s',(version_id,)).fetchone()),
            'items':[dict(row) for row in db.execute('SELECT * FROM report_collection_items WHERE version_id=%s ORDER BY position',(version_id,)).fetchall()],
        } for version_id in version_ids}


@pytest.mark.parametrize('initial_dependency',['configuration','figure'])
def test_new_contract3_missing_dependency_advances_v5_without_rewriting_history(client,monkeypatch,initial_dependency):
    config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'},
            'style':{'caption':'Historical figure caption.'}}
    workbench,project,result,version,plot=queued_figure(client,monkeypatch,config,contract_version=3)
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for',checked_policy)
    repository=CollectionStore(workbench.assets)
    provider=IndependentV2LineProvider(result,pending=False)
    with workbench.tasks.connection() as db:
        plot_snapshot=deepcopy(db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(plot['id'],)).fetchone()['input_snapshot'])
    if initial_dependency=='figure':
        plot=finish(plot,provider,run_figure_workbench_task)
        assert plot['status']=='succeeded',plot
        selection={'figure_id':plot['result_figure_id']}
    else:
        selection={'figure_config_version_id':version}

    # Simulate a collection frozen before the v5 upgrade. Production rows are
    # created through normal APIs; only this historical fixture uses the old default.
    enrich=CollectionStore.enrich_bundle
    with monkeypatch.context() as old_code:
        def historical_enrich(self,project_id,value):
            item=enrich(self,project_id,value)
            if item['configuration'].get('figure_contract')==3:
                item['dependency_engine']='figure_explanation_v4'
            return item
        old_code.setattr(CollectionStore,'enrich_bundle',historical_enrich)
        history=repository.create(project,CollectionRequest(title='Frozen v4 waiting',language='en',
            items=[selection|{'explanation_engine':'figure_explanation_v4'}]),'b07-frozen-v4')
    historical_version=history['current_version_id']
    original_history=frozen_collection_versions(repository,[historical_version])
    assert original_history[historical_version]['items'][0]['dependency_engine']=='figure_explanation_v4'

    root=f'/api/v1/projects/{project}/report-collections'
    candidates=client.get(root+'/candidates')
    assert candidates.status_code==200,candidates.text
    selected=next(item for item in candidates.json()['items'] if item['configuration']['id']==version)
    assert selected['dependency_engine']=='figure_explanation_v5'
    body={'title':'New v5 waiting','language':'en',
          'items':[selection|{'explanation_engine':'figure_explanation_v5'}]}
    created=client.post(root,json=body,headers={'Idempotency-Key':'b07-v5-waiting'})
    assert created.status_code==201,created.text
    fresh=created.json()
    revised=client.post(root+'/'+history['id']+'/versions',json=body|{'expected_revision':1},
        headers={'Idempotency-Key':'b07-v5-new-version'})
    assert revised.status_code==201,revised.text
    revision=revised.json()
    version_ids=[historical_version,fresh['current_version_id'],revision['current_version_id']]
    frozen=frozen_collection_versions(repository,version_ids)
    assert frozen[historical_version]==original_history[historical_version]
    for collection in (fresh,revision):
        item=collection['versions'][0]['items'][0]
        build=collection['versions'][0]['requests'][0]
        assert item['dependency_engine']=='figure_explanation_v5'
        assert build['status']=='waiting' and build['task_id'] is None
        assert build['missing'][0]['kind']==('figure' if initial_dependency=='configuration' else 'explanation')

    if initial_dependency=='configuration':
        plot=finish(plot,provider,run_figure_workbench_task)
        assert plot['status']=='succeeded',plot
    advance_pending(config=repository.store.db_config,directory=repository.store.directory)
    for collection in (fresh,revision):
        waiting=repository.get(project,collection['id'])['versions'][0]['requests'][0]
        assert waiting['status']=='waiting' and waiting['task_id'] is None
        assert waiting['missing']==[{'figure_id':plot['result_figure_id'],'kind':'explanation'}]
    figure=deepcopy(read_bundle(workbench.assets,project,plot['result_figure_id'])['figure'])
    assert figure['engine']['id']=='openai_figure_workbench_v3'
    assert figure['presentation']['schema_version']==2
    explanation=authenticated_v5_explanation(client,workbench,project,result,figure,'b07-missing-v5')
    saved=read_bundle(workbench.assets,project,figure['id'],explanation['result_explanation_id'])
    assert saved['figure']==figure
    assert saved['explanation']['engine']['id']=='figure_explanation_v5'
    advance_pending(config=repository.store.db_config,directory=repository.store.directory)
    for collection in (fresh,revision):
        build=repository.get(project,collection['id'])['versions'][0]['requests'][0]
        assert build['status']=='queued' and build['missing']==[],build
        done=run_collection_word_task(build['task_id'],1,config=repository.store.db_config,directory=repository.store.directory)
        assert done and done['status']=='succeeded',done
        report=repository.get(project,collection['id'])['versions'][0]['requests'][0]['report']
        _,content=repository.download(project,collection['id'],report['id'])
        with ZipFile(BytesIO(content)) as archive:
            assert [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]==[provider.png]
        with workbench.tasks.connection() as db:
            assert db.execute('SELECT count(*) n FROM model_calls WHERE task_id=%s',(build['task_id'],)).fetchone()['n']==0
    historical=next(row for row in repository.get(project,history['id'])['versions'] if row['id']==historical_version)
    assert historical['requests'][0]['status']=='waiting'
    assert historical['requests'][0]['missing']==[{'figure_id':figure['id'],'kind':'explanation'}]
    assert frozen_collection_versions(repository,version_ids)==frozen
    assert read_bundle(workbench.assets,project,figure['id'],explanation['result_explanation_id'])==saved
    with workbench.tasks.connection() as db:
        assert db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(plot['id'],)).fetchone()['input_snapshot']==plot_snapshot
    assert provider.posts==['container','upload','response']


@pytest.mark.parametrize('figure_contract',[3,4])
def test_authenticated_v5_pipeline_preserves_figure_version_and_exact_word_png(client,monkeypatch,figure_contract):
    config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'},
            'style':{'aliases':{'A':'Axis alias','C':'Response alias'},'caption':'Author caption.'}}
    workbench,project,result,version,plot=queued_figure(client,monkeypatch,config,contract_version=figure_contract)
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for',checked_policy)
    provider=IndependentV2LineProvider(result,pending=False)
    plot=finish(plot,provider,run_figure_workbench_task)
    assert plot['status']=='succeeded',plot
    bundle=read_bundle(workbench.assets,project,plot['result_figure_id'])
    figure=deepcopy(bundle['figure'])
    assert figure['engine']['id']=='openai_figure_workbench_v'+str(figure_contract)
    assert figure['presentation']['schema_version']==figure_contract-1
    base=f'/api/v1/projects/{project}/files/{result["file_id"]}/analysis-runs/{result["id"]}/figure-workbench/figures/{figure["id"]}'
    preview=client.post(base+'/explanation-preview')
    assert preview.status_code==200,preview.text
    payload=preview.json()['payload']
    assert payload['figure_explanation_contract']==5
    assert payload==build_payload(bundle)
    body={'idempotency_key':'b07-v5','external_processing':{'confirmed':True,'payload_sha256':preview.json()['payload_sha256']}}
    response=client.post(base+'/explanations',json=body)
    assert response.status_code==202,response.text
    task=response.json()['task']
    assert client.post(base+'/explanations',json=body).json()['task']['id']==task['id']
    prose=SyntheticSentenceProvider()
    task=finish(task,prose,run_figure_explanation_task)
    assert task['status']=='succeeded',task
    saved=read_bundle(workbench.assets,project,figure['id'],task['result_explanation_id'])
    assert saved['figure']==figure
    assert saved['explanation']['engine']['id']=='figure_explanation_v5'
    assert len(saved['explanation']['sections'])==6
    repository=CollectionStore(workbench.assets)
    request=CollectionRequest(title='B07 scoped integration',language='en',items=[{
        'figure_id':figure['id'],'explanation_id':task['result_explanation_id']}])
    collection=repository.create(project,request,'b07-v5-word')
    row=collection['versions'][0]['requests'][0]
    done=run_collection_word_task(row['task_id'],1,config=repository.store.db_config,directory=repository.store.directory)
    assert done and done['status']=='succeeded',done
    report=repository.get(project,collection['id'])['versions'][0]['requests'][0]['report']
    _,content=repository.download(project,collection['id'],report['id'])
    with ZipFile(BytesIO(content)) as archive:
        assert [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]==[provider.png]
        text=archive.read('word/document.xml').decode()
        assert text.count('Author caption.')==1
        assert all(text.count(note)==1 for note in figure['presentation']['statistical_notes'])
        assert 'Axis alias' in text and 'Response alias' in text
    assert provider.posts==['container','upload','response'] and len(prose.posts)==1
    with workbench.tasks.connection() as db:
        assert db.execute('SELECT count(*) n FROM model_calls WHERE task_id=%s',(row['task_id'],)).fetchone()['n']==0
