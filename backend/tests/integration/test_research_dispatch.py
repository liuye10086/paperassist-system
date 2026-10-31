"""Public research intents must reach the ordinary outbox and worker entrypoint."""
from tests.api.test_research_writing_handoff import client,prepared


def test_research_outbox_and_generic_worker_execute_candidate(client,tmp_path,monkeypatch):
    from app.workers.dispatcher import dispatch_once
    from app.domain.tasks.execution import run_task
    from app.db.database import database_connection
    base,deliveries,finding=prepared(client)
    report=client.post(base+'/research-reports',json=dict(title='Queue report',finding_version_id=finding['id']),headers={'Idempotency-Key':'queue-report'}).json()
    candidate=client.post(base+'/research-manuscript-candidates',json=dict(delivery_id=deliveries['sci_draft'],finding_version_ids=[finding['id']]),headers={'Idempotency-Key':'queue-candidate'}).json()
    messages=[];dispatch_once(publish=messages.append)
    assert {report['task_id'],candidate['task_id']}<={m['task_id'] for m in messages}
    monkeypatch.setenv('PAPERASSIST_RESEARCH_STAGING_DIR',str(tmp_path/'stage'))
    done=run_task(candidate['task_id'],1)
    assert done is not None and done['status']=='succeeded'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM manuscripts').fetchone()['n']==0
