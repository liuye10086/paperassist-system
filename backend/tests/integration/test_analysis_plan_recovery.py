"""Real database rollback/fencing and preserved published history audit."""
import pytest
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.analysis_plan_store import AnalysisPlanStore
from app.adapters.task_store import TaskStore
from app.db.database import database_connection,migration_connection
from tests.api.test_analysis import client
from tests.helpers.tasks import task_owner
from tests.helpers.analysis_plan import prepared_sample,create_plan,run_plan,review_plan,plan_decision,decide_plan,confirmed_sample


def test_expired_publish_lease_recovers_once_and_old_worker_cannot_publish(client):
    base,_,prepared=prepared_sample(client);task,_=create_plan(client,base,prepared)
    run_plan(task);approved=decide_plan(client,task,plan_decision(review_plan(client,task))).json()
    repository=TaskExecutionStore();lease=repository.claim(task['id'],approved['revision'],task_type='analysis_plan')
    store=AnalysisPlanStore(repository);_,checkpoint,_=store.load(lease)
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(task['id'],))
    with pytest.raises(LeaseLost): store.publish(lease,checkpoint)
    assert repository.recover_expired()>=1
    queued=TaskStore(task_owner(client)).get(task['id'])
    assert run_plan(queued)['status']=='succeeded'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans').fetchone()['n']==1
        assert db.execute('SELECT revision FROM analysis_setups').fetchone()['revision']==1


@pytest.mark.parametrize('table',['task_waits','analysis_plan_decisions','confirmed_analysis_plans'])
def test_failed_transaction_keeps_checkpoint_and_retry_is_atomic(client,table):
    base,_,prepared=prepared_sample(client);task,_=create_plan(client,base,prepared)
    if table!='task_waits':
        run_plan(task);view=review_plan(client,task);body=plan_decision(view)
        if table=='confirmed_analysis_plans': task=decide_plan(client,task,body).json()
    with migration_connection(write=True) as db:
        db.execute("CREATE FUNCTION reject_plan_write() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'isolated rollback'; END $$")
        db.execute('CREATE TRIGGER reject_plan_write BEFORE INSERT ON '+table+' FOR EACH ROW EXECUTE FUNCTION reject_plan_write()')
    try:
        if table=='analysis_plan_decisions':
            assert decide_plan(client,task,body).status_code==503
            after=review_plan(client,task)
            assert after['wait_id']==view['wait_id'] and after['checkpoint_id']==view['checkpoint_id']
        else:
            failed=run_plan(task)
            assert failed['status']=='failed' and failed['error_code']=='storage_unavailable'
            with database_connection() as db:
                assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans').fetchone()['n']==0
                assert db.execute('SELECT count(*) AS n FROM analysis_setups').fetchone()['n']==0
    finally:
        with migration_connection(write=True) as db:
            db.execute('DROP TRIGGER reject_plan_write ON '+table);db.execute('DROP FUNCTION reject_plan_write()')
    if table=='analysis_plan_decisions':
        task=decide_plan(client,task,body).json()
    else:
        response=client.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':failed['revision']})
        assert response.status_code==202,response.text
        task=response.json()
    if table=='task_waits':
        assert run_plan(task)['status']=='waiting_confirmation'
        task=decide_plan(client,task,plan_decision(review_plan(client,task))).json()
    assert run_plan(task)['status']=='succeeded'


def test_read_only_audit_includes_approved_plan_and_detects_modified_decision(client):
    from app.maintenance.database_audit import audit_database
    base,_,_,view=confirmed_sample(client)
    assert client.post(base+'/analysis-runs',json={'expected_revision':1}).status_code==200
    with database_connection() as db:
        audit=audit_database(db)
    assert audit['ok'],audit
    assert any(c['table']=='confirmed_analysis_plans' and c['rows']==1 for c in audit['data_checks'])
    with database_connection(write=True) as db:
        db.execute("UPDATE analysis_plan_decisions SET request_digest=%s",('f'*64,))
    with database_connection() as db:
        audit=audit_database(db)
    assert not audit['ok']
    assert any(c['table']=='analysis_plan_decisions' and c['invalid']==1 for c in audit['data_checks'])
