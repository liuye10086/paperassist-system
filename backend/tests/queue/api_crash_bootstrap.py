"""Test-owned loopback HTTP process: commit a task, then lose its response."""
import os
from pathlib import Path
import socket
import sys

# Direct-script startup must find app without installing or changing production code.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.queue.delivery_crash_support import durable_marker, require_isolated_test

config, assets = require_isolated_test()
if (os.environ.get('PAPERASSIST_PLOT_WORKER_ENABLED') != '0'
        or any(os.environ.get(key) for key in ('OPENAI_API_KEY', 'OPENAI_API_KEY_FILE',
                    'PAPERASSIST_EXPLANATION_POLICY_FILE', 'PAPERASSIST_PLOT_POLICY_FILE'))):
    raise SystemExit('Crash API must disable cloud keys, policies and legacy scanners.')
request_key = os.environ.get('PAPERASSIST_CRASH_REQUEST_KEY')
address_file = Path(os.environ.get('PAPERASSIST_TEST_API_ADDRESS_FILE', '')).resolve()
if not request_key or address_file.parent != assets:
    raise SystemExit('Crash API requires an isolated marker and explicit request key.')

from app.domain.tasks.service import TaskService

create = TaskService.create


def commit_then_exit(self, project_id, request, **kwargs):
    result = create(self, project_id, request, **kwargs)
    task, created = result
    if created and task['task_type'] == 'word_report' and kwargs['idempotency_key'] == request_key:
        # Original create returned only after its context manager committed.
        durable_marker(assets / '.test-api-crashed.json',
                       {'checkpoint': 'after_task_commit_before_http_response',
                        'task_id': task['id'], 'revision': task['revision'], 'created': created})
        os._exit(74)
    return result


TaskService.create = commit_then_exit
from app.main import app
import uvicorn

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bound:
    bound.bind(('127.0.0.1', 0))
    durable_marker(address_file, {'host': '127.0.0.1', 'port': bound.getsockname()[1],
                                  'pid': os.getpid(), 'parent_pid': os.getppid()})
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=bound.getsockname()[1],
                                          log_level='critical', access_log=False))
    server.run(sockets=[bound])
