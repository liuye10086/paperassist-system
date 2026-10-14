"""Test-only transport denial and hard exits at the preparation commit windows."""
import os
from pathlib import Path
import re

if (os.environ.get('PAPERASSIST_ENV') != 'test'
        or os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED') != '1'
        or not re.fullmatch(r'pa_test_[0-9a-f]{32}',os.environ.get('PAPERASSIST_DB_SCHEMA',''))):
    raise SystemExit('Preparation crash drill requires an isolated UUID test schema.')

import httpx2
from app.adapters.task_store import TaskStore
from app.workers.__main__ import main

ROOT = Path('/data')
client_init = httpx2.Client.__init__
async_client_init = httpx2.AsyncClient.__init__


def reject_network(request):
    with (ROOT/'.unexpected-preparation-network').open('a',encoding='ascii') as stream:
        stream.write(request.method+'\n')
    raise AssertionError('Local dataset preparation must never use an external provider.')


def isolated_client(self,*args,**kwargs):
    kwargs['transport'] = httpx2.MockTransport(reject_network)
    return client_init(self,*args,**kwargs)


def isolated_async_client(self,*args,**kwargs):
    kwargs['transport'] = httpx2.MockTransport(reject_network)
    return async_client_init(self,*args,**kwargs)


httpx2.Client.__init__ = isolated_client
httpx2.AsyncClient.__init__ = isolated_async_client
append_event = TaskStore.append_event


def crash_before_preparation_commit(db,task,event_type):
    if task['task_type'] == 'prepare_dataset':
        mode = {'preparation-crash-preview':'waiting','preparation-crash-publish':'succeeded'}.get(task['idempotency_key'])
        marker = ROOT/('.preparation-crash-'+task['id'])
        if mode == event_type and not marker.exists():
            with marker.open('w',encoding='ascii') as stream:
                stream.write(event_type)
                stream.flush()
                os.fsync(stream.fileno())
            os._exit(73)
    return append_event(db,task,event_type)


TaskStore.append_event = staticmethod(crash_before_preparation_commit)
if __name__ == '__main__':
    raise SystemExit(main())
