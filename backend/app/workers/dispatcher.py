"""Transactional outbox publication with bounded retries outside database locks."""
from datetime import timedelta
import logging

from app.adapters.task_execution_store import TaskExecutionStore


logger = logging.getLogger(__name__)


def dispatch_once(*, publish=None, config=None, limit=20):
    repository = TaskExecutionStore(config=config)
    from app.domain.tasks.serial_execution import execution_lock_path, file_lock
    path = execution_lock_path(repository.assets.directory)
    # Publication happens outside DB locks. Keep one host publisher through the
    # broker confirmation and its CAS acknowledgement, including slow confirms.
    with file_lock(path.with_name(path.name + '.dispatch'), blocking=False) as acquired:
        if not acquired:
            return 0
        return _dispatch_once(repository, publish=publish, limit=limit)


def _dispatch_once(repository, *, publish, limit):
    from app.domain.report_collections.service import advance_pending
    advance_pending(config=repository.config, directory=repository.assets.directory, limit=limit)
    if publish is None:
        from app.workers.celery_app import publish_confirmed
        publish = publish_confirmed
    with repository.connection(write=True) as db:
        from app.domain.bioinformatics.analysis_service import expire_stale_confirmations
        expire_stale_confirmations(db)
        from app.domain.bio_cloud.service import recover_receipts
        recover_receipts(db)
        head = repository.serial_head(db)
        rows = [] if head is None or limit <= 0 else db.execute('''
            SELECT o.id,o.task_id,o.task_revision,o.publish_attempts FROM task_outbox o
            JOIN tasks t ON t.id=o.task_id AND t.revision=o.task_revision
            WHERE t.id=%s AND o.published_at IS NULL AND o.event_type='task_ready'
            AND o.available_at<=clock_timestamp() AND (t.status='queued' OR (t.status='running' AND EXISTS (
                SELECT 1 FROM task_attempts a WHERE a.task_id=t.id AND a.attempt_no=t.current_attempt
                AND a.status='running' AND a.lease_owner IS NULL)))
            ORDER BY o.available_at,o.id LIMIT 1''', (head['id'],)).fetchall()
        now = repository.now(db)
        for row in rows:
            delay = min(60, 2 ** min(row['publish_attempts'] + 1, 6))
            db.execute('UPDATE task_outbox SET publish_attempts=publish_attempts+1,available_at=%s WHERE id=%s',
                       (now + timedelta(seconds=delay), row['id']))
    published = 0
    for row in rows:
        message = {key: row[key] for key in ('id', 'task_id', 'task_revision')}
        try:
            publish(message)
        except Exception:
            # Broker exceptions may contain connection credentials; never print them.
            logger.warning('outbox publication unavailable outbox_id=%s', row['id'])
            continue
        with repository.connection(write=True) as db:
            db.execute('''UPDATE task_outbox SET published_at=clock_timestamp()
                WHERE id=%s AND published_at IS NULL AND publish_attempts=%s''',
                       (row['id'], row['publish_attempts'] + 1))
        published += 1
    return published
