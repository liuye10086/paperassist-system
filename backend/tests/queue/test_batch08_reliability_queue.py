from tests.helpers.projection import check_projection,confirm_projection
"""Current and legacy real Linux recovery, with retained isolated evidence only."""
import hashlib
import json
import os
from pathlib import Path
import time
import pytest

from app.core.config import local_config
from app.core.paths import PROJECT_ROOT
from app.db.database import database_connection
from app.domain.model_usage.service import ModelUsageService
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.queue.test_real_worker import worker_stack
from tests.queue import test_plot_queue as legacy_plot
from tests.queue import test_explanation_queue as legacy_explanation
from tests.queue import test_batch05_collection_queue as collection_queue

pytestmark=pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS')!='1',
                             reason='Explicit isolated batch08 Linux queue test disabled.')
EVIDENCE=PROJECT_ROOT/'script/.runtime/stage04-batch08'


@pytest.fixture
def retained_stack(postgres_schema,tmp_path):
    assert postgres_schema.url.database=='paperassist_system_test'
    test_id=postgres_schema.schema.removeprefix('pa_test_')
    stack=worker_stack.prepare(PROJECT_ROOT,local_config(),test_id=test_id,assets=tmp_path/'data')
    assert stack.project=='pa-test-'+test_id
    assert (stack.directory/'model-api-key').read_text()==''
    worker_stack.ensure_docker()
    print('BATCH08_BUILD '+stack.project,flush=True)
    try:
        worker_stack.compose(stack,['build','worker'],timeout=1200)
        yield stack
    finally:
        worker_stack.stop(stack)
        containers=worker_stack.owned_containers(stack)
        assert not any(c['status']=='running' for c in containers)
        with database_connection() as db:
            task_counts=[dict(r) for r in db.execute('SELECT task_type,status,count(*) AS n FROM tasks GROUP BY task_type,status ORDER BY task_type,status')]
            calls=[dict(r) for r in db.execute('SELECT task_id,status,provider_status,provider_response_id,usage_status FROM model_calls ORDER BY created_at,id')]
        EVIDENCE.mkdir(parents=True,exist_ok=True)
        assets={p.relative_to(tmp_path/'data').as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (tmp_path/'data').rglob('*') if p.is_file()}
        value={'project':stack.project,'schema':postgres_schema.schema,'containers':containers,
               'broker_volume_retained':True,'model_secret_empty':True,'task_counts':task_counts,
               'model_calls':calls,'asset_directory':str(tmp_path/'data'),'asset_sha256':assets,
               'real_provider_calls':0,'provider_mode':'isolated in-memory SDK transport or synthetic host provider'}
        (EVIDENCE/('queue-stop-'+test_id+'.json')).write_text(json.dumps(value,indent=2),encoding='utf-8')
        print('BATCH08_STOPPED_VOLUME_RETAINED '+stack.project,flush=True)


def test_legacy_plot_boundaries_retain_isolated_volume(client,cloud,writer,retained_stack,tmp_path,monkeypatch):
    legacy_plot.test_plot_effect_boundaries_and_png_crash_recovery(client,cloud,writer,retained_stack,tmp_path,monkeypatch)


def test_legacy_explanation_boundaries_retain_isolated_volume(client,cloud,writer,retained_stack,tmp_path,monkeypatch):
    legacy_explanation.test_explanation_slices_and_real_crash_recovery(client,cloud,writer,retained_stack,tmp_path,monkeypatch)


def test_collection_wait_restart_and_word_crash_retain_isolated_volume(client,retained_stack,tmp_path,monkeypatch):
    monkeypatch.setattr(collection_queue,'evidence_directory',lambda:EVIDENCE)
    collection_queue.test_collection_wait_restart_compensation_and_word_crash_publish_once(
        client,retained_stack,tmp_path,monkeypatch)


def wait_for(check,seconds=240):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=check()
        if value:return value
        time.sleep(.5)
    pytest.fail('The isolated current artifact queue did not reach its expected state.')


def test_current_figure_and_explanation_real_crash_recovery(client,retained_stack,tmp_path,monkeypatch):
    from app.adapters.figure_workbench_store import read_bundle
    from app.domain.figure_workbench.contracts import SaveConfiguration,ConfirmProjection,GenerateFigure
    from app.domain.figure_workbench.tasks import submit
    from app.domain.figure_workbench.explanations import build_payload
    from app.domain.external_processing import digest
    from tests.integration.test_batch05_figure_store import source
    from tests.integration.test_batch05_figure_execution import frozen_policy

    stack=retained_stack
    cases={};snapshots={}
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for',frozen_policy)
    for mode in ('normal','response-unknown','response-saved','candidate'):
        store,project,result=source(client)
        args=(project,result['file_id'],result['id'])
        saved=store.save(*args,SaveConfiguration(config={'figure_kind':'line','language':'en',
            'projection':{'x_column':'A','y_column':'C'}}))
        version=saved['version']['id'];assert saved['version']['figure_contract']==3
        check=check_projection(store,*args,version)
        confirm_projection(store,*args,version,ConfirmProjection(input_sha256=check['input_sha256'],approved=True))
        preview=store.external_preview(*args,version)
        body=GenerateFigure(idempotency_key='batch08-figure-'+mode,
            external_processing={'confirmed':True,'payload_sha256':preview['payload_sha256']})
        task=submit(store,*args,version,body)['task']
        assert submit(store,*args,version,body)['task']['id']==task['id']
        service=ModelUsageService(store.tasks.user_id)
        for scope,key in [('user',store.tasks.user_id),('project',project)]:
            existing=service.get_budget(scope,key)
            if existing['limit_micro_usd'] is None:service.set_budget(scope,key,20000000,existing['revision'])
        with database_connection() as db:snapshots[task['id']]=db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()['input_snapshot']
        cases[mode]=(store,project,result,version,task)
    override=tmp_path/'batch08-worker.json'
    bootstrap=Path(__file__).with_name('batch08_artifact_bootstrap.py').resolve()
    override.write_text(json.dumps({'services':{'worker':{
        'command':['python','/app/batch08_artifact_bootstrap.py','worker'],
        'volumes':[{'type':'bind','source':str(bootstrap),'target':'/app/batch08_artifact_bootstrap.py','read_only':True}]}}}),encoding='utf-8')
    def start():worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
    start()
    def finished(items):
        states={mode:client.get('/api/v1/tasks/'+values[-1]['id']).json() for mode,values in items.items()}
        assert all(s['status']!='failed' for s in states.values()),states
        return states if all(s['status']==('waiting_confirmation' if mode=='response-unknown' else 'succeeded') for mode,s in states.items()) else None
    figures=wait_for(lambda:finished(cases))
    originals={}
    for mode,(store,project,result,version,task) in cases.items():
        tid=task['id'];state=figures[mode]
        actions=(tmp_path/'data'/('.batch08-calls-'+tid)).read_text().splitlines()
        assert actions.count('POST container')==actions.count('POST upload')==actions.count('POST response')==1
        with database_connection() as db:
            assert db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(tid,)).fetchone()['input_snapshot']==snapshots[tid]
            calls=db.execute('SELECT * FROM model_calls WHERE task_id=%s',(tid,)).fetchall();assert len(calls)==1
            call=dict(calls[0])
            assert call['policy_snapshot']['external_processing_version']==7
            assert snapshots[tid]['external_processing']['version']==7
            if mode=='response-unknown':
                assert state['reason_code']=='submission_unknown' and call['provider_response_id'] is None
                assert call['status'] in ('submitting','submission_unknown')
                assert call['usage_status']=='pending' and not any(a.startswith('GET') for a in actions)
                assert client.post('/api/v1/tasks/'+tid+'/retry',json={'expected_revision':state['revision']}).status_code==409
                assert db.execute('SELECT count(*) AS n FROM figures WHERE figure_config_version_id=%s',(version,)).fetchone()['n']==0
            else:
                assert call['status']=='completed' and call['provider_response_id']
                assert actions.count('GET cfile_png')==actions.count('GET cfile_result')==1
                assert db.execute('SELECT count(*) AS n FROM figures WHERE figure_config_version_id=%s',(version,)).fetchone()['n']==1
                if mode in ('response-saved','candidate'):
                    assert (tmp_path/'data'/('.batch08-crash-'+tid)).exists() and state['current_attempt']==2
        if mode!='response-unknown':
            bundle=read_bundle(store.assets,project,state['result_figure_id'])
            originals[tid]=(bundle['figure'],store.assets.figure_png(bundle['figure']))
            assert bundle['figure']['engine']['id']=='openai_figure_workbench_v3'
            assert bundle['figure']['verification']['status']=='matched'
            assert [p['y'] for p in bundle['figure']['statistics']['series'][0]['points']]==[9.,8.,7.,6.]

    # The same durable source/configuration is used after a real stack restart.
    worker_stack.stop(stack);start()
    def explanation_policy(payload,explanation=False):
        value=frozen_policy(payload);value['policy'].update(prompt_version='figure_explanation_v2',output_format='analysis_explanation_v2',tools=[])
        value.pop('tool_reserve_micro_usd');value.pop('tool_reserve_version');value['task_limit_micro_usd']=500000
        return value
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for',explanation_policy)
    explanations={}
    for mode,figure_mode in [('normal','normal'),('response-unknown','response-saved'),('response-saved','candidate')]:
        store,project,result,version,figure_task=cases[figure_mode]
        figure_id=figures[figure_mode]['result_figure_id']
        bundle=read_bundle(store.assets,project,figure_id)
        request=GenerateFigure(idempotency_key='batch08-explanation-'+mode,
            external_processing={'confirmed':True,'payload_sha256':digest(build_payload(bundle))})
        task=submit(store,project,result['file_id'],result['id'],version,request,figure_id=figure_id)['task']
        assert submit(store,project,result['file_id'],result['id'],version,request,figure_id=figure_id)['task']['id']==task['id']
        with database_connection() as db:snapshots[task['id']]=db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()['input_snapshot']
        explanations[mode]=(store,project,result,version,task)
    explained=wait_for(lambda:finished(explanations))
    for mode,(store,project,result,version,task) in explanations.items():
        tid=task['id'];state=explained[mode]
        actions=(tmp_path/'data'/('.batch08-calls-'+tid)).read_text().splitlines()
        assert actions.count('POST explanation')==1
        with database_connection() as db:
            assert db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(tid,)).fetchone()['input_snapshot']==snapshots[tid]
            calls=db.execute('SELECT * FROM model_calls WHERE task_id=%s',(tid,)).fetchall();assert len(calls)==1
            call=dict(calls[0]);reservations=db.execute('SELECT status FROM budget_reservations WHERE call_id=%s',(call['id'],)).fetchall()
            assert len(reservations)==3
            if mode=='response-unknown':
                assert state['reason_code']=='submission_unknown' and call['provider_response_id'] is None
                assert call['usage_status']=='pending' and {r['status'] for r in reservations}=={'held'}
                assert actions==['POST explanation']
                assert client.post('/api/v1/tasks/'+tid+'/retry',json={'expected_revision':state['revision']}).status_code==409
            else:
                assert call['status']=='completed' and call['provider_response_id']
                assert actions.count('GET explanation')>=1 and {r['status'] for r in reservations}=={'settled'}
                if mode=='response-saved':assert state['current_attempt']==2
                value=json.loads(db.execute('SELECT explanation_json FROM explanations WHERE id=%s',(state['result_explanation_id'],)).fetchone()['explanation_json'])
                assert value['engine']['id']=='figure_explanation_v2' and value['provenance']['model_call_id']==call['id']
    # Duplicate broker deliveries cannot publish another artifact or paid call.
    all_ids=[values[-1]['id'] for values in [*cases.values(),*explanations.values()]]
    call_logs={tid:(tmp_path/'data'/('.batch08-calls-'+tid)).read_bytes() for tid in all_ids}
    with database_connection(write=True) as db:
        for values in [*cases.values(),*explanations.values()]:
            db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s',(values[-1]['id'],))
    def all_republished():
        with database_connection() as db:
            return db.execute('SELECT count(*) AS n FROM task_outbox WHERE task_id=ANY(%s) AND published_at IS NULL',(all_ids,)).fetchone()['n']==0
    wait_for(all_republished,seconds=30)
    from tests.queue.delivery_crash_support import queue_stats
    def drained():
        stats=queue_stats(stack,worker_stack)
        return stats if stats and stats['ready']==stats['unacked']==0 else None
    final_queue=wait_for(drained,seconds=30)
    assert all((tmp_path/'data'/('.batch08-calls-'+tid)).read_bytes()==call_logs[tid] for tid in all_ids)
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM model_calls").fetchone()['n']==7
        assert db.execute('SELECT count(*) AS n FROM figures').fetchone()['n']==3
        assert db.execute('SELECT count(*) AS n FROM explanations').fetchone()['n']==2
    for mode,(store,project,result,version,task) in cases.items():
        if mode=='response-unknown':continue
        original,content=originals[task['id']]
        assert read_bundle(store.assets,project,original['id'])['figure']==original
        assert store.assets.figure_png(original)==content
    (EVIDENCE/'queue-current-artifacts.json').write_text(json.dumps({
        'project':stack.project,'schema':stack.environment['PAPERASSIST_DB_SCHEMA'],
        'figures':figures,'explanations':explained,'unchanged_frozen_inputs':len(snapshots),
        'model_calls':7,'published_figures':3,'published_explanations':2,
        'real_provider_calls':0,'mock_transport':True,'old_bytes_unchanged':True,
        'duplicates_republished_and_queue_drained':final_queue},indent=2),encoding='utf-8')
