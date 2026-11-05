"""Chunk callbacks share a renewal interval, never the final publication fence."""
import pytest
from tests.api.test_research_writing_handoff import client, prepared, publish_candidate


def test_transaction_chunk_progress_coalesces_sql_and_forced_fence_stays_live(client, tmp_path, monkeypatch):
    from app.adapters import task_execution_store
    from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
    base, deliveries, finding = prepared(client)
    published = publish_candidate(client, base, dict(delivery_id=deliveries['sci_draft'],
        finding_version_ids=[finding['id']]), tmp_path)
    response = client.post(base+'/manuscripts/'+published['manuscript_id']+'/versions/1/exports',
        json={}, headers={'Idempotency-Key':'progress-rate'})
    assert response.status_code == 201, response.text
    execution = TaskExecutionStore(); lease = execution.claim(response.json()['task_id'], 1)
    clock = [0.0]
    monkeypatch.setattr(task_execution_store, 'monotonic', lambda: clock[0], raising=False)
    with execution.connection(write=True) as db:
        updates = []; execute = db.execute
        def observed(sql, *args, **kwargs):
            if 'UPDATE task_attempts a SET heartbeat_at' in sql: updates.append(sql)
            return execute(sql, *args, **kwargs)
        monkeypatch.setattr(db, 'execute', observed)
        progress = execution.transaction_progress(db, lease)
        for _ in range(100): progress()
        assert len(updates) == 1
        clock[0] = 1.1; progress()
        assert len(updates) == 2
        execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",
            (lease.task_id,))
        with pytest.raises(LeaseLost): progress(force=True)
