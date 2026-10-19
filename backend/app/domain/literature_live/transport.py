"""Sessions for existing adapters; no implicit retry, redirect or ambient identity."""
from contextlib import contextmanager
import html
import json
from urllib.parse import quote, unquote

import requests
from defusedxml import ElementTree

from app.adapters.ncbi import BASE_URL, MAX_BYTES, NcbiError, parse_search, parse_fetch, _identity
from .policy import LivePolicyError, QUERIES


class _BufferedResponse:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def iter_content(self, chunk_size):
        yield self._data

    def close(self):
        pass


class _DoiResponse:
    def __init__(self, status, target):
        self.status_code = status
        self.headers = {'Location': target} if target is not None else {}

    def close(self):
        pass


class LiveTransport:
    def __init__(self, ledger, *, transport=None):
        self.ledger = ledger
        # Injection is for fixed offline tests only. Production creates a fresh session per dispatch.
        self._transport = transport
        self._secrets = set()

    @contextmanager
    def _wire(self):
        if self._transport is not None:
            yield self._transport
        else:
            with requests.Session() as session:
                session.trust_env = False
                session.headers.clear()
                yield session

    def ncbi_session(self, settings):
        try:
            _identity(settings)
            if settings.tool != 'PaperAssist':
                raise ValueError()
        except Exception:
            raise LivePolicyError('live_identity_invalid') from None
        self._secrets.update(value for value in (settings.email, settings.api_key) if value)
        return _NcbiSession(self, settings)

    def doi_session(self):
        return _DoiSession(self)

    def _contains_identity(self, data, *, xml=False):
        texts = [data.decode('utf-8', errors='replace')]
        try:
            if xml:
                texts.append(ElementTree.tostring(ElementTree.fromstring(data, forbid_dtd=False, forbid_entities=True, forbid_external=True), encoding='unicode'))
            else:
                texts.append(json.dumps(json.loads(data), ensure_ascii=False))
        except Exception:
            pass
        return any(secret in candidate for text in texts for candidate in (text, unquote(html.unescape(text))) for secret in self._secrets)


class _NcbiSession:
    def __init__(self, guard, settings):
        self._guard, self._settings = guard, settings

    def get(self, url, **kwargs):
        settings = self._settings
        identity = {'tool': 'PaperAssist', 'email': settings.email}
        if settings.api_key:
            identity['api_key'] = settings.api_key
        params = kwargs.get('params')
        if (set(kwargs) != {'params', 'timeout', 'allow_redirects', 'stream'}
                or kwargs['timeout'] != (10, 30) or kwargs['allow_redirects'] is not False
                or kwargs['stream'] is not True or not isinstance(params, dict)):
            raise LivePolicyError('live_request_denied')
        ledger = self._guard.ledger
        with ledger.locked() as state:
            action = None
            if url == BASE_URL + 'esearch.fcgi':
                for label, query in QUERIES.items():
                    if params == dict(db='pubmed', term=query, retmax=20, retmode='json', sort='relevance', **identity):
                        action = {'query': label}
            elif url == BASE_URL + 'efetch.fcgi':
                for result in state['searches']:
                    if result['ids'] and params == dict(db='pubmed', id=','.join(result['ids']), retmode='xml', rettype='abstract', **identity):
                        action = dict(search=result['attempt'], ids=result['ids'])
            if action is None:
                raise LivePolicyError('live_request_denied')
            attempt = ledger.reserve(state, 'ncbi', action)
            response = None
            try:
                with self._guard._wire() as wire:
                    response = wire.get(url, **kwargs)
                    status = response.status_code
                    if status != 200:
                        raise NcbiError('ncbi_unavailable' if status == 429 or 500 <= status <= 599 else 'ncbi_request_rejected')
                    chunks, size = [], 0
                    for chunk in response.iter_content(chunk_size=65536):
                        if not isinstance(chunk, bytes):
                            raise NcbiError('ncbi_response_invalid')
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise NcbiError('ncbi_response_invalid')
                        chunks.append(chunk)
                    data = b''.join(chunks)
                    if self._guard._contains_identity(data, xml='ids' in action):
                        raise NcbiError('ncbi_response_invalid')
                    if 'query' in action:
                        parse_search(data, 20)
                    else:
                        parse_fetch(data, action['ids'])
                    ledger.retain(attempt, data)
                    return _BufferedResponse(data)
            except NcbiError as error:
                ledger.finish(attempt, error.code)
                raise NcbiError(error.code) from None
            except Exception:
                ledger.finish(attempt, 'ncbi_unavailable')
                raise NcbiError('ncbi_unavailable') from None
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass


class _DoiSession:
    def __init__(self, guard):
        self._guard = guard

    def get(self, url, **kwargs):
        if (set(kwargs) != {'allow_redirects', 'timeout', 'stream', 'headers'}
                or kwargs['allow_redirects'] is not False or kwargs['timeout'] != (3.05, 8)
                or kwargs['stream'] is not True or kwargs['headers'] != {'Accept': 'text/html'}):
            raise LivePolicyError('live_request_denied')
        ledger = self._guard.ledger
        with ledger.locked() as state:
            allowed = ledger._dois(state)
            doi = next((d for d in allowed if url == 'https://doi.org/' + d.split('/', 1)[0] + '/' + quote(d.split('/', 1)[1], safe='')), None)
            if doi is None:
                raise LivePolicyError('live_request_denied')
            attempt = ledger.reserve(state, 'doi', {'doi': doi})
            response = None
            try:
                with self._guard._wire() as wire:
                    response = wire.get(url, **kwargs)
                    target = response.headers.get('Location')
                    if isinstance(target, str) and any(secret in unquote(target) for secret in self._guard._secrets):
                        target = None
                    result = _DoiResponse(response.status_code, target)
                    ledger.finish(attempt, 'doi_finished')
                    return result
            except requests.Timeout:
                ledger.finish(attempt, 'doi_unavailable')
                raise requests.Timeout('doi_timeout') from None
            except Exception:
                ledger.finish(attempt, 'doi_unavailable')
                raise requests.RequestException('doi_unavailable') from None
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
