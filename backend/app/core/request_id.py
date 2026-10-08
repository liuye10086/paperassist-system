"""Bounded tracing for the unified task API, preserving older API contracts."""
import json
import re
from uuid import uuid4

from app.core.errors import INTERNAL_MESSAGE, error_detail


class RequestIdMiddleware:
    # Public error envelopes are small; never collect arbitrary streaming bodies.
    MAX_ERROR_BYTES = 64 * 1024

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        task_api = path == '/api/v1/tasks' or path.startswith('/api/v1/tasks/')
        model_usage_api = re.fullmatch(r'/api/v1/projects/[^/]+/model-usage/?', path)
        project_tasks_api = re.fullmatch(r'/api/v1/projects/[^/]+/tasks/?', path)
        word_submission = scope.get('method') == 'POST' and re.fullmatch(
            r'/api/v1/projects/[^/]+/files/[^/]+/analysis-runs/[^/]+/report/?', path)
        if scope['type'] != 'http' or not (task_api or word_submission or model_usage_api or project_tasks_api):
            await self.app(scope, receive, send)
            return

        request_id = uuid4().hex
        scope.setdefault('state', {})['request_id'] = request_id
        start = None
        body = bytearray()
        discard_body = False

        async def send_error(payload):
            nonlocal start
            detail = payload['detail']
            detail['request_id'] = request_id
            detail['details'] = {}
            encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            headers = [(name, value) for name, value in start['headers'] if name.lower() != b'content-length']
            headers.append((b'content-length', str(len(encoded)).encode('ascii')))
            await send({**start, 'headers': headers})
            await send({'type': 'http.response.body', 'body': encoded})
            start = None

        async def traced_send(message):
            nonlocal start, discard_body
            if message['type'] == 'http.response.start':
                headers = [(name, value) for name, value in message.get('headers', [])
                           if name.lower() != b'x-request-id']
                headers.append((b'x-request-id', request_id.encode('ascii')))
                message = {**message, 'headers': headers}
                header_map = {name.lower(): value.lower() for name, value in headers}
                is_json = header_map.get(b'content-type', b'').split(b';', 1)[0].strip() == b'application/json'
                if (message['status'] >= 400 and is_json
                        and b'content-disposition' not in header_map and b'content-encoding' not in header_map):
                    start = message
                    return
            elif message['type'] == 'http.response.body':
                if discard_body:
                    return
                if start is not None:
                    chunk = message.get('body', b'')
                    if len(body) + len(chunk) > self.MAX_ERROR_BYTES:
                        # A malformed downstream error must not exhaust memory or expose its body.
                        start['status'] = 500
                        await send_error({'detail': error_detail('internal_error', INTERNAL_MESSAGE)})
                        body.clear()
                        discard_body = True
                        return
                    body.extend(chunk)
                    if not message.get('more_body', False):
                        try:
                            payload = json.loads(body)
                            if not isinstance(payload, dict) or not isinstance(payload.get('detail'), dict):
                                raise ValueError('Invalid public error envelope')
                        except (ValueError, UnicodeDecodeError):
                            start['status'] = 500
                            payload = {'detail': error_detail('internal_error', INTERNAL_MESSAGE)}
                        await send_error(payload)
                        body.clear()
                    return
            await send(message)

        await self.app(scope, receive, traced_send)
