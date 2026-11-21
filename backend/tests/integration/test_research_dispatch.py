"""Public research intents must reach the ordinary outbox and worker entrypoint."""
from tests.api.test_research_writing_handoff import client,prepared


def test_research_outbox_and_generic_worker_execute_candidate(client,tmp_path,monkeypatch, research_reader_narrative):
    from app.workers.dispatcher import dispatch_once
    from app.domain.tasks.execution import run_task
    from app.db.database import database_connection
    base,deliveries,finding=prepared(client)
    report=client.post(base+'/research-reports',json=dict(title='Queue report',finding_version_id=finding['id'],reader_narrative_id=research_reader_narrative),headers={'Idempotency-Key':'queue-report'})
    candidate=client.post(base+'/research-manuscript-candidates',json=dict(delivery_id=deliveries['sci_draft'],finding_version_ids=[finding['id']]),headers={'Idempotency-Key':'queue-candidate'})
    assert report.status_code == 201, report.text
    assert candidate.status_code == 201, candidate.text
    monkeypatch.setenv('PAPERASSIST_RESEARCH_STAGING_DIR',str(tmp_path/'stage'))
    for artifact, result_key in ((report.json(), 'result_research_report_version_id'),
                                 (candidate.json(), 'result_research_candidate_id')):
        messages = []
        assert dispatch_once(publish=messages.append) == 1
        assert [m['task_id'] for m in messages] == [artifact['task_id']]
        message = messages[0]
        done = run_task(message['task_id'], message['task_revision'])
        assert done is not None and done['status'] == 'succeeded', done
        assert done[result_key] == artifact['id']
    assert dispatch_once(publish=messages.append) == 0
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM manuscripts').fetchone()['n']==0
