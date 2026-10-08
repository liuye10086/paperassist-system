"""Waiting generations and capability reads; no network or implicit execution."""
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.core.errors import PUBLIC_CODES
from app.domain.tasks.wait_contracts import WaitView


def input_version(task):
    if 'input_version' in task:
        return task['input_version']
    snapshot = task['input_snapshot']
    return {'setup_revision': snapshot['result']['setup_revision'], 'output_language': snapshot['output_language']}


def get_open_wait(db, task):
    row = db.execute("SELECT * FROM task_waits WHERE task_id=%s AND status='open'", (task['id'],)).fetchone()
    if row is None:
        return None
    values = {key: row[key] for key in WaitView.model_fields}
    code = values['error_code']
    values['error_code'] = code if code in PUBLIC_CODES else ('internal_error' if code else None)
    return WaitView(**values).model_dump(mode='json')


def resolve_open_wait(db, task, *, status='resolved'):
    if status not in ('resolved', 'superseded'):
        raise ValueError('Invalid waiting resolution.')
    db.execute('''UPDATE task_waits SET status=%s,resolved_at=%s,resolved_task_revision=%s
        WHERE task_id=%s AND status='open' AND task_revision<%s''',
        (status, task['updated_at'], task['revision'], task['id'], task['revision']))


def persist_wait(db, task):
    if task['status'] not in ('waiting_input', 'waiting_confirmation'):
        raise ValueError('Only waiting tasks have pending requests.')
    existing = get_open_wait(db, task)
    if existing and existing['task_revision'] == task['revision']:
        return
    resolve_open_wait(db, task, status='superseded')
    kind = ('unsupported_input' if task['status'] == 'waiting_input' else
        {'budget_exceeded': 'budget_confirmation', 'submission_unknown': 'submission_unknown'}.get(
            task['reason_code'], 'unsupported_confirmation'))
    db.execute('''INSERT INTO task_waits
        (id,task_id,user_id,project_id,kind,status,task_revision,input_version,reason_code,error_code,created_at)
        VALUES (%s,%s,%s,%s,%s,'open',%s,%s,%s,%s,%s)''',
        (str(uuid4()), task['id'], task['user_id'], task['project_id'], kind, task['revision'],
         Jsonb(input_version(task)), task['reason_code'], task.get('error_code'), task['updated_at']))


def allowed_recovery_actions(db, task):
    if task['status'] not in ('failed', 'waiting_confirmation'):
        return []
    if task['status'] == 'waiting_confirmation':
        wait = get_open_wait(db, task)
        if (task['reason_code'] != 'budget_exceeded' or not wait
                or wait['kind'] != 'budget_confirmation' or wait['task_revision'] != task['revision']):
            return []
    budget_wait = task['status'] == 'waiting_confirmation'
    if task['task_type'] == 'word_report':
        return ['retry'] if not budget_wait else []
    if task['task_type'] == 'boxplot':
        from app.domain.plot_tasks import _can_resume, _last_call, _unknown_submission
    elif task['task_type'] == 'explanation':
        from app.domain.explanation_tasks import _can_resume, _last_call
        def _unknown_submission(call):
            return call and not call.get('provider_response_id') and call['status'] in ('submitting', 'submission_unknown')
    else:
        return []
    call = _last_call(db, task['id'])
    if _unknown_submission(call) or not (budget_wait or _can_resume(task, call)):
        return []
    return ['resume' if budget_wait else 'retry']
