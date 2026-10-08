"""Test-only SDK transport and hard-crash hooks, never included in the image."""
from email.parser import BytesParser
from email.policy import default
from io import BytesIO
import json
import os
from pathlib import Path
import re

if (os.environ.get('PAPERASSIST_ENV') != 'test'
        or os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED') != '1'
        or not re.fullmatch(r'pa_test_[0-9a-f]{32}', os.environ.get('PAPERASSIST_DB_SCHEMA', ''))):
    raise SystemExit('Plot bootstrap requires the isolated queue test environment.')

import httpx2
from PIL import Image
from app.adapters.models.openai_plot import OpenAIPlotProvider
from app.db.database import database_connection
from app.domain.boxplot import plot_data
from app.domain.model_usage.gateway import ModelGateway
from app.domain.model_usage.service import ModelUsageService
from app.domain.tasks import boxplot_execution
from app.workers.__main__ import main

ROOT = Path('/data')


def call_task(call_id):
    with database_connection() as db:
        return dict(db.execute('SELECT t.* FROM tasks t JOIN model_calls c ON c.task_id=t.id WHERE c.id=%s',
                               (call_id,)).fetchone())


def container_task(container_id):
    with database_connection() as db:
        return dict(db.execute("SELECT t.* FROM tasks t JOIN model_calls c ON c.task_id=t.id "
                               "WHERE c.provider_state->>'container_id'=%s", (container_id,)).fetchone())


def once_crash(task, mode):
    marker = ROOT / ('.crash-' + task['id'])
    if task['idempotency_key'] == 'plot-queue-' + mode and not marker.exists():
        with marker.open('w', encoding='ascii') as stream:
            stream.write(mode)
            stream.flush()
            os.fsync(stream.fileno())
        os._exit(73)


def log_call(task, action):
    with (ROOT / ('.calls-' + task['id'])).open('a', encoding='ascii') as stream:
        stream.write(action + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def response(task, container_id, pending):
    response_id = 'resp_' + task['id'].replace('-', '')
    return {'id': response_id, 'object': 'response', 'created_at': 1, 'model': 'test-plot',
        'status': 'in_progress' if pending else 'completed', 'output': [] if pending else [
            {'id': 'ci_test', 'type': 'code_interpreter_call', 'status': 'completed',
             'container_id': container_id, 'code': '# synthetic Python', 'outputs': []},
            {'id': 'msg_test', 'type': 'message', 'status': 'completed', 'role': 'assistant',
             'content': [{'type': 'output_text', 'text': 'Synthetic output', 'annotations': [
                 {'type': 'container_file_citation', 'container_id': container_id,
                  'file_id': 'cfile_png', 'filename': '/mnt/data/boxplot.png', 'start_index': 0, 'end_index': 1},
                 {'type': 'container_file_citation', 'container_id': container_id,
                  'file_id': 'cfile_result', 'filename': '/mnt/data/result.json', 'start_index': 0, 'end_index': 1}]}]}],
        'usage': None if pending else {'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30,
            'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}}}


def transport(request):
    assert request.url.host == 'api.openai.com'
    path, method = request.url.path, request.method
    if method == 'POST' and path == '/v1/containers':
        body = json.loads(request.content)
        task = call_task(body['name'].removeprefix('paperassist-'))
        assert body['network_policy'] == {'type': 'disabled'}
        container_id = 'cntr_' + task['id'].replace('-', '')
        data = {'id': container_id, 'object': 'container', 'created_at': 1, 'name': body['name'],
                'status': 'running', 'expires_after': body['expires_after']}
        action, crash = 'POST container', 'container_unknown'
    elif method == 'POST' and path.endswith('/files'):
        container_id = path.split('/')[3]
        task = container_task(container_id)
        parsed = BytesParser(policy=default).parsebytes(
            ('Content-Type: ' + request.headers['content-type'] + '\r\n\r\n').encode() + request.content)
        parts = [part for part in parsed.iter_parts() if part.get_filename() == 'data.json']
        assert len(parts) == 1
        payload = json.loads(parts[0].get_payload(decode=True))
        (ROOT / ('.payload-' + task['id'])).write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        data = {'id': 'cfile_input', 'object': 'container.file', 'created_at': 1,
                'container_id': container_id, 'path': '/mnt/data/cfile_prefix_data.json', 'source': 'user'}
        action, crash = 'POST upload', 'upload_unknown'
    elif method == 'POST' and path == '/v1/responses':
        body = json.loads(request.content)
        container_id = body['tools'][0]['container']
        task = container_task(container_id)
        assert body['background'] and body['store']
        assert '/mnt/data/cfile_prefix_data.json' in body['input']
        data = response(task, container_id, True)
        action, crash = 'POST response', 'response_unknown'
    elif method == 'GET' and path.startswith('/v1/responses/'):
        response_id = path.rsplit('/', 1)[-1]
        with database_connection() as db:
            row = db.execute('SELECT t.*, c.provider_state FROM tasks t JOIN model_calls c ON c.task_id=t.id '
                             'WHERE c.provider_response_id=%s', (response_id,)).fetchone()
        task = dict(row)
        pending = (task['idempotency_key'] == 'plot-queue-normal' and not (ROOT / '.release-plot-normal').exists())
        data = response(task, task['provider_state']['container_id'], pending)
        action, crash = 'GET response', None
    else:
        assert method == 'GET' and path.endswith('/content'), path
        container_id, file_id = path.split('/')[3], path.split('/')[5]
        task = container_task(container_id)
        log_call(task, 'GET ' + file_id)
        if (ROOT / ('.crash-' + task['id'])).exists() and task['idempotency_key'] == 'plot-queue-candidate':
            return httpx2.Response(410, json={'error': {'message': 'Synthetic expired container'}})
        if file_id == 'cfile_png':
            output = BytesIO()
            Image.new('RGB', (1600, 1200), 'white').save(output, format='PNG')
            return httpx2.Response(200, content=output.getvalue())
        assert file_id == 'cfile_result'
        result = task['input_snapshot']['result']
        payload = json.loads((ROOT / ('.payload-' + task['id'])).read_text(encoding='utf-8'))
        groups = {item['label']: item['values'] for item in payload['groups']}
        figure = plot_data(result, payload['values'], groups)
        metrics = ('n', 'mean', 'std', 'min', 'q1', 'median', 'q3', 'max', 'iqr')
        manifest = {'analysis_run_id': result['id'], 'source_sha256': result['source_sha256'], **payload['labels'],
            'overall': {key: result['overall'][key] for key in metrics},
            'groups': [{'label': group['label'], 'statistics': {key: group['statistics'][key] for key in metrics}}
                       for group in result['groups']], 'series': figure['series']}
        return httpx2.Response(200, json=manifest)
    log_call(task, action)
    if crash:
        once_crash(task, crash)
    return httpx2.Response(200, json=data, headers={'x-request-id': 'req_plot_test'})


def provider():
    return OpenAIPlotProvider(api_key='isolated-test-key',
                             http_client=httpx2.Client(transport=httpx2.MockTransport(transport)))


reserve, record_step, record = ModelUsageService.reserve_call, ModelUsageService.record_plot_step, ModelGateway._record
replace = os.replace


def reserve_and_crash(self, request, **kwargs):
    call = reserve(self, request, **kwargs)
    once_crash(call_task(call['id']), 'reserved')
    return call


def step_and_crash(self, call_id, step, **kwargs):
    result = record_step(self, call_id, step, **kwargs)
    once_crash(call_task(call_id), 'container_ready' if step == 'container' else 'upload_ready')
    return result


def record_and_crash(self, call_id, receipt, *, submitted):
    result = record(self, call_id, receipt, submitted=submitted)
    if submitted:
        once_crash(call_task(call_id), 'response_ready')
    return result


def replace_and_crash(source, target):
    result = replace(source, target)
    target = Path(target)
    if target.parent.name == 'figures' and target.suffix == '.png':
        with database_connection() as db:
            task = db.execute("SELECT * FROM tasks WHERE figure_candidate->'figure'->>'id'=%s", (target.stem,)).fetchone()
        if task:
            once_crash(dict(task), 'candidate')
    return result


boxplot_execution.create_provider = provider
ModelUsageService.reserve_call = reserve_and_crash
ModelUsageService.record_plot_step = step_and_crash
ModelGateway._record = record_and_crash
os.replace = replace_and_crash
raise SystemExit(main())
