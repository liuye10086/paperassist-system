"""Offline seam and opt-in source-restricted, IP-pinned HTTP acquisition."""
import http.client
import ipaddress
import socket
import ssl
import queue
import threading
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin

class OfflineWebAdapter:
    def __init__(self,*,resolver=None,transport=None,max_bytes=256*1024,timeout=5,max_redirects=3):
        self.resolver=resolver;self.transport=transport;self.max_bytes=max_bytes;self.timeout=timeout;self.max_redirects=max_redirects
    def address(self,url):
        u=urlsplit(url)
        if u.scheme not in ('http','https') or not u.hostname or u.username is not None or u.password is not None or u.fragment or u.port not in (None,80 if u.scheme=='http' else 443):raise ValueError('Unsafe URL')
        try:literal=ipaddress.ip_address(u.hostname)
        except ValueError:literal=None
        addresses=[str(literal)] if literal else self.resolver(u.hostname)
        if not addresses:raise ValueError('No addresses')
        for address in addresses:
            ip=ipaddress.ip_address(address);ip=ip.ipv4_mapped if isinstance(ip,ipaddress.IPv6Address) and ip.ipv4_mapped else ip
            if not ip.is_global:raise ValueError('Nonpublic address')
        return addresses
    def fetch(self,url):
        if self.resolver is None or self.transport is None:raise ValueError('Real network access is disabled; injected offline resolver and transport required')
        started=time.monotonic()
        for hop in range(self.max_redirects+1):
            ips=self.address(url)
            response=self.transport(url,ips,self.timeout,self.max_bytes)
            if time.monotonic()-started>self.timeout:raise ValueError('Timeout')
            body=response['body']
            if not isinstance(body,bytes) or len(body)>self.max_bytes:raise ValueError('Response too large')
            headers={k.casefold():v for k,v in response['headers'].items()}
            if int(headers.get('content-length','0'))>self.max_bytes:raise ValueError('Response too large')
            if response['status'] in (301,302,303,307,308):
                if hop==self.max_redirects or not headers.get('location'):raise ValueError('Redirect limit')
                url=urljoin(url,headers['location']);continue
            if response['status']!=200:raise ValueError('Unavailable source')
            return body


def resolve_public_candidates(host):
    return list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)))


def pinned_http_transport(url, ips, timeout, max_bytes):
    """No proxy, hostname re-resolution, retries or implicit redirects."""
    parsed = urlsplit(url)
    started = time.monotonic()
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    connection = http.client.HTTPConnection(parsed.hostname, port, timeout=timeout)
    response = None; deadline_timer = None
    try:
        connection.sock = socket.create_connection((ips[0], port), timeout=timeout)
        peer = ipaddress.ip_address(connection.sock.getpeername()[0])
        if peer != ipaddress.ip_address(ips[0]):
            raise ValueError('Connected IP mismatch')
        active_socket = connection.sock
        def abort_at_deadline():
            try: active_socket.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        deadline_timer = threading.Timer(max(0.001, timeout-(time.monotonic()-started)), abort_at_deadline)
        deadline_timer.daemon = True; deadline_timer.start()
        if parsed.scheme == 'https':
            connection.sock.settimeout(max(0.001, timeout-(time.monotonic()-started)))
            connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=parsed.hostname)
            active_socket = connection.sock
        def remaining():
            value = timeout - (time.monotonic() - started)
            if value <= 0: raise ValueError('Timeout')
            return value
        connection.sock.settimeout(remaining())
        connection.request('GET', parsed.path or '/' if not parsed.query else (parsed.path or '/') + '?' + parsed.query,
            headers={'Accept':'text/plain, text/html', 'Accept-Encoding':'identity', 'User-Agent':'PaperAssist-controlled-guide/1'})
        response = connection.getresponse()
        headers = {key.casefold():value for key,value in response.getheaders()}
        lengths=[value.strip() for header in response.headers.get_all('Content-Length',[]) for value in header.split(',')]
        if lengths and (any(not value or any(char not in '0123456789' for char in value) for value in lengths)
                or len({int(value) for value in lengths})!=1 or response.headers.get('Transfer-Encoding') is not None):
            raise ValueError('Invalid or ambiguous HTTP response framing')
        expected_length=int(lengths[0]) if lengths else None
        if expected_length is not None and expected_length > max_bytes: raise ValueError('Response too large')
        if expected_length is not None: headers['content-length']=str(expected_length)
        chunks = []; size = 0
        while expected_length is None or size < expected_length:
            # read1 returns available bytes without waiting to fill a large chunk.
            if connection.sock is not None: connection.sock.settimeout(remaining())
            elif response.fp is not None: response.fp.raw._sock.settimeout(remaining())
            read_limit=min(8192, max_bytes + 1 - size)
            if expected_length is not None: read_limit=min(read_limit,expected_length-size)
            chunk = response.read1(read_limit)
            if not chunk: break
            chunks.append(chunk); size += len(chunk)
            if size > max_bytes: raise ValueError('Response too large')
        remaining()
        if expected_length is not None and size != expected_length:
            raise ValueError('Incomplete HTTP response')
        return dict(status=response.status, headers=headers, body=b''.join(chunks))
    except (OSError, http.client.HTTPException) as exc:
        raise ValueError('Timeout or unavailable source') from exc
    finally:
        if deadline_timer is not None: deadline_timer.cancel()
        if response is not None: response.close()
        connection.close()


def origin(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname: raise ValueError('Unsafe URL')
    return (parsed.scheme, parsed.hostname.casefold(), parsed.port or (443 if parsed.scheme == 'https' else 80))


class ControlledWebAdapter(OfflineWebAdapter):
    def __init__(self, *, enabled=False, allowed_origins=(), resolver=None, transport=None, **limits):
        super().__init__(resolver=resolver or resolve_public_candidates, transport=transport or pinned_http_transport, **limits)
        self.enabled = enabled
        self.allowed_origins = {origin(value) for value in allowed_origins}

    def fetch(self, url):
        return self.fetch_result(url)['body']

    def bounded_address(self, url, timeout):
        # OS DNS cannot be cancelled; a late answer never creates an HTTP request.
        answer=queue.Queue(maxsize=1)
        def resolve():
            try: answer.put((self.address(url),None))
            except Exception as exc: answer.put((None,exc))
        threading.Thread(target=resolve,daemon=True).start()
        try: addresses,error=answer.get(timeout=max(0.001,timeout))
        except queue.Empty as exc: raise ValueError('Timeout during DNS validation') from exc
        if error is not None: raise error
        return addresses

    def fetch_result(self, url):
        if not self.enabled: raise ValueError('Real network access is disabled')
        started = time.monotonic()
        for hop in range(self.max_redirects + 1):
            if origin(url) not in self.allowed_origins: raise ValueError('Source origin is not allowed')
            ips = self.bounded_address(url,self.timeout-(time.monotonic()-started))
            remaining = self.timeout - (time.monotonic() - started)
            if remaining <= 0: raise ValueError('Timeout')
            try: response = self.transport(url, ips, remaining, self.max_bytes)
            except TimeoutError as exc: raise ValueError('Timeout') from exc
            if time.monotonic() - started > self.timeout: raise ValueError('Timeout')
            headers = {key.casefold():value for key,value in response['headers'].items()}
            body = response['body']
            if not isinstance(body, bytes) or len(body) > self.max_bytes or int(headers.get('content-length','0')) > self.max_bytes:
                raise ValueError('Response too large')
            if response['status'] in (301,302,303,307,308):
                if hop == self.max_redirects or not headers.get('location'): raise ValueError('Redirect limit')
                url = urljoin(url, headers['location']); continue
            if response['status'] != 200: raise ValueError('Unavailable source')
            content_type = headers.get('content-type','').split(';')[0].strip().lower()
            if content_type not in ('text/plain','text/html') or headers.get('content-encoding','identity').lower() != 'identity':
                raise ValueError('Unsupported source content')
            return dict(body=body, final_url=url, content_type=content_type,
                etag=headers.get('etag'), last_modified=headers.get('last-modified'))


def guide_text(body, content_type):
    text = body.decode('utf-8-sig')
    if content_type == 'text/html':
        class Text(HTMLParser):
            def __init__(self): super().__init__(); self.parts=[]; self.hidden=0
            def handle_starttag(self, tag, attrs):
                if tag in ('script','style'): self.hidden += 1
                if not self.hidden and tag in ('p','br','div','li','h1','h2','h3','tr'): self.parts.append('\n')
            def handle_endtag(self, tag):
                if tag in ('script','style'): self.hidden = max(0,self.hidden-1)
                if not self.hidden and tag in ('p','div','li','h1','h2','h3','tr'): self.parts.append('\n')
            def handle_data(self, data):
                if not self.hidden: self.parts.append(data)
        parser=Text(); parser.feed(text); text=''.join(parser.parts)
    text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
    if not text or len(text)>60000: raise ValueError('Empty or oversized guide text')
    return text
