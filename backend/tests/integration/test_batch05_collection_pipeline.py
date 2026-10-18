"""Actual confirmed plan/prepared source/configuration/figure dependency integration."""
from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_execution import queued_figure,IndependentLineProvider
from app.domain.figure_workbench.execution import run_figure_workbench_task
from app.adapters.collection_store import CollectionStore
from app.domain.report_collections.contracts import CollectionRequest
from app.domain.report_collections.service import advance_pending


def pending_collection(client,monkeypatch):
    workbench,project,result,config_id,task=queued_figure(client,monkeypatch)
    repository=CollectionStore(workbench.assets)
    request=CollectionRequest(title='Confirmed report',language='en',items=[{'figure_config_version_id':config_id}])
    state=repository.create(project,request,'pending-figure')
    return repository,workbench,project,result,config_id,task,state


def test_pending_figure_intent_keeps_exact_configuration_and_advances_only_after_publish(client,monkeypatch):
    from app.domain.file_lifecycle.service import FileLifecycleService
    from app.domain.file_lifecycle.contracts import DeletionRequest
    repository,workbench,project,result,config_id,task,state=pending_collection(client,monkeypatch)
    build=state['versions'][0]['requests'][0]
    assert build['status']=='waiting' and build['task_id'] is None
    assert build['missing']==[{'figure_config_version_id':config_id,'kind':'figure'}]
    with repository.store.connection() as db:
        before=db.execute("SELECT count(*) AS n FROM tasks WHERE task_type='collection_word_report'").fetchone()['n']
    assert before==0
    lifecycle=FileLifecycleService(repository.store)
    assessment=lifecycle.assessment(project,result['file_id'])
    assert assessment['counts']['report_build_requests']==1
    assert {'code':'report_build_pending'} in assessment['reasons']
    assert {'code':'integrity_unknown'} not in assessment['reasons']
    old_receipt,_=lifecycle.request_deletion(project,result['file_id'],DeletionRequest(
        expected_assessment_revision=assessment['assessment_revision'],reason='Retention fixture'),'old-receipt')
    provider=IndependentLineProvider(result,pending=False)
    for _ in range(5):
        task=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        if task['status'] in ('succeeded','failed'):break
    assert task['status']=='succeeded',task
    advance_pending(config=repository.store.db_config,directory=repository.store.directory)
    saved=repository.get(project,state['id'])
    assert saved['versions'][0]['items'][0]['figure'] is None # immutable intent
    assert saved['versions'][0]['requests'][0]['missing']==[{'figure_id':task['result_figure_id'],'kind':'explanation'}]
    assert saved['versions'][0]['requests'][0]['task_id'] is None
    preview=repository.preview(project,state['id'],state['current_version_id'])
    assert preview['items'][0]['figure']['id']==task['result_figure_id']
    assert preview['sections'][1]['content'][0]['record_count']==5
    assert lifecycle.history(project,result['file_id'])['items'][0]==old_receipt



def complete_collection(client,monkeypatch):
    import json
    from app.domain.figure_workbench.contracts import GenerateFigure
    from app.domain.figure_workbench.tasks import submit
    from app.domain.figure_workbench.explanations import build_payload
    from app.domain.figure_workbench.execution import run_figure_explanation_task
    from app.adapters.figure_workbench_store import read_bundle
    from app.adapters.report_store import digest
    from tests.integration.test_explanation_execution import SyntheticProvider
    from tests.integration.test_batch05_figure_execution import frozen_policy
    from app.domain.report_collections.execution import run_collection_word_task
    repository,workbench,project,result,config_id,task,state=pending_collection(client,monkeypatch)
    provider=IndependentLineProvider(result,pending=False)
    for _ in range(5):
        task=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        if task['status'] in ('succeeded','failed'):break
    assert task['status']=='succeeded',task
    figure_id=task['result_figure_id']
    def policy(payload,explanation=False):
        if not explanation:return frozen_policy(payload)
        return {'policy':{'model':'test-explanation','prompt_version':'figure_explanation_v1','max_output_tokens':10000,'timeout_seconds':15,'tools':[],
            'output_format':'analysis_explanation_v1','price':{'version':'synthetic-only','model':'test-explanation','input_micro_usd_per_million':100,'cached_input_micro_usd_per_million':50,'output_micro_usd_per_million':200}},
            'input_token_allowance':100000,'task_limit_micro_usd':500000}
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for',policy)
    payload=build_payload(read_bundle(workbench.assets,project,figure_id))
    explanation=submit(workbench,project,result['file_id'],result['id'],config_id,GenerateFigure(idempotency_key='explanation',external_processing={'confirmed':True,'payload_sha256':digest(payload)}),figure_id=figure_id)['task']
    class Provider(SyntheticProvider):
        def receipt(self):
            receipt=super().receipt()
            payload=self.posts[0][1]
            draft={key:' '.join('{{'+ref+'}}' for ref in refs) for key,refs in payload['required_references'].items()}
            receipt['response']['output'][0]['content'][0]['text']=json.dumps(draft)
            return receipt
    prose=Provider()
    for _ in range(5):
        explanation=run_figure_explanation_task(explanation['id'],explanation['revision'],provider_factory=lambda:prose)
        assert explanation is not None
        if explanation['status'] in ('succeeded','failed'):break
    assert explanation['status']=='succeeded',explanation
    advance_pending(config=repository.store.db_config,directory=repository.store.directory)
    state=repository.get(project,state['id']);build=state['versions'][0]['requests'][0]
    assert build['status']=='queued',build
    task=run_collection_word_task(build['task_id'],1,config=repository.store.db_config,directory=repository.store.directory)
    assert task['status']=='succeeded',task
    state=repository.get(project,state['id'])
    return repository,project,result,state,provider,prose


def test_real_source_complete_pipeline_preserves_n_and_has_no_word_model_call(client,monkeypatch):
    repository,project,result,state,provider,prose=complete_collection(client,monkeypatch)
    request=state['versions'][0]['requests'][0]
    report,content=repository.download(project,state['id'],request['report']['id'])
    preview=repository.preview(project,state['id'],state['current_version_id'])
    assert preview['items'][0]['result']['check']['valid_count']==3
    assert preview['items'][0]['projection']['result']['audit']['valid_n']==4
    assert preview['sections'][1]['content'][0]['record_count']==5
    with repository.store.connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s',(request['task_id'],)).fetchone()['n']==0
    assert len(prose.posts)==1
    response=client.get(f"/api/v1/projects/{project}/report-collections/{state['id']}/reports/{report['id']}/download")
    assert response.status_code==200 and response.content==content
    candidates=client.get(f'/api/v1/projects/{project}/report-collections/candidates').json()
    assert candidates['items'][0]['figure']['id']==preview['items'][0]['figure']['id']


def test_nonempty_collection_audit_and_file_retention_references(client,monkeypatch):
    from app.maintenance.database_audit import audit_database
    from app.domain.file_lifecycle.service import FileLifecycleService
    repository,project,result,state,_,_=complete_collection(client,monkeypatch)
    with repository.store.connection() as db: audit=audit_database(db)
    assert audit['ok'],__import__('json').dumps(audit,ensure_ascii=False)
    assessment=FileLifecycleService(repository.store).assessment(project,result['file_id'])
    assert assessment['original_integrity']=='valid'
    assert assessment['counts']['collection_reports']==1
    assert assessment['counts']['report_build_requests']==1
    assert assessment['history_downloads_preserved'] is True
    assert {'code':'integrity_unknown'} not in assessment['reasons']


def test_report_metadata_identity_corruption_is_rejected_before_asset_read(client,monkeypatch):
    from app.core.exceptions import StorageError
    import pytest
    repository,project,_,state,_,_=complete_collection(client,monkeypatch)
    report=state['versions'][0]['requests'][0]['report']
    with repository.store.connection(write=True) as db:
        db.execute("UPDATE collection_reports SET report_json=jsonb_set(report_json,'{id}','\"other\"'::jsonb) WHERE id=%s",(report['id'],))
    with pytest.raises(StorageError) as error: repository.download(project,state['id'],report['id'])
    assert error.value.code=='collection_source_conflict'


def test_http_pending_collection_versions_and_idempotency(client,monkeypatch):
    _,project,result,config_id,_=queued_figure(client,monkeypatch)
    url=f'/api/v1/projects/{project}/report-collections'
    payload={'title':'Waiting report','language':'en','automatic':True,'items':[{'figure_config_version_id':config_id}]}
    assert client.post(url,json=payload).status_code==422
    first=client.post(url,json=payload,headers={'Idempotency-Key':'collection-1'})
    assert first.status_code==201,first.text
    saved=first.json()
    assert saved['versions'][0]['requests'][0]['status']=='waiting'
    assert client.post(url,json=payload,headers={'Idempotency-Key':'collection-1'}).json()['id']==saved['id']
    conflict=client.post(url,json={**payload,'title':'Changed'},headers={'Idempotency-Key':'collection-1'})
    assert conflict.status_code==409
    preview=client.get(url+f"/{saved['id']}/versions/{saved['current_version_id']}/preview")
    assert preview.status_code==200 and len(preview.json()['sections'])==9
    newer=client.post(url+f"/{saved['id']}/versions",json={**payload,'expected_revision':1,'title':'Second'},headers={'Idempotency-Key':'collection-2'})
    assert newer.status_code==201 and len(newer.json()['versions'])==2
    exported=client.post(url+f"/{saved['id']}/versions/{saved['current_version_id']}/exports",json={},headers={'Idempotency-Key':'export-1'})
    assert exported.status_code==202 and exported.json()['export_revision']==2
    assert client.get(url).json()['items'][0]['id']==saved['id']
