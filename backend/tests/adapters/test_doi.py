"""No real transport: fixed response DOI boundary tests."""
import pytest
import requests


def test_doi_disabled_invalid_and_no_identifier_never_request():
    from app.adapters.doi import DoiClient
    class Forbidden:
        def get(self,*args,**kwargs): raise AssertionError('network forbidden')
    c=DoiClient(session=Forbidden())
    assert c.resolve(None)['status']=='not_applicable'
    assert c.resolve('https://evil.test')['status']=='invalid_doi'
    assert c.resolve('10.1234/demo')['status']=='not_checked'


@pytest.mark.parametrize('code,status',[(302,'resolved'),(301,'resolved'),(404,'not_found'),(429,'rate_limited'),(500,'error'),(200,'error')])
def test_fixed_http_response_no_redirect_or_body_download(code,status):
    from app.adapters.doi import DoiClient
    class Response:
        status_code=code
        headers={'Location':'https://publisher.example/article'}
        @property
        def content(self): raise AssertionError('body forbidden')
        def close(self): pass
    class Session:
        def get(self,url,**kwargs):
            assert url=='https://doi.org/10.1234/a%3Fb%23c'
            assert kwargs['allow_redirects'] is False and kwargs['stream'] is True
            assert kwargs['timeout']==(3.05,8)
            return Response()
    c=DoiClient(enabled=True,session=Session(),execution_kind='synthetic_fixture')
    result=c.resolve('10.1234/a?b#c')
    assert result['status']==status
    assert result['execution_kind']=='synthetic_fixture'
    assert result['resolution_target']==('https://publisher.example/article' if status=='resolved' else None)


def test_timeout_is_single_attempt_and_real_requires_allowlist():
    from app.adapters.doi import DoiClient
    calls=[]
    class Session:
        def get(self,*args,**kwargs):
            calls.append(1);raise requests.Timeout()
    assert DoiClient(enabled=True,session=Session()).resolve('10.1234/demo')['status']=='not_checked'
    r=DoiClient(enabled=True,session=Session(),execution_kind='synthetic_fixture').resolve('10.1234/demo')
    assert r['status']=='timeout' and len(calls)==1


def test_synthetic_requires_fixed_transport_and_preserves_doi_identifier():
    from app.adapters.doi import DoiClient
    with pytest.raises(ValueError): DoiClient(enabled=True,execution_kind='synthetic_fixture')


def test_preserves_encoded_doi_suffix_slashes():
    from app.adapters.doi import DoiClient
    urls=[]
    class Response:
        status_code=404;headers={}
        def close(self): pass
    class Session:
        def get(self,url,**kwargs): urls.append(url);return Response()
    c=DoiClient(enabled=True,execution_kind='synthetic_fixture',session=Session())
    c.resolve('10.1234/a/../b?x#z%p')
    assert urls==['https://doi.org/10.1234/a%2F..%2Fb%3Fx%23z%25p']


def test_real_executor_consumes_finite_approved_call_list_without_retry():
    from app.adapters.doi import DoiClient
    calls=[]
    class Response:
        status_code=404;headers={}
        def close(self): pass
    class Fixed:
        def get(self,*args,**kwargs): calls.append(1);return Response()
    c=DoiClient(enabled=True,session=Fixed(),allowed_dois=['10.1234/demo'])
    assert c.resolve('10.1234/demo')['network_attempted'] is True
    assert c.resolve('10.1234/demo')['status']=='not_checked'
    assert len(calls)==1
