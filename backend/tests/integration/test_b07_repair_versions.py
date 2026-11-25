"""New version integration. Providers and white PNGs are explicitly synthetic.

Real isolated PostgreSQL, numerical worker, public authenticated API, persisted
tasks and Word export run locally; these tests never establish paid evidence.
"""
from copy import deepcopy
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile
import json
import pytest
from tests.api.test_analysis import client
from tests.api.test_admin_configurations import accounts, admin, baseline, saved as save_config, validated, switch
from tests.integration.test_batch05_figure_execution import queued_figure, FigureExplanationProvider
from tests.integration.test_batch06_pipeline import IndependentV2LineProvider, checked_policy
from tests.integration.test_batch08_recovery import finish
from app.adapters.figure_workbench_store import read_bundle
from app.adapters.collection_store import CollectionStore
from app.domain.figure_workbench.execution import run_figure_workbench_task, run_figure_explanation_task
from app.domain.figure_workbench.explanations import build_payload
from app.domain.figure_workbench.explanation_v5 import sentence_draft_v5
from app.domain.external_processing import digest
from app.domain.model_usage.gateway import input_digest
from app.domain.report_collections.contracts import CollectionRequest
from app.domain.report_collections.execution import run_collection_word_task
from app.domain.report_collections.service import advance_pending


class SyntheticSentenceProvider(FigureExplanationProvider):
    source_kind = 'synthetic_fixture'

    def __init__(self, *, pending=False):
        super().__init__()
        self.pending = pending
        self.gets = []

    def create(self, **kwargs):
        self.instructions = kwargs['instructions']
        assert kwargs['policy'].tools == []
        receipt=super().create(**kwargs)
        receipt['model'] = receipt['response']['model'] = kwargs['policy'].model
        payload=kwargs['payload']
        receipt['response']['output'][0]['content'][0]['text']=json.dumps(sentence_draft_v5(payload))
        if self.pending:
            self.completed = deepcopy(receipt)
            receipt['status'] = receipt['response']['status'] = 'in_progress'
            receipt['usage'] = receipt['response']['usage'] = None
        return receipt

    def retrieve(self, response_id, *, policy):
        self.gets.append(response_id)
        assert response_id == self.completed['response_id']
        return self.completed


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


@pytest.mark.parametrize(('figure_contract', 'skills'), [(3, False), (4, False), (4, True)],
                         ids=['3', '4', 'statistics-skills'])
def test_authenticated_v5_pipeline_preserves_figure_version_and_exact_word_png(client,monkeypatch,figure_contract,skills,request,tmp_path):
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
    if skills:
        monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'statistical_explanation')
    preview=client.post(base+'/explanation-preview')
    assert preview.status_code==200,preview.text
    payload=preview.json()['payload']
    assert payload['figure_explanation_contract']==5
    assert payload==build_payload(bundle)
    body={'idempotency_key':'b07-v5','external_processing':{'confirmed':True,'payload_sha256':preview.json()['payload_sha256']}}
    if skills:
        assert preview.json()['payload_sha256'] != digest(payload)
        snapshot = preview.json()['skills_snapshot']
        trace = snapshot['trace']
        assert (trace['workflow'], trace['step'], trace['tool']['id']) == (
            'statistical_explanation', 'explain_fixed_figure', 'figure_explanation')
        assert [rule['name'] for rule in trace['skills']] == ['statistical-reading']
        assert snapshot['instructions'] in preview.json()['effective_instructions']
        with monkeypatch.context() as disabled:
            disabled.delenv('PAPERASSIST_SKILL_WORKFLOWS')
            assert client.post(base+'/explanations', json=body).status_code == 409
        with workbench.tasks.connection() as db:
            assert db.execute("SELECT count(*) n FROM tasks WHERE project_id=%s AND task_type='figure_explanation'",
                              (project,)).fetchone()['n'] == 0
        from fastapi.testclient import TestClient
        from app.main import app
        from tests.api.test_customer_workspace import sign_in
        with TestClient(app) as customer:
            sign_in(customer, 'stats-review-customer@example.test', 'customer')
            assert customer.post(base+'/explanation-preview').status_code in (403, 404)
            assert customer.post(base+'/explanations', json=body).status_code in (403, 404)
        wrong_run = base.replace('/analysis-runs/'+result['id']+'/', '/analysis-runs/other-run/')
        assert client.post(wrong_run+'/explanation-preview').status_code == 409
        assert client.post(wrong_run+'/explanations', json=body).status_code == 409

        from tests.domain.test_explanation_policy import execution_policy
        policy = execution_policy()
        policy['policy']['model'] = policy['policy']['price']['model'] = 'gpt-6.1-sol'
        policy['policy']['max_output_tokens'] = 16000
        policy['input_token_allowance'] = 100000
        policy_file = tmp_path / 'statistical-policy.json'
        policy_file.write_text(json.dumps(policy), encoding='utf-8')
        monkeypatch.setenv('PAPERASSIST_EXPLANATION_POLICY_FILE', str(policy_file))
        administrator = request.getfixturevalue('admin')
        first = save_config(administrator, baseline(administrator), 'prompts', 'explanation_instruction',
                            'Use concise sentences.')
        validated(administrator, first)
        assert switch(administrator, first, 0, 'statistical-style').status_code == 200
        assert client.post(base+'/explanations', json=body).status_code == 409
        preview = client.post(base+'/explanation-preview')
        assert preview.json()['skills_snapshot'] == snapshot and preview.json()['payload'] == payload
        assert 'Use concise sentences.' in preview.json()['effective_instructions']
        body['external_processing']['payload_sha256'] = preview.json()['payload_sha256']
    response=client.post(base+'/explanations',json=body)
    assert response.status_code==202,response.text
    task=response.json()['task']
    if skills:
        second = save_config(administrator, first, 'prompts', 'explanation_instruction', 'Use short paragraphs.')
        validated(administrator, second)
        assert switch(administrator, second, 1, 'statistical-style-changed').status_code == 200
        monkeypatch.setenv('PAPERASSIST_SKILLS_MANIFEST_SHA256', '0'*64)
        assert client.post(base+'/explanation-preview').status_code == 503
        assert client.post(base+'/explanations',json=body).json()['task']['id']==task['id']
        monkeypatch.delenv('PAPERASSIST_SKILL_WORKFLOWS')
    assert client.post(base+'/explanations',json=body).json()['task']['id']==task['id']
    prose=SyntheticSentenceProvider(pending=skills)
    task=finish(task,prose,run_figure_explanation_task)
    assert task['status']=='succeeded',task
    saved=read_bundle(workbench.assets,project,figure['id'],task['result_explanation_id'])
    assert saved['figure']==figure
    assert saved['explanation']['engine']['id']=='figure_explanation_v5'
    assert len(saved['explanation']['sections'])==6
    with workbench.tasks.connection() as db:
        frozen = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task['id'],)).fetchone()['input_snapshot']
        call = db.execute('SELECT input_digest FROM model_calls WHERE task_id=%s', (task['id'],)).fetchone()
    if skills:
        assert frozen['skills_snapshot'] == snapshot
        assert frozen['external_processing']['version'] == 8
        assert saved['explanation']['provenance']['skills_trace'] == trace
        assert prose.posts == [payload] and prose.instructions == preview.json()['effective_instructions']
        assert prose.gets == [saved['explanation']['provenance']['response_id']]
        assert call['input_digest'] == input_digest(instructions=prose.instructions, payload=payload)
    else:
        assert frozen['external_processing']['version'] == 7
        assert 'skills_snapshot' not in frozen and 'skills_trace' not in saved['explanation']['provenance']
    repository=CollectionStore(workbench.assets)
    selection = {'figure_id': figure['id'], 'explanation_id': task['result_explanation_id']}
    assert saved['configuration']['config']['style']['caption'] == 'Author caption.'
    assert figure['caption'].count('Author caption.') == 1
    if figure_contract == 4:
        selection['caption'] = 'Collection annotation.'
    request=CollectionRequest(title='B07 scoped integration',language='en',items=[selection])
    collection=repository.create(project,request,'b07-v5-word')
    row=collection['versions'][0]['requests'][0]
    done=run_collection_word_task(row['task_id'],1,config=repository.store.db_config,directory=repository.store.directory)
    assert done and done['status']=='succeeded',done
    report=repository.get(project,collection['id'])['versions'][0]['requests'][0]['report']
    _,content=repository.download(project,collection['id'],report['id'])
    with ZipFile(BytesIO(content)) as archive:
        assert [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]==[provider.png]
        document = ElementTree.fromstring(archive.read('word/document.xml'))
        word = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text = '\n'.join(''.join(node.text or '' for node in paragraph.findall('.//w:t', word))
                         for paragraph in document.findall('.//w:p', word))
        assert text.count('Author caption.')==1
        assert text.count('Collection annotation.') == (1 if figure_contract == 4 else 0)
        assert all(text.count(note)==1 for note in figure['presentation']['statistical_notes'])
        assert 'Axis alias' in text and 'Response alias' in text
    assert provider.posts==['container','upload','response'] and len(prose.posts)==1
    with workbench.tasks.connection() as db:
        assert db.execute('SELECT count(*) n FROM model_calls WHERE task_id=%s',(row['task_id'],)).fetchone()['n']==0
    if figure_contract == 3:
        from app.domain.statistics_reader_reports.service import StatisticsReaderReportService
        service = StatisticsReaderReportService(workbench.assets)
        build = StatisticsReaderReportService._build
        with monkeypatch.context() as historical:
            def prepare_old_context(self, *args, **kwargs):
                kwargs.setdefault('context_schema_version', 1)
                return build(self, *args, **kwargs)
            historical.setattr(StatisticsReaderReportService, '_build', prepare_old_context)
            old = repository.create(project, request, 'b07-historical-reader-caption')
        with workbench.tasks.connection() as db:
            frozen = db.execute('SELECT id,content_json,content_sha256 FROM statistics_report_context_versions '
                                'WHERE collection_id=%s', (old['id'],)).fetchone()
        assert frozen['content_json']['schema_version'] == 1
        assert service.get(project, frozen['id'])['source']['sha256'] == frozen['content_sha256']


@pytest.mark.parametrize('collection_caption', ['Collection annotation.', 'Author caption.'], ids=['distinct','same'])
def test_reader_figure_keeps_each_authored_caption_once(collection_caption):
    from app.domain.external_processing import digest
    from app.domain.statistics_reader_reports.narrative import figure_output

    item = dict(figure={'title': 'Line plot', 'figure_kind': 'line'}, result={},
                explanation={'sections': [{'key': key, 'text': 'Saved text.'}
                                          for key in ('methods', 'results', 'interpretation')]},
                configuration={'config': {'style': {'caption': 'Author caption.'}}},
                user_caption=collection_caption)
    interpreted = figure_output(item, 1, 'en')['interpretation']
    assert interpreted.count('Author caption.') == 1
    assert interpreted.count('Collection annotation.') == (1 if collection_caption != 'Author caption.' else 0)
    # Digests captured from the original, unmodified v1 projection.
    old_digests = {'Collection annotation.': '39863374b0f771fe9b24b8a1708c40bccbf48714b090ec87cc4760d00e46149c',
                   'Author caption.': 'a3db97882abd1c5251f0a66921829500db060d8195991fd80cc7c1c7c40dced9'}
    assert digest(figure_output(item, 1, 'en', context_schema_version=1)) == old_digests[collection_caption]


@pytest.mark.parametrize('reserved', [False, True], ids=['before-reserve','reserved'])
def test_skills_submission_reuses_saved_v5_without_a_matching_task_or_model_post(client, monkeypatch, reserved):
    from app.domain.figure_workbench.explanations import render
    from app.domain.figure_workbench.contracts import GenerateFigure
    from app.domain.figure_workbench.tasks import submit
    config = {'figure_kind':'line', 'language':'en', 'projection':{'x_column':'A', 'y_column':'C'}}
    workbench, project, result, version, plot = queued_figure(client, monkeypatch, config, contract_version=4)
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', checked_policy)
    plot = finish(plot, IndependentV2LineProvider(result, pending=False), run_figure_workbench_task)
    bundle = read_bundle(workbench.assets, project, plot['result_figure_id'])
    figure = bundle['figure']
    payload = build_payload(bundle)
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'statistical_explanation')
    base = f'/api/v1/projects/{project}/files/{result["file_id"]}/analysis-runs/{result["id"]}/figure-workbench/figures/{figure["id"]}'
    preview = client.post(base+'/explanation-preview').json()
    body = dict(idempotency_key='queued-before-local-reuse',
                external_processing=dict(confirmed=True, payload_sha256=preview['payload_sha256']))
    queued = client.post(base+'/explanations', json=body).json()['task']
    # A separately approved plain request keeps its v7 fact-only identity.
    # It cannot silently adopt the in-progress, differently approved v8 task.
    plain = GenerateFigure(idempotency_key='separate-workflow', external_processing={
        'confirmed': True, 'payload_sha256': digest(payload)})
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError) as mismatch:
        submit(workbench, project, result['file_id'], result['id'], version, plain, figure_id=figure['id'])
    assert mismatch.value.code == 'task_transition_invalid'
    # Represent an existing separately saved v5 artifact with no originating task in this database.
    old = render(bundle, sentence_draft_v5(payload), {
        'model':'fixture', 'model_call_id':'historical-offline-call', 'response_id':'historical-offline-response'})
    with workbench.tasks.connection(write=True) as db:
        db.execute('INSERT INTO explanations(id,analysis_run_id,figure_id,engine_version,explanation_json) VALUES(%s,%s,%s,%s,%s)',
                   (old['id'],result['id'],figure['id'],old['engine']['id'],json.dumps(old)))
    repeated = client.post(base+'/explanations', json={**body, 'idempotency_key':'reuse-saved-v5'})
    assert repeated.status_code == 202 and repeated.json() == {'task':None, 'explanation':old}
    def unexpected_provider():
        pytest.fail('An already saved explanation must finish without constructing a provider.')
    if reserved:
        from app.adapters.task_execution_store import TaskExecutionStore
        from app.domain.figure_workbench import execution
        from app.domain.figure_workbench.tasks import EXPLANATION_KEY
        from app.domain.model_usage.contracts import CallRequest, ModelPolicy
        from app.domain.model_usage.service import ModelUsageService
        executor = TaskExecutionStore()
        lease = executor.claim(queued['id'], queued['revision'])
        with executor.connection() as db:
            running = executor.require_lease(db,lease)
        policy = running['input_snapshot']['explanation_policy']
        service = ModelUsageService(running['user_id'])
        service.reserve_call(CallRequest(task_id=queued['id'],expected_task_revision=running['revision'],
            call_key=EXPLANATION_KEY, input_digest=input_digest(instructions=preview['effective_instructions'],payload=payload),
            policy=ModelPolicy.model_validate(policy['policy']),input_token_allowance=policy['input_token_allowance']),
            execution_lease=lease)
        done = execution._execute(executor,lease,unexpected_provider,[],True)
    else:
        done = run_figure_explanation_task(queued['id'], queued['revision'], provider_factory=unexpected_provider)
    assert done['status'] == 'succeeded' and done['result_explanation_id'] == old['id']
    assert read_bundle(workbench.assets, project, figure['id'], old['id'])['explanation'] == old
    with workbench.tasks.connection() as db:
        calls = db.execute('SELECT status,provider_response_id,estimated_cost_micro_usd FROM model_calls WHERE task_id=%s',
                           (queued['id'],)).fetchall()
        assert [dict(call) for call in calls] == ([{'status':'released','provider_response_id':None,
                                                    'estimated_cost_micro_usd':0}] if reserved else [])
