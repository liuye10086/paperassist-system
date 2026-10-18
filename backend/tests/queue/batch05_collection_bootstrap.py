"""Opt-in isolated Linux collection worker observability and single crash window."""
import json
import os
from pathlib import Path
import re
import sys

if (sys.platform != 'linux' or os.environ.get('PAPERASSIST_ENV') != 'test'
        or os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED') != '1'
        or not re.fullmatch(r'pa_test_[0-9a-f]{32}',os.environ.get('PAPERASSIST_DB_SCHEMA',''))):
    raise SystemExit('Batch05 collection bootstrap requires an isolated Linux test schema.')

from app.adapters.task_store import TaskStore
from app.workers.__main__ import main
import httpx2

ROOT=Path('/data')
original_client=httpx2.Client.__init__
original_async=httpx2.AsyncClient.__init__

def reject(request):
    with (ROOT/'.batch05-unexpected-network').open('a',encoding='ascii') as output:output.write(request.method+'\n')
    raise AssertionError('Local collection Word must not contact a model provider.')

def guarded_client(self,*args,**kwargs):
    kwargs['transport']=httpx2.MockTransport(reject)
    return original_client(self,*args,**kwargs)

def guarded_async(self,*args,**kwargs):
    kwargs['transport']=httpx2.MockTransport(reject)
    return original_async(self,*args,**kwargs)

httpx2.Client.__init__=guarded_client
httpx2.AsyncClient.__init__=guarded_async
append_event=TaskStore.append_event

def observed_event(db,task,event_type):
    if task['task_type']=='collection_word_report':
        snapshot=task['input_snapshot']
        with (ROOT/'.batch05-linux-events.jsonl').open('a',encoding='utf-8') as output:
            output.write(json.dumps({'task_id':task['id'],'event':event_type,'attempt':task['current_attempt'],
                'platform':sys.platform,'export_revision':snapshot['export_revision']})+'\n')
            output.flush();os.fsync(output.fileno())
        marker=ROOT/('.batch05-crash-'+task['id'])
        if event_type=='succeeded' and snapshot['export_revision']==2 and not marker.exists():
            marker.write_text('after Word file creation, before publication transaction commit',encoding='ascii')
            os._exit(73)
    return append_event(db,task,event_type)

TaskStore.append_event=staticmethod(observed_event)
if __name__=='__main__':raise SystemExit(main())
