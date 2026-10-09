"""Safe response correlation uses no request paths, queries or research bodies."""
import json
import logging
import subprocess
import sys
import textwrap

import pytest
from starlette.testclient import TestClient

from app.core.request_id import RequestIdMiddleware


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.mark.parametrize('method,suffix,status,operation', [
    ('GET', '/boxplot/disclosure', 200, 'boxplot_disclosure'),
    ('GET', '/explanation/disclosure', 409, 'explanation_disclosure'),
    ('POST', '/boxplot', 422, 'boxplot_submission'),
    ('POST', '/explanation', 200, 'explanation_submission'),
])
def test_task_trace_logs_only_generated_identity_and_fixed_operation(caplog, method, suffix, status, operation):
    async def application(scope, receive, send):
        response = {'ok': True} if status < 400 else {'detail': {'code': 'task_input_invalid', 'message': 'safe'}}
        await send({'type': 'http.response.start', 'status': status,
                    'headers': [(b'content-type', b'application/json')]})
        await send({'type': 'http.response.body', 'body': json.dumps(response).encode()})
    caplog.set_level(logging.INFO, logger='app.core.request_id')
    path = '/api/v1/projects/PRIVATE_PROJECT/files/PRIVATE_FILE/analysis-runs/PRIVATE_RUN' + suffix
    client = TestClient(RequestIdMiddleware(application))
    try:
        response = client.request(method, path + '?q=PRIVATE_QUERY',
            headers={'X-Request-ID': 'PRIVATE_CLIENT_ID'}, content=b'PRIVATE_RESEARCH_BODY')
    finally:
        client.close()
    assert response.status_code == status
    request_id = response.headers['x-request-id']
    records = [record for record in caplog.records if record.name == 'app.core.request_id']
    assert len(records) == 1
    message = records[0].getMessage()
    assert f'request_id={request_id}' in message
    assert f'operation={operation}' in message
    assert f'method={method}' in message and f'status={status}' in message
    assert 'PRIVATE_' not in message


def test_default_uvicorn_configuration_outputs_success_and_failure_once():
    script = textwrap.dedent('''
        import asyncio
        import uvicorn
        from app.core.request_id import RequestIdMiddleware, configure_request_logging
        from app.main import app
        uvicorn.Config(app, access_log=False)
        configure_request_logging()
        configure_request_logging()
        async def application(scope, receive, send):
            await send({'type': 'http.response.start', 'status': scope['test_status'], 'headers': []})
            await send({'type': 'http.response.body', 'body': b''})
        async def send(message):
            pass
        async def receive():
            return {'type': 'http.request', 'body': b''}
        async def run():
            middleware = RequestIdMiddleware(application)
            for status in (200, 409):
                await middleware({'type': 'http', 'method': 'GET', 'test_status': status,
                    'path': '/api/v1/tasks/PRIVATE_TASK', 'query_string': b'q=PRIVATE_QUERY'}, receive, send)
        asyncio.run(run())
    ''')
    child = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, check=True)
    output = child.stdout + child.stderr
    assert output.count('task response request_id=') == 2
    assert 'status=200' in output and 'status=409' in output
    assert 'PRIVATE_' not in output
