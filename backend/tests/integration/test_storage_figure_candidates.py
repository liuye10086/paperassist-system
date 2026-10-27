"""Original figure tasks recover captured bytes through their real retry action."""
import json
import hashlib
import pytest
from app.db.database import database_connection
from app.domain.storage_governance import service as storage
from app.domain.tasks.resume import TaskResumeService
from app.domain.tasks.workspace import TaskWorkspaceService
from tests.api.test_analysis import client
from tests.integration.test_boxplot_execution import queued,run,SyntheticPlotProvider
from tests.api.test_boxplot import cloud


@pytest.mark.parametrize('kind',['boxplot','workbench'])
def test_paid_candidate_survives_quota_tightening_and_real_resume(client,monkeypatch,kind):
    if kind=='boxplot':
        task,owner,_,result=queued(client)
        provider=SyntheticPlotProvider(result,pending=False)
        execute=lambda t:run(t,provider)
    else:
        from tests.integration.test_batch05_figure_execution import queued_figure,IndependentLineProvider
        from app.domain.figure_workbench.execution import run_figure_workbench_task
        store,project,result,vid,task=queued_figure(client,monkeypatch)
        owner=store.tasks.user_id;provider=IndependentLineProvider(result,pending=False)
        execute=lambda t:run_figure_workbench_task(t['id'],t['revision'],provider_factory=lambda:provider)
    original=task['id'];project=task['project_id']
    download=provider.download
    def tightened(*args,**kwargs):
        value=download(*args,**kwargs)
        with database_connection(write=True) as db:storage.set_policy(db,'project',project,0,'enforced')
        return value
    provider.download=tightened
    for _ in range(5):
        task=execute(task)
        assert task is not None
        if task['status']=='failed':break
    assert task['status']=='failed' and task['error_code']=='storage_quota_exceeded'
    with database_connection() as db:
        saved=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(original,)).fetchone())
        call=dict(db.execute('SELECT * FROM model_calls WHERE task_id=%s',(original,)).fetchone())
        reservations=[dict(row) for row in db.execute('SELECT * FROM budget_reservations WHERE call_id=%s ORDER BY budget_id',(call['id'],))]
        events=[dict(row) for row in db.execute('SELECT * FROM usage_events WHERE call_id=%s ORDER BY id',(call['id'],))]
        holds=list(db.execute('SELECT * FROM storage_reservations WHERE task_id=%s',(original,)))
        assert saved['figure_candidate'] and len(holds)==1 and holds[0]['size_bytes']==len(provider.png)
        assert storage.usage(db,project_id=project)['reserved_bytes']==len(provider.png)+holds[0]['candidate_json']['descriptor']['size_bytes']
        assert not db.execute('SELECT id FROM figures').fetchall()
    view=TaskWorkspaceService(owner).get(original)
    assert view['allowed_actions']==['retry']
    with database_connection(write=True) as db:storage.set_policy(db,'project',project,1024**3,'enforced')
    request={'operation':'retry','wait_id':None,'expected_task_revision':task['revision'],'input_version':task['input_version']}
    resumed=TaskResumeService(owner).resume(original,request,idempotency_key='storage-local-recovery')
    def forbidden(*args,**kwargs):raise AssertionError('captured result must never initialize provider')
    if kind=='boxplot':
        from app.domain.tasks.boxplot_execution import run_boxplot_task
        done=run_boxplot_task(original,resumed['revision'],provider_factory=forbidden)
    else:done=run_figure_workbench_task(original,resumed['revision'],provider_factory=forbidden)
    assert done['status']=='succeeded' and done['id']==original
    assert provider.posts==['container','upload','response']
    with database_connection() as db:
        after=dict(db.execute('SELECT * FROM model_calls WHERE task_id=%s',(original,)).fetchone())
        for key in ('id','provider_response_id','provider_state','input_digest','policy_snapshot','actual_token_micro_usd','actual_tool_micro_usd','usage_status','reconciliation_revision'):
            assert after[key]==call[key]
        assert [dict(row) for row in db.execute('SELECT * FROM budget_reservations WHERE call_id=%s ORDER BY budget_id',(call['id'],))]==reservations
        assert [dict(row) for row in db.execute('SELECT * FROM usage_events WHERE call_id=%s ORDER BY id',(call['id'],))]==events
        current=db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(original,)).fetchone()
        assert current['input_snapshot']==saved['input_snapshot']
        assert db.execute('SELECT count(*) AS n FROM figures').fetchone()['n']==1


def test_boxplot_insufficient_admission_never_initializes_provider(client):
    task,owner,_,result=queued(client)
    with database_connection(write=True) as db:storage.set_policy(db,'project',task['project_id'],0,'enforced')
    from app.domain.tasks.boxplot_execution import run_boxplot_task
    initialized=[]
    def forbidden():initialized.append(True);raise AssertionError('admission must precede provider')
    failed=run_boxplot_task(task['id'],task['revision'],provider_factory=forbidden)
    assert failed and failed['status']=='failed' and failed['error_code']=='storage_quota_exceeded'
    assert initialized==[]
    with database_connection(write=True) as db:
        assert not db.execute('SELECT id FROM storage_reservations WHERE task_id=%s',(task['id'],)).fetchall()
        assert not db.execute('SELECT id FROM model_calls WHERE task_id=%s',(task['id'],)).fetchall()
        original_tasks=[r['id'] for r in db.execute('SELECT id FROM tasks ORDER BY id')]
        storage.set_policy(db,'project',task['project_id'],1024**3,'enforced')
    assert TaskWorkspaceService(owner).get(task['id'])['allowed_actions']==['retry']
    response=client.post('/api/v1/tasks/'+task['id']+'/resume',json={'operation':'retry','wait_id':None,
        'expected_task_revision':failed['revision'],'input_version':failed['input_version']},headers={'Idempotency-Key':'admission-only-retry'})
    assert response.status_code==202,response.text
    current=response.json();provider=SyntheticPlotProvider(result,pending=False)
    for _ in range(5):
        current=run(current,provider)
        if current['status']=='succeeded':break
    assert current['status']=='succeeded' and current['id']==task['id']
    assert provider.posts==['container','upload','response']
    with database_connection() as db:
        assert original_tasks==[r['id'] for r in db.execute('SELECT id FROM tasks ORDER BY id')]
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone()['n']==1


def test_first_capture_transaction_rollback_preserves_local_descriptor_and_paid_png(client,monkeypatch):
    from contextlib import contextmanager
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.core.exceptions import StorageError
    from app.domain.tasks.boxplot_execution import run_boxplot_task
    task,owner,_,result=queued(client);provider=SyntheticPlotProvider(result,pending=False)
    task=run(run(task,provider),provider)
    original=TaskExecutionStore.connection;hit=[]
    @contextmanager
    def rollback(self,write=False):
        with original(self,write=write) as db:
            yield db
            if write and not hit and db.execute('SELECT 1 FROM tasks WHERE id=%s AND figure_candidate IS NOT NULL',(task['id'],)).fetchone():
                hit.append(True)
                raise StorageError('storage_unavailable','Synthetic first capture rollback')
    monkeypatch.setattr(TaskExecutionStore,'connection',rollback)
    failed=run(task,provider)
    monkeypatch.setattr(TaskExecutionStore,'connection',original)
    assert hit and failed['status']=='failed'
    with database_connection(write=True) as db:
        assert storage.reconcile_intents(db,TaskExecutionStore().assets.directory)==0
        hold=db.execute('SELECT * FROM storage_reservations WHERE task_id=%s',(task['id'],)).fetchone()
        assert hold['state']=='unknown' and hold['candidate_json'].get('descriptor')
    request={'operation':'retry','wait_id':None,'expected_task_revision':failed['revision'],'input_version':failed['input_version']}
    resumed=TaskResumeService(owner).resume(task['id'],request,idempotency_key='capture-rollback')
    def forbidden():raise AssertionError('captured bytes plus descriptor must recover locally')
    done=run_boxplot_task(task['id'],resumed['revision'],provider_factory=forbidden)
    assert done['status']=='succeeded' and provider.posts==['container','upload','response']


def test_legacy_poll_captures_then_explicit_original_job_retry_is_local(client,cloud,monkeypatch):
    from tests.api.test_boxplot import prepared,seed_legacy
    from app.domain.boxplot import poll_pending_figures
    from app.adapters.storage import get_project_store
    base,file,result,url=prepared(client);project=base.split('/')[4]
    job=seed_legacy(client,url);fetch=cloud.fetch;retrievals=[]
    with database_connection() as db:original_tasks=[r['id'] for r in db.execute('SELECT id FROM tasks ORDER BY id')]
    def tighten(self,current):
        retrievals.append(current['response_id']);output=fetch(self,current)
        with database_connection(write=True) as db:storage.set_policy(db,'project',project,0,'enforced')
        return output
    monkeypatch.setattr(cloud,'fetch',tighten)
    poll_pending_figures()
    state=client.get(url).json()
    assert state['figure'] is None and state['job']['status']=='failed'
    assert state['job']['message_code']=='storage_quota_exceeded'
    assert state['job']['recovery_mode']=='local_candidate'
    assert state['job']['recovery_requires_provider'] is False
    with database_connection() as db:
        saved=json.loads(db.execute('SELECT job_json FROM figure_jobs WHERE id=%s',(job['id'],)).fetchone()['job_json'])
        assert saved['figure_candidate']['provenance']['usage']=={'input_tokens':100,'output_tokens':100}
    with database_connection(write=True) as db:storage.set_policy(db,'project',project,1024**3,'enforced')
    def forbidden(*args,**kwargs):raise AssertionError('original candidate is local-only')
    monkeypatch.setattr(cloud,'__init__',forbidden)
    monkeypatch.setenv('OPENAI_API_KEY','')
    poll_pending_figures()
    assert client.get(url).json()['job']['status']=='failed'
    response=client.post(url,json={'expected_revision':result['setup_revision'],'retry':True,'expected_predecessor_id':job['id']})
    assert response.status_code==200,response.text
    state=response.json();assert state['figure'] and state['job']['id']==job['id'] and state['job']['status']=='completed'
    repeated=client.post(url,json={'expected_revision':result['setup_revision'],'retry':True,'expected_predecessor_id':job['id']})
    assert repeated.status_code==200 and repeated.json()['figure']==state['figure']
    assert retrievals==[job['response_id']] and cloud.calls==[]
    with database_connection() as db:
        assert [r['id'] for r in db.execute('SELECT id FROM tasks ORDER BY id')]==original_tasks
        assert not db.execute('SELECT id FROM model_calls').fetchall()
        assert db.execute('SELECT count(*) AS n FROM figure_jobs').fetchone()['n']==1
        after=json.loads(db.execute('SELECT job_json FROM figure_jobs WHERE id=%s',(job['id'],)).fetchone()['job_json'])
        for key in ('id','response_id','container_id','payload','expected','model'):assert after[key]==job[key]


def test_legacy_descriptor_io_failure_stops_poll_and_retains_png(client,cloud,monkeypatch):
    from tests.api.test_boxplot import prepared,seed_legacy
    from app.domain.boxplot import poll_pending_figures
    from app.domain.storage_governance import candidates
    from app.adapters.storage import get_project_store
    _,_,result,url=prepared(client);job=seed_legacy(client,url)
    fetch=cloud.fetch;retrievals=[]
    def fetched(self,current):
        retrievals.append(current['response_id']);return fetch(self,current)
    monkeypatch.setattr(cloud,'fetch',fetched)
    before=_storage_recovery_identity()
    write=candidates._write_immutable
    def io_failure(path,content):
        if path.suffix=='.json':raise OSError('synthetic descriptor filesystem failure')
        return write(path,content)
    monkeypatch.setattr(candidates,'_write_immutable',io_failure)
    poll_pending_figures()
    state=client.get(url).json()
    assert state['figure'] is None and state['job']['status']=='failed'
    assert state['job']['recovery_mode']=='original_response'
    paths=list((get_project_store().directory/'task-staging').glob('*.candidate'))
    assert len(paths)==1
    png_hash=storage._digest(paths[0])
    journals={p.name:p.read_bytes() for p in (get_project_store().directory/'.storage-intents').glob('*.capture.json')}
    poll_pending_figures()
    assert client.get(url).json()['job']['id']==job['id'] and retrievals==[job['response_id']]
    monkeypatch.setattr(candidates,'_write_immutable',write)
    response=client.post(url,json={'expected_revision':result['setup_revision'],'retry':True,'expected_predecessor_id':job['id']})
    assert response.status_code==200,response.text
    assert response.json()['job']['id']==job['id'] and response.json()['job']['status']=='completed'
    figure=response.json()['figure']
    assert (figure['size_bytes'],figure['sha256'])==png_hash
    assert retrievals==[job['response_id'],job['response_id']] and cloud.calls==[]
    assert _storage_recovery_identity()==before
    assert journals=={p.name:p.read_bytes() for p in (get_project_store().directory/'.storage-intents').glob('*.capture.json')}
    with database_connection() as db:
        after=json.loads(db.execute('SELECT job_json FROM figure_jobs WHERE id=%s',(job['id'],)).fetchone()['job_json'])
        for key in ('id','response_id','container_id','payload','expected','model'):assert after[key]==job[key]


def _storage_recovery_identity():
    with database_connection() as db:
        return {table:[dict(r) for r in db.execute('SELECT '+columns+' FROM '+table+' ORDER BY '+('budget_id,call_id' if table=='budget_reservations' else 'id'))]
            for table,columns in [('tasks','id,input_snapshot'),('figure_jobs','id'),
                ('model_calls','id,provider_response_id,provider_state,input_digest,policy_snapshot,actual_token_micro_usd,actual_tool_micro_usd,usage_status,reconciliation_revision'),
                ('budget_reservations','*'),('usage_events','*')]}


@pytest.mark.parametrize('kind',['boxplot','workbench'])
def test_initial_descriptor_io_failure_http_retry_uses_original_response(client,monkeypatch,kind):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.storage_governance import candidates
    from tests.integration.test_boxplot_execution import lease_for,expired
    if kind=='boxplot':
        task,owner,_,result=queued(client);provider=SyntheticPlotProvider(result,pending=False)
        execute=lambda t:run(t,provider)
    else:
        from tests.integration.test_batch05_figure_execution import queued_figure,IndependentLineProvider
        from app.domain.figure_workbench.execution import run_figure_workbench_task
        store,project,result,vid,task=queued_figure(client,monkeypatch)
        provider=IndependentLineProvider(result,pending=False)
        execute=lambda t:run_figure_workbench_task(t['id'],t['revision'],provider_factory=lambda:provider)
    write=candidates._write_immutable;hit=[]
    def broken(path,content):
        if path.suffix=='.json':hit.append(True);raise OSError('synthetic first descriptor failure')
        return write(path,content)
    monkeypatch.setattr(candidates,'_write_immutable',broken)
    for _ in range(5):
        value=execute(task)
        if hit:break
        task=value
    assert hit
    if value is None:
        expired(lease_for(task));assert TaskExecutionStore().recover_expired()==1
    with database_connection() as db:failed=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone())
    assert failed['status']=='failed' and failed['error_code'].startswith('storage_')
    before=_storage_recovery_identity();root=TaskExecutionStore().assets.directory
    journals={p.name:p.read_bytes() for p in (root/'.storage-intents').glob('*.capture.json')}
    posts=list(provider.posts);gets=len(provider.gets)
    monkeypatch.setattr(candidates,'_write_immutable',write)
    response=client.post('/api/v1/tasks/'+task['id']+'/resume',json={'operation':'retry','wait_id':None,
        'expected_task_revision':failed['revision'],'input_version':task['input_version']},headers={'Idempotency-Key':'descriptor-io-retry'})
    assert response.status_code==202,response.text
    with database_connection() as db:resumed=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone())
    done=execute(resumed)
    assert done['status']=='succeeded' and done['id']==task['id']
    assert provider.posts==posts==['container','upload','response'] and len(provider.gets)==gets+1
    assert _storage_recovery_identity()==before
    assert journals=={p.name:p.read_bytes() for p in (root/'.storage-intents').glob('*.capture.json')}
    with database_connection() as db:
        figure=json.loads(db.execute('SELECT figure_json FROM figures').fetchone()['figure_json'])
        assert (figure['size_bytes'],figure['sha256'])==(len(provider.png),hashlib.sha256(provider.png).hexdigest())


def test_legacy_admission_without_hold_can_explicitly_retrieve_original_response(client,cloud,monkeypatch):
    from tests.api.test_boxplot import prepared,seed_legacy
    from app.domain.boxplot import poll_pending_figures
    base,_,result,url=prepared(client);job=seed_legacy(client,url);project=base.split('/')[4]
    fetch=cloud.fetch;retrievals=[]
    def fetched(self,current):retrievals.append(current['response_id']);return fetch(self,current)
    monkeypatch.setattr(cloud,'fetch',fetched)
    with database_connection(write=True) as db:storage.set_policy(db,'project',project,0,'enforced')
    before=_storage_recovery_identity();poll_pending_figures()
    state=client.get(url).json()
    assert state['job']['status']=='failed' and state['job']['recovery_mode']=='original_response' and retrievals==[]
    with database_connection(write=True) as db:
        assert not db.execute('SELECT id FROM storage_reservations WHERE task_id=%s',(job['id'],)).fetchall()
        storage.set_policy(db,'project',project,1024**3,'enforced')
    poll_pending_figures();assert retrievals==[]
    response=client.post(url,json={'expected_revision':result['setup_revision'],'retry':True,'expected_predecessor_id':job['id']})
    assert response.status_code==200,response.text
    assert response.json()['job']['id']==job['id'] and response.json()['job']['status']=='completed'
    assert retrievals==[job['response_id']] and cloud.calls==[] and _storage_recovery_identity()==before


@pytest.mark.parametrize('kind',['boxplot','workbench','legacy'])
def test_completed_descriptor_loss_blocks_http_retry_and_capability(client,cloud,monkeypatch,kind):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.storage_governance.candidates import _path
    from app.adapters.storage import get_project_store
    if kind=='legacy':
        from tests.api.test_boxplot import prepared,seed_legacy
        from app.domain.boxplot import poll_pending_figures
        base,_,result,url=prepared(client);original=seed_legacy(client,url);project=base.split('/')[4]
        fetch=cloud.fetch
        def tightened(self,job):
            output=fetch(self,job)
            with database_connection(write=True) as db:storage.set_policy(db,'project',project,0,'enforced')
            return output
        monkeypatch.setattr(cloud,'fetch',tightened);poll_pending_figures()
        root=get_project_store().directory;identifier=original['id']
    else:
        if kind=='boxplot':
            task,owner,_,result=queued(client);provider=SyntheticPlotProvider(result,pending=False)
            execute=lambda t:run(t,provider)
        else:
            from tests.integration.test_batch05_figure_execution import queued_figure,IndependentLineProvider
            from app.domain.figure_workbench.execution import run_figure_workbench_task
            store,_,result,_,task=queued_figure(client,monkeypatch);owner=store.tasks.user_id
            provider=IndependentLineProvider(result,pending=False)
            execute=lambda t:run_figure_workbench_task(t['id'],t['revision'],provider_factory=lambda:provider)
        project=task['project_id'];download=provider.download
        def tightened(*args,**kwargs):
            output=download(*args,**kwargs)
            with database_connection(write=True) as db:storage.set_policy(db,'project',project,0,'enforced')
            return output
        provider.download=tightened
        for _ in range(5):
            task=execute(task)
            if task['status']=='failed':break
        assert task['status']=='failed'
        root=TaskExecutionStore().assets.directory;identifier=task['id']
    with database_connection(write=True) as db:
        hold=db.execute('SELECT * FROM storage_reservations WHERE task_id=%s',(identifier,)).fetchone()
        descriptor=_path(root,hold['candidate_json']['descriptor']['object_key'])
        assert descriptor.exists() and hold['candidate_json']['descriptor_complete']
        storage.set_policy(db,'project',project,1024**3,'enforced')
    descriptor.unlink() # Exact newly-created synthetic descriptor; PNG and journals retained.
    before=_storage_recovery_identity()
    if kind=='legacy':
        monkeypatch.setattr(cloud,'__init__',lambda *a,**k:(_ for _ in ()).throw(AssertionError('completed descriptor loss must not use provider')))
        state=client.get(url).json()
        assert state['job']['recovery_mode']=='blocked' and state['job']['recovery_requires_provider'] is False
        response=client.post(url,json={'expected_revision':result['setup_revision'],'retry':True,'expected_predecessor_id':identifier})
    else:
        assert TaskWorkspaceService(owner).get(identifier)['allowed_actions']==[]
        response=client.post('/api/v1/tasks/'+identifier+'/resume',json={'operation':'retry','wait_id':None,
            'expected_task_revision':task['revision'],'input_version':task['input_version']},headers={'Idempotency-Key':'lost-descriptor'})
    assert response.status_code==409,response.text
    assert _storage_recovery_identity()==before and not descriptor.exists()


def test_newer_modern_task_racing_legacy_local_recovery_blocks_publication(client,cloud,monkeypatch):
    from tests.api.test_boxplot import prepared,seed_legacy
    from app.domain.boxplot import poll_pending_figures
    from app.adapters.storage import ProjectStore
    from app.domain.tasks.service import TaskService
    from app.domain.tasks.contracts import TaskCreateRequest
    base,file,result,url=prepared(client);project=base.split('/')[4];job=seed_legacy(client,url)
    fetch=cloud.fetch
    def blocked(self,current):
        output=fetch(self,current)
        with database_connection(write=True) as db:storage.set_policy(db,'project',project,0,'enforced')
        return output
    monkeypatch.setattr(cloud,'fetch',blocked);poll_pending_figures()
    assert client.get(url).json()['job']['recovery_mode']=='local_candidate'
    with database_connection(write=True) as db:storage.set_policy(db,'project',project,1024**3,'enforced')
    owner=client.get('/api/v1/auth/me').json()['user']['id'];saved=ProjectStore.save_figure;created=[]
    def raced(store,*args,**kwargs):
        # After API and recovery admission reads, before the actual publisher's writer.
        task,_=TaskService(owner).create(project,TaskCreateRequest(task_type='boxplot',file_id=file['id'],
            analysis_run_id=result['id'],expected_revision=result['setup_revision']),idempotency_key='newer-modern-plot')
        created.append(task['id'])
        return saved(store,*args,**kwargs)
    monkeypatch.setattr(ProjectStore,'save_figure',raced)
    monkeypatch.setattr(cloud,'__init__',lambda *a,**k:(_ for _ in ()).throw(AssertionError('local recovery must not initialize provider')))
    response=client.post(url,json={'expected_revision':result['setup_revision'],'retry':True,'expected_predecessor_id':job['id']})
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='task_source_conflict'
    assert len(created)==1
    # The subsequent stale old-job request is rejected at the ordinary read gate too.
    again=client.post(url,json={'expected_revision':result['setup_revision'],'retry':True,'expected_predecessor_id':job['id']})
    assert again.status_code==409 and len(created)==1
    with database_connection() as db:
        assert not db.execute('SELECT id FROM figures').fetchall()
        assert not db.execute('SELECT id FROM model_calls').fetchall()
        row=json.loads(db.execute('SELECT job_json FROM figure_jobs WHERE id=%s',(job['id'],)).fetchone()['job_json'])
        assert row['id']==job['id'] and row['response_id']==job['response_id'] and row['figure_candidate']
