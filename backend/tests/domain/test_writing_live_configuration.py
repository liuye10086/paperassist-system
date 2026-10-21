from pathlib import Path
import pytest
from app.core.exceptions import StorageError
from app.domain.manuscript_writing import policy,live_execution

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

def test_capabilities_accepts_configured_secret_file_without_reading_it(monkeypatch):
    monkeypatch.setenv('PAPERASSIST_ENV','development');monkeypatch.setenv('PAPERASSIST_WRITING_LIVE_ENABLED','1')
    monkeypatch.setenv('OPENAI_API_KEY','');monkeypatch.setenv('OPENAI_API_KEY_FILE','/run/secrets/synthetic-key')
    def forbidden(*args,**kwargs): raise AssertionError('Preview must not open credential file')
    monkeypatch.setattr('app.domain.explanation_policy._small_text',forbidden)
    result=policy.capabilities()
    assert result['real_calls_enabled'] is True
    assert result['credential_status']=='configured_unverified'
    assert 'synthetic-key' not in str(result)

def test_production_provider_uses_existing_safe_file_key_resolver(monkeypatch,tmp_path):
    key=tmp_path/'synthetic-key';key.write_text('\ufefftest-credential\n',encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_ENV','development');monkeypatch.setenv('PAPERASSIST_WRITING_LIVE_ENABLED','1')
    monkeypatch.setenv('OPENAI_API_KEY','');monkeypatch.setenv('OPENAI_API_KEY_FILE',str(key))
    seen=[]
    monkeypatch.setattr('app.adapters.models.openai_responses.OpenAIResponsesProvider',lambda **kwargs: seen.append(kwargs) or object())
    assert callable(getattr(live_execution,'create_production_provider',None))
    live_execution.create_production_provider()
    assert seen==[dict(api_key='test-credential')]

@pytest.mark.parametrize('content',['','bad key','a'*8193],ids=['empty','whitespace','oversized'])
def test_invalid_file_key_never_constructs_provider(monkeypatch,tmp_path,content):
    key=tmp_path/'synthetic-key';key.write_text(content,encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_ENV','development');monkeypatch.setenv('PAPERASSIST_WRITING_LIVE_ENABLED','1')
    monkeypatch.setenv('OPENAI_API_KEY','');monkeypatch.setenv('OPENAI_API_KEY_FILE',str(key))
    def forbidden(**kwargs): raise AssertionError('Invalid key must not construct provider')
    monkeypatch.setattr('app.adapters.models.openai_responses.OpenAIResponsesProvider',forbidden)
    assert callable(getattr(live_execution,'create_production_provider',None))
    with pytest.raises(StorageError) as exc: live_execution.create_production_provider()
    assert exc.value.code=='manuscript_writing_not_authorized'
    assert str(key) not in str(exc.value)

def test_authorization_requires_literal_boolean_confirmation_not_integer_one():
    from app.domain.manuscript_writing.live_contracts import AuthorizationRequest
    body=dict(schema_version=2,confirmed=1,tasks=[dict(logical_task_id=str(i),bundles=[dict(bundle_id='b',bundle_sha256='a'*64)]) for i in range(4)])
    with pytest.raises(ValueError): AuthorizationRequest.model_validate(body)


@pytest.mark.parametrize('status',['submitting','submission_unknown'])
def test_unknown_without_response_does_not_construct_or_call_provider(monkeypatch,status):
    from contextlib import nullcontext
    from types import SimpleNamespace
    task=dict(user_id='owner',project_id='project',id='task')
    snapshot=dict(execution=dict(bundle_id='bundle'))
    service=SimpleNamespace(writing=SimpleNamespace(assert_current=lambda *a: None),bundle=lambda *a: {})
    repository=SimpleNamespace(connection=lambda: nullcontext(object()),require_lease=lambda *a: task,
        require_owner=lambda *a: None,config=SimpleNamespace(environment='development'),assets=SimpleNamespace(directory=None))
    monkeypatch.setattr(live_execution,'LiveWritingService',lambda *a: service)
    monkeypatch.setattr(live_execution,'scoped_store',lambda *a: None)
    monkeypatch.setattr(live_execution,'require_live_snapshot',lambda *a: snapshot)
    monkeypatch.setattr('app.domain.manuscript_writing.service.checkpoint',lambda *a: None)
    monkeypatch.setattr('app.domain.literature_assistance.service.last_call',lambda *a: dict(status=status,provider_response_id=None))
    monkeypatch.setattr(live_execution,'capabilities',lambda: dict(real_calls_enabled=True))
    monkeypatch.setattr('app.domain.manuscript_writing.execution.wait',lambda *args: args[-2:])
    def forbidden(*args,**kwargs): raise AssertionError('Unknown submission must not construct or call provider')
    monkeypatch.setattr(live_execution,'create_production_provider',forbidden)
    monkeypatch.setattr(live_execution,'ModelGateway',forbidden)
    assert live_execution.execute_live(repository,object(),None)==('submission_unknown','model_submission_unknown')
