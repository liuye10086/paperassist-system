import pytest

@pytest.fixture(autouse=True)
def postgres_schema():
    """Pure injected-client unit tests: no database or migrations."""
    yield None


@pytest.fixture(autouse=True)
def forbid_cloud_http(monkeypatch):
    """SDK contract tests must never reach an actual AWS HTTP endpoint."""
    from botocore.httpsession import URLLib3Session
    def blocked(*args, **kwargs):
        raise AssertionError('Cloud HTTP is forbidden in offline contract tests')
    monkeypatch.setattr(URLLib3Session, 'send', blocked)
