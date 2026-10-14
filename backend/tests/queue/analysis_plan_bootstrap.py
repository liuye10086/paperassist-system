"""Isolated plan crash windows and an explicit provider transport denial."""
import os
from pathlib import Path
import re

if (os.environ.get('PAPERASSIST_ENV')!='test' or os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED')!='1'
        or not re.fullmatch(r'pa_test_[0-9a-f]{32}',os.environ.get('PAPERASSIST_DB_SCHEMA',''))):
    raise SystemExit('Plan drill requires an isolated UUID test schema.')

import httpx2
from app.adapters.task_store import TaskStore
from app.workers.__main__ import main

ROOT=Path('/data')
client_init=httpx2.Client.__init__
async_init=httpx2.AsyncClient.__init__


def reject_network(request):
    (ROOT/'.unexpected-plan-network').write_text(request.method,encoding='ascii')
    raise AssertionError('Analysis planning cannot call providers.')


def local_client(self,*args,**kwargs):
    kwargs['transport']=httpx2.MockTransport(reject_network)
    return client_init(self,*args,**kwargs)


def local_async(self,*args,**kwargs):
    kwargs['transport']=httpx2.MockTransport(reject_network)
    return async_init(self,*args,**kwargs)


httpx2.Client.__init__=local_client
httpx2.AsyncClient.__init__=local_async
append_event=TaskStore.append_event


def crash_before_commit(db,task,event_type):
    if task['task_type']=='analysis_plan':
        expected={'plan-crash-wait':'waiting','plan-crash-publish':'succeeded'}.get(task['idempotency_key'])
        marker=ROOT/('.plan-crash-'+task['id'])
        if expected==event_type and not marker.exists():
            with marker.open('w',encoding='ascii') as stream:
                stream.write(event_type);stream.flush();os.fsync(stream.fileno())
            os._exit(73)
    return append_event(db,task,event_type)


TaskStore.append_event=staticmethod(crash_before_commit)
if __name__=='__main__': raise SystemExit(main())
