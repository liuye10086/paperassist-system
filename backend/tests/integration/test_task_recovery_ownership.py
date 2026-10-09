"""Real authenticated recovery boundaries in disposable PostgreSQL schemas."""
import json
from uuid import uuid4

import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.api.test_explanation_tasks import transition
from tests.api.test_plot_tasks import policy, post, prepared  # noqa: F401
from tests.api.test_task_request_id import assert_request_id
from tests.integration.test_project_ownership import account_client
from tests.integration.test_task_resume import request_for


BUSINESS_TABLES = (
    'projects', 'files', 'analysis_setups', 'analysis_runs', 'figures',
    'figure_jobs', 'explanations', 'explanation_jobs', 'reports',
    'tasks', 'task_attempts', 'task_events', 'task_outbox', 'task_waits',
    'task_resume_requests', 'model_calls', 'model_budgets', 'usage_events',
    'budget_reservations',
)
RECOVERY_ROUTES = ('budget_resume', 'failed_retry', 'failed_resume_retry')


@pytest.fixture
def other_account():
    clients = []

    def create(role):
        other, created = account_client('recovery-' + uuid4().hex + '@example.test', role=role)
        clients.append(other)
        identity = other.get('/api/v1/auth/me')
        assert identity.status_code == 200
        assert identity.json()['user']['id'] == created['id']
        assert identity.json()['user']['role'] == role
        assert other.cookies.get('paperassist_session')
        with database_connection() as db:
            assert db.execute('SELECT active FROM users WHERE id=%s', (created['id'],)).fetchone()['active']
        return other, created

    yield create
    for instance in clients:
        instance.close()


def business_snapshot():
    # Authentication legitimately refreshes sessions.last_seen_at on requests.
    # Compare every column/row of all 19 business tables, excluding auth tables.
    with database_connection() as db:
        return {table: [row['payload'] for row in db.execute(
            f'SELECT to_jsonb(item) AS payload FROM {table} item ORDER BY to_jsonb(item)::text')]
            for table in BUSINESS_TABLES}


def recovery_request(client, route):
    _, _, result, url = prepared(client)
    response = post(client, url)
    assert response.status_code == 202, response.text
    task = response.json()['task']
    if route == 'budget_resume':
        task = transition(client, task, 'waiting_confirmation', 'budget_exceeded')
        body = request_for(task)
    else:
        task = transition(client, task, 'failed', 'execution_failed', 'task_worker_interrupted')
        body = {'operation': 'retry', 'wait_id': None,
                'expected_task_revision': task['revision'], 'input_version': task['input_version']}
    suffix = 'retry' if route == 'failed_retry' else 'resume'
    if suffix == 'retry':
        body = {'expected_revision': task['revision']}
    return task, '/api/v1/tasks/' + task['id'] + '/' + suffix, body, url.split('/analysis-runs/')[0], result


def send(client, endpoint, body, key='owner-recovery'):
    return client.post(endpoint, json=body, headers={'Idempotency-Key': key})


def assert_safe_error(response, status, code):
    assert response.status_code == status, response.text
    assert_request_id(response)
    detail = response.json()['detail']
    assert set(detail) == {'code', 'message', 'params', 'details', 'request_id'}
    assert detail['code'] == code
    assert detail['params'] == {} and detail['details'] == {}
    assert detail['request_id'] == response.headers['X-Request-ID']


@pytest.mark.parametrize('role', ['user', 'admin'])
@pytest.mark.parametrize('route', RECOVERY_ROUTES)
def test_foreign_recovery_is_read_only_then_owner_same_body_succeeds(client, cloud, policy, other_account, role, route):
    task, endpoint, body, _, _ = recovery_request(client, route)
    other, identity = other_account(role)
    owner = client.get('/api/v1/auth/me').json()['user']
    assert identity['id'] != owner['id']
    before = business_snapshot()
    denied = send(other, endpoint, body)
    assert_safe_error(denied, 404, 'task_not_found')
    assert business_snapshot() == before
    assert cloud.calls == []

    accepted_response = send(client, endpoint, body)
    assert accepted_response.status_code == 202, accepted_response.text
    assert_request_id(accepted_response)
    accepted = accepted_response.json()
    assert accepted['id'] == task['id'] and accepted['status'] == 'queued'
    assert accepted['revision'] == task['revision'] + 1
    assert accepted['input_version'] == task['input_version']
    after = business_snapshot()
    assert len(after['tasks']) == len(before['tasks']) == 1
    for table in ('task_events', 'task_outbox'):
        assert len(after[table]) == len(before[table]) + 1
    event = next(row for row in after['task_events'] if row['task_revision'] == accepted['revision'])
    assert event['event_type'] == 'requeued'
    outbox = [row for row in after['task_outbox'] if row['task_revision'] == accepted['revision']]
    assert len(outbox) == 1
    if route == 'budget_resume':
        assert len(after['task_waits']) == 1
        wait = after['task_waits'][0]
        assert wait['id'] == body['wait_id'] and wait['status'] == 'resolved'
        assert wait['resolved_task_revision'] == accepted['revision']
    else:
        assert after['task_waits'] == []
    if endpoint.endswith('/resume'):
        assert len(after['task_resume_requests']) == 1
        receipt = after['task_resume_requests'][0]
        assert receipt['user_id'] == owner['id'] and receipt['response_json'] == accepted
    else:
        assert after['task_resume_requests'] == []
    changed = {'tasks', 'task_events', 'task_outbox', 'task_waits', 'task_resume_requests'}
    assert {table: rows for table, rows in before.items() if table not in changed} == {
        table: rows for table, rows in after.items() if table not in changed}

    replay = send(client, endpoint, body)
    assert replay.status_code == 202, replay.text
    assert replay.json() == accepted
    assert_request_id(replay)
    assert business_snapshot() == after
    # An existing owner receipt/event must not authorize a stranger's replay.
    assert_safe_error(send(other, endpoint, body), 404, 'task_not_found')
    assert business_snapshot() == after

    if endpoint.endswith('/resume'):
        assert_safe_error(send(client, endpoint, body, key='different-key'), 409, 'task_revision_conflict')
        changed_body = {**body, 'expected_task_revision': task['revision'] - 1}
        assert_safe_error(send(client, endpoint, changed_body), 409, 'task_idempotency_conflict')
    else:
        assert_safe_error(send(client, endpoint, {'expected_revision': 1}), 409, 'task_revision_conflict')
    assert business_snapshot() == after and cloud.calls == []
    print(json.dumps({'role': role, 'route': route, 'denied': denied.status_code,
                      'accepted': accepted_response.status_code, 'revision': [task['revision'], accepted['revision']],
                      'before': {table: len(rows) for table, rows in before.items()},
                      'after': {table: len(rows) for table, rows in after.items()}}, sort_keys=True))


@pytest.mark.parametrize('field,code', [
    ('revision', 'task_revision_conflict'), ('wait', 'task_revision_conflict'),
    ('input_version', 'task_source_conflict'),
])
def test_budget_resume_rejects_stale_request_without_business_writes(client, cloud, policy, field, code):
    task, endpoint, body, _, _ = recovery_request(client, 'budget_resume')
    if field == 'revision':
        body = {**body, 'expected_task_revision': task['revision'] - 1}
    elif field == 'wait':
        body = {**body, 'wait_id': str(uuid4())}
    else:
        body = {**body, 'input_version': {**body['input_version'], 'setup_revision': 2}}
    before = business_snapshot()
    assert_safe_error(send(client, endpoint, body), 409, code)
    assert business_snapshot() == before and cloud.calls == []


def test_failed_retry_rejects_stale_revision_before_acceptance(client, cloud, policy):
    _, endpoint, body, _, _ = recovery_request(client, 'failed_retry')
    before = business_snapshot()
    assert_safe_error(send(client, endpoint, {**body, 'expected_revision': 1}), 409, 'task_revision_conflict')
    assert business_snapshot() == before and cloud.calls == []


@pytest.mark.parametrize('route', RECOVERY_ROUTES)
def test_recovery_rejects_changed_source_without_business_writes(client, cloud, policy, route):
    _, endpoint, body, base, result = recovery_request(client, route)
    changed = client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'changed'})
    assert changed.status_code == 200, changed.text
    before = business_snapshot()
    assert_safe_error(send(client, endpoint, body), 409, 'task_source_conflict')
    assert business_snapshot() == before and cloud.calls == []
