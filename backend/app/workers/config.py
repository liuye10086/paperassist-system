"""Queue/database startup configuration; model secrets are read lazily by explanations."""
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from app.db.database import get_database_config


def concurrency_ceiling():
    """Deployment must explicitly allow a second process; old environments keep one."""
    from app.core.config import local_config
    value = local_config().get('PAPERASSIST_WORKER_CONCURRENCY_CEILING', '1')
    if value not in ('1', '2'):
        raise ValueError('Worker concurrency ceiling must be 1 or 2.')
    return int(value)


def startup_configuration(db=None):
    from uuid import uuid4
    from app.db.database import database_connection
    from app.domain.admin_configuration.bindings import current
    if db is None:
        with database_connection() as connection:
            return startup_configuration(connection)
    version = current(db)
    desired = version['bundle']['basic'].get('worker_concurrency', 1) if version else 1
    if type(desired) is not int or desired not in (1, 2):
        raise ValueError('Worker concurrency configuration is invalid.')
    return dict(concurrency=min(desired, concurrency_ceiling()), startup_id=str(uuid4()),
                configuration_id=version['id'] if version else None,
                configuration_sha256=version['sha256'] if version else None)


def load_secrets():
    for key in ('PAPERASSIST_BROKER_URL', 'PAPERASSIST_DATABASE_URL', 'PAPERASSIST_TEST_DATABASE_URL'):
        path = os.environ.get(key + '_FILE')
        if path:
            try:
                value = Path(path).read_text(encoding='utf-8-sig').strip()
            except (OSError, UnicodeError) as exc:
                raise ValueError('Worker secret configuration is unavailable.') from exc
            if not value or '\n' in value or '\r' in value:
                raise ValueError('Worker secret configuration is invalid.')
            os.environ[key] = value


def queue_config():
    config = get_database_config()
    broker = os.environ.get('PAPERASSIST_BROKER_URL', '')
    queue = os.environ.get('PAPERASSIST_TASK_QUEUE', 'paperassist.word')
    try:
        url = urlsplit(broker)
        valid = (url.scheme in ('amqp', 'amqps') and url.hostname and url.username and url.password
                 and url.path and not url.query and not url.fragment and url.port != 0)
    except (TypeError, ValueError):
        valid = False
    if not valid or any(char.isspace() for char in broker):
        raise ValueError('An explicit RabbitMQ URL is required.')
    if not re.fullmatch(r'paperassist\.[a-z0-9_.-]{1,100}', queue):
        raise ValueError('Worker queue name is invalid.')
    if config.environment == 'test':
        if os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED') != '1' or not queue.startswith('paperassist.test.'):
            raise ValueError('Real test queues require explicit opt-in and an isolated queue name.')
    elif queue.startswith('paperassist.test.'):
        raise ValueError('A test queue cannot use a development database.')
    return broker, queue
