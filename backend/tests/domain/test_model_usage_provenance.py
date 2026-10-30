"""Admission source evidence; no network, database, credentials or model calls."""
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def module():
    assert (Path(__file__).parents[2] / 'app/domain/model_usage/provenance.py').exists(), 'Missing trusted admission provenance'
    return import_module('app.domain.model_usage.provenance')


def request(**changes):
    from tests.domain.test_model_pricing import policy
    return SimpleNamespace(**(dict(task_id='task-1', input_digest='a'*64, policy=policy()) | changes))


def subject(**changes):
    return dict(id='call-1', task_id='task-1', input_digest='a'*64,
                task_type='explanation', workflow_version='explanation_v1',
                provider='openai', provider_state={}, policy_snapshot={}) | changes


def task(**changes):
    return dict(id='task-1', task_type='explanation', workflow_version='explanation_v1') | changes


def test_default_official_transport_is_distinct_from_injection_and_subclass():
    p=module()
    from app.adapters.models.openai_responses import OpenAIResponsesProvider
    class Unapproved(OpenAIResponsesProvider): pass
    providers=[OpenAIResponsesProvider(api_key='offline-test-only'),
               OpenAIResponsesProvider(api_key='offline-test-only', http_client=httpx2.Client(transport=httpx2.MockTransport(lambda r:pytest.fail('network forbidden')))),
               Unapproved(api_key='offline-test-only')]
    try:
        for provider, expected in zip(providers,['openai_live',None,None]):
            provider.source_kind='openai_live'
            context=p.admission_context(provider,request=request(),operation='text')
            state=p.apply_admission_provenance(subject(),task(),context)
            assert p.public_provider_provenance(subject(provider_state=state))==expected
    finally:
        for provider in providers: provider.close()


def test_new_unknown_blocks_old_writing_flag_and_does_not_change_old_records():
    p=module()
    call=subject(task_type='manuscript_writing',workflow_version='manuscript_writing_v2',provider_state={'writing_provider_provenance':'openai_live'})
    before=deepcopy(call)
    assert p.public_provider_provenance(call)=='openai_live'
    context=p.admission_context(SimpleNamespace(source_kind='openai_live'),request=request(),operation='frozen_writing')
    state=p.apply_admission_provenance(call,task(task_type='manuscript_writing',workflow_version='manuscript_writing_v2'),context)
    assert state['submission_provenance']['kind']=='unknown'
    assert p.public_provider_provenance({**call,'provider_state':state}) is None
    assert call==before
    assert p.public_provider_provenance(subject(provider_state={'writing_provider_provenance':'openai_live'})) is None


@pytest.mark.parametrize('mutation',[{'task_id':'other'},{'input_digest':'b'*64}])
def test_context_cannot_be_rebound_to_another_call(mutation):
    p=module();context=p.admission_context(SimpleNamespace(source_kind='synthetic_fixture'),request=request(),operation='text')
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError):p.apply_admission_provenance(subject(**mutation),task(),context)


def test_json_cannot_forge_context_and_payload_flags_never_prove_live():
    p=module()
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError):p.apply_admission_provenance(subject(),task(),{'kind':'openai_live'})
    assert p.public_provider_provenance(subject(input_snapshot={'provenance':'openai_live'},provider_state={'source_kind':'openai_live','provider_provenance':'openai_live'})) is None
    from app.domain.model_usage.contracts import CallRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):CallRequest.model_validate({'provenance':'openai_live'})


def test_explicit_fixture_stays_synthetic_even_with_live_writing_legacy_flag():
    p=module();context=p.admission_context(SimpleNamespace(source_kind='synthetic_fixture'),request=request(),operation='text')
    state=p.apply_admission_provenance(subject(provider_state={'writing_provider_provenance':'openai_live'}),task(),context)
    assert p.public_provider_provenance(subject(provider_state=state))=='synthetic_fixture'


def test_reader_rejects_mismatched_or_malformed_saved_evidence():
    p=module()
    from app.adapters.models.openai_responses import OpenAIResponsesProvider
    provider=OpenAIResponsesProvider(api_key='offline-test-only')
    try:state=p.apply_admission_provenance(subject(),task(),p.admission_context(provider,request=request(),operation='text'))
    finally:provider.close()
    for field,value in [('task_id','other'),('input_digest','b'*64),('version',2),('transport','injected'),('adapter','unapproved')]:
        changed=deepcopy(state);changed['submission_provenance'][field]=value
        assert p.public_provider_provenance(subject(provider_state=changed)) is None
    assert p.public_provider_provenance(subject(provider_state={'submission_provenance':None,'writing_provider_provenance':'openai_live'})) is None


def test_batch06_requires_ledger_authorization_even_before_transport_classification(tmp_path):
    p=module()
    from tests.domain.test_literature_batch06 import ledger_at,INSTRUCTIONS,PAYLOAD,SCHEMA
    from app.domain.literature_live.batch06 import Batch06ModelProvider
    from app.domain.literature_live.policy import LivePolicyError
    from app.domain.model_usage.gateway import input_digest
    provider=Batch06ModelProvider(ledger_at(tmp_path),task_id='task-0',snapshot_digest='0'*64,api_key='offline-test-only')
    req=request(task_id='task-0',input_digest=input_digest(instructions=INSTRUCTIONS,payload=PAYLOAD),policy=provider.policy)
    try:
        with pytest.raises(LivePolicyError):p.admission_context(provider,request=req,operation='text')
        provider.authorize_task(dict(id='task-0',input_digest='0'*64),config=SimpleNamespace(environment='test',schema=SCHEMA,url=SimpleNamespace(database='paperassist_system_test')),instructions=INSTRUCTIONS,payload=PAYLOAD)
        context=p.admission_context(provider,request=req,operation='text')
        call=subject(task_id='task-0',input_digest=req.input_digest,task_type='literature_assistance',workflow_version='literature_assistance_v1')
        state=p.apply_admission_provenance(call,task(id='task-0',task_type='literature_assistance',workflow_version='literature_assistance_v1'),context)
        assert p.public_provider_provenance({**call,'provider_state':state})=='openai_live'
        with pytest.raises(LivePolicyError):p.admission_context(provider,request=request(policy=provider.policy),operation='text')
    finally:provider.close()


def test_plot_context_only_labels_matching_plot_operation():
    p=module()
    from app.adapters.models.openai_plot import OpenAIPlotProvider
    provider=OpenAIPlotProvider(api_key='offline-test-only')
    try:
        context=p.admission_context(provider,request=request(),operation='plot')
        call=subject(task_type='boxplot',workflow_version='boxplot_v1')
        state=p.apply_admission_provenance(call,task(task_type='boxplot',workflow_version='boxplot_v1'),context)
        assert p.public_provider_provenance({**call,'provider_state':state})=='openai_live'
        wrong=p.apply_admission_provenance(subject(),task(),context)
        assert p.public_provider_provenance(subject(provider_state=wrong)) is None
    finally:provider.close()
