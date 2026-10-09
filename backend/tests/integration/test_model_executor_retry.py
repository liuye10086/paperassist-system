"""Finite GET/download retries using disposable PostgreSQL and synthetic providers."""
import pytest

from app.adapters.models.openai_responses import ModelProviderError
from app.adapters.task_execution_store import TaskExecutionStore
from app.adapters.task_store import TaskStore
from app.db.database import DatabaseConnection, database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanation_execution import execution_setup, SyntheticProvider, run as run_explanation
from tests.integration.test_boxplot_execution import queued, SyntheticPlotProvider, run as run_plot, until_response


def prepared(client, kind):
    if kind == 'explanation':
        task, owner, *_ = execution_setup(client)
        provider = SyntheticProvider(pending=True)
        execute = run_explanation
        current = execute(task, provider)
    else:
        task, owner, _, result = queued(client)
        provider = SyntheticPlotProvider(result)
        execute = run_plot
        current = until_response(task, provider)
    return current, owner, provider, execute


def failed_read(provider, error):
    def retrieve(response_id, *, policy):
        provider.gets.append(response_id)
        raise error
    provider.retrieve = retrieve


@pytest.mark.parametrize('kind', ['explanation', 'boxplot'])
@pytest.mark.parametrize('status,code', [(401, 'model_authentication_failed'),
    (403, 'model_permission_denied'), (400, 'model_request_rejected'), (501, 'model_request_rejected')])
def test_permanent_read_failure_stops_immediately(client, cloud, kind, status, code):
    current, _, provider, execute = prepared(client, kind)
    posts = len(provider.posts)
    failed_read(provider, ModelProviderError(status_code=status))
    failed = execute(current, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == code
    assert failed['retry_count'] == 0 and len(provider.posts) == posts
    assert execute(failed, provider) is None


@pytest.mark.parametrize('kind', ['explanation', 'boxplot'])
@pytest.mark.parametrize('status', [None, 429, 500, 502, 503, 504])
def test_fourth_temporary_read_failure_stops_after_10_30_90(client, cloud, kind, status):
    current, owner, provider, execute = prepared(client, kind)
    posts = len(provider.posts)
    failed_read(provider, ModelProviderError(status_code=status))
    for count, delay in enumerate((10, 30, 90), 1):
        current = execute(current, provider)
        assert current['status'] == 'running' and current['retry_count'] == count
        event = TaskStore(owner).events(current['id'])['items'][-1]
        assert event['event_type'] == 'deferred'
        assert event['error_code'] == 'model_provider_unavailable'
        assert event['error_category'] == 'temporary'
        assert event['retry_reason'] == 'temporary_provider_error'
        assert event['retry_count'] == count and event['retry_delay_seconds'] == delay
        with database_connection() as db:
            row = db.execute('SELECT * FROM task_outbox ORDER BY task_revision DESC LIMIT 1').fetchone()
            assert (row['available_at'] - row['created_at']).total_seconds() >= delay
    current = execute(current, provider)
    assert current['status'] == 'failed' and current['retry_count'] == 3
    assert current['error_code'] == 'model_provider_unavailable'
    event = TaskStore(owner).events(current['id'])['items'][-1]
    assert event['retry_count'] == 3 and event['retry_delay_seconds'] is None
    assert execute(current, provider) is None and len(provider.posts) == posts
    with database_connection() as db:
        assert db.execute('SELECT provider_response_id FROM model_calls').fetchone()['provider_response_id']
        assert {row['status'] for row in db.execute('SELECT status FROM budget_reservations')} == {'held'}


@pytest.mark.parametrize('kind', ['explanation', 'boxplot'])
def test_normal_pending_poll_does_not_consume_or_reset_retry_count(client, cloud, kind):
    current, owner, provider, execute = prepared(client, kind)
    assert current['retry_count'] == 0
    original = provider.retrieve
    failed_read(provider, ModelProviderError(status_code=503))
    current = execute(current, provider)
    provider.retrieve = original
    current = execute(current, provider)
    assert current['status'] == 'running' and current['retry_count'] == 1
    event = TaskStore(owner).events(current['id'])['items'][-1]
    assert all(event[field] is None for field in (
        'error_code', 'error_category', 'retry_reason', 'retry_count', 'retry_delay_seconds'))
    failed_read(provider, ModelProviderError(status_code=429))
    current = execute(current, provider)
    assert current['retry_count'] == 2
    assert TaskStore(owner).events(current['id'])['items'][-1]['retry_delay_seconds'] == 30


def test_plot_download_and_refresh_share_one_persistent_retry_budget(client):
    current, owner, provider, execute = prepared(client, 'boxplot')
    provider.pending, provider.fail_download = False, True
    current = execute(current, provider)
    assert current['retry_count'] == 1
    original = provider.retrieve
    failed_read(provider, ModelProviderError(status_code=503))
    current = execute(current, provider)
    assert current['retry_count'] == 2
    provider.retrieve = original
    current = execute(current, provider)
    assert current['retry_count'] == 3
    failed = execute(current, provider)
    assert failed['status'] == 'failed' and failed['retry_count'] == 3
    assert len(provider.posts) == 3
    assert [event['retry_delay_seconds'] for event in TaskStore(owner).events(failed['id'])['items']
            if event['error_code'] == 'model_provider_unavailable'] == [10, 30, 90, None]


@pytest.mark.parametrize('shape,code', [('invalid_json', 'plot_invalid_result'),
    ('invalid_png', 'plot_invalid_image'), ('mismatch', 'plot_result_mismatch')])
def test_plot_download_validation_retains_explicit_output_failure(client, shape, code):
    current, _, provider, execute = prepared(client, 'boxplot')
    provider.pending = False
    if shape == 'invalid_png':
        provider.png = b'invalid image'
    elif shape == 'mismatch':
        provider.corrupt = True
    else:
        download = provider.download
        provider.download = lambda file_id, *args, **kwargs: (
            b'{invalid' if file_id == 'cfile_result' else download(file_id, *args, **kwargs))
    failed = execute(current, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == code
    assert failed['retry_count'] == 0 and len(provider.posts) == 3
    with database_connection() as db:
        assert db.execute('SELECT provider_status FROM model_calls').fetchone()['provider_status'] == 'completed'
        assert not db.execute('SELECT id FROM figures').fetchall()


@pytest.mark.parametrize('kind', ['explanation', 'boxplot'])
@pytest.mark.parametrize('error', [RuntimeError('private error'), ModelProviderError('arbitrary_private_code', status_code=503)])
def test_unclassified_read_failure_is_internal_and_never_retried(client, cloud, kind, error):
    current, _, provider, execute = prepared(client, kind)
    failed_read(provider, error)
    failed = execute(current, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == 'internal_error'
    assert failed['retry_count'] == 0


@pytest.mark.parametrize('error,code', [(ModelProviderError(status_code=401), 'model_authentication_failed'),
    (ModelProviderError(status_code=403), 'model_permission_denied'),
    (ModelProviderError(status_code=400), 'model_request_rejected'),
    (ModelProviderError('arbitrary_private_code', status_code=503), 'internal_error'),
    (RuntimeError('private error'), 'internal_error')])
def test_plot_download_permanent_or_unknown_error_does_not_retry(client, error, code):
    current, _, provider, execute = prepared(client, 'boxplot')
    provider.pending = False
    def reject(*args, **kwargs):
        raise error
    provider.download = reject
    failed = execute(current, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == code
    assert failed['retry_count'] == 0 and len(provider.posts) == 3


@pytest.mark.parametrize('status', [401, 429, 503])
@pytest.mark.parametrize('kind', ['explanation', 'boxplot'])
def test_unknown_post_outcome_waits_without_spending_read_retry_budget(client, cloud, kind, status):
    if kind == 'explanation':
        task, owner, *_ = execution_setup(client)
        provider, execute = SyntheticProvider(), run_explanation
        def reject(**kwargs):
            provider.posts.append('response')
            raise ModelProviderError(status_code=status)
        provider.create = reject
    else:
        task, owner, _, result = queued(client)
        provider, execute = SyntheticPlotProvider(result), run_plot
        def reject(**kwargs):
            provider.posts.append('container')
            raise ModelProviderError(status_code=status)
        provider.create_container = reject
    current = execute(task, provider)
    assert current['status'] == 'waiting_confirmation' and current['reason_code'] == 'submission_unknown'
    assert current['retry_count'] == 0
    assert execute(current, provider) is None and len(provider.posts) == 1
    with database_connection() as db:
        assert {row['status'] for row in db.execute('SELECT status FROM budget_reservations')} == {'held'}


@pytest.mark.parametrize('kind', ['explanation', 'boxplot'])
def test_initial_receipt_persistence_failure_is_recovered_as_unknown_without_repost(client, cloud, kind, monkeypatch):
    if kind == 'explanation':
        task, owner, *_ = execution_setup(client)
        provider, execute = SyntheticProvider(), run_explanation
    else:
        task, owner, _, result = queued(client)
        provider, execute = SyntheticPlotProvider(result), run_plot
        task = execute(execute(task, provider), provider)
    original = DatabaseConnection.execute
    def reject(db, sql, parameters=()):
        if 'INSERT INTO usage_events' in sql:
            raise RuntimeError('private persistence failure')
        return original(db, sql, parameters)
    with monkeypatch.context() as patch:
        patch.setattr(DatabaseConnection, 'execute', reject)
        assert execute(task, provider) is None
    current = TaskStore(owner).get(task['id'])
    assert current['status'] == 'running' and current['retry_count'] == 0
    with database_connection(write=True) as db:
        assert db.execute('SELECT lease_owner FROM task_attempts').fetchone()['lease_owner']
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second'")
    assert TaskExecutionStore().recover_expired() == 1
    current = TaskStore(owner).get(task['id'])
    assert current['status'] == 'waiting_confirmation' and current['retry_count'] == 0
    assert execute(current, provider) is None
    assert len(provider.posts) == (1 if kind == 'explanation' else 3)


@pytest.mark.parametrize('kind', ['explanation', 'boxplot'])
@pytest.mark.parametrize('shape', ['missing_usage', 'no_response', 'invalid_status'])
def test_invalid_known_response_stops_instead_of_deferring_forever(client, cloud, kind, shape):
    current, _, provider, execute = prepared(client, kind)
    receipt = provider.receipt
    def malformed():
        value = receipt()
        if shape == 'missing_usage':
            del value['usage']
        elif shape == 'no_response':
            value['response'] = None
        else:
            value['status'] = 'unrecognized_status'
        return value
    provider.receipt = malformed
    failed = execute(current, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == 'model_response_invalid'
    assert failed['retry_count'] == 0


@pytest.mark.parametrize('kind', ['explanation', 'boxplot'])
def test_receipt_database_failure_leaves_lease_for_recovery_without_error_retry(client, cloud, kind, monkeypatch):
    current, owner, provider, execute = prepared(client, kind)
    provider.pending = False
    original = DatabaseConnection.execute
    def reject(db, sql, parameters=()):
        if 'INSERT INTO usage_events' in sql:
            raise RuntimeError('private SQL persistence failure')
        return original(db, sql, parameters)
    with monkeypatch.context() as patch:
        patch.setattr(DatabaseConnection, 'execute', reject)
        assert execute(current, provider) is None
    saved = TaskStore(owner).get(current['id'])
    assert saved['status'] == 'running' and saved['retry_count'] == 0
    with database_connection(write=True) as db:
        assert db.execute('SELECT lease_owner FROM task_attempts').fetchone()['lease_owner']
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second'")
    assert TaskExecutionStore().recover_expired() == 1
    provider.pending = False
    complete = execute(TaskStore(owner).get(current['id']), provider)
    assert complete['status'] == 'succeeded' and complete['retry_count'] == 0
    assert len(provider.posts) == (1 if kind == 'explanation' else 3)


@pytest.mark.parametrize('kind', ['explanation', 'boxplot'])
def test_manual_retry_reuses_known_response_and_preserves_single_settlement(client, cloud, kind):
    current, owner, provider, execute = prepared(client, kind)
    original = provider.retrieve
    failed_read(provider, ModelProviderError(status_code=503))
    for _ in range(4):
        current = execute(current, provider)
    response = client.post('/api/v1/tasks/' + current['id'] + '/retry',
        json={'expected_revision': current['revision']})
    assert response.status_code == 202
    current = response.json()
    assert current['retry_count'] == 0
    current = execute(current, provider)
    assert current['retry_count'] == 1
    provider.retrieve, provider.pending = original, False
    complete = execute(current, provider)
    assert complete['status'] == 'succeeded' and complete['retry_count'] == 1
    assert len(provider.posts) == (1 if kind == 'explanation' else 3)
    with database_connection() as db:
        calls = db.execute('SELECT id FROM model_calls').fetchall()
        assert len(calls) == 1
        reservations = db.execute('SELECT * FROM budget_reservations ORDER BY budget_id').fetchall()
        assert len(reservations) == 3
        observations = db.execute('SELECT count(*) AS n FROM usage_events').fetchone()['n']
        assert observations == 2  # One pending and one terminal observation.
    from app.domain.model_usage.gateway import ModelGateway
    from app.domain.model_usage.service import ModelUsageService
    ModelGateway(ModelUsageService(owner), provider).refresh(calls[0]['id'])
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM usage_events').fetchone()['n'] == observations
        assert db.execute('SELECT * FROM budget_reservations ORDER BY budget_id').fetchall() == reservations
