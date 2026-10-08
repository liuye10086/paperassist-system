"""A source changed after Excel reconstruction cannot cross the paid POST fence."""
import pytest

from app.db.database import database_connection
from app.domain.model_usage.service import ModelUsageService
from tests.api.test_analysis import client  # noqa: F401
from app.adapters.task_execution_store import TaskExecutionStore
from app.adapters.task_store import TaskStore
from tests.integration.test_boxplot_execution import queued, run, SyntheticPlotProvider, change_source, lease_for
from tests.integration.test_task_execution import expired


@pytest.mark.parametrize('prior_posts', [0, 1, 2])
def test_source_changed_after_reservation_before_effect_fence_never_posts(client, monkeypatch, prior_posts):
    task, _, _, result = queued(client)
    provider = SyntheticPlotProvider(result)
    for _ in range(prior_posts):
        task = run(task, provider)
    original = ModelUsageService.reserve_call

    def reserve_then_change_source(self, request, **kwargs):
        call = original(self, request, **kwargs)
        # Workbook reconstruction and budget reservation are already finished.
        change_source()
        return call

    monkeypatch.setattr(ModelUsageService, 'reserve_call', reserve_then_change_source)
    failed = run(task, provider)
    assert failed['status'] == 'failed' and failed['error_code'] == 'task_source_conflict'
    assert provider.posts == ['container', 'upload'][:prior_posts]
    assert provider.gets == []
    with database_connection() as db:
        call = db.execute('SELECT * FROM model_calls WHERE task_id=%s', (task['id'],)).fetchone()
        assert call['provider_response_id'] is None
        assert (call['provider_state'] or {}).get('phase') == [None, 'container_ready', 'file_ready'][prior_posts]
        reservations = db.execute('SELECT status FROM budget_reservations WHERE call_id=%s', (call['id'],)).fetchall()
        assert len(reservations) == 3
        assert {row['status'] for row in reservations} == ({'released'} if prior_posts == 0 else {'held'})
        releases = db.execute("SELECT * FROM usage_events WHERE call_id=%s AND event_type='release'",
                              (call['id'],)).fetchall()
        assert len(releases) == (1 if prior_posts == 0 else 0)
        if prior_posts == 0:
            assert call['status'] == 'released' and releases[0]['reason_code'] == 'task_source_conflict'
        assert db.execute('SELECT count(*) AS n FROM figures').fetchone()['n'] == 0


@pytest.mark.parametrize('committed', [False, True])
def test_source_failure_release_persistence_error_does_not_finish_task_and_recovers_once(client, monkeypatch, committed):
    task, owner, _, result = queued(client)
    provider = SyntheticPlotProvider(result)
    reserve, release = ModelUsageService.reserve_call, ModelUsageService.release_unsubmitted
    def reserve_then_change_source(self, request, **kwargs):
        call = reserve(self, request, **kwargs)
        change_source()
        return call
    def interrupted_release(self, *args, **kwargs):
        if committed:
            release(self, *args, **kwargs)
        raise RuntimeError('synthetic release persistence failure')
    with monkeypatch.context() as patch:
        patch.setattr(ModelUsageService, 'reserve_call', reserve_then_change_source)
        patch.setattr(ModelUsageService, 'release_unsubmitted', interrupted_release)
        assert run(task, provider) is None
    current = TaskStore(owner).get(task['id'])
    assert current['status'] == 'running'
    assert provider.posts == []
    with database_connection() as db:
        call = db.execute('SELECT * FROM model_calls').fetchone()
        assert call['status'] == ('released' if committed else 'reserved')
        assert {row['status'] for row in db.execute('SELECT status FROM budget_reservations')} == (
            {'released'} if committed else {'held'})
    if committed:
        # Even if the isolated input is restored, a released call cannot return
        # to a paid stage after the failure transaction was interrupted.
        with database_connection(write=True) as db:
            db.execute('UPDATE analysis_setups SET revision=revision-1')
    expired(lease_for(task))
    assert TaskExecutionStore().recover_expired() == 1
    failed = run(TaskStore(owner).get(task['id']), provider)
    assert failed['status'] == 'failed' and failed['error_code'] == 'task_source_conflict'
    assert provider.posts == []
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM usage_events WHERE event_type='release'").fetchone()['n'] == 1
        assert {row['status'] for row in db.execute('SELECT status FROM budget_reservations')} == {'released'}
