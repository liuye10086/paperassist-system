"""Transport to the local isolated converter; never calls an external provider."""
from base64 import b64decode
from dataclasses import dataclass
import json
import hashlib
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from app.core.config import local_config
from app.core.exceptions import StorageError

MAX_INPUT = 50 * 1024 * 1024
MAX_OUTPUT = 80 * 1024 * 1024


@dataclass(frozen=True)
class PdfRenderResult:
    content: bytes
    manifest: dict


def renderer_identity():
    return json.loads(Path(__file__).with_name('pdf_renderer_lock.json').read_text(encoding='utf-8'))


def failure(code):
    return StorageError(code, '本地PDF转换未完成，成功的DOCX仍然保留，请检查导出状态后重试。', 503)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(content, path, *, cache=False):
    if not content or len(content) > MAX_INPUT:
        raise failure('pdf_input_invalid')
    base = local_config().get('PAPERASSIST_PDF_RENDERER_URL') or 'http://pdf-renderer:8080'
    endpoint = urlsplit(base)
    if (endpoint.scheme != 'http' or endpoint.hostname not in {'pdf-renderer', '127.0.0.1', 'localhost', '::1'}
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or endpoint.path not in ('', '/')):
        raise failure('pdf_renderer_unavailable')
    request = Request(base.rstrip('/') + path, data=content,
                      headers={'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'})
    try:
        # Disable inherited proxy configuration so research bytes cannot leave the local network.
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=105) as response:
            if response.url != request.full_url or response.status != 200:
                raise failure('pdf_renderer_mismatch')
            manifest = json.loads(b64decode(response.headers.get('X-Renderer-Manifest', ''), validate=True))
            if manifest != renderer_identity():
                raise failure('pdf_renderer_mismatch')
            data = response.read((2 * 1024 * 1024 if cache else MAX_OUTPUT) + 1)
            if cache:
                if len(data) > 2 * 1024 * 1024:
                    raise failure('pdf_conversion_failed')
                result = json.loads(data)
                if (not isinstance(result, dict) or result.get('source_sha256') != hashlib.sha256(content).hexdigest()
                        or not isinstance(result.get('fields'), dict) or not isinstance(result.get('toc_lines'), list)):
                    raise failure('pdf_conversion_failed')
                return result
            if len(data) > MAX_OUTPUT or not data.startswith(b'%PDF-') or b'%%EOF' not in data[-1024:]:
                raise failure('pdf_conversion_failed')
            return PdfRenderResult(data, manifest)
    except HTTPError as exc:
        try:
            body = json.loads(exc.read(1024))
            code = body.get('code') if isinstance(body, dict) else None
        except (ValueError, OSError):
            code = None
        if code not in {'pdf_renderer_busy', 'pdf_conversion_timeout', 'pdf_conversion_failed', 'pdf_input_invalid', 'pdf_renderer_mismatch'}:
            code = 'pdf_renderer_unavailable'
        raise failure(code) from None
    except TimeoutError:
        raise failure('pdf_conversion_timeout') from None
    except (URLError, OSError):
        raise failure('pdf_renderer_unavailable') from None
    except (ValueError, TypeError):
        raise failure('pdf_renderer_mismatch') from None


def render_pdf(content):
    return _request(content, '/convert')


def update_layout_fields(content):
    """Local-only actual page/field results; caller merges into original OOXML."""
    return _request(content, '/layout-cache', cache=True)
