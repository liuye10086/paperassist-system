"""Single resolver request; never follow publisher redirects or consume bodies."""
import re
from threading import Lock
from urllib.parse import quote, urlsplit
import requests


def valid_doi(value):
    return isinstance(value,str) and len(value)<=2048 and re.fullmatch(r'10\.[0-9]{4,9}/[^\s\x00-\x1f\x7f]+',value) is not None


class DoiClient:
    def __init__(self,*,enabled=False,session=None,execution_kind='doi_org',allowed_dois=()):
        if execution_kind not in ('doi_org','synthetic_fixture'):
            raise ValueError('Unsupported DOI execution kind')
        if execution_kind=='synthetic_fixture' and session is None:
            raise ValueError('Synthetic DOI execution requires a fixed transport')
        self.enabled=bool(enabled)
        self.session=session
        self.execution_kind=execution_kind
        self.allowed_dois=list(allowed_dois)
        if any(not valid_doi(doi) for doi in self.allowed_dois):
            raise ValueError("Invalid approved DOI call list")
        self._budget_lock=Lock()

    @property
    def available(self):
        return self.enabled and (self.execution_kind=='synthetic_fixture' or bool(self.allowed_dois))

    def resolve(self,doi):
        result=dict(status='not_checked',network_attempted=False,execution_kind='disabled',
                    error_code=None,doi=doi or None,http_status=None,resolution_target=None)
        if not doi:
            result['status']='not_applicable';return result
        if not valid_doi(doi):
            result.update(status='invalid_doi',error_code='doi_invalid');return result
        with self._budget_lock:
            if not self.available or (self.execution_kind=='doi_org' and doi not in self.allowed_dois):
                return result
            if self.execution_kind=='doi_org':
                self.allowed_dois.remove(doi)
        result.update(network_attempted=self.execution_kind=='doi_org',execution_kind=self.execution_kind)
        response=None
        try:
            transport=self.session if self.session is not None else requests
            response=transport.get('https://doi.org/'+doi.split('/',1)[0]+'/'+quote(doi.split('/',1)[1],safe=''),allow_redirects=False,
                timeout=(3.05,8),stream=True,headers={'Accept':'text/html'})
            code=response.status_code;result['http_status']=code
            target=response.headers.get('Location')
            target_ok=False
            if isinstance(target,str) and len(target)<=4096 and not any(ord(c)<32 or ord(c)==127 for c in target):
                parsed=urlsplit(target)
                target_ok=parsed.scheme in ('https','http') and bool(parsed.hostname) and not parsed.username and not parsed.password
            if code in (301,302,303,307,308) and target_ok:
                result.update(status='resolved',resolution_target=target)
            elif code==404:
                result.update(status='not_found',error_code='doi_not_found')
            elif code==429:
                result.update(status='rate_limited',error_code='doi_rate_limited')
            else:
                result.update(status='error',error_code='doi_response_invalid' if code in (200,301,302,303,307,308) else 'doi_unavailable')
        except requests.Timeout:
            result.update(status='timeout',error_code='doi_timeout')
        except (requests.RequestException,ValueError):
            result.update(status='error',error_code='doi_unavailable')
        finally:
            if response is not None:
                response.close()
        return result
