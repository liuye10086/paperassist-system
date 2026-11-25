"""Frozen response streaming with offline transport and accounting fixtures."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import httpx2
import pytest

from app.adapters.models.openai_responses import ModelProviderError, OpenAIResponsesProvider
from app.domain.manuscript_writing.policy import policy
from app.domain.model_usage.gateway import ModelGateway, ModelGatewayError
from tests.adapters.test_model_gateway import Service, receipt, request


FROZEN_WIRE = '{"background":true,"store":true,"stream":true}'
CONTRACT = {'response_stream': True}
MODEL = policy().model


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def delta(sequence_number, text):
    return dict(sequence_number=sequence_number, item_id='msg_fixture', output_index=1,
                content_index=0, delta=text)


def observation(status, **kwargs):
    return receipt(model=MODEL, status=status, usage=None, response={'status': status}, **kwargs)


def test_frozen_sdk_emits_created_delta_and_terminal_receipts_and_resumes_by_get(monkeypatch):
    from app.domain.manuscript_writing import frozen

    def validate_wire(wire_json, execution_contract):
        assert wire_json == FROZEN_WIRE and execution_contract == CONTRACT
        return policy()

    monkeypatch.setattr(frozen, 'validate_wire', validate_wire)
    calls = []

    def event(kind, sequence_number, status):
        response = dict(id='resp_text', status=status, model=MODEL, output=[], usage=None)
        if status == 'completed':
            response['usage'] = {'input_tokens': 12, 'output_tokens': 4, 'total_tokens': 16}
        return dict(type=kind, sequence_number=sequence_number, response=response)

    def transport(req):
        calls.append(req)
        if req.method == 'POST':
            events = [event('response.created', 0, 'queued'),
                      {'type': 'keepalive', 'sequence_number': 99},
                      {'type': 'response.output_text.delta', **delta(3, 'First part')}]
        else:
            events = [event('response.completed', 4, 'completed')]
        payload = ''.join(f'event: {value["type"]}\ndata: {json.dumps(value)}\n\n' for value in events)
        return httpx2.Response(200, text=payload, headers={'Content-Type': 'text/event-stream', 'X-Request-Id': 'req_stream'})

    provider = OpenAIResponsesProvider(api_key='synthetic-not-real',
                                       http_client=httpx2.Client(transport=httpx2.MockTransport(transport)))
    try:
        created, output = list(provider.create_frozen_events(wire_json=FROZEN_WIRE, execution_contract=CONTRACT))
        completed, = list(provider.retrieve_events('resp_text', policy=policy(), starting_after=3))
    finally:
        provider.close()

    assert created[0] == 'receipt' and created[1]['request_id'] == 'req_stream' and created[1]['status'] == 'queued'
    assert output == ('delta', delta(3, 'First part'))
    assert completed[0] == 'receipt' and completed[1]['usage'] == {'input_tokens': 12, 'output_tokens': 4, 'total_tokens': 16}
    assert [(req.method, req.url.path) for req in calls] == [('POST', '/v1/responses'), ('GET', '/v1/responses/resp_text')]
    assert calls[0].content == FROZEN_WIRE.encode() and dict(calls[1].url.params) == {'stream': 'true', 'starting_after': '3'}
    assert provider.client.max_retries == 0


@pytest.fixture
def writing(monkeypatch):
    from app.domain.manuscript_writing import authorization, frozen, live_execution
    from app.domain.report_collections import service as collections

    task = dict(id='task-1', user_id='owner', project_id='project')
    bundle = dict(wire_json=FROZEN_WIRE, execution_contract=CONTRACT)

    class WritingUsage(Service):
        def __init__(self):
            super().__init__(row={'model': MODEL, 'policy_snapshot': policy().model_dump(mode='json')})
            self.store = self
            self.config = SimpleNamespace(environment='test')
            self.mismatched = False

        @contextmanager
        def connection(self):
            self.in_transaction = True
            try:
                yield self
            finally:
                self.in_transaction = False

        def require_task(self, db, task_id):
            assert db is self and task_id == task['id']
            return task

        def execute(self, query, params):
            assert self.in_transaction and 'model_mismatch' in query and params == (self.row['id'],)
            return SimpleNamespace(fetchone=lambda: self.mismatched or None)

        def reserve_call(self, req, *, execution_lease):
            assert execution_lease == 'lease'
            return super().reserve_call(req)

        def begin_submission(self, call_id, *, execution_lease, expected_task_revision, provenance_context):
            assert execution_lease == 'lease' and expected_task_revision == 2
            return super().begin_submission(call_id, provenance_context=provenance_context)

        def record_response(self, call_id, **values):
            self.row['provider_status'] = values['status']
            self.mismatched |= values['model'] != MODEL
            return super().record_response(call_id, **values)

    monkeypatch.setattr(authorization, 'LiveWritingService', lambda _: SimpleNamespace(bundle=lambda *_: bundle))
    monkeypatch.setattr(collections, 'scoped_store', lambda *_: None)
    monkeypatch.setattr(live_execution, 'require_live_snapshot', lambda _: {'execution': {'bundle_id': 'bundle'}})
    monkeypatch.setattr(frozen, 'bundle_contract', lambda value: value['execution_contract'])
    return WritingUsage(), request(policy=policy())


class StreamingFixture:
    source_kind = 'synthetic_fixture'

    def __init__(self, usage, events):
        self.usage = usage
        self.events = events
        self.posts = 0
        self.gets = []
        self.closed = 0

    def create_frozen_events(self, *, wire_json, execution_contract):
        assert not self.usage.in_transaction and self.usage.row['status'] == 'submitting'
        assert wire_json == FROZEN_WIRE and execution_contract == CONTRACT
        self.posts += 1
        try:
            yield from self.events
            raise ModelProviderError('model_provider_request_failed')
        finally:
            self.closed += 1

    def retrieve(self, response_id, *, policy):
        assert not self.usage.in_transaction and policy.model == MODEL
        self.gets.append((response_id, None))
        return observation('in_progress')

    def retrieve_events(self, response_id, *, policy, starting_after):
        assert not self.usage.in_transaction and policy.model == MODEL
        self.gets.append((response_id, starting_after))
        try:
            yield 'delta', delta(5, 'Second part')
            yield 'receipt', observation('completed')
        finally:
            self.closed += 1


def test_gateway_records_response_before_delta_and_resumes_without_posting_again(writing):
    usage, req = writing
    provider = StreamingFixture(usage, [('delta', delta(1, 'Before receipt')),
                                        ('receipt', observation('queued')), ('delta', delta(3, 'First part'))])
    gateway = ModelGateway(usage, provider)
    deltas = []

    def receive(call, event):
        assert usage.row['provider_response_id'] == call['provider_response_id'] == 'resp_text'
        assert not usage.in_transaction
        deltas.append(event)

    pending = gateway.submit_frozen_writing(req, wire_json=FROZEN_WIRE, execution_lease='lease', on_delta=receive)
    assert pending['response']['status'] == 'in_progress'
    assert deltas == [delta(3, 'First part')]
    completed = gateway.resume_frozen_writing('call-1', starting_after=3, on_delta=receive)
    assert completed['response']['status'] == 'completed'
    assert deltas == [delta(3, 'First part'), delta(5, 'Second part')]
    assert provider.posts == 1 and provider.gets == [('resp_text', None), ('resp_text', 3)] and provider.closed == 2


def test_gateway_keeps_submission_unknown_when_stream_disconnects_before_response_id(writing):
    usage, req = writing
    provider = StreamingFixture(usage, [])
    gateway = ModelGateway(usage, provider)
    with pytest.raises(ModelGatewayError, match='统一模型调用'):
        gateway.submit_frozen_writing(req, wire_json=FROZEN_WIRE, execution_lease='lease', on_delta=None)
    second = gateway.submit_frozen_writing(req, wire_json=FROZEN_WIRE, execution_lease='lease', on_delta=None)
    assert second['call']['status'] == 'submission_unknown' and second['response'] is None
    assert provider.posts == 1 and provider.gets == [] and provider.closed == 1


def test_gateway_suppresses_deltas_from_mismatched_model_even_after_reconnect(writing):
    usage, req = writing
    wrong_model = observation('queued') | {'model': 'other-model'}
    provider = StreamingFixture(usage, [('receipt', wrong_model), ('delta', delta(3, 'Wrong model'))])
    gateway = ModelGateway(usage, provider)
    deltas = []
    receive = lambda _call, event: deltas.append(event)
    gateway.submit_frozen_writing(req, wire_json=FROZEN_WIRE, execution_lease='lease', on_delta=receive)
    gateway.resume_frozen_writing('call-1', starting_after=3, on_delta=receive)
    assert deltas == [] and provider.gets == [('resp_text', None), ('resp_text', None)]


def test_gateway_expiry_does_not_allow_a_stream_without_observation_grant(writing):
    usage, _ = writing
    usage.row.update(status='submitted', provider_status='in_progress', provider_response_id='resp_text',
                     created_at=datetime.now(timezone.utc) - timedelta(hours=1))
    provider = StreamingFixture(usage, [])
    gateway = ModelGateway(usage, provider)
    with pytest.raises(ModelGatewayError) as exc:
        gateway.resume_frozen_writing('call-1', starting_after=3, on_delta=None)
    assert exc.value.code == 'model_observation_expired' and provider.gets == []


def test_gateway_closes_stream_after_failed_delta_write(writing):
    usage, req = writing
    provider = StreamingFixture(usage, [('receipt', observation('queued')), ('delta', delta(3, 'First part'))])

    def cannot_write(_call, _event):
        raise RuntimeError('write stopped')

    with pytest.raises(RuntimeError, match='write stopped'):
        ModelGateway(usage, provider).submit_frozen_writing(req, wire_json=FROZEN_WIRE, execution_lease='lease', on_delta=cannot_write)
    assert provider.closed == 1 and usage.row['provider_response_id'] == 'resp_text' and provider.gets == []


@pytest.mark.parametrize('environment, fixture, allowed', [('test', True, True), ('test', False, False), ('development', True, False)])
def test_legacy_provider_fallback_is_limited_to_admitted_test_fixture(writing, environment, fixture, allowed):
    usage, req = writing
    usage.config.environment = environment
    posts = []

    def create_frozen(*, wire_json, execution_contract):
        assert usage.row['status'] == 'submitting'
        posts.append((wire_json, execution_contract))
        return observation('completed')

    provider = SimpleNamespace(source_kind='synthetic_fixture' if fixture else None, create_frozen=create_frozen)
    gateway = ModelGateway(usage, provider)
    if allowed:
        result = gateway.submit_frozen_writing(req, wire_json=FROZEN_WIRE, execution_lease='lease')
        assert result['response']['status'] == 'completed' and posts == [(FROZEN_WIRE, CONTRACT)]
    else:
        with pytest.raises(ModelGatewayError):
            gateway.submit_frozen_writing(req, wire_json=FROZEN_WIRE, execution_lease='lease')
        assert posts == [] and usage.row['status'] == 'reserved'
