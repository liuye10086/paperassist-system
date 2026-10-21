from app.db.database import database_connection, SCHEMA_HEAD
from tests.api.test_analysis import client
from tests.api.test_descriptive import configured


def test_analysis_post_queues_without_computing(client, monkeypatch):
    base, _ = configured(client)
    import app.domain.descriptive as operations
    monkeypatch.setattr(operations, 'summarize', lambda *a, **k: (_ for _ in ()).throw(AssertionError('HTTP computed')))
    response = client.post(base + '/analysis-runs', json={'expected_revision': 1, 'idempotency_key': 'batch10-request'})
    assert response.status_code == 202, response.text
    task = response.json()
    assert task['task_type'] == 'statistics_compute'
    assert task['status'] == 'queued'
    assert task['result_analysis_run_id'] is None
    assert task['execution_receipt'] is None
    assert client.post(base + '/analysis-runs', json={'expected_revision': 1, 'idempotency_key': 'batch10-request'}).json()['id'] == task['id']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM analysis_runs').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM task_outbox WHERE task_id=%s', (task['id'],)).fetchone()['n'] == 1
    detail = client.get('/api/v1/tasks/' + task['id']).json()
    assert detail['id'] == task['id']


def test_statistics_schema_is_exact_and_nullable():
    from app.db.schema import metadata
    assert SCHEMA_HEAD == '0040_manuscript_writing_live'
    assert 'result_analysis_run_id' in metadata.tables['tasks'].c
    assert 'execution_receipt' in metadata.tables['tasks'].c
    with database_connection() as db:
        from app.maintenance.database_audit import audit_database
        assert audit_database(db)['schema_issues'] == []

def test_direct_execution_is_not_an_http_bypass(client):
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir, get_excel_settings
    from app.domain.descriptive import execute, RunRequest
    from app.core.exceptions import StorageError
    import pytest
    base, _ = configured(client)
    parts = base.split('/')
    with pytest.raises(StorageError, match='任务资料'):
        execute(parts[4], parts[6], RunRequest(expected_revision=1), ProjectStore(get_data_dir()), get_excel_settings())


def test_statistics_worker_claims_and_records_failure_without_retry(client, monkeypatch):
    from app.domain.tasks.execution import run_task
    from app.domain.regression.common import NumericError
    import app.domain.descriptive as descriptive
    base, _ = configured(client)
    task = client.post(base+'/analysis-runs',json={'expected_revision':1}).json()
    def exceeded(*args, **kwargs):
        raise NumericError('numeric_timeout','bounded timeout')
    monkeypatch.setattr(descriptive,'execute',exceeded)
    result = run_task(task['id'],task['revision'])
    assert result['status'] == 'failed'
    assert result['error_code'] == 'numeric_timeout'
    assert result['execution_receipt']['nodes'] == []
    assert result['result_analysis_run_id'] is None
    detail = client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert detail.status_code == 200, detail.text
    assert detail.json()['allowed_actions'] == []
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM analysis_runs').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM task_outbox WHERE task_id=%s',(task['id'],)).fetchone()['n'] == 1

def test_refresh_recovers_current_queued_task(client):
    base, _ = configured(client)
    task=client.post(base+'/analysis-runs',json={'expected_revision':1}).json()
    state=client.get(base+'/analysis-result').json()
    assert state['active_task']['id']==task['id']
    assert state['execution_verification'] is None


def test_receipt_constraint_rejects_missing_structure(client):
    import pytest
    from sqlalchemy.exc import IntegrityError
    from psycopg.types.json import Jsonb
    base, _ = configured(client)
    task=client.post(base+'/analysis-runs',json={'expected_revision':1}).json()
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute('UPDATE tasks SET execution_receipt=%s WHERE id=%s',(Jsonb({}),task['id']))

def test_statistics_result_and_success_commit_once_and_read_never_computes(client, monkeypatch):
    from app.domain.tasks.execution import run_task
    from app.domain.fixed_statistics_runtime import record_execution
    import app.domain.descriptive as descriptive
    base, _ = configured(client, [['value'],[1],[2],[3]], group_column=None)
    task = client.post(base+'/analysis-runs',json={'expected_revision':1}).json()
    def bounded_fixture(values, **kwargs):
        # Pipeline fault injection: actual numerical sandbox is exercised in Linux tests.
        record_execution({'contract_version':'fixed_statistics_v2','sandbox_version':'fixed_statistics_linux_v1_as1073741824_cpu30_wall30',
            'input_bytes':30,'output_bytes':300,'timeout_seconds':30,'elapsed_seconds':0.01,'cache_hit':False,
            'stdout_policy':'bounded_protocol','stderr_policy':'discard','input_policy':'frozen_projection','output_policy':'bounded_pipe',
            'memory_hard_limit':1073741824,'isolation':'linux_landlock_seccomp','cpu_hard_limit_seconds':30,'cpu_affinity_count':1,
            'child_cpu_seconds':0.01,'child_peak_rss_bytes':1024,'error_code':None})
        return {'n':3,'mean':2.,'std':1.,'min':1.,'q1':1.5,'median':2.,'q3':2.5,'max':3.,'iqr':1.,'warnings':[]}
    monkeypatch.setattr(descriptive,'summarize',bounded_fixture)
    result=run_task(task['id'],task['revision'])
    assert result['status']=='succeeded', result
    assert result['result_analysis_run_id']
    assert run_task(task['id'],task['revision']) is None
    monkeypatch.setattr(descriptive,'summarize',lambda *a,**k: (_ for _ in ()).throw(AssertionError('GET computed')))
    exact=client.get(base+'/analysis-runs/'+result['result_analysis_run_id'])
    assert exact.status_code==200,exact.text
    state=client.get(base+'/analysis-result').json()
    assert state['execution_verification']=='verified'
    assert state['result']==exact.json()
    assert client.get('/api/v1/tasks/'+task['id']+'/workspace').json()['artifacts']['analysis']==exact.json()
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM analysis_runs').fetchone()['n']==1
    from psycopg.types.json import Jsonb
    with database_connection(write=True) as db:
        db.execute("UPDATE analysis_runs SET result_json=replace(result_json,%s,%s) WHERE id=%s",('"mean": 2.0','"mean": 999.0',result['result_analysis_run_id']))
    assert client.get(base+'/analysis-runs/'+result['result_analysis_run_id']).status_code==409


def test_statistics_publication_rolls_back_if_task_completion_fails(client, monkeypatch):
    from app.domain.statistics_execution.execution import run_statistics_task
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.core.exceptions import StorageError
    import app.domain.descriptive as descriptive
    from app.domain.fixed_statistics_runtime import record_execution
    base, _ = configured(client,[['value'],[1],[2],[3]],group_column=None)
    task=client.post(base+'/analysis-runs',json={'expected_revision':1}).json()
    def summary(*a,**k):
        record_execution({'contract_version':'fixed_statistics_v2','sandbox_version':'fixed_statistics_linux_v1_as1073741824_cpu30_wall30','input_bytes':30,'output_bytes':300,'timeout_seconds':30,'elapsed_seconds':0.01,'cache_hit':False,'stdout_policy':'bounded_protocol','stderr_policy':'discard','input_policy':'frozen_projection','output_policy':'bounded_pipe','memory_hard_limit':1073741824,'isolation':'linux_landlock_seccomp','cpu_hard_limit_seconds':30,'cpu_affinity_count':1,'child_cpu_seconds':0.01,'child_peak_rss_bytes':1024,'error_code':None})
        return {'n':3,'mean':2.,'std':1.,'min':1.,'q1':1.5,'median':2.,'q3':2.5,'max':3.,'iqr':1.,'warnings':[]}
    monkeypatch.setattr(descriptive,'summarize',summary)
    finish=TaskExecutionStore._finish
    def fail_completion(self,db,task,status,error):
        if status=='succeeded': raise StorageError('storage_unavailable','injected completion failure')
        return finish(self,db,task,status,error)
    monkeypatch.setattr(TaskExecutionStore,'_finish',fail_completion)
    result=run_statistics_task(task['id'],task['revision'])
    assert result['status']=='failed'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM analysis_runs').fetchone()['n']==0

def test_modern_setup_without_independent_plan_is_rejected():
    import pytest
    from app.core.exceptions import StorageError
    from app.domain.statistics_execution.service import validate_setup
    with pytest.raises(StorageError):
        validate_setup(None,'project','file',{'source':{'kind':'prepared_dataset_version'},'selection':{'task_type':'descriptive_boxplot'}})


def test_0029_migration_preserves_old_rows_and_null_receipts(postgres_migration_config):
    from app.db.database import migration_connection, alembic_config
    from alembic import command
    from tests.db.test_task_schema import seed_owner, task_row
    from psycopg.types.json import Jsonb
    with migration_connection(write=True,config=postgres_migration_config) as db:
        settings=alembic_config(); settings.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
        command.downgrade(settings,'0028_research_materials')
        seed_owner(db)
        row=task_row()
        db.execute('INSERT INTO tasks ('+','.join(row)+') VALUES ('+','.join(['%s']*len(row))+')',tuple(Jsonb(v) if k=='input_snapshot' else v for k,v in row.items()))
        before=dict(db.execute("SELECT * FROM tasks WHERE id='t'").fetchone())
        command.upgrade(settings,'head')
        after=dict(db.execute("SELECT * FROM tasks WHERE id='t'").fetchone())
        assert {key:after[key] for key in before}==before
        assert after['execution_receipt'] is None and after['result_analysis_run_id'] is None
        command.downgrade(settings,'0028_research_materials')
        assert dict(db.execute("SELECT * FROM tasks WHERE id='t'").fetchone())==before
        command.upgrade(settings,'head')


def test_numeric_deadline_bounds_database_statement():
    import pytest
    from app.domain.fixed_statistics_runtime import numeric_execution_scope
    from app.domain.regression.common import NumericError
    from app.adapters.storage import _storage_connection
    with pytest.raises(NumericError) as caught:
        with numeric_execution_scope(timeout_seconds=0.05):
            with _storage_connection() as db:
                db.execute('SELECT pg_sleep(0.3)')
    assert caught.value.code=='numeric_timeout'

def test_successful_receipt_requires_real_isolation_measurements():
    from app.domain.statistics_execution import verification
    assert hasattr(verification,'validate_statistics_receipt')
    import pytest
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError):
        verification.validate_statistics_receipt({'schema_version':1,'status':'succeeded','nodes':[{'cache_hit':False}],'result_sha256':'a'*64})
    verification.validate_statistics_receipt({'schema_version':1,'status':'failed','nodes':[],'error_code':'numeric_environment_unavailable'})

def test_real_linux_statistics_task_produces_measured_receipt(client):
    import sys,pytest
    if sys.platform!='linux':pytest.skip('Real sandbox requires Linux; never replace it with a Windows fallback')
    from app.domain.tasks.execution import run_task
    base,_=configured(client,[['value'],[1],[2],[3]],group_column=None)
    queued=client.post(base+'/analysis-runs',json={'expected_revision':1}).json()
    task=run_task(queued['id'],queued['revision'])
    assert task['status']=='succeeded',task
    state=client.get(base+'/analysis-result').json()
    assert state['result']['overall']['mean']==2.
    assert state['execution_verification']=='verified'
    nodes=task['execution_receipt']['nodes']
    assert any(n['child_cpu_seconds'] is not None and n['child_peak_rss_bytes']>0 for n in nodes if not n['cache_hit'])
    with database_connection() as db:
        from app.maintenance.database_audit import audit_database
        audit=audit_database(db)
    assert audit['ok'],audit

def test_legacy_result_read_stays_available_without_forged_sandbox_status(client, monkeypatch):
    # A legacy persisted row remains readable, but is not labelled newly verified.
    from app.domain.tasks.execution import run_task
    from app.domain.fixed_statistics_runtime import record_execution
    import app.domain.descriptive as descriptive
    base,_=configured(client,[['value'],[1],[2],[3]],group_column=None)
    queued=client.post(base+'/analysis-runs',json={'expected_revision':1}).json()
    def summary(*a,**k):
        record_execution({'contract_version':'fixed_statistics_v2','sandbox_version':'fixed_statistics_linux_v1_as1073741824_cpu30_wall30','input_bytes':30,'output_bytes':300,'timeout_seconds':30,'elapsed_seconds':0.01,'cache_hit':False,'stdout_policy':'bounded_protocol','stderr_policy':'discard','input_policy':'frozen_projection','output_policy':'bounded_pipe','memory_hard_limit':1073741824,'isolation':'linux_landlock_seccomp','cpu_hard_limit_seconds':30,'cpu_affinity_count':1,'child_cpu_seconds':0.01,'child_peak_rss_bytes':1024,'error_code':None})
        return {'n':3,'mean':2.,'std':1.,'min':1.,'q1':1.5,'median':2.,'q3':2.5,'max':3.,'iqr':1.,'warnings':[]}
    monkeypatch.setattr(descriptive,'summarize',summary)
    task=run_task(queued['id'],queued['revision'])
    with database_connection(write=True) as db:
        # Simulate an unchanged pre-0029 result by removing only the test task lineage.
        db.execute('DELETE FROM task_events WHERE task_id=%s',(task['id'],))
        db.execute('DELETE FROM task_attempts WHERE task_id=%s',(task['id'],))
        db.execute('DELETE FROM task_outbox WHERE task_id=%s',(task['id'],))
        db.execute('DELETE FROM tasks WHERE id=%s',(task['id'],))
    monkeypatch.setattr(descriptive,'summarize',lambda *a,**k: (_ for _ in ()).throw(AssertionError('GET computed')))
    state=client.get(base+'/analysis-result')
    assert state.status_code==200,state.text
    assert state.json()['execution_verification']=='legacy_unverified'
    assert client.get(base+'/analysis-runs/'+task['result_analysis_run_id']).status_code==200


def test_modern_get_reads_saved_plan_statistics_without_any_numeric_spawn(client,monkeypatch):
    import sys,pytest
    if sys.platform!='linux':pytest.skip('Fixture must be published by the real Linux sandbox')
    from tests.integration.test_correlation_plan import prepared_correlations,create_correlation
    from tests.helpers.analysis_plan import run_plan,review_plan,plan_decision,decide_plan
    from app.domain.tasks.execution import run_task
    base,_,prepared=prepared_correlations(client)
    plan,_=create_correlation(client,base,prepared)
    run_plan(plan);approved=decide_plan(client,plan,plan_decision(review_plan(client,plan))).json();run_plan(approved)
    queued=client.post(base+'/analysis-runs',json={'expected_revision':1}).json()
    result=run_task(queued['id'],queued['revision'])
    assert result['status']=='succeeded',result
    def forbidden(*a,**k): raise AssertionError('GET spawned numerical work')
    import app.domain.fixed_statistics as fixed
    import app.domain.regression.service as models
    import app.domain.regression.bounded as bounded
    monkeypatch.setattr(fixed,'correlate_bounded',forbidden)
    monkeypatch.setattr(fixed,'compare_bounded',forbidden)
    monkeypatch.setattr(fixed,'summarize_bounded',forbidden)
    monkeypatch.setattr(models,'compute_bounded',forbidden)
    monkeypatch.setattr(bounded,'compute_bounded',forbidden)
    assert client.get(base+'/analysis-result').status_code==200
    assert client.get(base+'/analysis-runs/'+result['result_analysis_run_id']).status_code==200
    assert client.get(base+'/analysis-runs').status_code==200
    assert client.get('/api/v1/tasks/'+result['id']+'/workspace').status_code==200
    assert review_plan(client,plan)['result'] is not None

def test_existing_dispatcher_publishes_statistics_outbox(client):
    from app.workers.dispatcher import dispatch_once
    base,_=configured(client)
    task=client.post(base+'/analysis-runs',json={'expected_revision':1}).json()
    messages=[]
    assert dispatch_once(publish=messages.append)==1
    assert messages[0]['task_id']==task['id']
    assert set(messages[0])=={'id','task_id','task_revision'}

def test_queued_statistics_never_publishes_after_configuration_changes(client):
    from app.domain.tasks.execution import run_task
    from tests.api.test_analysis import selection
    base,_=configured(client)
    queued=client.post(base+'/analysis-runs',json={'expected_revision':1}).json()
    changed=client.put(base+'/analysis-setup',json=selection(expected_revision=1,unit='changed'))
    assert changed.status_code==200,changed.text
    failed=run_task(queued['id'],queued['revision'])
    assert failed['status']=='failed' and failed['error_code']=='task_source_conflict'
    assert failed['result_analysis_run_id'] is None
    assert client.get(base+'/analysis-result').json()['active_task'] is None
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM analysis_runs').fetchone()['n']==0


def test_failed_statistics_resource_limit_has_no_manual_retry_or_recovery_loop(client,monkeypatch):
    from app.domain.tasks.execution import run_task
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.regression.common import NumericError
    import app.domain.descriptive as descriptive
    base,_=configured(client)
    queued=client.post(base+'/analysis-runs',json={'expected_revision':1}).json()
    def blocked(*a,**k):raise NumericError('numeric_resource_limit','limit')
    monkeypatch.setattr(descriptive,'execute',blocked)
    failed=run_task(queued['id'],queued['revision'])
    assert failed['error_code']=='numeric_resource_limit'
    retry=client.post('/api/v1/tasks/'+failed['id']+'/retry',json={'expected_revision':failed['revision']})
    assert retry.status_code==409
    assert TaskExecutionStore().recover_expired()==0
