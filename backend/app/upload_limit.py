from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import get_excel_settings


class UploadLimitMiddleware:
    """Bound the request before multipart parsing, including chunked uploads."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if (scope["type"] != "http" or scope["method"] != "POST"
                or scope["path"].rstrip("/") != "/api/v1/excel/preview"):
            return await self.app(scope, receive, send)

        # Small fixed allowance for the multipart boundary and file headers.
        limit = get_excel_settings().max_upload_bytes + 64 * 1024
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                response = JSONResponse(status_code=413, content={"detail": {
                    "code": "file_too_large",
                    "message": "上传请求超过大小限制，请缩小文件后重试。",
                }})
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
