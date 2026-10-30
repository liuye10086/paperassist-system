"""Bounded tracing and fail-open safe operational events for all API requests."""
from datetime import datetime, timezone
import json
import logging
import re
import time
from uuid import uuid4

from app.core.errors import INTERNAL_MESSAGE, error_detail

logger = logging.getLogger(__name__)


def configure_request_logging():
    """Keep bounded request traces visible when Uvicorn access logging is off."""
    logger.setLevel(logging.INFO)
    if not logger.hasHandlers():
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(levelname)s %(message)s'))
        logger.addHandler(handler)


class RequestIdMiddleware:
    # Public error envelopes are small; never collect arbitrary streaming bodies.
    MAX_ERROR_BYTES = 64 * 1024

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        model_usage_api = re.fullmatch(r'/api/v1/projects/[^/]+/model-usage/?', path)
        project_tasks_api = re.fullmatch(r'/api/v1/projects/[^/]+/tasks/?', path)
        task_submission = scope.get('method') == 'POST' and re.fullmatch(
            r'/api/v1/projects/[^/]+/files/[^/]+/analysis-runs/[^/]+/(report|boxplot|explanation)/?', path)
        disclosure_api = re.fullmatch(
            r'/api/v1/projects/[^/]+/files/[^/]+/analysis-runs/[^/]+/(boxplot|explanation)/disclosure/?', path)
        if scope['type'] != 'http' or not path.startswith('/api/'):
            await self.app(scope, receive, send)
            return

        request_id = uuid4().hex
        began=time.monotonic()
        created_at=datetime.now(timezone.utc)
        scope.setdefault('state', {})['request_id'] = request_id
        start = None
        body = bytearray()
        discard_body = False
        operation = (disclosure_api.group(1) + '_disclosure' if disclosure_api else
                     task_submission.group(1) + '_submission' if task_submission else
                     'model_usage' if model_usage_api else 'project_tasks' if project_tasks_api else 'task')
        method = scope.get('method')
        if method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'):
            method = 'OTHER'
        response_status=500
        error_code=None
        candidate_body=bytearray()
        candidate_overflow=False
        candidate_json=False
        task_candidate=None

        async def logged_send(message):
            nonlocal response_status,candidate_overflow,candidate_json
            if message['type'] == 'http.response.start':
                status = message['status']
                response_status=status
                headers={key.lower():value.lower() for key,value in message.get('headers',[])}
                candidate_json=(status<400 and method=='POST' and
                    headers.get(b'content-type',b'').split(b';',1)[0].strip()==b'application/json')
                logger.log(logging.WARNING if status >= 400 else logging.INFO,
                           'task response request_id=%s operation=%s method=%s status=%s',
                           request_id, operation, method, status)
            elif message['type']=='http.response.body' and candidate_json and not candidate_overflow:
                chunk=message.get('body',b'')
                if len(candidate_body)+len(chunk)>self.MAX_ERROR_BYTES:
                    candidate_body.clear();candidate_overflow=True
                else:candidate_body.extend(chunk)
            await send(message)

        async def send_error(payload):
            nonlocal start,error_code
            detail = payload['detail']
            from app.core.errors import PUBLIC_CODES
            error_code=detail.get('code') if detail.get('code') in PUBLIC_CODES else 'internal_error'
            detail['request_id'] = request_id
            detail['details'] = {}
            encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            headers = [(name, value) for name, value in start['headers'] if name.lower() != b'content-length']
            headers.append((b'content-length', str(len(encoded)).encode('ascii')))
            await logged_send({**start, 'headers': headers})
            await logged_send({'type': 'http.response.body', 'body': encoded})
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
            await logged_send(message)

        try:
            await self.app(scope, receive, traced_send)
        finally:
            # Capture has its own DB acquisition/statement limits. These do not
            # bound business execution or thread-pool scheduling time.
            try:
                from starlette.concurrency import run_in_threadpool
                from starlette.routing import Match
                from app.domain import admin_operations
                route_template=None
                route=scope.get('route')
                if route is not None:route_template=getattr(route,'path',None)
                if route_template is None:
                    candidates=[]
                    for branch in getattr(scope.get('app'),'routes',[]):
                        # FastAPI may retain included routers as wrappers without
                        # a path. Match their registered effective route contexts.
                        contexts=getattr(branch,'effective_route_contexts',None)
                        candidates.extend(contexts() if callable(contexts) else [branch])
                    for candidate in candidates:
                        match,_=candidate.matches(scope)
                        if match in (Match.FULL,Match.PARTIAL):
                            route_template=getattr(candidate,'path',None)
                            if match==Match.FULL:break
                if route_template is not None and len(route_template)>512:route_template=None
                state=scope.get('state',{})
                user=state.get('user') or {}
                task_candidate=scope.get('path_params',{}).get('task_id')
                if not task_candidate and candidate_body:
                    try:
                        candidate_payload=json.loads(candidate_body)
                        if isinstance(candidate_payload,dict):
                            candidate_task=candidate_payload.get('task',candidate_payload)
                            if isinstance(candidate_task,dict):task_candidate=candidate_task.get('id')
                    except (ValueError,UnicodeDecodeError):pass
                if not isinstance(task_candidate,str) or len(task_candidate)>128:task_candidate=None
                event=dict(request_id=request_id,route_template=route_template,method=method,
                    status=response_status,elapsed_ms=max(0,int((time.monotonic()-began)*1000)),
                    user_id=user.get('id'),error_code=error_code,created_at=created_at)
                # Never inspect a request body for telemetry. Only the validated
                # recovery endpoint may supply this bounded intent.
                intent=state.get('task_operation')
                event['task_operation']=(intent if method=='POST' and
                    route_template=='/api/v1/tasks/{task_id}/resume' and intent in ('retry','resume') else None)
                await run_in_threadpool(admin_operations.record_request,event,task_candidate)
            except Exception:
                # Never change the response, recurse into API logging, or emit
                # exception text that could contain SQL, paths or credentials.
                logger.warning('code=operational_capture_unavailable request_id=%s',request_id)
