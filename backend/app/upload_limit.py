import re

from starlette.types import ASGIApp, Receive, Scope, Send

from .config import get_excel_settings
from .errors import error_response


class UploadLimitMiddleware:
    """Bound the request before multipart parsing, including chunked uploads."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        path = scope.get("path", "").rstrip("/")
        is_upload = path == "/api/v1/excel/preview" or re.fullmatch(r"/api/v1/projects/[^/]+/files", path)
        if scope["type"] != "http" or scope["method"] != "POST" or not is_upload:
            return await self.app(scope, receive, send)

        # Small fixed allowance for the multipart boundary and file headers.
        max_upload_bytes = get_excel_settings().max_upload_bytes
        limit = max_upload_bytes + 64 * 1024
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                response = error_response(413, 'file_too_large', '上传请求超过大小限制，请缩小文件后重试。',
                                          {'max_bytes': max_upload_bytes})
                return await response(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
