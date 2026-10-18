"""Research input generations, immutable contexts, and unchanged cloud boundaries."""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.helpers.statistics import statistics_post
import copy
import json
import math

import pytest
from psycopg.types.json import Jsonb
from app.db.database import database_connection
from tests.api.test_analysis import client
from tests.helpers.analysis_plan import prepared_sample, run_plan, review_plan, plan_decision, decide_plan


def research(**changes):
    value=dict(question='  LOCAL-RESEARCH-SENTINEL  描述测量值分布\n', output_language='en',
        population='合成样本', study_design='横断面观察', observation_unit='每行一名受试者',
        observation_structure='independent', relationship_description='', output_requirements='')
    return {**value,**changes}


def create_research(client, request=None):
    base, file, prepared = prepared_sample(client)
    from tests.api.test_analysis import selection
    body = dict(dataset_id=prepared['id'], expected_setup_revision=0,
        selection=selection(numeric_column='D', group_column='C', unit='mg'),
        research_request=research() if request is None else request)
    response = seed_legacy_plan(client, base+'/analysis-plans', json=body, headers={'Idempotency-Key': 'research'})
    assert response.status_code == 202, response.text
    return base, file, response.json(), body


def confirm_research(client, request=None):
    base, file, task, body = create_research(client, request)
    assert run_plan(task)['status'] == 'waiting_confirmation'
    view = review_plan(client, task)
    accepted = decide_plan(client, task, plan_decision(view))
    assert accepted.status_code == 202, accepted.text
    assert run_plan(accepted.json())['status'] == 'succeeded'
    return base, file, task, body, review_plan(client, task)


def test_missing_research_waits_for_input_and_rechecks_before_separate_approval(client):
    incomplete = research()
    incomplete.update(population='', study_design='  ', observation_unit='', observation_structure='unknown')
    base, _, task, body = create_research(client, incomplete)
    assert run_plan(task)['status'] == 'waiting_input'
    first = review_plan(client, task)
    assert first['research_request'] == incomplete
    assert first['check']['research_missing'] == ['population', 'study_design', 'observation_unit', 'observation_structure']
    workspace = client.get('/api/v1/tasks/'+task['id']+'/workspace').json()
    assert workspace['wait']['kind'] == 'analysis_plan_input'
    assert workspace['allowed_actions'] == ['revise']
    with database_connection() as db:
        attempt = db.execute('SELECT * FROM task_attempts WHERE task_id=%s', (task['id'],)).fetchone()
        assert attempt['finished_at'] and attempt['lease_owner'] is None
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
    blocked = decide_plan(client, task, plan_decision(first), 'early-approve')
    assert blocked.status_code == 409, blocked.text
    correction = {**plan_decision(first, 'revise', first['selection']), 'research_request': research()}
    correction.pop('selection')
    supplied = decide_plan(client, task, correction, 'supply')
    assert supplied.status_code == 202, supplied.text
    assert supplied.json()['reason_code'] == 'input_provided'
    assert decide_plan(client, task, correction, 'supply').json() == supplied.json()
    assert run_plan(supplied.json())['status'] == 'waiting_confirmation'
    second = review_plan(client, task)
    assert second['plan_revision'] == 2 and second['wait_id'] != first['wait_id']
    assert second['check']['research_missing'] == []
    assert decide_plan(client, task, plan_decision(first), 'stale').status_code == 409
    accepted = decide_plan(client, task, plan_decision(second), 'confirm')
    assert run_plan(accepted.json())['status'] == 'succeeded'
    result = statistics_post(client, base+'/analysis-runs', json={'expected_revision': 1})
    assert result.status_code == 200, result.text
    value = result.json()
    assert value['schema_version'] == 2
    assert value['overall']['n'] == 4 and value['overall']['mean'] == 5.5
    assert value['overall']['std'] == pytest.approx(math.sqrt(35/3))
    assert value['check']['excluded_count'] == 2
    context = value['analysis_context']
    assert context['plan'] == review_plan(client, task)['result']
    assert context['plan']['research_request']['question'] == research()['question']
    assert context['method'] == dict(id='descriptive', parameters=body['selection'], observation_basis='rows')
    assert context['rounding'] == dict(display_significant_digits=6, stored_values='full_precision')
    assert all(item == dict(value=None, reason='not_applicable_descriptive') for item in context['not_computed'].values())
    assert statistics_post(client, base+'/analysis-runs', json={'expected_revision': 1}).json() == value
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:
        assert audit_database(db)['ok']


@pytest.mark.parametrize('structure', ['paired', 'repeated'])
def test_related_observations_need_relationship_but_keep_fixed_row_statistics(client, structure):
    request = research()
    request.update(observation_structure=structure)
    base, _, task, _ = create_research(client, request)
    assert run_plan(task)['status'] == 'waiting_input'
    view = review_plan(client, task)
    assert view['check']['research_missing'] == ['relationship_description']
    request['relationship_description'] = '合成的同一受试者关联观测'
    decision = plan_decision(view, 'revise', view['selection'])
    decision.pop('selection'); decision['research_request'] = request
    updated = decide_plan(client, task, decision).json()
    assert run_plan(updated)['status'] == 'waiting_confirmation'
    view = review_plan(client, task)
    approved = decide_plan(client, task, plan_decision(view), 'approve').json()
    assert run_plan(approved)['status'] == 'succeeded'
    assert statistics_post(client, base+'/analysis-runs', json={'expected_revision': 1}).json()['overall']['mean'] == 5.5


def test_research_revision_and_approval_shape_are_strict(client):
    base, _, task, _ = create_research(client)
    run_plan(task); first = review_plan(client, task)
    approve = plan_decision(first)
    for extra in ({'research_request': None}, {'research_request': research()}, {'selection': None}):
        assert decide_plan(client, task, {**approve, **extra}, 'invalid').status_code == 422
    changed = research(); changed.update(question='不同的本地问题', output_language='zh-CN')
    assert decide_plan(client, task, {**plan_decision(first,'revise',None),'research_request':changed}, 'null-selection').status_code == 422
    revision = {**plan_decision(first, 'revise', first['selection']), 'research_request': changed}
    revised = decide_plan(client, task, revision, 'change')
    assert revised.status_code == 202, revised.text
    run_plan(revised.json()); second = review_plan(client, task)
    assert second['research_request'] == changed and second['source'] == first['source']
    assert decide_plan(client, task, approve, 'late').status_code == 409
    selected={**second['selection'],'group_column':None}
    selection_only=decide_plan(client,task,plan_decision(second,'revise',selected),'change-selection')
    assert selection_only.status_code==202,selection_only.text
    run_plan(selection_only.json());third=review_plan(client,task)
    assert third['research_request']==changed and third['selection']==selected
    accepted=decide_plan(client,task,plan_decision(third),'final-confirm')
    assert run_plan(accepted.json())['status']=='succeeded'
    value=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    assert value['overall']['n']==5 and value['overall']['mean']==5
    assert value['analysis_context']['method']['parameters']==selected


def test_v1_cannot_accept_research_revision_or_gain_default_fields(client):
    from tests.helpers.analysis_plan import create_plan
    base,_,prepared=prepared_sample(client)
    task,body=create_plan(client,base,prepared)
    run_plan(task); view=review_plan(client,task)
    assert 'research_request' not in view and 'research_missing' not in view['check']
    request={**plan_decision(view,'revise',view['selection']),'research_request':research()}
    assert decide_plan(client,task,request,'upgrade-v1').status_code==422
    approved=decide_plan(client,task,plan_decision(view)).json()
    assert run_plan(approved)['status']=='succeeded'
    value=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    assert 'schema_version' not in value and 'analysis_context' not in value


@pytest.mark.parametrize('extra',[{'schema_version':2},{'analysis_context':{}},{'schema_version':2,'analysis_context':{}}])
def test_unplanned_result_cannot_claim_research_context(client,extra):
    from tests.api.test_analysis import add_file,selection
    base,_=add_file(client)
    assert client.put(base+'/analysis-setup',json=selection(expected_revision=0)).status_code==200
    result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    with database_connection(write=True) as db:
        db.execute('UPDATE analysis_runs SET result_json=%s WHERE id=%s',(json.dumps({**result,**extra}),result['id']))
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==409
    assert client.get(base+'/analysis-result').status_code==409
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:
        assert not audit_database(db)['ok']


@pytest.mark.parametrize('damage', ['remove_context', 'remove_version', 'remove_both', 'disguise_revision', 'question', 'method', 'rounding', 'not_computed', 'plan_hash'])
def test_result_context_tampering_is_rejected_on_cache_history_and_audit(client, damage):
    base, file, task, body, view = confirm_research(client)
    response = statistics_post(client, base+'/analysis-runs', json={'expected_revision': 1})
    assert response.status_code == 200, response.text
    result = response.json(); altered = copy.deepcopy(result)
    if damage == 'remove_context': altered.pop('analysis_context')
    elif damage == 'remove_version': altered.pop('schema_version')
    elif damage in ('remove_both','disguise_revision'):
        altered.pop('analysis_context'); altered.pop('schema_version')
        if damage=='disguise_revision':
            altered.pop('analysis_plan'); altered['setup_revision']=2
    elif damage == 'question': altered['analysis_context']['plan']['research_request']['question'] = 'forged'
    elif damage == 'method': altered['analysis_context']['method']['parameters']['unit'] = 'forged'
    elif damage == 'rounding': altered['analysis_context']['rounding']['display_significant_digits'] = 3
    elif damage == 'not_computed': altered['analysis_context']['not_computed']['p_value']['value'] = .05
    else: altered['analysis_context']['plan']['sha256'] = 'f'*64
    with database_connection(write=True) as db:
        db.execute('UPDATE analysis_runs SET result_json=%s WHERE id=%s', (json.dumps(altered), result['id']))
    assert statistics_post(client, base+'/analysis-runs', json={'expected_revision': 1}).status_code == 409
    assert client.get(base+'/analysis-result').status_code == 409
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError):
        ProjectStore(get_data_dir()).analysis_result_by_id(base.split('/')[4], file['id'], result['id'])
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:
        assert not audit_database(db)['ok']


@pytest.mark.parametrize('target', ['snapshot', 'checkpoint', 'decision', 'plan'])
def test_research_lineage_tampering_is_rejected(client, target):
    base, _, task, _, view = confirm_research(client)
    with database_connection(write=True) as db:
        if target == 'snapshot':
            row = db.execute('SELECT input_snapshot AS value FROM tasks WHERE id=%s', (task['id'],)).fetchone()
            value = row['value']; value['research_request']['question'] = 'forged'
            db.execute('UPDATE tasks SET input_snapshot=%s WHERE id=%s', (Jsonb(value), task['id']))
        elif target == 'checkpoint':
            row = db.execute('SELECT id,state_json AS value FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1', (task['id'],)).fetchone()
            value = row['value']; value['research_request']['question'] = 'forged'
            db.execute('UPDATE task_checkpoints SET state_json=%s WHERE id=%s', (Jsonb(value), row['id']))
        elif target == 'decision':
            row = db.execute('SELECT id,request_json AS value FROM analysis_plan_decisions WHERE task_id=%s', (task['id'],)).fetchone()
            value = row['value']; value['research_request'] = research()
            db.execute('UPDATE analysis_plan_decisions SET request_json=%s WHERE id=%s', (Jsonb(value), row['id']))
        else:
            value = copy.deepcopy(view['result']); value.pop('sha256'); value['research_request']['question'] = 'forged'
            db.execute('UPDATE confirmed_analysis_plans SET plan_json=%s WHERE task_id=%s', (Jsonb(value), task['id']))
    assert client.get('/api/v1/tasks/'+task['id']+'/analysis-plan').status_code == 409
    assert statistics_post(client, base+'/analysis-runs', json={'expected_revision': 1}).status_code == 409


def test_research_plaintext_does_not_expand_plot_or_explanation_material(client):
    base, file, _, _, _ = confirm_research(client,research(output_language='zh-CN'))
    result = statistics_post(client, base+'/analysis-runs', json={'expected_revision': 1}).json()
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir, ExcelSettings
    from app.domain.dataset_analysis import load_dataset
    from app.domain.boxplot_material import build_material
    from app.domain.external_material import explanation_material
    from app.domain.external_processing import disclosure, freeze_confirmation
    from tests.helpers.tasks import task_owner
    store=ProjectStore(get_data_dir(), owner_id=task_owner(client))
    record, _, sheet=load_dataset(store,base.split('/')[4],file['id'],result['source']['dataset_id'])
    snapshot=dict(result=result,source=result['source'],file=record,output_language='zh-CN')
    def external(kind, current):
        disclosed=disclosure(current,kind,store.owner_id)
        return freeze_confirmation(current,kind,store.owner_id,dict(version=3,confirmed=True,
            source_digest=disclosed['source_digest'],labels={i['key']:i['value'] for i in disclosed['labels']}))
    # Both builders are exercised against actual frozen v2 statistics.
    plot = build_material(result,record,None,ExcelSettings(),dataset_sheet=sheet,external=external('boxplot',snapshot))
    assert 'LOCAL-RESEARCH-SENTINEL' not in json.dumps(plot, ensure_ascii=False)
    from app.domain.boxplot import plot_data
    figure = dict(**plot_data(result,[1.,5.,7.,9.],{'A':[1.,5.],'B':[7.,9.]}),
        id='fixture',sha256='a'*64)
    snapshot['figure']=figure
    explanation = explanation_material(result, figure, external('explanation',snapshot))
    assert 'LOCAL-RESEARCH-SENTINEL' not in json.dumps(explanation, ensure_ascii=False)


def test_research_result_existing_artifact_chain_preserves_local_context_and_historical_download(client,monkeypatch):
    from tests.browser.task_browser_support import block_real_providers
    from tests.integration import test_dataset_artifact_chain as chain_helper
    blocked_attempts=block_real_providers(monkeypatch)
    base,file,_,_,_=confirm_research(client,research(output_language='zh-CN'))
    result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).json()
    monkeypatch.setattr(chain_helper,'new_result',lambda _: (base,file,result))
    outbound=[]
    original_plot=chain_helper.SyntheticPlotProvider
    original_explanation=chain_helper.SyntheticProvider
    class RecordedPlot(original_plot):
        def upload_input(self,container_id,payload,**kwargs):
            outbound.append(payload)
            return super().upload_input(container_id,payload,**kwargs)
        def create_plot(self,**kwargs):
            outbound.append(kwargs['instructions'])
            return super().create_plot(**kwargs)
    class RecordedExplanation(original_explanation):
        def create(self,**kwargs):
            outbound.extend([kwargs['payload'],kwargs['instructions']])
            return super().create(**kwargs)
    monkeypatch.setattr(chain_helper,'SyntheticPlotProvider',RecordedPlot)
    monkeypatch.setattr(chain_helper,'SyntheticProvider',RecordedExplanation)
    chain=chain_helper.complete_chain(client,monkeypatch)
    assert blocked_attempts==[]
    serialized=json.dumps(outbound,ensure_ascii=False)
    assert 'LOCAL-RESEARCH-SENTINEL' not in serialized
    assert 'research_request' not in serialized and 'analysis_context' not in serialized
    content=client.get(chain['report_url']).content
    with database_connection() as db:
        snapshots=db.execute("SELECT input_snapshot FROM tasks WHERE task_type IN ('boxplot','explanation','word_report')").fetchall()
        assert len(snapshots)==3 and all(row['input_snapshot']['result']==result for row in snapshots)
    from tests.api.test_analysis import selection
    saved=client.put(base+'/analysis-setup',json=selection(dataset_id=result['source']['dataset_id'],expected_revision=1,
        numeric_column='D',group_column=None,unit='mg'))
    assert saved.status_code==200,saved.text
    assert client.get(chain['report_url']).content==content
    assert client.get(base+'/analysis-result').json()['result']==result
