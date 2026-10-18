from tests.helpers.projection import check_projection,confirm_projection
"""Real RabbitMQ/Linux Word/dispatcher; local synthetic figures, no paid provider."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time
import pytest

from app.core.config import local_config
from app.core.paths import PROJECT_ROOT
from app.db.database import database_connection
from app.adapters.collection_store import CollectionStore
from app.domain.report_collections.contracts import CollectionRequest
from app.domain.figure_workbench.contracts import SaveConfiguration,ConfirmProjection,GenerateFigure
from app.domain.figure_workbench.tasks import submit
from app.domain.figure_workbench.execution import run_figure_workbench_task,run_figure_explanation_task
from app.domain.figure_workbench.explanations import build_payload
from app.adapters.figure_workbench_store import read_bundle
from app.domain.external_processing import digest
from app.domain.model_usage.service import ModelUsageService
from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_store import source
from tests.integration.test_batch05_figure_execution import frozen_policy,IndependentLineProvider,FigureExplanationProvider
from tests.queue.test_real_worker import worker_stack

def evidence_directory():
    name=os.environ.get('PAPERASSIST_QUEUE_EVIDENCE_STAGE','stage04-batch05')
    if name not in ('stage04-batch05','stage04-batch06'):
        raise ValueError('Queue evidence stage must be stage04-batch05 or stage04-batch06.')
    directory=PROJECT_ROOT/'script'/'.runtime'/name
    directory.mkdir(parents=True,exist_ok=True)
    return directory


class VersionedIndependentLineProvider(IndependentLineProvider):
    def download(self,file_id,container_id,limit,*,policy):
        raw=super().download(file_id,container_id,limit,policy=policy)
        if file_id=='cfile_png' or 'presentation' not in self.payload:return raw
        manifest=json.loads(raw)
        manifest['presentation']=deepcopy(self.payload['presentation'])
        return json.dumps(manifest).encode()


pytestmark=pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS')!='1',reason='Explicit isolated Linux queue test disabled.')


@pytest.fixture
def batch05_stack(postgres_schema,tmp_path):
    assert postgres_schema.url.database=='paperassist_system_test'
    test_id=postgres_schema.schema.removeprefix('pa_test_')
    stack=worker_stack.prepare(PROJECT_ROOT,local_config(),test_id=test_id,assets=tmp_path/'data')
    assert stack.project=='pa-test-'+test_id
    assert stack.environment['PAPERASSIST_TASK_QUEUE']=='paperassist.test.'+test_id
    assert (stack.directory/'model-api-key').read_text()==''
    worker_stack.ensure_docker()
    print('BATCH05_QUEUE_BUILD '+stack.project,flush=True)
    try:
        worker_stack.compose(stack,['build','worker'],timeout=1200)
        yield stack
    finally:
        # This drill explicitly preserves all volumes, including the isolated broker.
        worker_stack.stop(stack)
        states=worker_stack.owned_containers(stack)
        assert not any(c['status']=='running' for c in states)
        evidence=evidence_directory()/('queue-stop-'+test_id+'.json')
        evidence.write_text(json.dumps({'project':stack.project,'schema':postgres_schema.schema,'containers':states,'volumes_preserved':True},indent=2),encoding='utf-8')
        print('BATCH05_QUEUE_STOPPED_VOLUMES_RETAINED '+stack.project,flush=True)


def override_file(tmp_path):
    path=tmp_path/'batch05-worker.json'
    path.write_text(json.dumps({'services':{'worker':{'command':['python','/app/batch05_collection_bootstrap.py','worker'],
        'volumes':[{'type':'bind','source':str(Path(__file__).with_name('batch05_collection_bootstrap.py').resolve()),
        'target':'/app/batch05_collection_bootstrap.py','read_only':True}]}}}),encoding='utf-8')
    return path


def start(stack,override):
    worker_stack.compose(stack,['--file',str(override),'up','-d','--wait','--wait-timeout','90'],timeout=180)
    assert {c['service'] for c in worker_stack.owned_containers(stack) if c['health']=='healthy'}=={'worker','dispatcher','rabbitmq'}


def until(check,timeout=150):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=check()
        if value:return value
        time.sleep(.3)
    pytest.fail('Isolated batch05 queue did not reach the expected durable state.')


def build_state(repository,project,collection_id,request_id):
    state=repository.get(project,collection_id)
    return next(r for v in state['versions'] for r in v['requests'] if r['id']==request_id)


def succeeded(repository,project,collection_id,request_id):
    request=build_state(repository,project,collection_id,request_id)
    assert request['status'] not in ('failed','blocked'),request
    return request if request['status']=='succeeded' else None


def synthetic_figure(workbench,project,result,config_id,monkeypatch):
    args=(project,result['file_id'],result['id'],config_id)
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for',frozen_policy)
    preview=workbench.external_preview(*args)
    task=submit(workbench,*args,GenerateFigure(idempotency_key='queue-source-figure',external_processing={'confirmed':True,'payload_sha256':preview['payload_sha256']}))['task']
    budgets=ModelUsageService(workbench.tasks.user_id)
    for scope,key in [('user',workbench.tasks.user_id),('project',project)]:budgets.set_budget(scope,key,5000000,0)
    provider=VersionedIndependentLineProvider(result,pending=False)
    for _ in range(5):
        task=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        assert task is not None
        if task['status'] in ('succeeded','failed'):break
    assert task['status']=='succeeded',task
    return read_bundle(workbench.assets,project,task['result_figure_id'])


def synthetic_explanation(workbench,project,result,config_id,bundle,monkeypatch):
    def policy(payload,explanation=False):
        value=frozen_policy(payload)
        value['policy'].update(prompt_version='figure_explanation_v2' if payload.get('figure_explanation_contract')==2 else 'figure_explanation_v1',output_format='analysis_explanation_v2',tools=[])
        value.pop('tool_reserve_micro_usd');value.pop('tool_reserve_version');value['task_limit_micro_usd']=500000
        return value
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for',policy)
    task=submit(workbench,project,result['file_id'],result['id'],config_id,GenerateFigure(idempotency_key='queue-source-explanation',
        external_processing={'confirmed':True,'payload_sha256':digest(build_payload(bundle))}),figure_id=bundle['figure']['id'])['task']
    provider=FigureExplanationProvider()
    task=run_figure_explanation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert task is not None and task['status']=='succeeded',task
    return task


def test_collection_wait_restart_compensation_and_word_crash_publish_once(client,batch05_stack,tmp_path,monkeypatch):
    stack=batch05_stack;override=override_file(tmp_path)
    workbench,project,result=source(client)
    args=(project,result['file_id'],result['id'])
    configured=workbench.save(*args,SaveConfiguration(config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'}}))
    assert configured['version']['figure_contract']==3
    config_id=configured['version']['id'];check=check_projection(workbench,*args,config_id)
    confirm_projection(workbench,*args,config_id,ConfirmProjection(input_sha256=check['input_sha256'],approved=True))
    repository=CollectionStore(workbench.assets)
    state=repository.create(project,CollectionRequest(title='Linux queue report',language='en',items=[{'figure_config_version_id':config_id}]),'queue-collection')
    assert state['versions'][0]['items'][0]['dependency_engine']=='figure_explanation_v2'
    collection_id=state['id'];version_id=state['current_version_id'];request_id=state['versions'][0]['requests'][0]['id']
    assert build_state(repository,project,collection_id,request_id)['missing']==[{'figure_config_version_id':config_id,'kind':'figure'}]
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM task_attempts a JOIN tasks t ON t.id=a.task_id WHERE t.task_type='figure_projection'").fetchone()['n']==0
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE task_type='collection_word_report'").fetchone()['n']==0
    start(stack,override)
    # Real dispatcher is alive; waiting does not occupy its sole worker.
    assert build_state(repository,project,collection_id,request_id)['task_id'] is None
    worker_stack.stop(stack);start(stack,override)
    assert build_state(repository,project,collection_id,request_id)['missing'][0]['kind']=='figure'
    worker_stack.stop(stack)
    bundle=synthetic_figure(workbench,project,result,config_id,monkeypatch)
    assert bundle['figure']['engine']['id']=='openai_figure_workbench_v3'
    assert [point['y'] for point in bundle['figure']['statistics']['series'][0]['points']]==[9.,8.,7.,6.]
    start(stack,override)
    until(lambda:build_state(repository,project,collection_id,request_id)['missing']==[{'figure_id':bundle['figure']['id'],'kind':'explanation'}],timeout=60)
    assert build_state(repository,project,collection_id,request_id)['task_id'] is None
    worker_stack.stop(stack);start(stack,override)
    assert build_state(repository,project,collection_id,request_id)['missing'][0]['kind']=='explanation'
    worker_stack.stop(stack)
    # Simulate the publication/advancement process gap: publisher is local synthetic,
    # and the stopped real dispatcher is the only component allowed to enqueue Word.
    with monkeypatch.context() as gap:
        gap.setattr('app.domain.report_collections.service.advance_pending',lambda **kwargs:0)
        explained=synthetic_explanation(workbench,project,result,config_id,bundle,gap)
    assert build_state(repository,project,collection_id,request_id)['task_id'] is None
    start(stack,override)
    first=until(lambda:succeeded(repository,project,collection_id,request_id))
    first_meta,first_bytes=repository.download(project,collection_id,first['report']['id'])
    assert hashlib.sha256(first_bytes).hexdigest()==first_meta['sha256']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM collection_reports WHERE build_request_id=%s',(request_id,)).fetchone()['n']==1
        assert db.execute('SELECT current_attempt FROM tasks WHERE id=%s',(first['task_id'],)).fetchone()['current_attempt']==1
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s',(first['task_id'],)).fetchone()['n']==0
    second=repository.export(project,collection_id,version_id,'queue-explicit-2')
    assert repository.export(project,collection_id,version_id,'queue-explicit-2')['id']==second['id']
    assert second['export_revision']==2
    # The Linux child exits after writing DOCX but before the publication commit.
    until(lambda:(tmp_path/'data'/('.batch05-crash-'+second['task_id'])).exists(),timeout=60)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM collection_reports WHERE build_request_id=%s',(second['id'],)).fetchone()['n']==0
    recovered=until(lambda:succeeded(repository,project,collection_id,second['id']),timeout=150)
    with database_connection() as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(second['task_id'],)).fetchone()
        assert task['current_attempt']==2
        assert db.execute('SELECT count(*) AS n FROM collection_reports WHERE build_request_id=%s',(second['id'],)).fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==2
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE task_type='collection_word_report'").fetchone()['n']==2
        assert db.execute('SELECT count(*) AS n FROM task_outbox WHERE task_id=%s AND published_at IS NOT NULL',(second['task_id'],)).fetchone()['n']>=2
    assert repository.download(project,collection_id,first_meta['id'])[1]==first_bytes
    assert recovered['report']['id']!=first_meta['id']
    assert len(list((tmp_path/'data'/'collection_reports').glob('*.docx')))==2
    worker_stack.stop(stack);start(stack,override)
    assert repository.export(project,collection_id,version_id,'queue-explicit-2')['report']['id']==recovered['report']['id']
    assert repository.download(project,collection_id,first_meta['id'])[1]==first_bytes
    events=[json.loads(line) for line in (tmp_path/'data'/'.batch05-linux-events.jsonl').read_text().splitlines()]
    assert {entry['platform'] for entry in events}=={'linux'}
    assert {entry['task_id'] for entry in events}=={first['task_id'],second['task_id']}
    assert not (tmp_path/'data'/'.batch05-unexpected-network').exists()
    evidence={'schema':stack.environment['PAPERASSIST_DB_SCHEMA'],'project':stack.project,'collection_id':collection_id,
        'first_request':first['id'],'first_task':first['task_id'],'first_report':first_meta['id'],'first_sha256':first_meta['sha256'],
        'second_request':second['id'],'second_task':second['task_id'],'second_report':recovered['report']['id'],
        'second_attempts':2,'model_calls':2,'word_model_calls':0,'projection_worker_attempts':0,'linux_events':events,
        'figure_engine':bundle['figure']['engine']['id'],'explanation_engine':'figure_explanation_v2','provider_mode':'host synthetic source assets; Linux local Word only','volumes_preserved':True}
    (evidence_directory()/'queue-evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print('BATCH05_REAL_QUEUE_VERIFIED '+json.dumps({'schema':evidence['schema'],'reports':2,'recovery_attempts':2,'word_model_calls':0}),flush=True)
