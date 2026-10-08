"""Transactional outbox publication with bounded retries outside database locks."""
from datetime import timedelta
import logging

from app.adapters.task_execution_store import TaskExecutionStore


logger = logging.getLogger(__name__)


def dispatch_once(*, publish=None, config=None, limit=20):
    repository = TaskExecutionStore(config=config)
    if publish is None:
        from app.workers.celery_app import publish_confirmed
        publish = publish_confirmed
    with repository.connection(write=True) as db:
        rows = db.execute('''SELECT o.id,o.task_id,o.task_revision,o.publish_attempts FROM task_outbox o
            JOIN tasks t ON t.id=o.task_id WHERE o.published_at IS NULL
            AND o.available_at<=clock_timestamp() AND t.task_type IN ('word_report','explanation','boxplot')
            ORDER BY o.available_at,o.id LIMIT %s''', (limit,)).fetchall()
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
            db.execute('UPDATE task_outbox SET published_at=clock_timestamp() WHERE id=%s AND published_at IS NULL',
                       (row['id'],))
        published += 1
    return published
