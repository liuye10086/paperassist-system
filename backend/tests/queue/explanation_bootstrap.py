"""Test-only, mounted entry point: official SDK with an in-memory transport.

The production image never includes this module. No request can leave MockTransport.
"""
import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone
from threading import local

if (os.environ.get('PAPERASSIST_ENV') != 'test'
        or os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED') != '1'
        or not re.fullmatch(r'pa_test_[0-9a-f]{32}', os.environ.get('PAPERASSIST_DB_SCHEMA', ''))):
    raise SystemExit('Explanation bootstrap requires the isolated queue test environment.')

import httpx2
from app.adapters.models.openai_responses import OpenAIResponsesProvider
from app.db.database import database_connection
from app.domain.external_material import explanation_material
from app.domain.model_usage.gateway import ModelGateway
from app.domain.model_usage.service import ModelUsageService
from app.domain.tasks import explanation_execution
from app.workers.__main__ import main

ROOT = Path('/data')
ACTIVE_CALL = local()


def call_task(call_id):
    with database_connection() as db:
        return dict(db.execute('SELECT t.* FROM tasks t JOIN model_calls c ON c.task_id=t.id WHERE c.id=%s',
                               (call_id,)).fetchone())


def once_crash(task, mode):
    marker = ROOT / ('.crash-' + task['id'])
    if task['idempotency_key'] == 'queue-' + mode and not marker.exists():
        marker.write_text(mode, encoding='ascii')
        os._exit(73)


def transport(request):
    assert request.url.host == 'api.openai.com'
    if request.method == 'POST':
        body = json.loads(request.content)
        payload = json.loads(body['input'])
        assert body['background'] and body['store']
        assert body['text']['format']['strict']
        # The production payload no longer contains internal source identifiers.
        # Associate the synthetic receipt using this worker's local reserve hook.
        task = call_task(ACTIVE_CALL.call_id)
        response_id = 'resp_' + task['id'].replace('-', '')
    else:
        assert request.method == 'GET'
        response_id = request.url.path.rsplit('/', 1)[-1]
        with database_connection() as db:
            task = dict(db.execute('SELECT t.* FROM tasks t JOIN model_calls c ON c.task_id=t.id '
                                   'WHERE c.provider_response_id=%s', (response_id,)).fetchone())
        snapshot = task['input_snapshot']
        _, payload = explanation_material(snapshot['result'], snapshot['figure'],
                                          snapshot.get('external_processing'))
    log = ROOT / ('.calls-' + task['id'])
    with log.open('a', encoding='ascii') as stream:
        stream.write(request.method + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    if task['idempotency_key'] == 'queue-finite-retry' and request.method == 'GET':
        with (ROOT / ('.retry-times-' + task['id'])).open('a', encoding='ascii') as stream:
            stream.write(datetime.now(timezone.utc).isoformat() + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        if not (ROOT / '.release-finite-retry').exists():
            return httpx2.Response(503, json={'error': {'message': 'Synthetic temporary failure'}})
    # Keep the normal task pending so a queued Word export can prove fairness.
    pending = request.method == 'POST' or (task['idempotency_key'] == 'queue-normal'
                                          and not (ROOT / '.release-normal').exists())
    draft = {key: '依据' + '、'.join('{{' + ref + '}}' for ref in refs) + '进行描述。'
             for key, refs in payload['required_references'].items()}
    data = {'id': response_id, 'object': 'response', 'created_at': 1,
            'model': 'test-model', 'status': 'in_progress' if pending else 'completed',
            'output': [] if pending else [{'id': 'msg_test', 'type': 'message', 'role': 'assistant',
                'status': 'completed', 'content': [{'type': 'output_text',
                'text': json.dumps(draft, ensure_ascii=False), 'annotations': []}]}],
            'usage': None if pending else {'input_tokens': 10,
                'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0},
                'output_tokens': 20, 'total_tokens': 30}}
    if request.method == 'POST':
        once_crash(task, 'unknown')
    return httpx2.Response(200, json=data, headers={'x-request-id': 'req_test'})


def provider():
    return OpenAIResponsesProvider(api_key='isolated-test-key',
                                   http_client=httpx2.Client(transport=httpx2.MockTransport(transport)))


reserve = ModelUsageService.reserve_call
record = ModelGateway._record


def reserve_and_crash(self, request, **kwargs):
    call = reserve(self, request, **kwargs)
    ACTIVE_CALL.call_id = call['id']
    once_crash(call_task(call['id']), 'reserved')
    return call


def record_and_crash(self, call_id, receipt, *, submitted):
    result = record(self, call_id, receipt, submitted=submitted)
    if submitted:
        once_crash(call_task(call_id), 'receipt')
    return result


explanation_execution.create_provider = provider
ModelUsageService.reserve_call = reserve_and_crash
ModelGateway._record = record_and_crash
raise SystemExit(main())
