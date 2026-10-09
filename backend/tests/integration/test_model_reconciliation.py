"""Actual cost evidence and atomic accounting in fixture-owned test schemas."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from psycopg.types.json import Jsonb

from app.core.exceptions import StorageError
from app.db.database import database_connection
from tests.integration.test_model_usage import context, configure, request, response  # noqa: F401
from tests.domain.test_model_pricing import policy


def reconciliation(context):
    assert importlib.util.find_spec('app.domain.model_usage.reconciliation') is not None
    from app.domain.model_usage.reconciliation import ModelReconciliationService
    return ModelReconciliationService(context[1], context[0].store.config)


def evidence(component='token', amount=1000, revision=0, key='proof', **changes):
    return dict(event_key=key, expected_revision=revision, component=component,
        amount_micro_usd=amount, evidence_kind='provider_statement',
        evidence_reference='restricted:invoice-test', evidence_sha256='b' * 64,
        provider_object_id='response-test' if component == 'token' else 'cntr_test',
        operator='local-test-admin', **changes)


def plot(context, usage=True):
    service = configure(context, 10000)
    saved = service.reserve_call(request(context[3], policy=policy(tools=['code_interpreter']),
        tool_reserve_micro_usd=300))
    service.begin_submission(saved['id'])
    with database_connection(write=True) as db:
        db.execute('UPDATE model_calls SET provider_state=%s WHERE id=%s',
            (Jsonb({'container_id': 'cntr_test'}), saved['id']))
    response(service, saved, usage={'input_tokens': 1000, 'output_tokens': 5,
        'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}} if usage else None)
    return service, saved


def test_partial_preserves_unreconciled_excess_full_and_correction(context):
    service, saved = plot(context)
    recon = reconciliation(context)
    before = service.get_call(saved['id'])
    receipt = recon.preview(saved['id'], evidence('tool', 600))
    assert receipt['reserved_after_micro_usd'] == 600
    assert service.get_call(saved['id']) == before
    assert recon.reconcile(saved['id'], evidence('tool', 600)) == receipt
    view = service.project_usage(context[2])
    assert (view['estimated_micro_usd'], view['accounted_micro_usd'], view['reserved_micro_usd']) == (1010, 1010, 600)
    complete = recon.reconcile(saved['id'], evidence('token', 1000, 1, 'token'))
    assert complete['reconciliation_status'] == 'reconciled'
    assert complete['accounted_after_micro_usd'] == 1600 and complete['reserved_after_micro_usd'] == 0
    assert recon.reconcile(saved['id'], evidence('tool', 600)) == receipt
    corrected = recon.reconcile(saved['id'], evidence('token', 900, 2, 'fix'))
    assert corrected['delta_micro_usd'] == -100
    assert service.get_call(saved['id'])['usage_status'] == 'pending'
    assert service.get_call(saved['id'])['estimated_cost_micro_usd'] == 1010
    with database_connection() as db:
        rows = db.execute('SELECT * FROM budget_reservations WHERE call_id=%s', (saved['id'],)).fetchall()
        assert len(rows) == 3 and {row['accounted_micro_usd'] for row in rows} == {1500}
        assert {row['reserved_micro_usd'] for row in rows} == {420}


@pytest.mark.parametrize('status', ['reserved', 'submitting', 'submitted', 'submission_unknown', 'released'])
def test_non_final_calls_rejected(context, status):
    service, saved = plot(context)
    with database_connection(write=True) as db:
        db.execute('UPDATE model_calls SET status=%s WHERE id=%s', (status, saved['id']))
    with pytest.raises(StorageError) as error:
        reconciliation(context).reconcile(saved['id'], evidence())
    assert error.value.code == 'model_reconciliation_transition_invalid'


@pytest.mark.parametrize('changes', [{'provider_object_id': 'wrong'}, {'amount_micro_usd': True},
    {'evidence_sha256': 'B' * 64}, {'evidence_reference': 'C:/secret/invoice.pdf'},
    {'operator': 'admin\u200b'}, {'amount_micro_usd': -1}, {'unexpected': 1}])
def test_wrong_object_and_strict_evidence_rejected(context, changes):
    service, saved = plot(context)
    record = {**evidence(), **changes}
    with pytest.raises(StorageError):
        reconciliation(context).reconcile(saved['id'], record)
    assert service.get_call(saved['id']).get('reconciliation_revision', 0) == 0


def test_missing_response_and_ambiguous_container_rejected(context):
    service, saved = plot(context)
    recon = reconciliation(context)
    with database_connection(write=True) as db:
        db.execute('UPDATE model_calls SET provider_response_id=NULL WHERE id=%s', (saved['id'],))
    with pytest.raises(StorageError):
        recon.reconcile(saved['id'], evidence())
    other = service.reserve_call(request(context[3], call_key='other', policy=policy(tools=['code_interpreter']), tool_reserve_micro_usd=300))
    with database_connection(write=True) as db:
        db.execute('UPDATE model_calls SET provider_state=%s WHERE id=%s', (Jsonb({'container_id': 'cntr_test'}), other['id']))
    with pytest.raises(StorageError):
        recon.reconcile(saved['id'], evidence('tool', 0))


def test_replay_conflict_revision_race_and_owner(context):
    from app.auth.service import create_user
    service, saved = plot(context)
    recon = reconciliation(context)
    first = recon.reconcile(saved['id'], evidence('tool', 600))
    with pytest.raises(StorageError) as error:
        recon.reconcile(saved['id'], {**evidence('tool', 600), 'amount_micro_usd': 601})
    assert error.value.code == 'model_reconciliation_event_conflict'
    ready = Barrier(2)
    def finish(key):
        ready.wait(timeout=10)
        try:
            return recon.reconcile(saved['id'], evidence('token', 1000, 1, key))
        except StorageError as error:
            assert error.code == 'model_reconciliation_revision_conflict'
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(finish, ['one', 'two']))
    assert sum(row is not None for row in results) == 1
    assert recon.reconcile(saved['id'], evidence('tool', 600)) == first
    from app.domain.model_usage.reconciliation import ModelReconciliationService
    other = ModelReconciliationService(create_user('other-proof@local.test', 'safe-test-password-2026')['id'])
    with pytest.raises(StorageError) as error:
        other.inspect(saved['id'])
    assert error.value.status == 404


def test_failure_rolls_back_event_call_and_budgets(context, monkeypatch):
    from app.db.database import DatabaseConnection
    service, saved = plot(context)
    recon = reconciliation(context)
    original = DatabaseConnection.execute
    def reject(db, sql, parameters=()):
        if sql.startswith('UPDATE budget_reservations'):
            raise RuntimeError('test reconciliation rollback')
        return original(db, sql, parameters)
    with monkeypatch.context() as patch:
        patch.setattr(DatabaseConnection, 'execute', reject)
        with pytest.raises(RuntimeError):
            recon.reconcile(saved['id'], evidence('tool', 600))
    assert service.get_call(saved['id'])['reconciliation_revision'] == 0
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM usage_events WHERE event_type='reconciliation'").fetchone()['n'] == 0


def test_late_observation_preserves_actual_accounting(context):
    service, saved = plot(context, usage=False)
    recon = reconciliation(context)
    recon.reconcile(saved['id'], evidence('tool', 600))
    recon.reconcile(saved['id'], evidence('token', 1000, 1, 'token'))
    response(service, saved, event_key='late', usage={'input_tokens': 2000, 'output_tokens': 0,
        'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}}, tool_cost_micro_usd=700)
    view = service.project_usage(context[2])
    assert (view['estimated_micro_usd'], view['accounted_micro_usd'], view['reserved_micro_usd']) == (2700, 1600, 0)


def test_token_zero_full_and_unknown_released_projection(context):
    service = configure(context, 10000)
    saved = service.reserve_call(request(context[3]))
    service.begin_submission(saved['id'])
    response(service, saved)
    result = reconciliation(context).reconcile(saved['id'], evidence(amount=0))
    assert result['actual_micro_usd'] == 0 and result['reconciliation_status'] == 'reconciled'
    pending = service.reserve_call(request(context[3], call_key='pending'))
    released = service.reserve_call(request(context[3], call_key='released'))
    service.release_unsubmitted(released['id'], event_key='release', reason_code='cancelled')
    view = service.task_usage(context[3], page_size=1)
    assert view['reconciliation'] == dict(actual_micro_usd=0, reconciled_count=1, partial_count=0, pending_count=1)
    all_items = service.task_usage(context[3])['items']
    states = {item['id']: item['reconciliation'] for item in all_items}
    assert states[pending['id']]['actual_micro_usd'] is None
    assert states[released['id']]['status'] == 'not_applicable'


def test_large_actual_excess_is_preserved_and_prevents_admission(context):
    from app.domain.model_usage.contracts import MAX_ACCOUNTED_MICRO_USD
    service, saved = plot(context)
    recon = reconciliation(context)
    partial = recon.reconcile(saved['id'], evidence('tool', 2_000_000_000_000))
    assert partial['reserved_after_micro_usd'] == 2_000_000_000_000
    assert service.get_budget('task', context[3])['exceeded']
    with pytest.raises(StorageError) as error:
        service.reserve_call(request(context[3], call_key='blocked'))
    assert error.value.code == 'model_budget_exceeded'
    with pytest.raises(StorageError) as error:
        recon.reconcile(saved['id'], evidence('token', MAX_ACCOUNTED_MICRO_USD, 1, 'overflow'))
    assert error.value.code == 'model_reconciliation_input_invalid'
    assert service.get_call(saved['id'])['reconciliation_revision'] == 1


def test_partial_corrections_rebuild_original_hold_without_accumulation(context):
    service, saved = plot(context)
    recon = reconciliation(context)
    recon.reconcile(saved['id'], evidence('tool', 600))
    reduced = recon.reconcile(saved['id'], evidence('tool', 100, 1, 'reduced'))
    assert reduced['accounted_after_micro_usd'] == 1010
    assert reduced['reserved_after_micro_usd'] == 300
    increased = recon.reconcile(saved['id'], evidence('tool', 600, 2, 'increased'))
    assert increased['reserved_after_micro_usd'] == 600
    assert service.get_budget('task', context[3])['reserved_micro_usd'] == 600


def test_tool_inapplicable_and_no_evidence_are_rejected(context):
    service = configure(context, 10000)
    saved = service.reserve_call(request(context[3]))
    service.begin_submission(saved['id'])
    response(service, saved)
    recon = reconciliation(context)
    for record in [evidence('tool', 0), {}, None]:
        with pytest.raises(StorageError):
            recon.reconcile(saved['id'], record)
    assert service.get_call(saved['id'])['reconciliation_revision'] == 0


def test_late_evidence_does_not_rewrite_final_original_estimate(context):
    service = configure(context, 10000)
    saved = service.reserve_call(request(context[3]))
    service.begin_submission(saved['id'])
    response(service, saved)
    reconciliation(context).reconcile(saved['id'], evidence(amount=1000))
    before = service.get_call(saved['id'])
    response(service, saved, event_key='late', usage={'input_tokens': 2000})
    after = service.get_call(saved['id'])
    assert after['estimated_cost_micro_usd'] == before['estimated_cost_micro_usd'] == 60
    assert after['usage_status'] == before['usage_status'] == 'estimated'
    assert service.get_budget('task', context[3])['accounted_micro_usd'] == 1000
    with database_connection() as db:
        event = db.execute("SELECT * FROM usage_events WHERE event_key='late'").fetchone()
        assert event['estimated_cost_micro_usd'] == 2000 and event['usage_status'] == 'pending'
