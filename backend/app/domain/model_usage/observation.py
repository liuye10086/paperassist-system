"""Cloud observation is bounded independently of local numerical execution."""
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

WINDOW = timedelta(minutes=20)
SUPPORTED_TASKS = frozenset({'boxplot', 'explanation', 'figure_workbench', 'figure_explanation', 'analysis_recommendation', 'literature_assistance', 'manuscript_writing', 'school_rule_suggestion'})


def _date(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Observation timestamp requires a timezone.')
    return parsed.astimezone(timezone.utc)


def start(state, now):
    state = dict(state or {})
    if 'observation' not in state:
        state['observation'] = {'version': 1, 'started_at': now.isoformat(),
                                'deadline_at': (now + WINDOW).isoformat(), 'continuations': 0}
    return state


def window(call):
    observation = (call.get('provider_state') or {}).get('observation')
    if observation is not None:
        if (not isinstance(observation, dict) or observation.get('version') != 1
                or type(observation.get('continuations')) is not int or observation['continuations'] < 0):
            raise ValueError('Invalid observation window.')
        if _date(observation['deadline_at']) < _date(observation['started_at']):
            raise ValueError('Invalid observation order.')
        return observation
    # Historic calls retain their original persisted start; a restart cannot renew it.
    created = call.get('created_at')
    if created is None:
        return None  # In-memory adapters have no durable clock; production rows require it.
    return start({}, _date(created))['observation']


def expired(call, now=None):
    observed = window(call)
    return observed is not None and (now or datetime.now(timezone.utc)) >= _date(observed['deadline_at'])


def resumable_call(db, task):
    if (task['task_type'] not in SUPPORTED_TASKS or task['status'] != 'waiting_confirmation'
            or task.get('reason_code') != 'observation_expired'):
        return None
    call = db.execute('SELECT * FROM model_calls WHERE task_id=%s AND user_id=%s AND project_id=%s ORDER BY created_at DESC,id DESC LIMIT 1',
                      (task['id'], task['user_id'], task['project_id'])).fetchone()
    return call if call and call.get('provider_response_id') and call['status'] != 'released' else None


def continue_original(store, db, task, wait):
    """Resolve this exact wait and enqueue only a retrieval of its saved response."""
    from app.core.exceptions import StorageError
    from app.domain.tasks.waits import resolve_open_wait
    call = resumable_call(db, task)
    if not call or wait['kind'] != 'remote_observation':
        raise StorageError('task_transition_invalid', '此任务没有可继续查询的原始回执。', 409)
    now = datetime.now(timezone.utc)
    observed = window(call)
    if observed is None:
        raise StorageError('task_source_conflict', '原始云端观察依据缺失。', 409)
    state = dict(call.get('provider_state') or {})
    state['observation'] = {**observed,
                           'continued_at': now.isoformat(), 'continuations': observed['continuations'] + 1,
                           'last_wait_id': wait['id'],
                           'retrieval_grant': {'version': 1, 'call_id': call['id'],
                               'response_id': call['provider_response_id'], 'wait_id': wait['id'],
                               'task_revision': task['revision'] + 1,
                               'granted_at': now.isoformat(), 'consumed_at': None}}
    db.execute('UPDATE model_calls SET provider_state=%s,updated_at=%s WHERE id=%s', (Jsonb(state), now, call['id']))
    revision = task['revision']
    task.update(status='queued', revision=revision + 1, reason_code='confirmation_received', error_code=None,
                retry_count=0, updated_at=now)
    store.update_task(db, task, revision)
    store.append_event(db, task, 'requeued')
    store.enqueue(db, task)
    resolve_open_wait(db, task)
    return store.public_task(task)


def consume_grant(store, call_id, response_id):
    """Commit one GET authorization before network I/O; concurrent consumers lose CAS."""
    with store.connection(write=True) as db:
        call = store.require_call(db, call_id)
        observed = window(call)
        grant = observed.get('retrieval_grant') if observed else None
        if (not isinstance(grant, dict)
                or set(grant) != {'version', 'call_id', 'response_id', 'wait_id', 'task_revision', 'granted_at', 'consumed_at'}
                or type(grant['version']) is not int or grant['version'] != 1
                or grant.get('call_id') != call_id or grant.get('response_id') != response_id
                or call.get('provider_response_id') != response_id or grant.get('consumed_at') is not None
                or not isinstance(grant.get('wait_id'), str)
                or type(grant.get('task_revision')) is not int or grant['task_revision'] < 1):
            return False
        try:
            _date(grant['granted_at'])
        except (TypeError, ValueError):
            return False
        now = datetime.now(timezone.utc)
        # The resolved wait and committed resume decision are part of the same
        # transaction that minted this grant. Never trust an unbound JSON flag.
        row = db.execute('''UPDATE model_calls c SET
            provider_state=jsonb_set(provider_state,'{observation,retrieval_grant,consumed_at}',%s,false),
            updated_at=%s WHERE c.id=%s AND c.user_id=%s AND c.provider_response_id=%s
            AND c.provider_state->'observation'->'retrieval_grant'=%s
            AND EXISTS (SELECT 1 FROM task_waits w JOIN task_resume_requests r ON r.wait_id=w.id
                WHERE w.id=%s AND w.task_id=c.task_id AND w.user_id=c.user_id
                AND w.project_id=c.project_id AND w.status='resolved'
                AND r.task_id=c.task_id AND r.user_id=c.user_id AND r.operation='resume'
                AND r.expected_task_revision=w.task_revision AND r.result_task_revision=%s)
            RETURNING c.id''', (Jsonb(now.isoformat()), now, call_id, store.user_id, response_id,
                                Jsonb(grant), grant['wait_id'], grant['task_revision'])).fetchone()
        return row is not None
