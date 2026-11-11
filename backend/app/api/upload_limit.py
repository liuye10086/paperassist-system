from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
import re

from anyio import CancelScope
from python_multipart.multipart import parse_options_header
from starlette.datastructures import FormData
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import ClientDisconnect, Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_request_excel_settings
from app.core.errors import error_response
from app.core.exceptions import StorageError
from app.domain.bioinformatics.settings import MAX_BULK_IMPORT_REQUEST_BYTES


MULTIPART_ALLOWANCE = 64 * 1024


def bio_upload_too_large(max_bytes):
    return StorageError('file_too_large', '生信原始文件超过上传限制。', 413,
                        params={'max_bytes': max_bytes})


class _BioUploadMultipartParser(MultiPartParser):
    def __init__(self, headers, stream, maximum):
        super().__init__(headers, stream, max_files=1, max_fields=16, max_part_size=MULTIPART_ALLOWANCE)
        self.maximum = maximum
        self.file_bytes = 0
        self.header_bytes = 0
        self.complete = False

    def _bound_header(self, start, end):
        self.header_bytes += end - start
        if self.header_bytes > MULTIPART_ALLOWANCE:
            raise MultiPartException('Multipart headers exceeded the upload allowance.')

    def on_header_field(self, data, start, end):
        self._bound_header(start, end)
        super().on_header_field(data, start, end)

    def on_header_value(self, data, start, end):
        self._bound_header(start, end)
        super().on_header_value(data, start, end)

    def on_part_data(self, data, start, end):
        if self._current_part.file is not None:
            self.file_bytes += end - start
            if self.file_bytes > self.maximum:
                raise bio_upload_too_large(self.maximum)
        super().on_part_data(data, start, end)

    def on_end(self):
        self.complete = True


@asynccontextmanager
async def bio_upload_form(request: Request, maximum: int) -> AsyncIterator[FormData]:
    limit = maximum + MULTIPART_ALLOWANCE
    try:
        declared_length = int(request.headers.get('Content-Length', '0'))
    except ValueError:
        declared_length = 0
    if declared_length > limit:
        raise bio_upload_too_large(maximum)

    content_type, _ = parse_options_header(request.headers.get('Content-Type'))
    if content_type != b'multipart/form-data':
        yield FormData()
        return

    async def bounded_chunks():
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > limit:
                raise bio_upload_too_large(maximum)
            for start in range(0, len(chunk), MULTIPART_ALLOWANCE):
                yield chunk[start:start + MULTIPART_ALLOWANCE]
        # python-multipart.finalize() does not reject an unfinished final part.
        if not parser.complete:
            raise MultiPartException('Incomplete multipart data.')

    parser = _BioUploadMultipartParser(request.headers, bounded_chunks(), maximum)
    try:
        # Starlette closes its spools on parser, receive and cancellation errors.
        form = await parser.parse()
    except (MultiPartException, ClientDisconnect) as exc:
        raise StorageError('invalid_request', '请求格式无效，请检查上传文件后重试。', 400) from exc
    except OSError as exc:
        raise StorageError('storage_unavailable', '无法暂存上传文件，请检查目录权限和磁盘空间。') from exc
    try:
        yield form
    finally:
        with CancelScope(shield=True):
            await form.close()


class UploadLimitMiddleware:
    """Bound buffered requests. Bio originals use the streaming form above."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        path = scope.get("path", "").rstrip("/")
        is_research_json = bool(re.fullmatch(r"/api/v1/projects/[^/]+/(requirements|research-designs|design-table-preview|design-table-previews|deliveries)",path))
        is_import_create = bool(re.fullmatch(r"/api/v1/projects/[^/]+/bio-imports", path))
        is_bio_json = is_import_create or bool(re.fullmatch(
            r"/api/v1/projects/[^/]+/(bio-imports/[^/]+/confirm|bio-upload-batches)", path
        ))
        is_upload = (path == "/api/v1/excel/preview" or re.fullmatch(r"/api/v1/projects/[^/]+/files", path)
                     or re.fullmatch(r"/api/v1/projects/[^/]+/file-batches/[^/]+/items/[^/]+", path))
        if scope["type"] != "http" or scope["method"] != "POST" or not (is_upload or is_research_json or is_bio_json):
            return await self.app(scope, receive, send)

        # Small fixed allowance for the multipart boundary and file headers.
        small_bio_json_bytes = 64 * 1024
        if is_import_create:
            max_upload_bytes = MAX_BULK_IMPORT_REQUEST_BYTES
        elif is_research_json:
            max_upload_bytes = 4 * 1024**2
        elif is_bio_json:
            max_upload_bytes = small_bio_json_bytes
        else:
            max_upload_bytes = get_request_excel_settings().max_upload_bytes
        limit = max_upload_bytes + (MULTIPART_ALLOWANCE if is_upload else 0)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                response = error_response(413, 'research_content_too_large' if is_research_json else 'bio_input_limit' if is_bio_json else 'file_too_large', '请求超过大小限制，请缩小内容后重试。',
                                          {'max_bytes': max_upload_bytes})
                return await response(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        if is_import_create and len(body) > small_bio_json_bytes:
            try:
                config = json.loads(body)
            except (ValueError, RecursionError):
                config = None
            bulk_counts = (isinstance(config, dict) and config.get('workflow_version') == 'bio_import_v3'
                           and config.get('assay') == 'bulk_rna_counts')
            del config
            if not bulk_counts:
                response = error_response(413, 'bio_input_limit', '请求超过大小限制，请缩小内容后重试。',
                                          {'max_bytes': small_bio_json_bytes})
                return await response(scope, receive, send)

        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
