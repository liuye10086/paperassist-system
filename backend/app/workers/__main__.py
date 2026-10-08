"""Container entry points, with explicit configuration and safe operational logs."""
import argparse
import logging
import os
from pathlib import Path
import signal
import socket
import sys
from threading import Event
import time

from app.workers.config import load_secrets, queue_config


def health_path():
    return Path(os.environ.get('PAPERASSIST_WORKER_HEALTH_FILE', '/tmp/dispatcher-health'))


def dispatch_health():
    try:
        age = time.time() - float(health_path().read_text(encoding='ascii'))
        return 0 <= age < 45
    except (OSError, ValueError):
        return False


def run_dispatcher():
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.workers.dispatcher import dispatch_once
    stopping = Event()
    def stop(*_):
        stopping.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    repository = TaskExecutionStore()
    path = health_path()
    while not stopping.is_set():
        try:
            repository.recover_expired()
            dispatch_once()
            path.write_text(str(time.time()), encoding='ascii')
        except Exception:
            logging.getLogger(__name__).warning('dispatcher storage unavailable; will retry')
        stopping.wait(2)


def main(argv=None):
    parser = argparse.ArgumentParser(description='PaperAssist independent Word and explanation task execution')
    parser.add_argument('command', choices=['worker', 'dispatch', 'health'])
    parser.add_argument('service', nargs='?', choices=['worker', 'dispatch'])
    arguments = parser.parse_args(argv)
    try:
        load_secrets()
        queue_config()
        from app.db.database import database_connection, ensure_schema_current
        with database_connection() as db:
            ensure_schema_current(db)
        if arguments.command == 'health' and arguments.service == 'dispatch':
            return 0 if dispatch_health() else 1
        from app.workers.celery_app import get_app
        app = get_app()
        node = 'celery@' + socket.gethostname()
        if arguments.command == 'health':
            if arguments.service != 'worker':
                return 1
            return 0 if app.control.inspect(destination=[node], timeout=3).ping() else 1
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
        if arguments.command == 'worker':
            # Dispose the startup-check connection before forking child processes.
            from app.db.database import get_engine
            get_engine().dispose()
            app.worker_main(['worker', '--loglevel=WARNING', '--concurrency=1', '--pool=prefork', '--hostname=' + node])
        else:
            run_dispatcher()
        return 0
    except Exception:
        print('Worker configuration or service is unavailable; check private configuration and service health.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
