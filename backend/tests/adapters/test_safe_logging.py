"""Synthetic SDK calls only: no database, API credentials, or network sockets."""
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace

import httpx2
from openai import APIConnectionError, APITimeoutError, BadRequestError, InternalServerError, OpenAI, RateLimitError
import pytest

from app.core.safe_logging import configure_safe_logging


NAMESPACES = ('openai', 'httpx2', 'httpx', 'httpcore')
SENTINELS = ('SYNTHETIC_KEY_918', 'SYNTHETIC_INPUT_918', 'SYNTHETIC_URL_918',
             'SYNTHETIC_HEADER_918', 'SYNTHETIC_PROVIDER_BODY_918', 'SYNTHETIC_REQUEST_ID_918')


@pytest.fixture(autouse=True)
def postgres_schema():
    # This module exercises logging and MockTransport only; do not create a schema.
    yield None


@pytest.fixture(autouse=True)
def no_network_and_restore_logging(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Network sockets are forbidden in safe logging tests.')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    for name in NAMESPACES:
        logging.getLogger(name)
    saved = {name: (logger.level, logger.disabled) for name, logger in
             logging.Logger.manager.loggerDict.copy().items()
             if isinstance(logger, logging.Logger) and is_vendor(name)}
    yield
    for name, logger in logging.Logger.manager.loggerDict.copy().items():
        if isinstance(logger, logging.Logger) and is_vendor(name):
            logger.setLevel(saved.get(name, (logging.NOTSET, False))[0])
            logger.disabled = saved.get(name, (logging.NOTSET, False))[1]


def is_vendor(name):
    return any(name == namespace or name.startswith(namespace + '.') for namespace in NAMESPACES)


def sdk_response():
    return {'id': 'resp_synthetic', 'object': 'response', 'created_at': 1,
            'model': 'synthetic-model', 'status': 'queued', 'output': [], 'usage': None}


@pytest.mark.parametrize('kind', ['success', '400', '429', '500', 'timeout'])
def test_real_sdk_details_never_reach_caplog_stdout_or_stderr(kind, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    for name in (*NAMESPACES, 'openai._base_client', 'httpcore.http11'):
        logging.getLogger(name).setLevel(logging.DEBUG)
    configure_safe_logging()
    calls = []

    def transport(request):
        calls.append(request)
        assert request.url.host == 'api.openai.com'
        assert b'SYNTHETIC_INPUT_918' in request.content
        if kind == 'timeout':
            raise httpx2.ReadTimeout('SYNTHETIC_PROVIDER_BODY_918', request=request)
        status = 200 if kind == 'success' else int(kind)
        data = sdk_response() if status == 200 else {'error': {'message': 'SYNTHETIC_PROVIDER_BODY_918'}}
        return httpx2.Response(status, json=data,
                              headers={'x-request-id': 'SYNTHETIC_REQUEST_ID_918\nforged=true',
                                       'x-synthetic': 'SYNTHETIC_HEADER_918'})

    with httpx2.Client(transport=httpx2.MockTransport(transport)) as http_client:
        client = OpenAI(api_key='SYNTHETIC_KEY_918', http_client=http_client, max_retries=0)
        try:
            client.responses.create(model='synthetic-model', input='SYNTHETIC_INPUT_918',
                                    extra_query={'marker': 'SYNTHETIC_URL_918'})
        except Exception as exc:
            assert kind != 'success'
            expected = {'400': BadRequestError, '429': RateLimitError,
                        '500': InternalServerError, 'timeout': APITimeoutError}
            assert isinstance(exc, expected[kind])
            logging.getLogger('app.synthetic').warning('model request failed request_id=%s error_type=%s',
                                                       'server-generated-id', type(exc).__name__)
        else:
            assert kind == 'success'
            logging.getLogger('app.synthetic').info('model request completed request_id=%s', 'server-generated-id')
        finally:
            client.close()
    assert len(calls) == 1
    # Trace class used by httpcore; MockTransport does not open HTTP connections.
    from httpcore._trace import Trace
    with Trace('receive_response_headers', logging.getLogger('httpcore.http11')) as trace:
        trace.return_value = (b'HTTP/1.1', 200, b'OK', [(b'x-synthetic', b'SYNTHETIC_HEADER_918')])
    output = capsys.readouterr()
    observed = caplog.text + output.out + output.err
    for marker in SENTINELS:
        assert marker not in observed
    assert 'server-generated-id' in observed


def test_existing_and_late_vendor_children_are_quiet_initialization_is_idempotent(caplog):
    caplog.set_level(logging.DEBUG)
    existing = [logging.getLogger(name + '.synthetic_existing') for name in NAMESPACES]
    for logger in existing:
        logger.setLevel(logging.DEBUG)
    root = logging.getLogger()
    handlers = root.handlers[:]
    configure_safe_logging()
    configure_safe_logging()
    for name in NAMESPACES:
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
        logger = logging.getLogger(name + '.synthetic_late')
        logger.debug('SYNTHETIC_HEADER_918')
        logger.info('SYNTHETIC_URL_918')
    for logger in existing:
        assert logger.getEffectiveLevel() >= logging.WARNING
        logger.debug('SYNTHETIC_HEADER_918')
    logging.getLogger('app.synthetic').warning('worker failed task_id=%s', 'server-task-id')
    assert root.handlers == handlers
    assert 'worker failed task_id=server-task-id' in caplog.text
    assert 'SYNTHETIC_' not in caplog.text


SUBPROCESS = r'''
import importlib.util
import logging
import socket
import sys
def forbidden(*args, **kwargs):
    raise AssertionError('Network sockets are forbidden.')
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.create_connection = forbidden
socket.getaddrinfo = forbidden
root = logging.getLogger()
root.setLevel(logging.DEBUG)
root.addHandler(logging.StreamHandler(sys.stdout))
root.addHandler(logging.StreamHandler(sys.stderr))
if sys.argv[1] == 'sdk_first':
    import openai
from app.core.safe_logging import configure_safe_logging
configure_safe_logging()
import openai
import httpx2
def transport(request):
    return httpx2.Response(200, json={'id': 'resp_synthetic', 'object': 'response',
        'model': 'synthetic-model', 'status': 'queued', 'created_at': 1, 'output': [], 'usage': None},
        headers={'x-request-id': 'SYNTHETIC_REQUEST_ID_918\nforged=true',
                 'x-synthetic': 'SYNTHETIC_HEADER_918'})
with httpx2.Client(transport=httpx2.MockTransport(transport)) as transport_client:
    with openai.OpenAI(api_key='SYNTHETIC_KEY_918', http_client=transport_client, max_retries=0) as client:
        client.responses.create(model='synthetic-model', input='SYNTHETIC_INPUT_918',
                                extra_query={'marker': 'SYNTHETIC_URL_918'})
logging.getLogger('app.synthetic').warning('model request completed request_id=server-generated-id')
'''


@pytest.mark.parametrize('order', ['sdk_first', 'logging_first'])
@pytest.mark.parametrize('openai_log', ['debug', 'info'])
def test_root_debug_and_openai_log_import_order_is_safe(order, openai_log):
    environment = {**os.environ, 'OPENAI_LOG': openai_log,
                   'OPENAI_API_KEY': 'SYNTHETIC_KEY_918',
                   'PYTHONPATH': str(Path(__file__).parents[2])}
    result = subprocess.run([sys.executable, '-c', SUBPROCESS, order], env=environment,
                            cwd=Path(__file__).parents[2], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    for output in (result.stdout, result.stderr):
        assert 'model request completed request_id=server-generated-id' in output
        for marker in SENTINELS:
            assert marker not in output


def test_responses_provider_constructor_restores_policy_and_sanitizes_error(caplog):
    from app.adapters.models.openai_responses import ModelProviderError, OpenAIResponsesProvider
    caplog.set_level(logging.DEBUG)
    for name in (*NAMESPACES, 'openai._base_client'):
        logging.getLogger(name).setLevel(logging.DEBUG)

    def handler(request):
        return httpx2.Response(400, json={'error': {'message': 'SYNTHETIC_PROVIDER_BODY_918'}},
                              headers={'x-request-id': 'SYNTHETIC_REQUEST_ID_918\nforged=true'})

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as http_client:
        provider = OpenAIResponsesProvider(api_key='SYNTHETIC_KEY_918', http_client=http_client)
        try:
            with pytest.raises(ModelProviderError) as error:
                provider.create(policy=SimpleNamespace(tools=[], model='synthetic-model', max_output_tokens=20,
                                                        timeout_seconds=2, output_format='text'),
                                instructions='fixed synthetic instructions', payload={'label': 'SYNTHETIC_INPUT_918'})
            assert error.value.request_id is None
            assert error.value.status_code == 400
            assert 'SYNTHETIC_' not in str(error.value)
        finally:
            provider.close()
    assert 'SYNTHETIC_' not in caplog.text


def test_legacy_explanation_constructor_restores_policy(monkeypatch, caplog):
    from app.adapters import openai_explanation
    caplog.set_level(logging.DEBUG)
    for name in (*NAMESPACES, 'openai._base_client'):
        logging.getLogger(name).setLevel(logging.DEBUG)
    monkeypatch.setattr(openai_explanation, 'configuration', lambda: {'configured': True, 'model': 'synthetic-model'})
    monkeypatch.setattr(openai_explanation, 'local_config', lambda: {'OPENAI_API_KEY': 'SYNTHETIC_KEY_918'})

    def handler(request):
        return httpx2.Response(200, json=sdk_response(),
                              headers={'x-request-id': 'SYNTHETIC_REQUEST_ID_918\nforged=true'})

    def factory(**kwargs):
        return OpenAI(**kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))

    monkeypatch.setattr(openai_explanation, 'OpenAI', factory)
    assert openai_explanation.CloudExplanation().start({'label': 'SYNTHETIC_INPUT_918'}) == 'resp_synthetic'
    assert 'SYNTHETIC_' not in caplog.text


def test_legacy_plot_constructor_restores_policy(monkeypatch, caplog):
    from app.adapters import openai_plot
    caplog.set_level(logging.DEBUG)
    for name in (*NAMESPACES, 'openai._base_client'):
        logging.getLogger(name).setLevel(logging.DEBUG)
    monkeypatch.setattr(openai_plot, 'configuration', lambda: {'configured': True, 'model': 'synthetic-model'})
    monkeypatch.setattr(openai_plot, 'local_config', lambda: {'OPENAI_API_KEY': 'SYNTHETIC_KEY_918'})

    def handler(request):
        return httpx2.Response(200, json=sdk_response(),
                              headers={'x-request-id': 'SYNTHETIC_REQUEST_ID_918\nforged=true'})

    monkeypatch.setattr(openai_plot, 'OpenAI', lambda **kwargs: OpenAI(
        **kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))))
    provider = openai_plot.CloudPlot()
    try:
        provider.client.responses.retrieve('resp_synthetic')
    finally:
        provider.client.close()
    assert 'SYNTHETIC_' not in caplog.text


@pytest.mark.parametrize('entry', ['app.main', 'app.workers.__main__', 'app.workers.celery_app'])
def test_api_and_worker_imports_apply_policy_without_starting_services(entry):
    # Substitute the entry import for explicit setup. Config is synthetic and no
    # ASGI lifespan/worker main/queue creation is invoked; socket use is forbidden.
    initialization = """import openai
import app.core.config
app.core.config.local_config = lambda: {'PAPERASSIST_ENV': 'test'}
importlib.import_module(sys.argv[1])
"""
    script = SUBPROCESS.replace("from app.core.safe_logging import configure_safe_logging\n"
                                "configure_safe_logging()\n", initialization)
    result = subprocess.run([sys.executable, '-c', script, entry],
                            env={**os.environ, 'OPENAI_LOG': 'debug',
                                 'PYTHONPATH': str(Path(__file__).parents[2])},
                            cwd=Path(__file__).parents[2], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'model request completed request_id=server-generated-id' in result.stdout
    for marker in SENTINELS:
        assert marker not in result.stdout + result.stderr


def test_download_stream_failure_is_quiet_and_app_summary_is_preserved(caplog, capsys):
    caplog.set_level(logging.DEBUG)
    for name in (*NAMESPACES, 'openai._base_client'):
        logging.getLogger(name).setLevel(logging.DEBUG)
    configure_safe_logging()

    class BrokenStream(httpx2.SyncByteStream):
        def __iter__(self):
            yield b'SYNTHETIC_PROVIDER_BODY_918'
            raise httpx2.ReadError('SYNTHETIC_HEADER_918 SYNTHETIC_KEY_918')

    def handler(request):
        return httpx2.Response(200, stream=BrokenStream(),
                              headers={'x-request-id': 'SYNTHETIC_REQUEST_ID_918\nforged=true'})

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as http_client:
        with OpenAI(api_key='SYNTHETIC_KEY_918', http_client=http_client, max_retries=0) as client:
            with pytest.raises(APIConnectionError):
                client.containers.files.content.retrieve(file_id='file_synthetic', container_id='cntr_synthetic')
    logging.getLogger('app.synthetic').warning('model download failed request_id=server-generated-id')
    output = capsys.readouterr()
    observed = caplog.text + output.out + output.err
    assert 'model download failed request_id=server-generated-id' in observed
    for marker in SENTINELS:
        assert marker not in observed
