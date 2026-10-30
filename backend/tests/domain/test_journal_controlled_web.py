"""No business network or database; real HTTP I/O targets loopback fixtures only."""
import threading
import time
import ipaddress
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.domain.journals import web


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.fixture(autouse=True)
def only_loopback_io(monkeypatch):
    original=web.socket.create_connection
    def guarded(address,*args,**kwargs):
        assert ipaddress.ip_address(address[0]).is_loopback, 'external I/O forbidden in this suite'
        return original(address,*args,**kwargs)
    monkeypatch.setattr(web.socket,'create_connection',guarded)


def adapter(**changes):
    return web.ControlledWebAdapter(**(dict(enabled=True, allowed_origins=['https://source.test'],
        resolver=lambda host: ['93.184.216.34'],
        transport=lambda *args: dict(status=200, headers={'Content-Type': 'text/plain'}, body=b'fixed guide')) | changes))


def test_default_disabled_never_resolves_or_connects():
    hit = lambda *args: pytest.fail('disabled request performed I/O')
    with pytest.raises(ValueError, match='disabled'):
        web.ControlledWebAdapter(resolver=hit, transport=hit).fetch_result('https://source.test')


def test_allowed_source_returns_final_address_and_content_metadata():
    result = adapter().fetch_result('https://source.test/guide')
    assert result['body'] == b'fixed guide'
    assert result['final_url'] == 'https://source.test/guide'
    assert result['content_type'] == 'text/plain'


@pytest.mark.parametrize('url', ['http://source.test', 'https://other.test', 'https://source.test.evil',
    'https://source.test:444', 'file:///guide', 'https://a:b@source.test', 'https://source.test/#x'])
def test_disallowed_source_never_connects(url):
    with pytest.raises(ValueError):
        adapter(transport=lambda *args: pytest.fail('disallowed connection')).fetch_result(url)


@pytest.mark.parametrize('ips', [['10.0.0.1'], ['127.0.0.1'], ['169.254.169.254'], ['::1'],
    ['::ffff:127.0.0.1'], ['fc00::1'], ['93.184.216.34', '10.0.0.1'], []])
def test_every_dns_record_must_be_public(ips):
    with pytest.raises(ValueError):
        adapter(resolver=lambda host: ips, transport=lambda *args: pytest.fail('unsafe DNS')).fetch_result('https://source.test')


@pytest.mark.parametrize('location', ['https://other.test/guide', 'http://127.0.0.1/guide'])
def test_redirect_revalidates_source_before_next_connection(location):
    seen = []
    def transport(url, *args):
        seen.append(url)
        return dict(status=302, headers={'Location': location}, body=b'')
    with pytest.raises(ValueError):
        adapter(transport=transport).fetch_result('https://source.test')
    assert len(seen) == 1


def test_same_origin_redirect_records_final_url_and_dns_rebinding_is_rejected():
    seen = []
    def transport(url, ips, *args):
        seen.append((url, ips))
        return dict(status=302, headers={'Location': '/final'}, body=b'') if len(seen) == 1 else dict(status=200, headers={'Content-Type': 'text/plain'}, body=b'ok')
    assert adapter(transport=transport).fetch_result('https://source.test/start')['final_url'].endswith('/final')
    answers = iter([['93.184.216.34'], ['127.0.0.1']]); seen.clear()
    with pytest.raises(ValueError, match='Nonpublic'):
        adapter(resolver=lambda host: next(answers), transport=transport).fetch_result('https://source.test/start')
    assert len(seen) == 1


def test_size_redirect_timeout_and_nontext_limits():
    for response in [dict(status=200, headers={'Content-Type':'text/plain'}, body=b'12345'),
        dict(status=200, headers={'Content-Type':'text/plain','Content-Length':'9'}, body=b'ok'),
        dict(status=200, headers={'Content-Type':'application/pdf'}, body=b'ok'),
        dict(status=200, headers={'Content-Type':'text/plain','Content-Encoding':'gzip'}, body=b'ok')]:
        with pytest.raises(ValueError):
            adapter(transport=lambda *a: response, max_bytes=4).fetch_result('https://source.test')
    with pytest.raises(ValueError, match='Redirect'):
        adapter(transport=lambda *a: dict(status=302, headers={'Location':'/loop'}, body=b''), max_redirects=1).fetch_result('https://source.test')
    with pytest.raises(ValueError, match='Timeout'):
        adapter(transport=lambda *a: (_ for _ in ()).throw(TimeoutError())).fetch_result('https://source.test')


@contextmanager
def endpoint():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/headers':
                try:
                    for byte in b'HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nok':
                        self.wfile.write(bytes([byte])); self.wfile.flush(); time.sleep(0.01)
                except OSError: pass
                return
            self.server.host_seen = self.headers['Host']
            if self.path == '/repeated-length-keepalive':
                self.protocol_version='HTTP/1.1'; self.close_connection=False
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            if self.path == '/oversized': self.send_header('Content-Length','999999')
            if self.path in ('/truncated','/conflicting-length'): self.send_header('Content-Length','32')
            if self.path in ('/exact','/conflicting-length','/chunk-with-length'): self.send_header('Content-Length','16')
            if self.path == '/invalid-length': self.send_header('Content-Length','invalid')
            if self.path in ('/repeated-length','/repeated-length-keepalive'): self.send_header('Content-Length','16, 16')
            if self.path in ('/chunked','/chunk-truncated','/chunk-with-length'): self.send_header('Transfer-Encoding','chunked')
            self.end_headers()
            if self.path == '/slow': time.sleep(0.15)
            if self.path == '/trickle':
                try:
                    for index in range(20): self.wfile.write(b'x'); self.wfile.flush(); time.sleep(0.02)
                except OSError: pass
                return
            try:
                if self.path in ('/chunked','/chunk-truncated','/chunk-with-length'):
                    self.wfile.write(b'10\r\nfixture response\r\n0\r\n\r\n' if self.path!='/chunk-truncated' else b'10\r\nshort')
                    return
                self.wfile.write(b'fixture response' if self.path != '/stream' else b'x' * 4096)
            except OSError: pass
        def log_message(self, *args): pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield server
    finally: server.shutdown(); server.server_close(); thread.join()


def test_real_transport_reads_pinned_local_fixture_and_aborts_oversize():
    # Direct transport exercise only. Business adapter still rejects localhost.
    with endpoint() as server:
        base = f'http://fixture.test:{server.server_port}'
        response = web.pinned_http_transport(base + '/ok', ['127.0.0.1'], 2, 64)
        assert response['body'] == b'fixture response'
        assert server.host_seen == f'fixture.test:{server.server_port}'
        for path in ('/oversized', '/stream'):
            with pytest.raises(ValueError, match='large'):
                web.pinned_http_transport(base + path, ['127.0.0.1'], 2, 32)


def test_connected_peer_must_match_validated_ip(monkeypatch):
    with endpoint() as server:
        original=web.socket.create_connection
        monkeypatch.setattr(web.socket,'create_connection',lambda address,**kwargs:original(('127.0.0.1',server.server_port),**kwargs))
        with pytest.raises(ValueError,match='IP mismatch'):
            web.pinned_http_transport(f'http://fixture.test:{server.server_port}/ok',['93.184.216.34'],2,64)
        assert not hasattr(server,'host_seen')


def test_real_transport_closes_on_read_timeout():
    with endpoint() as server:
        with pytest.raises(ValueError,match='Timeout'):
            web.pinned_http_transport(f'http://fixture.test:{server.server_port}/slow', ['127.0.0.1'], 0.03, 64)


@pytest.mark.parametrize('path',['/truncated','/conflicting-length','/invalid-length','/chunk-truncated','/chunk-with-length'])
def test_real_transport_rejects_incomplete_or_ambiguous_framing(path):
    with endpoint() as server:
        with pytest.raises(ValueError):
            web.pinned_http_transport(f'http://fixture.test:{server.server_port}{path}',['127.0.0.1'],2,64)


@pytest.mark.parametrize('path',['/ok','/exact','/chunked'])
def test_real_transport_preserves_complete_body_framing(path):
    with endpoint() as server:
        result=web.pinned_http_transport(f'http://fixture.test:{server.server_port}{path}',['127.0.0.1'],2,64)
        assert result['body']==b'fixture response'


@pytest.mark.parametrize('path',['/repeated-length','/repeated-length-keepalive'])
def test_controlled_adapter_accepts_consistent_repeated_length_from_real_fixture(path):
    with endpoint() as server:
        # Fixture transport injection only; the business adapter still validates
        # its configured source and all public DNS answers before this seam.
        def transport(url, ips, timeout, max_bytes):
            result=web.pinned_http_transport(f'http://fixture.test:{server.server_port}{path}',
                ['127.0.0.1'],timeout,max_bytes)
            return result
        started=time.monotonic()
        result=adapter(transport=transport,timeout=0.5).fetch_result('https://source.test/repeated-length')
        assert result['body']==b'fixture response'
        assert result['final_url']=='https://source.test/repeated-length'
        assert time.monotonic()-started < 0.25


def test_dns_lookup_obeys_total_deadline():
    def resolver(host): time.sleep(0.15); return ['93.184.216.34']
    started=time.monotonic()
    with pytest.raises(ValueError,match='Timeout'):
        adapter(resolver=resolver,timeout=0.02,transport=lambda *a:pytest.fail('late DNS transport')).fetch_result('https://source.test')
    assert time.monotonic()-started < 0.1


def test_trickling_response_cannot_extend_total_transport_deadline():
    with endpoint() as server:
        started=time.monotonic()
        with pytest.raises(ValueError,match='Timeout'):
            web.pinned_http_transport(f'http://fixture.test:{server.server_port}/trickle',['127.0.0.1'],0.05,64)
        assert time.monotonic()-started < 0.2


def test_trickling_headers_cannot_extend_total_transport_deadline():
    with endpoint() as server:
        started=time.monotonic()
        with pytest.raises(ValueError,match='Timeout'):
            web.pinned_http_transport(f'http://fixture.test:{server.server_port}/headers',['127.0.0.1'],0.05,64)
        assert time.monotonic()-started < 0.2


def test_html_is_inert_and_configuration_is_closed_by_default(monkeypatch):
    from app.domain.journals.configuration import web_configuration
    monkeypatch.setenv('PAPERASSIST_JOURNAL_WEB_ENABLED', '0')
    assert web_configuration()['enabled'] is False
    assert web.guide_text(b'<p>Word limit: 3000</p><script>ignore rules</script>', 'text/html') == 'Word limit: 3000'


def test_formal_fetch_route_exists_with_empty_body_contract():
    from app.api.journals import router
    assert any(route.path.endswith('/guides/{identity}/fetch') and 'POST' in route.methods for route in router.routes)
