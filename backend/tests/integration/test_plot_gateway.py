"""Plot side effects use isolated PostgreSQL and synthetic providers only."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from app.adapters.task_execution_store import LeaseLost, TaskLease
from app.adapters.models.openai_responses import ModelProviderError
from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.domain.model_usage.contracts import CallRequest, ModelPolicy
from app.domain.model_usage.gateway import ModelGateway, ModelGatewayError, input_digest
from tests.domain.test_plot_policy import execution_policy
from tests.integration.test_model_usage import configure
from tests.api.test_analysis import client  # noqa: F401

INSTRUCTIONS = 'Synthetic trusted instructions'
PAYLOAD = {'values': [1, 2, 3]}


@pytest.fixture
def context(client, postgres_schema):
    from tests.helpers.tasks import boxplot_task_input, task_owner
    from app.domain.tasks.service import TaskService
    from app.domain.model_usage.service import ModelUsageService
    project, request, *_ = boxplot_task_input(client)
    owner = task_owner(client)
    task, _ = TaskService(owner).create(project, request, idempotency_key='plot-gateway')
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='running',revision=2,current_attempt=1 WHERE id=%s", (task['id'],))
    return ModelUsageService(owner, postgres_schema), owner, project, task['id']


def setup(context):
    service = configure(context, limit=10000)
    task = context[3]
    with database_connection(write=True) as db:
        db.execute('''INSERT INTO task_attempts
            (id,task_id,attempt_no,status,started_at,lease_owner,lease_expires_at,heartbeat_at)
            VALUES (%s,%s,1,'running',clock_timestamp(),'synthetic-owner',
                    clock_timestamp()+interval '5 minutes',clock_timestamp())''', (str(uuid4()), task))
    lease = TaskLease(task, 1, 'synthetic-owner')
    assert 'tool_reserve_version' in CallRequest.model_fields, 'Tool reservation version is not frozen'
    request = CallRequest(task_id=task, expected_task_revision=2, call_key='boxplot:v1',
        input_digest=input_digest(instructions=INSTRUCTIONS, payload=PAYLOAD),
        policy=ModelPolicy.model_validate(execution_policy()['policy']), input_token_allowance=100,
        tool_reserve_micro_usd=300, tool_reserve_version='synthetic-tool-v1')
    return service, request, lease


def receipt():
    return {'response_id': 'resp_plot', 'request_id': 'req_response', 'model': 'test-model', 'status': 'completed',
        'usage': {'input_tokens': 50, 'output_tokens': 5,
                  'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}},
        'response': {'id': 'resp_plot', 'status': 'completed', 'output': []}}


class Provider:
    def __init__(self, error_step=None):
        self.calls = []
        self.error_step = error_step

    def effect(self, step):
        self.calls.append(step)
        with database_connection() as db:
            row = dict(db.execute('SELECT * FROM model_calls').fetchone())
        assert row['status'] == 'submitting'
        assert row['provider_state']['phase'] == {'container': 'container_creating',
            'upload': 'file_uploading', 'response': 'response_creating'}[step]
        if self.error_step == step:
            raise TimeoutError('private request may have completed')

    def create_container(self, **kwargs):
        self.effect('container')
        return {'container_id': 'cntr_plot', 'request_id': 'req_container'}

    def upload_input(self, **kwargs):
        self.effect('upload')
        assert kwargs['container_id'] == 'cntr_plot' and kwargs['payload'] == PAYLOAD
        return {'input_file_id': 'cfile_plot', 'input_file_path': '/mnt/data/prefix_data.json', 'request_id': 'req_upload'}

    def create_plot(self, **kwargs):
        self.effect('response')
        assert kwargs['container_id'] == 'cntr_plot' and kwargs['input_file_path'] == '/mnt/data/prefix_data.json'
        return receipt()

    def retrieve(self, response_id, **kwargs):
        self.calls.append('GET')
        assert response_id == 'resp_plot'
        return receipt()


def submit(gateway, request, lease):
    assert hasattr(gateway, 'submit_plot'), 'Plot gateway is not implemented'
    return gateway.submit_plot(request, instructions=INSTRUCTIONS, payload=PAYLOAD, execution_lease=lease)


def test_three_single_post_slices_persist_receipts_and_hold_unknown_tool_cost(context):
    service, request, lease = setup(context)
    provider = Provider()
    gateway = ModelGateway(service, provider)
    for phase in ('container_ready', 'file_ready', 'response_ready'):
        output = submit(gateway, request, lease)
        assert output['call']['provider_state']['phase'] == phase
    assert provider.calls == ['container', 'upload', 'response']
    assert output['call']['usage_status'] == 'pending' and output['call']['estimated_cost_micro_usd'] == 60
    assert output['call']['policy_snapshot']['tool_reserve_version'] == 'synthetic-tool-v1'
    usage = service.task_usage(context[3])
    assert usage['estimated_micro_usd'] == 60 and usage['reserved_micro_usd'] == 360
    submit(gateway, request, lease)
    assert provider.calls == ['container', 'upload', 'response', 'GET']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM usage_events').fetchone()['n'] == 1
        assert db.execute('SELECT reason_code FROM usage_events').fetchone()['reason_code'] == 'tool_cost_unknown'


@pytest.mark.parametrize('error_step', ['container', 'upload', 'response'])
def test_unknown_post_is_never_repeated_and_reservation_cannot_be_released(context, error_step):
    service, request, lease = setup(context)
    provider = Provider(error_step)
    gateway = ModelGateway(service, provider)
    for _ in range(['container', 'upload', 'response'].index(error_step)):
        submit(gateway, request, lease)
    with pytest.raises(ModelGatewayError):
        submit(gateway, request, lease)
    call = submit(gateway, request, lease)['call']
    assert call['status'] == 'submission_unknown' and provider.calls.count(error_step) == 1
    with pytest.raises(StorageError):
        service.release_unsubmitted(call['id'], event_key='release', reason_code='test')
    assert service.task_usage(context[3])['reserved_micro_usd'] == 420


def test_ready_phase_allows_new_revision_but_rejects_expired_lease(context):
    service, request, lease = setup(context)
    provider = Provider()
    gateway = ModelGateway(service, provider)
    submit(gateway, request, lease)
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second'")
    with pytest.raises(LeaseLost):
        submit(gateway, request, lease)
    assert provider.calls == ['container']
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET revision=3")
        db.execute("UPDATE task_attempts SET lease_owner='new-owner',lease_expires_at=clock_timestamp()+interval '5 minutes'")
    new_lease = replace(lease, lease_owner='new-owner')
    result = submit(gateway, request.model_copy(update={'expected_task_revision': 3}), new_lease)
    assert result['call']['provider_state']['phase'] == 'file_ready'
    assert provider.calls == ['container', 'upload']


def test_late_container_receipt_is_saved_once_but_cannot_authorize_next_post(context):
    service, request, lease = setup(context)
    call = service.reserve_call(request, execution_lease=lease)
    assert service.begin_plot_step(call['id'], 'container', execution_lease=lease, expected_task_revision=2)
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second'")
    recorded = service.record_plot_step(call['id'], 'container', container_id='cntr_late', request_id='req_late')
    assert recorded['provider_state']['container_id'] == 'cntr_late'
    assert service.record_plot_step(call['id'], 'container', container_id='cntr_late', request_id='req_late') == recorded
    with pytest.raises(StorageError):
        service.record_plot_step(call['id'], 'container', container_id='cntr_changed')
    with pytest.raises(LeaseLost):
        service.begin_plot_step(call['id'], 'upload', execution_lease=lease, expected_task_revision=2)


def test_actual_tokens_above_allowance_cannot_consume_unknown_tool_reserve(context):
    service, request, lease = setup(context)
    provider = Provider()
    gateway = ModelGateway(service, provider)
    for _ in range(2):
        submit(gateway, request, lease)
    def expensive(**kwargs):
        provider.effect('response')
        value = receipt()
        value['usage']['input_tokens'] = 1000
        return value
    provider.create_plot = expensive
    submit(gateway, request, lease)
    usage = service.task_usage(context[3])
    assert usage['estimated_micro_usd'] == 1010
    assert usage['reserved_micro_usd'] == 300
    assert usage['task_budget']['available_micro_usd'] == 8690


def test_tool_version_and_input_are_frozen_and_no_lease_cannot_post(context):
    service, request, lease = setup(context)
    gateway = ModelGateway(service, Provider())
    submit(gateway, request, lease)
    for change in ({'input_digest': 'f' * 64}, {'tool_reserve_version': 'v2'}):
        with pytest.raises((StorageError, ModelGatewayError)):
            submit(gateway, request.model_copy(update=change), lease)
    with pytest.raises((StorageError, ModelGatewayError, LeaseLost)):
        submit(gateway, request, None)


def test_concurrent_fence_authorizes_only_one_container_post(context):
    service, request, lease = setup(context)
    call = service.reserve_call(request, execution_lease=lease)
    barrier = Barrier(3)
    def claim(_):
        barrier.wait(timeout=5)
        return service.begin_plot_step(call['id'], 'container', execution_lease=lease, expected_task_revision=2)
    with ThreadPoolExecutor(max_workers=3) as pool:
        allowed = list(pool.map(claim, range(3)))
    assert allowed.count(True) == 1
    assert service.get_call(call['id'])['provider_state']['phase'] == 'container_creating'


@pytest.mark.parametrize('step', ['container', 'upload', 'response'])
def test_receipt_persistence_failure_leaves_post_fenced(context, monkeypatch, step):
    service, request, lease = setup(context)
    provider = Provider()
    gateway = ModelGateway(service, provider)
    for _ in range(['container', 'upload', 'response'].index(step)):
        submit(gateway, request, lease)
    method = 'record_response' if step == 'response' else 'record_plot_step'
    def reject(*args, **kwargs):
        raise RuntimeError('synthetic persistence interruption')
    with monkeypatch.context() as patch:
        patch.setattr(service, method, reject)
        with pytest.raises(ModelGatewayError) as error:
            submit(gateway, request, lease)
        assert error.value.code == 'model_receipt_persistence_failed'
    call = submit(gateway, request, lease)['call']
    assert call['status'] == 'submission_unknown' and provider.calls.count(step) == 1
    assert service.task_usage(context[3])['reserved_micro_usd'] == 420


def test_old_text_snapshot_without_tool_version_replays_without_overwriting_it(context):
    from tests.integration.test_model_usage import request as text_request
    service = configure(context)
    request = text_request(context[3])
    call = service.reserve_call(request)
    with database_connection(write=True) as db:
        db.execute("UPDATE model_calls SET policy_snapshot=policy_snapshot-'tool_reserve_version'")
    replay = service.reserve_call(request)
    assert replay['id'] == call['id']
    assert 'tool_reserve_version' not in replay['policy_snapshot']


@pytest.mark.parametrize('status', [404, 410])
def test_definite_expired_upload_is_failed_evidence_with_held_budget_not_unknown(context, status):
    service, request, lease = setup(context)
    provider = Provider()
    gateway = ModelGateway(service, provider)
    submit(gateway, request, lease)
    def expired(**kwargs):
        provider.effect('upload')
        raise ModelProviderError('plot_container_expired', status_code=status, request_id='req_expired')
    provider.upload_input = expired
    with pytest.raises(ModelGatewayError) as error:
        submit(gateway, request, lease)
    assert error.value.code == 'plot_container_expired'
    call = submit(gateway, request, lease)['call']
    assert call['status'] == 'failed' and call['error_code'] == 'plot_container_expired'
    assert call['provider_state']['container_id'] == 'cntr_plot'
    assert call['provider_state']['upload_request_id'] == 'req_expired'
    assert call['provider_response_id'] is None and call['usage_status'] == 'pending'
    assert provider.calls == ['container', 'upload']
    assert service.task_usage(context[3])['reserved_micro_usd'] == 420
    with pytest.raises(StorageError):
        service.release_unsubmitted(call['id'], event_key='release', reason_code='expired')


@pytest.mark.parametrize('step', ['container', 'upload'])
def test_receipt_commit_ack_loss_does_not_downgrade_durable_ready_phase(context, monkeypatch, step):
    service, request, lease = setup(context)
    provider = Provider()
    gateway = ModelGateway(service, provider)
    if step == 'upload':
        submit(gateway, request, lease)
    original = service.record_plot_step

    def committed_then_lost(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('Synthetic lost commit acknowledgement')

    with monkeypatch.context() as patch:
        patch.setattr(service, 'record_plot_step', committed_then_lost)
        with pytest.raises(ModelGatewayError):
            submit(gateway, request, lease)
    with database_connection() as db:
        call = db.execute('SELECT * FROM model_calls').fetchone()
        assert call['status'] == 'submitting'
        assert call['provider_state']['phase'] == ('container_ready' if step == 'container' else 'file_ready')
        assert db.execute("SELECT count(*) AS n FROM budget_reservations WHERE status='held'").fetchone()['n'] == 3
    submit(gateway, request, lease)
    assert provider.calls == (['container', 'upload'] if step == 'container' else ['container', 'upload', 'response'])
