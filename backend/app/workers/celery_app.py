"""Celery transport configuration; PostgreSQL remains the only result backend."""
from functools import lru_cache
import logging
import time

from app.core.safe_logging import configure_safe_logging

configure_safe_logging()

from celery import Celery
from celery.exceptions import Reject
from kombu import Exchange, Queue

from app.workers.config import queue_config


logger = logging.getLogger(__name__)


def create_app():
    configure_safe_logging()
    broker, queue_name = queue_config()
    queue = Queue(queue_name, Exchange(queue_name, type='direct', durable=True),
                  routing_key=queue_name, durable=True)
    app = Celery('paperassist', broker=broker, backend=None, set_as_current=False)
    app.conf.update(
        task_queues=(queue,), task_default_queue=queue_name, task_default_exchange=queue_name,
        task_default_routing_key=queue_name, task_default_delivery_mode='persistent',
        task_create_missing_queues=False, task_serializer='json', accept_content=['json'],
        task_ignore_result=True, task_store_errors_even_if_ignored=False,
        task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
        broker_transport_options={'confirm_publish': True, 'read_timeout': 5, 'write_timeout': 5},
        broker_connection_timeout=5, broker_connection_retry_on_startup=True,
        task_publish_retry=False, worker_hijack_root_logger=False,
        worker_redirect_stdouts=False, worker_send_task_events=False,
        task_send_sent_event=False, timezone='UTC', enable_utc=True,
        # RabbitMQ 4.3 forbids transient non-exclusive queues. Control and
        # monitoring queues live only as long as their owning connection.
        control_queue_exclusive=True, event_queue_exclusive=True,
    )

    @app.task(name='paperassist.word_report', ignore_result=True)
    def execute_word(task_id, task_revision):
        # Retain the durable message name so messages already on the broker are
        # accepted; the stored task type now selects Word or explanation work.
        from app.domain.tasks.execution import run_task
        try:
            run_task(task_id, task_revision)
        except Exception:
            # A database outage before claim must leave its message recoverable.
            # Suppress original tracebacks: drivers can include private DSNs/details.
            logger.error('task persistence unavailable task_id=%s', task_id)
            time.sleep(5)
            raise Reject('task_storage_unavailable', requeue=True) from None
    return app


@lru_cache(maxsize=1)
def get_app():
    return create_app()


def publish_confirmed(message, *, app=None):
    app = app or get_app()
    app.send_task('paperassist.word_report', args=[message['task_id'], message['task_revision']],
        task_id=message['id'], queue=app.conf.task_default_queue, serializer='json',
        delivery_mode=2, retry=False, ignore_result=True, confirm_timeout=5)
