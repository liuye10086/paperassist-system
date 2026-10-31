"""Keep deterministic storage failures fenced across rollback of publication."""
from contextlib import contextmanager
from app.adapters.task_execution_store import LeaseLost
from app.adapters.task_store import TaskStore
from app.core.exceptions import StorageError


class PublicationFailed(Exception):
    def __init__(self,task):
        self.task=task
        super().__init__(task['error_code'])


@contextmanager
def publication_transaction(execution,lease):
    failed=None
    with execution.connection(write=True) as db:
        execution.require_lease(db,lease)
        progress=execution.transaction_progress(db,lease)
        db.execute('SAVEPOINT local_publication')
        try:
            yield db,progress
        except StorageError as exc:
            if exc.code not in ('storage_quota_exceeded','storage_disk_insufficient'):raise
            # Save only a renewal actually granted to this still-live attempt.
            # Roll back all partial business records before restoring that exact
            # deadline. Never replace an expired deadline with a new one.
            renewed=progress.renewed
            db.execute('ROLLBACK TO SAVEPOINT local_publication')
            db.execute('RELEASE SAVEPOINT local_publication')
            result=db.execute("""UPDATE task_attempts a SET heartbeat_at=%s,lease_expires_at=%s FROM tasks t
                WHERE t.id=%s AND t.id=a.task_id AND t.current_attempt=%s AND a.attempt_no=t.current_attempt
                AND t.status='running' AND a.status='running' AND a.lease_owner=%s
                AND %s>clock_timestamp()""",(renewed['heartbeat_at'],renewed['lease_expires_at'],
                lease.task_id,lease.attempt_no,lease.lease_owner,renewed['lease_expires_at']))
            if result.rowcount!=1:raise LeaseLost()
            # A complete local candidate may already have durable journal bytes.
            # Reconcile them under the same fence; retain them for explicit retry.
            from app.domain.storage_governance.service import reconcile_intents
            unresolved=reconcile_intents(db,execution.assets.directory,progress=progress)
            task=execution.require_lease(db,lease)
            execution._finish(db,task,'failed','storage_accounting_unknown' if unresolved else exc.code)
            failed=TaskStore.public_task(task)
        else:
            db.execute('RELEASE SAVEPOINT local_publication')
    if failed is not None:raise PublicationFailed(failed)
