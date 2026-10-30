"""Same-connection renewal for the three fenced bio task executors only."""


def renew_bio_lease(db,lease):
    from app.adapters.task_execution_store import LEASE_SECONDS,LeaseLost
    updated=db.execute('''UPDATE task_attempts a SET heartbeat_at=clock_timestamp(),
        lease_expires_at=clock_timestamp()+(%s*interval '1 second') FROM tasks t
        WHERE t.id=%s AND t.id=a.task_id AND t.current_attempt=%s AND a.attempt_no=t.current_attempt
          AND t.task_type IN ('bio_import','bio_analysis','bio_figure') AND t.status='running' AND a.status='running'
          AND a.lease_owner=%s AND a.lease_expires_at>clock_timestamp()''',
        (LEASE_SECONDS,lease.task_id,lease.attempt_no,lease.lease_owner))
    if updated.rowcount!=1:raise LeaseLost()
