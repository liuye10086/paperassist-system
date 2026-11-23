"""Model calls and historical holds use only fixture-owned isolated PostgreSQL schemas."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from app.core.exceptions import StorageError
from app.db.database import database_connection
from tests.domain.test_model_pricing import policy


@pytest.fixture
def context(postgres_schema):
    from app.auth.service import create_user
    from app.domain.model_usage.service import ModelUsageService
    user = create_user('model-test@local.test', 'safe-test-password-2026')['id']
    project, task = str(uuid4()), str(uuid4())
    now = datetime.now(timezone.utc)
    with database_connection(write=True) as db:
        db.execute('''INSERT INTO projects
            (id,name,research_topic,project_type,created_at,updated_at,owner_id)
            VALUES (%s,'test','test','sci',%s,%s,%s)''', (project, now.isoformat(), now.isoformat(), user))
        db.execute('''INSERT INTO tasks
            (id,project_id,user_id,task_type,idempotency_key,input_digest,input_snapshot,
             workflow_version,status,phase,revision,current_attempt,created_at,updated_at)
            VALUES (%s,%s,%s,'boxplot','test',%s,%s,'test','running','compute',2,1,%s,%s)''',
            (task, project, user, 'a' * 64, Jsonb({}), now, now))
    return ModelUsageService(user, postgres_schema), user, project, task


def request(task, **changes):
    from app.domain.model_usage.contracts import CallRequest
    values = dict(task_id=task, expected_task_revision=2, call_key='test-call', input_digest='a' * 64,
                  policy=policy(), input_token_allowance=100)
    return CallRequest(**{**values, **changes})


def seed_historical_budgets(user, project, task, limit=0):
    with database_connection(write=True) as db:
        for scope, key, project_id, task_id in [('user', user, None, None),
                ('project', project, project, None), ('task', task, project, task)]:
            db.execute("""INSERT INTO model_budgets (id,user_id,scope_type,scope_key,project_id,task_id,
                limit_micro_usd,revision,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,1,now(),now())""",
                (str(uuid4()), user, scope, key, project_id, task_id, limit))


def seed_historical_holds(call, amount=120, tool_reserve=0):
    seed_historical_budgets(call['user_id'], call['project_id'], call['task_id'])
    with database_connection(write=True) as db:
        db.execute("""INSERT INTO budget_reservations
            (call_id,budget_id,reserved_micro_usd,accounted_micro_usd,status,updated_at)
            SELECT %s,id,%s,0,'held',now() FROM model_budgets WHERE user_id=%s
                AND scope_key IN (%s,%s,%s)""",
            (call['id'], amount, call['user_id'], call['user_id'], call['project_id'], call['task_id']))
        if tool_reserve:
            db.execute("""UPDATE model_calls SET policy_snapshot=policy_snapshot || %s WHERE id=%s""",
                (Jsonb({'tool_reserve_micro_usd': tool_reserve, 'tool_reserve_version': 'legacy'}), call['id']))


def call(context, *, historical=False, **changes):
    service = context[0]
    saved = service.reserve_call(request(context[3], **changes))
    if historical:
        seed_historical_holds(saved)
    assert service.begin_submission(saved['id'])
    return service, saved


def response(service, saved, **changes):
    values = dict(event_key='reply', response_id='response-test', request_id='request-test',
        model='test-model', status='completed', usage={'input_tokens': 50, 'output_tokens': 5,
            'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}})
    return service.record_response(saved['id'], **{**values, **changes})


def test_admission_without_any_budget_creates_only_the_call(context):
    service, _, _, task = context
    saved = service.reserve_call(request(task))
    assert saved['status'] == 'reserved'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM model_budgets').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n'] == 0


def test_external_material_version_is_frozen_in_call_policy_and_replay(context):
    service = context[0]
    task_id = context[3]
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET input_snapshot=%s WHERE id=%s',
                   (Jsonb({'external_processing': {'version': 1}}), task_id))
    original = service.reserve_call(request(task_id))
    assert original['policy_snapshot'].get('external_processing_version') == 1
    repeated = service.reserve_call(request(task_id))
    assert repeated['id'] == original['id']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n'] == 0


def test_independent_parallel_calls_ignore_zero_historical_limits(context):
    service, _, project, task = context
    seed_historical_budgets(*context[1:])
    ready = Barrier(3)

    def reserve(number):
        ready.wait(timeout=10)
        return service.reserve_call(request(task, call_key=str(number)))['id']

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert len(set(pool.map(reserve, range(3)))) == 3
    usage = service.project_usage(project)
    assert usage['reserved_micro_usd'] == 0 and usage['total'] == 3
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM model_budgets WHERE limit_micro_usd=0').fetchone()['n'] == 3


def test_parallel_same_key_creates_one_call_and_fences_submission(context):
    service = context[0]
    ready = Barrier(3)
    def reserve(_):
        ready.wait(timeout=10)
        return service.reserve_call(request(context[3]))['id']
    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(reserve, range(3)))
    assert len(set(ids)) == 1
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(service.begin_submission, ids))
    assert sum(results) == 1
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n'] == 0


def test_idempotency_is_stable_across_attempts_but_compares_policy_and_allowances(context):
    service = context[0]
    original = service.reserve_call(request(context[3]))
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET revision=4,current_attempt=2 WHERE id=%s', (context[3],))
    assert service.reserve_call(request(context[3], expected_task_revision=4))['id'] == original['id']
    for changes in [{'input_digest': 'b' * 64}, {'input_token_allowance': 101},
                    {'policy': policy(timeout_seconds=46)}]:
        with pytest.raises(StorageError) as error:
            service.reserve_call(request(context[3], expected_task_revision=4, **changes))
        assert error.value.code == 'model_call_idempotency_conflict'
    assert original['price_snapshot']['version'] == 'test-v1'


@pytest.mark.parametrize('status', ['completed', 'incomplete', 'failed', 'cancelled'])
def test_all_terminal_responses_with_usage_settle_once(context, status):
    service, saved = call(context)
    result = response(service, saved, status=status)
    assert result['estimated_cost_micro_usd'] == 60 and result['usage_status'] == 'estimated'
    assert response(service, saved, status=status, request_id='new-request')['id'] == saved['id']
    assert response(service, saved, status=status, event_key='another-poll')['id'] == saved['id']
    usage = service.project_usage(context[2])
    assert usage['estimated_micro_usd'] == 60 and usage['reserved_micro_usd'] == 0
    assert usage['accounted_micro_usd'] == 60
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM usage_events').fetchone()['n'] == 2
        reservations = db.execute('SELECT * FROM budget_reservations').fetchall()
    assert reservations == []


@pytest.mark.parametrize('changes', [{'usage': None}, {'model': 'other'},
    {'usage': {'input_tokens': 1}}, {'status': 'in_progress'}])
def test_missing_model_mismatch_and_nonterminal_stay_pending(context, changes):
    service, saved = call(context)
    result = response(service, saved, **changes)
    usage = service.project_usage(context[2])
    assert usage['reserved_micro_usd'] == 0
    assert usage['pending_count'] == 1
    assert result['usage_status'] == 'pending'


def test_tool_cost_unknown_uses_larger_known_estimate_without_double_count(context):
    service, saved = call(context, policy=policy(tools=['code_interpreter']))
    result = response(service, saved, usage={'input_tokens': 200, 'output_tokens': 0,
        'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}})
    assert result['estimated_cost_micro_usd'] == 200 and result['usage_status'] == 'pending'
    usage = service.project_usage(context[2])
    assert usage['estimated_micro_usd'] == 200 and usage['reserved_micro_usd'] == 0
    assert usage['accounted_micro_usd'] == 200
    assert service.reserve_call(request(context[3], call_key='next'))['id'] != saved['id']


def test_submission_unknown_cannot_be_released_or_resubmitted(context):
    service, saved = call(context)
    result = service.mark_submission_unknown(saved['id'], error_code='openai_connection')
    assert result['status'] == 'submission_unknown'
    assert not service.begin_submission(saved['id'])
    with pytest.raises(StorageError) as error:
        service.release_unsubmitted(saved['id'], event_key='release', reason_code='cancelled')
    assert error.value.code == 'model_call_transition_invalid'
    assert service.project_usage(context[2])['reserved_micro_usd'] == 0


@pytest.mark.parametrize('historical', [False, True])
def test_release_reserved_call_is_atomic_idempotent_and_free_of_consumption(context, historical):
    service = context[0]
    saved = service.reserve_call(request(context[3]))
    if historical:
        seed_historical_holds(saved)
    result = service.release_unsubmitted(saved['id'], event_key='release', reason_code='cancelled')
    assert result['status'] == 'released'
    assert service.release_unsubmitted(saved['id'], event_key='release', reason_code='cancelled')['id'] == saved['id']
    assert not service.begin_submission(saved['id'])
    usage = service.project_usage(context[2])
    assert usage['estimated_micro_usd'] == usage['reserved_micro_usd'] == usage['pending_count'] == 0
    with database_connection() as db:
        states = [row['status'] for row in db.execute('SELECT status FROM budget_reservations')]
    assert states == (['released'] * 3 if historical else [])


def test_estimate_above_a_historical_limit_allows_new_calls(context):
    service, saved = call(context, historical=True)
    response(service, saved, usage={'input_tokens': 200, 'output_tokens': 10,
        'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}})
    view = service.project_usage(context[2])
    assert view['estimated_micro_usd'] == view['accounted_micro_usd'] == 220
    assert service.reserve_call(request(context[3], call_key='new'))['id'] != saved['id']


def test_event_conflicts_and_older_nonterminal_do_not_regress_terminal(context):
    service, saved = call(context)
    response(service, saved)
    with pytest.raises(StorageError) as error:
        response(service, saved, usage={'input_tokens': 90, 'output_tokens': 1,
            'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}})
    assert error.value.code == 'model_usage_event_conflict'
    older = response(service, saved, event_key='old', status='in_progress', usage=None)
    assert older['status'] == 'completed' and older['provider_status'] == 'completed'
    assert service.project_usage(context[2])['estimated_micro_usd'] == 60


def test_explicit_different_event_keys_are_audited_without_losing_key_conflicts(context):
    service, saved = call(context)
    response(service, saved, usage=None, event_key='A')
    response(service, saved, usage=None, event_key='B')
    with pytest.raises(StorageError) as error:
        response(service, saved, event_key='B')
    assert error.value.code == 'model_usage_event_conflict'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM usage_events').fetchone()['n'] == 2
    assert service.project_usage(context[2])['reserved_micro_usd'] == 0


@pytest.mark.parametrize('detail_fields', [{}, {'input_tokens_details': None},
    {'input_tokens_details': {}}, {'input_tokens_details': {'cached_tokens': 0}},
    {'input_tokens_details': {'cache_write_tokens': 0}}])
def test_incomplete_cache_details_hold_reservations_until_complete_usage(context, detail_fields):
    service, saved = call(context, historical=True)
    usage = {'input_tokens': 50, 'output_tokens': 5, **detail_fields}
    result = response(service, saved, usage=usage)
    assert result['usage_status'] == 'pending'
    view = service.project_usage(context[2])
    assert (view['estimated_micro_usd'], view['reserved_micro_usd'], view['pending_count']) == (60, 60, 1)
    with database_connection() as db:
        reservations = db.execute('SELECT * FROM budget_reservations').fetchall()
    assert len(reservations) == 3
    assert {row['status'] for row in reservations} == {'held'}
    assert {row['reserved_micro_usd'] for row in reservations} == {120}
    complete = {'input_tokens': 50, 'output_tokens': 5,
                'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}}
    assert response(service, saved, event_key='complete', usage=complete)['usage_status'] == 'estimated'
    view = service.project_usage(context[2])
    assert (view['estimated_micro_usd'], view['reserved_micro_usd'], view['pending_count']) == (60, 0, 0)


@pytest.mark.parametrize('old_status', ['completed', 'incomplete', 'failed', 'cancelled'])
@pytest.mark.parametrize('old_usage', [None, {'input_tokens': 200}])
def test_historical_pending_receipt_with_new_key_cannot_reopen_settlement(context, old_status, old_usage):
    service, saved = call(context, historical=True)
    response(service, saved, event_key='A', status=old_status, usage=old_usage)
    complete = {'input_tokens': 50, 'output_tokens': 5,
                'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}}
    settled = response(service, saved, event_key='B', usage=complete)
    assert settled['usage_status'] == 'estimated'
    with database_connection() as db:
        settled_reservations = db.execute('SELECT * FROM budget_reservations ORDER BY budget_id').fetchall()
    replayed = response(service, saved, event_key='C', status=old_status, usage=old_usage)
    assert replayed == settled
    view = service.project_usage(context[2])
    assert (view['estimated_micro_usd'], view['reserved_micro_usd'], view['pending_count']) == (60, 0, 0)
    with database_connection() as db:
        events = db.execute('SELECT event_key,usage_status,provider_usage FROM usage_events ORDER BY event_key').fetchall()
        reservations = db.execute('SELECT * FROM budget_reservations ORDER BY budget_id').fetchall()
    assert [row['event_key'] for row in events] == ['A', 'B', 'C']
    assert events[-1]['usage_status'] == 'pending' and events[-1]['provider_usage'] == old_usage
    assert reservations == settled_reservations
    assert len(reservations) == 3
    assert {row['status'] for row in reservations} == {'settled'}
    assert {row['accounted_micro_usd'] for row in reservations} == {60}
    response(service, saved, event_key='C', status=old_status, usage=old_usage, request_id='repeat-poll')
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM usage_events').fetchone()['n'] == 3
    with pytest.raises(StorageError) as conflict:
        response(service, saved, event_key='C', usage=complete)
    assert conflict.value.code == 'model_usage_event_conflict'
    with pytest.raises(StorageError) as conflict:
        response(service, saved, event_key='new-incompatible', usage={**complete, 'output_tokens': 6})
    assert conflict.value.code == 'model_usage_event_conflict'


def test_owner_enabled_revision_and_non_word_are_required(context):
    from app.auth.service import create_user
    from app.domain.model_usage.service import ModelUsageService
    service = context[0]
    saved = service.reserve_call(request(context[3]))
    other = ModelUsageService(create_user('other@local.test', 'safe-test-password-2026')['id'])
    for action in [lambda: other.get_call(saved['id']), lambda: other.reserve_call(request(context[3])),
                   lambda: other.project_usage(context[2]), lambda: other.task_usage(context[3])]:
        with pytest.raises(StorageError) as error:
            action()
        assert error.value.status == 404
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET revision=3 WHERE id=%s', (context[3],))
    with pytest.raises(StorageError) as error:
        service.begin_submission(saved['id'])
    assert error.value.code == 'task_revision_conflict'
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET revision=2,task_type='word_report' WHERE id=%s", (context[3],))
    with pytest.raises(StorageError):
        service.reserve_call(request(context[3], call_key='word'))
    with database_connection(write=True) as db:
        db.execute('UPDATE users SET active=false WHERE id=%s', (context[1],))
    with pytest.raises(StorageError):
        service.get_call(saved['id'])


def test_public_usage_projection_has_only_costs_and_call_details(context):
    service, _, project, task = context
    empty = service.project_usage(project)
    assert empty['period'] == 'cumulative' and empty['items'] == []
    saved = service.reserve_call(request(task))
    page = service.task_usage(task)
    assert set(page) == {'currency','period',
        'estimated_micro_usd','accounted_micro_usd','reconciliation','reserved_micro_usd','pending_count','items','total','page','page_size'}
    assert set(page['items'][0]) == {'id','task_type','model','status','provider_status','usage_status',
                                   'estimated_cost_micro_usd','created_at','updated_at','reconciliation','provider_provenance'}
    assert page['items'][0]['id'] == saved['id']
    assert page['items'][0]['provider_provenance'] is None


def test_settlement_side_effects_roll_back_together(context, monkeypatch):
    from app.db.database import DatabaseConnection
    service, saved = call(context, historical=True)
    original = DatabaseConnection.execute
    def reject(db, sql, parameters=()):
        if sql.startswith('UPDATE budget_reservations'):
            raise RuntimeError('settle failure')
        return original(db, sql, parameters)
    with monkeypatch.context() as patch:
        patch.setattr(DatabaseConnection, 'execute', reject)
        with pytest.raises(RuntimeError, match='settle failure'):
            response(service, saved)
    assert service.get_call(saved['id'])['status'] == 'submitting'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM usage_events').fetchone()['n'] == 0
    assert service.project_usage(context[2])['reserved_micro_usd'] == 120


def test_partial_usage_over_reservation_is_held_until_complete_receipt(context):
    service, saved = call(context, historical=True)
    response(service, saved, usage={'input_tokens': 200,
        'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}})
    view = service.project_usage(context[2])
    assert view['estimated_micro_usd'] == view['accounted_micro_usd'] == 200
    with database_connection() as db:
        assert {r['status'] for r in db.execute('SELECT status FROM budget_reservations')} == {'held'}
    result = response(service, saved, event_key='complete-usage', usage={'input_tokens': 200, 'output_tokens': 0,
        'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}})
    assert result['usage_status'] == 'estimated'
    with database_connection() as db:
        assert {r['status'] for r in db.execute('SELECT status FROM budget_reservations')} == {'settled'}


def test_release_side_effects_roll_back_together(context, monkeypatch):
    from app.db.database import DatabaseConnection
    service = context[0]
    saved = service.reserve_call(request(context[3]))
    seed_historical_holds(saved)
    original = DatabaseConnection.execute
    def reject(db, sql, parameters=()):
        if sql.startswith('UPDATE budget_reservations'):
            raise RuntimeError('release failure')
        return original(db, sql, parameters)
    with monkeypatch.context() as patch:
        patch.setattr(DatabaseConnection, 'execute', reject)
        with pytest.raises(RuntimeError, match='release failure'):
            service.release_unsubmitted(saved['id'], event_key='release', reason_code='cancelled')
    assert service.get_call(saved['id'])['status'] == 'reserved'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM usage_events').fetchone()['n'] == 0
    assert service.task_usage(context[3])['reserved_micro_usd'] == 120


def test_bypassed_request_copies_are_revalidated_before_database_effects(context):
    service = context[0]
    forged = request(context[3]).model_copy(update={'input_token_allowance': True})
    with pytest.raises(StorageError) as error:
        service.reserve_call(forged)
    assert error.value.code == 'model_usage_input_invalid'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0


def test_receipt_status_type_is_strict(context):
    service, saved = call(context)
    with pytest.raises(StorageError) as error:
        response(service, saved, status=[])
    assert error.value.code == 'model_usage_input_invalid'


def test_actual_tool_fee_above_configuration_cap_is_fully_recorded(context):
    service, saved = call(context, policy=policy(tools=['code_interpreter']))
    result = response(service, saved, usage={'input_tokens': 0, 'output_tokens': 0},
                      tool_cost_micro_usd=2_000_000_000_000)
    assert result['usage_status'] == 'estimated'
    assert service.task_usage(context[3])['estimated_micro_usd'] == 2_000_000_000_000
