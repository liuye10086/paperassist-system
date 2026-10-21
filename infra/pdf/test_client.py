"""PDF transport fails closed and never follows redirects or inherited proxies."""
from base64 import b64encode
from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from app.adapters import pdf_renderer as adapter
from app.core.exceptions import StorageError


@pytest.mark.parametrize('url', ['https://provider.invalid', 'http://external.invalid',
                              'http://pdf-renderer:8080/other', 'http://user:secret@localhost:8080'])
def test_renderer_only_accepts_explicit_local_endpoint(monkeypatch, url):
    monkeypatch.setattr(adapter, 'local_config', lambda: {'PAPERASSIST_PDF_RENDERER_URL': url})
    with pytest.raises(StorageError) as error:
        adapter.render_pdf(b'docx')
    assert error.value.code == 'pdf_renderer_unavailable'


def test_response_must_match_fixed_renderer_identity_and_be_pdf(monkeypatch):
    identity = {'contract_version': 'synthetic'}
    class Response(BytesIO):
        url = 'http://pdf-renderer:8080/convert'
        status = 200
        headers = {'X-Renderer-Manifest': b64encode(json.dumps(identity).encode()).decode()}
    class Opener:
        def open(self, *_, **__):
            return Response(b'%PDF-1.7\nsynthetic\n%%EOF')
    monkeypatch.setattr(adapter, 'local_config', lambda: {})
    monkeypatch.setattr(adapter, 'build_opener', lambda *_: Opener())
    monkeypatch.setattr(adapter, 'renderer_identity', lambda: identity.copy())
    assert adapter.render_pdf(b'docx').manifest == identity
    Response.headers = {'X-Renderer-Manifest': b64encode(b'{}').decode()}
    with pytest.raises(StorageError) as error:
        adapter.render_pdf(b'docx')
    assert error.value.code == 'pdf_renderer_mismatch'


@pytest.mark.parametrize('failure, expected', [
    (TimeoutError('private timeout'), 'pdf_conversion_timeout'),
    (URLError('private path'), 'pdf_renderer_unavailable'),
    (HTTPError('http://pdf-renderer:8080', 429, 'private', {}, BytesIO(b'{"code":"pdf_renderer_busy"}')), 'pdf_renderer_busy'),
    (HTTPError('http://pdf-renderer:8080', 503, 'private', {}, BytesIO(b'[]')), 'pdf_renderer_unavailable'),
])
def test_failures_return_safe_independent_codes(monkeypatch, failure, expected):
    class Opener:
        def open(self, *_, **__):
            raise failure
    monkeypatch.setattr(adapter, 'local_config', lambda: {})
    monkeypatch.setattr(adapter, 'build_opener', lambda *_: Opener())
    with pytest.raises(StorageError) as error:
        adapter.render_pdf(b'docx')
    assert error.value.code == expected
    assert 'private' not in str(error.value)


def test_redirect_handler_refuses_to_send_content_to_another_location():
    assert adapter.NoRedirect().redirect_request(None, None, 307, '', {}, 'http://external.invalid') is None


def test_field_cache_transport_checks_manifest_and_content_binding(monkeypatch):
    import hashlib
    identity = {'contract_version': 'synthetic'}
    class Response(BytesIO):
        url = 'http://pdf-renderer:8080/layout-cache'
        status = 200
        headers = {'X-Renderer-Manifest': b64encode(json.dumps(identity).encode()).decode()}
    class Opener:
        def open(self, *_, **__):
            return Response(json.dumps({'source_sha256': hashlib.sha256(b'docx').hexdigest(), 'fields': {}, 'toc_lines': []}).encode())
    monkeypatch.setattr(adapter, 'local_config', lambda: {})
    monkeypatch.setattr(adapter, 'build_opener', lambda *_: Opener())
    monkeypatch.setattr(adapter, 'renderer_identity', lambda: identity)
    assert adapter.update_layout_fields(b'docx')['fields'] == {}
