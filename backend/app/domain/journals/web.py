"""Offline-only injected transport: no DNS, sockets or configurable business switch."""
import ipaddress
import time
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
