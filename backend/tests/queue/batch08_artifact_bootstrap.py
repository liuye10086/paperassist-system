"""Mounted test-only SDK transport and real process-death windows; no network."""
import json
import os
from pathlib import Path
import re
from email.parser import BytesParser
from email.policy import default
from io import BytesIO
from threading import local

if (os.environ.get('PAPERASSIST_ENV') != 'test'
        or os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED') != '1'
        or not re.fullmatch(r'pa_test_[0-9a-f]{32}', os.environ.get('PAPERASSIST_DB_SCHEMA', ''))):
    raise SystemExit('Batch08 transport requires the isolated test schema and stack.')

import httpx2
from PIL import Image
from app.adapters.models.openai_plot import OpenAIPlotProvider
from app.adapters.models.openai_responses import OpenAIResponsesProvider
from app.db.database import database_connection
from app.domain.model_usage.gateway import ModelGateway
from app.domain.model_usage.service import ModelUsageService
from app.domain.tasks import boxplot_execution, explanation_execution
from app.domain.figure_workbench import execution
from app.workers.__main__ import main

ROOT = Path('/data')
ACTIVE = local()


def task_for(*, call_id=None, container=None, response=None):
    field, value = ('c.id', call_id) if call_id else (
        ("c.provider_state->>'container_id'", container) if container else ('c.provider_response_id', response))
    with database_connection() as db:
        row = db.execute('SELECT t.*,c.provider_state FROM tasks t JOIN model_calls c ON c.task_id=t.id '
                         'WHERE '+field+'=%s', (value,)).fetchone()
    assert row is not None
    return dict(row)


def log(task, action):
    with (ROOT/('.batch08-calls-'+task['id'])).open('a', encoding='ascii') as stream:
        stream.write(action+'\n'); stream.flush(); os.fsync(stream.fileno())


def crash(task, mode):
    marker = ROOT/('.batch08-crash-'+task['id'])
    if task['idempotency_key'] == 'batch08-'+mode and not marker.exists():
        with marker.open('x', encoding='ascii') as stream:
            stream.write(mode); stream.flush(); os.fsync(stream.fileno())
        os._exit(73)


def plot_response(task, container, pending):
    return {'id':'resp_'+task['id'].replace('-',''), 'object':'response', 'created_at':1,
        'model':'test-plot','status':'in_progress' if pending else 'completed',
        'usage':None if pending else {'input_tokens':10,'output_tokens':20,'total_tokens':30,
            'input_tokens_details':{'cached_tokens':0,'cache_write_tokens':0}},
        'output':[] if pending else [
            {'id':'ci_test','type':'code_interpreter_call','status':'completed','container_id':container,
             'code':'# synthetic queue transport','outputs':[]},
            {'id':'msg_test','type':'message','status':'completed','role':'assistant','content':[
                {'type':'output_text','text':'Synthetic output','annotations':[
                    {'type':'container_file_citation','container_id':container,'file_id':file_id,
                     'filename':'/mnt/data/'+filename,'start_index':0,'end_index':1}
                    for file_id,filename in [('cfile_png','figure.png'),('cfile_result','result.json')]]}]}]}


def plot_transport(request, context):
    assert request.url.host == 'api.openai.com'
    path, method = request.url.path, request.method
    if method == 'POST' and path == '/v1/containers':
        task = task_for(call_id=context['call_id'])
        body = json.loads(request.content)
        assert body['network_policy'] == {'type':'disabled'}
        data = {'id':'cntr_'+task['id'].replace('-',''),'object':'container','created_at':1,
                'name':body['name'],'status':'running','expires_after':body['expires_after']}
        action = 'POST container'
    elif method == 'POST' and path.endswith('/files'):
        container = path.split('/')[3]
        task = task_for(container=container)
        parsed = BytesParser(policy=default).parsebytes(
            ('Content-Type: '+request.headers['content-type']+'\r\n\r\n').encode()+request.content)
        parts = [part for part in parsed.iter_parts() if part.get_filename() == 'data.json']
        assert len(parts) == 1
        payload = json.loads(parts[0].get_payload(decode=True))
        (ROOT/('.batch08-payload-'+task['id'])).write_text(json.dumps(payload), encoding='utf-8')
        data = {'id':'cfile_input','object':'container.file','created_at':1,'container_id':container,
                'path':'/mnt/data/cfile_prefix_data.json','source':'user'}
        action = 'POST upload'
    elif method == 'POST' and path == '/v1/responses':
        body = json.loads(request.content)
        container = body['tools'][0]['container']
        task = task_for(container=container)
        assert body['background'] and body['store']
        data = plot_response(task, container, True)
        log(task, 'POST response')
        crash(task, 'figure-response-unknown')
        return httpx2.Response(200, json=data, headers={'x-request-id':'req_batch08_plot'})
    elif method == 'GET' and path.startswith('/v1/responses/'):
        task = task_for(response=path.rsplit('/',1)[-1])
        data = plot_response(task, task['provider_state']['container_id'], False)
        action = 'GET response'
    else:
        assert method == 'GET' and path.endswith('/content'), (method,path)
        container, file_id = path.split('/')[3], path.split('/')[5]
        task = task_for(container=container)
        log(task, 'GET '+file_id)
        # Once candidate bytes exist and the publisher has crashed, recovery
        # must use those bytes. Any later network access is a test failure.
        if task['idempotency_key']=='batch08-figure-candidate' and (ROOT/('.batch08-crash-'+task['id'])).exists():
            return httpx2.Response(410,json={'error':{'message':'Synthetic expired container'}})
        if file_id == 'cfile_png':
            output=BytesIO();Image.new('RGB',(2400,1600),'white').save(output,format='PNG')
            return httpx2.Response(200,content=output.getvalue())
        assert file_id == 'cfile_result'
        payload=json.loads((ROOT/('.batch08-payload-'+task['id'])).read_text(encoding='utf-8'))
        manifest={key:payload[key] for key in ('schema_version','figure_kind','language','plot_config','presentation')}
        manifest.update(payload['labels'])
        manifest['statistics']={'series':[{'group':None,'points':[
            {'x':float(x),'y':float(y),'n':1,'missing':0} for x,y in [(1,9),(2,8),(3,7),(4,6)]]}]}
        return httpx2.Response(200,json=manifest)
    log(task, action)
    return httpx2.Response(200,json=data,headers={'x-request-id':'req_batch08_plot'})


def explanation_transport(request):
    assert request.url.host == 'api.openai.com'
    if request.method == 'POST':
        task=task_for(call_id=ACTIVE.call_id)
        body=json.loads(request.content);payload=json.loads(body['input'])
        assert body['background'] and body['store']
        (ROOT/('.batch08-explanation-payload-'+task['id'])).write_text(json.dumps(payload),encoding='utf-8')
    else:
        assert request.method == 'GET'
        task=task_for(response=request.url.path.rsplit('/',1)[-1])
        payload=json.loads((ROOT/('.batch08-explanation-payload-'+task['id'])).read_text(encoding='utf-8'))
    log(task,request.method+' explanation')
    pending=request.method=='POST'
    draft={key:'; '.join('{{'+ref+'}}' for ref in refs) for key,refs in payload['required_references'].items()}
    data={'id':'resp_'+task['id'].replace('-',''),'object':'response','created_at':1,'model':'test-plot',
          'status':'in_progress' if pending else 'completed','usage':None if pending else {
              'input_tokens':10,'output_tokens':20,'total_tokens':30,'input_tokens_details':{'cached_tokens':0,'cache_write_tokens':0}},
          'output':[] if pending else [{'id':'msg_test','type':'message','status':'completed','role':'assistant',
              'content':[{'type':'output_text','text':json.dumps(draft),'annotations':[]}]}]}
    if pending:crash(task,'explanation-response-unknown')
    return httpx2.Response(200,json=data,headers={'x-request-id':'req_batch08_explanation'})


def plot_provider():
    context={}
    provider=OpenAIPlotProvider(api_key='isolated-test-key',http_client=httpx2.Client(
        transport=httpx2.MockTransport(lambda request:plot_transport(request,context))))
    create=provider.create_container
    def create_container(*,policy,call_id):
        context['call_id']=call_id
        return create(policy=policy,call_id=call_id)
    provider.create_container=create_container
    return provider


def explanation_provider():
    return OpenAIResponsesProvider(api_key='isolated-test-key',http_client=httpx2.Client(
        transport=httpx2.MockTransport(explanation_transport)))


reserve=ModelUsageService.reserve_call
record=ModelGateway._record
publish=execution._publish_figure
def reserve_call(self,request,**kwargs):
    result=reserve(self,request,**kwargs);ACTIVE.call_id=result['id'];return result
def record_receipt(self,call_id,receipt,*,submitted):
    result=record(self,call_id,receipt,submitted=submitted)
    if submitted:
        task=task_for(call_id=call_id)
        crash(task,'figure-response-saved');crash(task,'explanation-response-saved')
    return result
def publish_figure(repository,lease,store,figure):
    with repository.connection() as db:task=dict(repository.require_lease(db,lease))
    crash(task,'figure-candidate')
    return publish(repository,lease,store,figure)

ModelUsageService.reserve_call=reserve_call
ModelGateway._record=record_receipt
execution._publish_figure=publish_figure
boxplot_execution.create_provider=plot_provider
explanation_execution.create_provider=explanation_provider

if __name__=='__main__':raise SystemExit(main())
