"""Authenticated v8 approval, assignment history and local reuse races."""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from app.adapters.figure_workbench_store import FigureWorkbenchStore, read_bundle
from app.adapters.storage import ProjectStore
from app.core.config import get_data_dir
from app.domain.figure_workbench.execution import run_figure_explanation_task, run_figure_workbench_task
from tests.api.test_admin_configurations import accounts, admin
from tests.api.test_analysis import client
from tests.api.test_customer_workspace import create_customer_project, sign_in
from tests.api.test_project_assignments import assign
from tests.integration.test_batch05_figure_execution import queued_figure
from tests.integration.test_batch06_pipeline import checked_policy, IndependentV2LineProvider
from tests.integration.test_batch08_recovery import finish
from tests.integration.test_b07_repair_versions import SyntheticSentenceProvider, authenticated_v5_explanation
from tests.integration.test_model_usage import context as usage_context,request as call_request


LINE = {'figure_kind':'line', 'language':'en', 'projection':{'x_column':'A','y_column':'C'}}


@pytest.mark.parametrize(('guard', 'code'), [
    ('stop-external', 'model_configuration_disabled'), ('demote-owner', 'permission_denied')])
def test_current_stop_forbids_a_new_statistical_submission(usage_context, admin, guard, code):
    from psycopg.types.json import Jsonb
    from app.core.exceptions import StorageError
    from app.db.database import database_connection
    from tests.api.test_admin_configurations import baseline,validated,switch
    service, owner, _, task_id = usage_context
    # Isolate the exact durable pre-POST transition. No provider is constructed.
    with database_connection(write=True) as db:
        db.execute("""UPDATE tasks SET task_type='figure_explanation',workflow_version='figure_explanation_v1',
            input_snapshot=%s WHERE id=%s""",(Jsonb({'external_processing':{'version':8,'confirmed_by':owner}}),task_id))
    call = service.reserve_call(call_request(task_id))
    if guard == 'stop-external':
        current = baseline(admin)
        validated(admin,current)
        assert current['bundle']['models']['real_calls_enabled'] is False
        assert switch(admin,current,0,'stop-external').status_code == 200
    else:
        changed = admin.patch('/api/v1/admin/users/'+owner, json=dict(
            role='customer', active=True, expected_revision=1, reason='Owner role changed before submission'))
        assert changed.status_code == 200, changed.text
        assert changed.json()['role'] == 'customer' and changed.json()['active']
    with pytest.raises(StorageError) as blocked:
        service.begin_submission(call['id'])
    assert blocked.value.code == code
    assert service.get_call(call['id'])['status'] == 'reserved'


def figure_approval(client, workbench_url, figure_id):
    base = f'{workbench_url}/figures/{figure_id}'
    preview = client.post(base+'/explanation-preview')
    assert preview.status_code == 200, preview.text
    request = dict(idempotency_key='statistical-approval', external_processing={
        'confirmed':True, 'payload_sha256':preview.json()['payload_sha256']})
    result = client.post(base+'/explanations', json=request)
    assert result.status_code == 202, result.text
    return base, request, result.json()['task']


def test_statistical_local_reuse_fences_active_v8_and_unsettled_call(client, monkeypatch):
    store, project, result, _, plot = queued_figure(client, monkeypatch, LINE, contract_version=4)
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', checked_policy)
    old_plot = finish(plot, IndependentV2LineProvider(result, pending=False), run_figure_workbench_task)
    old_bundle = read_bundle(store.assets, project, old_plot['result_figure_id'])
    old = authenticated_v5_explanation(client,store,project,result,old_bundle['figure'],'origin')
    workbench = f'/api/v1/projects/{project}/files/{result["file_id"]}/analysis-runs/{result["id"]}/figure-workbench'
    changed = client.post(workbench+'/configurations', json={
        'configuration_id':old_bundle['configuration']['configuration_id'], 'expected_revision':1,
        'config':{**LINE, 'style':{'palette':'gray'}}})
    assert changed.status_code == 200, changed.text
    version_url = workbench+'/versions/'+changed.json()['version']['id']
    preview = client.post(version_url+'/external-preview').json()
    plot = client.post(version_url+'/generate', json={'idempotency_key':'gray', 'external_processing':{
        'confirmed':True, 'payload_sha256':preview['payload_sha256']}}).json()['task']
    class GrayPlot(IndependentV2LineProvider):
        def receipt(self):
            receipt = super().receipt()
            receipt['response_id'] = receipt['response']['id'] = 'resp_gray_plot'
            return receipt
    target = finish(plot, GrayPlot(result,pending=False), run_figure_workbench_task)
    assert target['status'] == 'succeeded', target
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'statistical_explanation')
    _, _, task = figure_approval(client, workbench, target['result_figure_id'])
    route = version_url+'/reuse-explanation'
    request = {'source_explanation_id':old['result_explanation_id']}
    def blocked_in_workbench():
        state = client.get(workbench).json()
        entries = [e for config in state['configurations'] for e in config['versions']]
        return next(e for e in entries if e['version']['id'] == changed.json()['version']['id']).get('explanation_reuse_blocked',False)
    assert blocked_in_workbench()
    denied = client.post(route,json=request)
    assert denied.status_code == 409 and denied.json()['detail']['code'] == 'task_transition_invalid', denied.text
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.model_usage.contracts import CallRequest, ModelPolicy
    from app.domain.model_usage.service import ModelUsageService
    from app.domain.figure_workbench.tasks import EXPLANATION_KEY
    executor = TaskExecutionStore()
    lease = executor.claim(task['id'],task['revision'])
    with executor.connection() as db:
        running = executor.require_lease(db,lease)
    policy = running['input_snapshot']['explanation_policy']
    service = ModelUsageService(running['user_id'])
    call = service.reserve_call(CallRequest(task_id=task['id'],expected_task_revision=running['revision'],
        call_key=EXPLANATION_KEY,input_digest='a'*64,policy=ModelPolicy.model_validate(policy['policy']),
        input_token_allowance=policy['input_token_allowance']),execution_lease=lease)
    executor.fail(lease,'task_source_conflict')
    assert client.post(route,json=request).status_code == 409
    service.release_unsubmitted(call['id'],event_key='fixture-release',reason_code='fixture_release')
    assert not blocked_in_workbench()
    reused = client.post(route,json=request)
    assert reused.status_code == 200, reused.text
    assert reused.json()['derived_from'] == old['result_explanation_id']
    assert 'skills_trace' not in reused.json()['provenance']
    assert client.post(route,json=request).json() == reused.json()


@pytest.mark.parametrize('submitted', [False, True], ids=['revoked-before-submit','recover-known-id'])
def test_assigned_analyst_approves_customer_statistical_task(admin, monkeypatch, submitted):
    from app.domain.descriptive import RunRequest
    from app.domain.statistics_execution.service import create
    from app.domain.statistics_execution.execution import run_statistics_task
    from tests.integration.test_correlation_plan import prepared_correlations,create_correlation
    from tests.helpers.analysis_plan import run_plan,review_plan,plan_decision
    from app.domain.analysis_plan.service import AnalysisPlanService
    customer, analyst = TestClient(app), TestClient(app)
    owner_id = sign_in(customer,'stats-owner@assignments.test','customer')
    actor_id = sign_in(analyst,'stats-analyst@assignments.test','analyst')
    project_url = create_customer_project(customer)
    project = project_url.rsplit('/',1)[1]
    assert assign(admin,project_url,actor_id,0).status_code == 200
    def upload(_client, rows):
        book = Workbook()
        for row in rows:
            book.active.append(row)
        stream = BytesIO()
        book.save(stream)
        book.close()
        response = customer.post(project_url+'/files', files={'file':('assigned.xlsx',stream.getvalue())})
        assert response.status_code == 201, response.text
        record = response.json()['file']
        return project_url+'/files/'+record['id'], record
    monkeypatch.setattr('tests.integration.test_dataset_preparation.add_file', upload)
    file_url, record, prepared = prepared_correlations(analyst)
    # Seed an existing owner-scoped historical plan, then run the real numerical worker.
    plan,_ = create_correlation(customer,file_url,prepared)
    assert run_plan(plan)['status'] == 'waiting_confirmation'
    assets = ProjectStore(get_data_dir(),owner_id=owner_id)
    approved,_ = AnalysisPlanService(assets).decide(plan['id'],plan_decision(review_plan(analyst,plan)),'fixture-plan')
    assert run_plan(approved)['status'] == 'succeeded'
    compute = create(project,record['id'],RunRequest(expected_revision=1),assets)
    done = run_statistics_task(compute['id'],compute['revision'])
    result = analyst.get(file_url+'/analysis-runs/'+done['result_analysis_run_id']).json()
    store = FigureWorkbenchStore(assets)
    monkeypatch.setattr('tests.integration.test_batch05_figure_execution.source',lambda _: (store,project,result))
    _,_,_,_,plot = queued_figure(analyst,monkeypatch,LINE,contract_version=4)
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', checked_policy)
    plot = finish(plot,IndependentV2LineProvider(result,pending=False),run_figure_workbench_task)
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'statistical_explanation')
    workbench = file_url+'/analysis-runs/'+result['id']+'/figure-workbench'
    base, body, task = figure_approval(analyst,workbench,plot['result_figure_id'])
    with store.tasks.connection() as db:
        saved = db.execute('SELECT user_id,input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()
    approval = saved['input_snapshot']['external_processing']
    assert saved['user_id'] == owner_id != actor_id
    assert approval['confirmed_by'] == actor_id and approval['assignment_revision'] == 1
    provider = SyntheticSentenceProvider(pending=submitted)
    if submitted:
        task = run_figure_explanation_task(task['id'],task['revision'],provider_factory=lambda:provider)
        assert len(provider.posts) == 1 and not provider.gets
    assert assign(admin,project_url,None,1).status_code == 200
    assert analyst.post(base+'/explanations',json=body).status_code == 404
    assert analyst.get(base+'/png').status_code == 404
    assert analyst.get(base+'/package').status_code == 404
    replacement = TestClient(app)
    replacement_id = sign_in(replacement,'stats-replacement@assignments.test','analyst')
    assert assign(admin,project_url,replacement_id,2).status_code == 200
    new_preview = replacement.post(base+'/explanation-preview')
    assert new_preview.status_code == 200
    assert new_preview.json()['payload_sha256'] != body['external_processing']['payload_sha256']
    stale = replacement.post(base+'/explanations',json={**body,'idempotency_key':'replacement-request'})
    assert stale.status_code == 409 and stale.json()['detail']['code'] == 'task_source_conflict'
    done = finish(task,provider,run_figure_explanation_task)
    with store.tasks.connection() as db:
        ledger = db.execute('SELECT user_id,status,provider_response_id FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone()
        assert ledger['user_id'] == owner_id
    if submitted:
        assert done['status'] == 'succeeded' and len(provider.posts) == 1
        assert provider.gets == [ledger['provider_response_id']]
        assert actor_id not in str(provider.posts) and actor_id not in provider.instructions
    else:
        assert done['status'] == 'failed' and done['error_code'] == 'project_assignment_stale', done
        assert not provider.posts and not provider.gets and ledger['status'] == 'released'
