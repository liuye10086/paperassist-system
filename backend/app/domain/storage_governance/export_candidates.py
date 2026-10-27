"""Exact local export candidates; explicit typed retry grants one next attempt.

Every caller checks its existing source/version/lease before these byte fences.
Complete envelopes retain the first renderer result and never invoke a renderer.
"""
from hashlib import sha256
from pathlib import Path
from psycopg.types.json import Jsonb

from . import service as s
from . import candidates as c
from . import local_candidates as local

TYPES = frozenset(('word_report','collection_word_report','manuscript_docx',
                  'pdf_export','layout_docx','review_document_export'))
STORAGE_ERRORS = frozenset(('storage_unavailable','storage_quota_exceeded',
                           'storage_disk_insufficient','storage_accounting_unknown','task_worker_interrupted'))


def hold(db, task):
    if task['task_type'] not in TYPES:
        return None
    row = db.execute('SELECT * FROM storage_reservations WHERE namespace=%s AND project_id=%s AND operation_key=%s',
        (s.NAMESPACE,task['project_id'],'export-task:'+task['id'])).fetchone()
    if row and (row['owner_id']!=task['user_id'] or row['task_id']!=task['id']
                or row['kind']!=task['task_type'] or row['capacity_bytes'] is None
                or row['candidate_json']['source_identity']!=task['input_digest']):
        raise s.invalid()
    return dict(row) if row else None


def reconcile(db,root,task):
    if s.reconcile_intents(db,root):
        raise s.invalid()
    return hold(db,task)


def value(root,row,task):
    saved,raw = local.read(root,row,task['input_digest'])
    metadata=saved['metadata']
    if (saved['task_type']!=task['task_type'] or saved['task_id']!=task['id']
            or metadata['sha256']!=sha256(raw).hexdigest() or metadata['size_bytes']!=len(raw)):
        raise s.invalid()
    return saved,raw


def authorized(db,row,task,lease):
    grant=row['candidate_json'];revision=grant.get('recovery_revision')
    return (grant.get('recovery_attempt')==lease.attempt_no and type(revision) is int
        and revision<task['revision'] and bool(db.execute("""SELECT 1 FROM task_events
            WHERE task_id=%s AND seq=%s AND event_type='requeued'
              AND reason_code='retry_requested' AND retry_reason='manual_retry'""",
            (task['id'],revision)).fetchone()))


def restore(db,root,task,lease):
    row=reconcile(db,root,task)
    if not row:
        return None
    saved,raw=value(root,row,task)
    if row['state']=='unknown' or saved['attempt_no']!=lease.attempt_no:
        if not authorized(db,row,task,lease):
            raise s.invalid()
    return saved['metadata'],raw,Path(root)/row['object_key']


def capture(db,root,task,lease,target,staged,content,metadata):
    row=reconcile(db,root,task)
    if row:
        saved,raw=value(root,row,task)
        if saved['metadata']!=metadata or raw!=content or s._key(root,target)!=row['object_key']:
            raise s.invalid()
        return row
    return local.capture(db,root,task['project_id'],'export-task:'+task['id'],target,content,
        dict(task_type=task['task_type'],task_id=task['id'],attempt_no=lease.attempt_no,metadata=metadata),
        source_identity=task['input_digest'],kind=task['task_type'],task_id=task['id'],staged=staged)


def publish(db,root,task,lease,metadata):
    row=reconcile(db,root,task)
    if not row:
        raise s.invalid()
    saved,_=value(root,row,task)
    permitted=authorized(db,row,task,lease)
    if saved['metadata']!=metadata or (saved['attempt_no']!=lease.attempt_no and not permitted):
        raise s.invalid()
    return s.publish_candidate(db,root,row['id'],explicit_recovery=permitted)


def authorize(db,root,task):
    row=reconcile(db,root,task)
    if not row:
        return False
    value(root,row,task)
    s._scope_check(db,s._project(db,task['project_id']),0,allow_attributed_unknown=True)
    s.require_publication_allowed(db,task['project_id'],row['object_key'],task_id=task['id'])
    db.execute('UPDATE storage_reservations SET candidate_json=candidate_json || %s WHERE id=%s',
        (Jsonb(dict(recovery_revision=task['revision']+1,recovery_attempt=task['current_attempt']+1)),row['id']))
    return True


def recovery_mode(db,root,task):
    row=hold(db,task)
    if not row or task['status']!='failed':
        return None
    try:
        value(root,row,task)
        return 'local_candidate'
    except (s.StorageError,OSError,KeyError,TypeError):
        return 'blocked'


def protected(db,root,task):
    # Reconcile before old expiry cleanup: a rolled-back capture exists on disk.
    return reconcile(db,root,task) is not None


def retry_conversion(service,db,row,key,table):
    """Existing PDF/layout retry route; None means ordinary child semantics."""
    from app.adapters.task_store import TaskStore
    from app.domain.manuscripts.service import now
    from app.core.exceptions import StorageError
    task=dict(service.verify(db,row))
    candidate=reconcile(db,service.assets.directory,task)
    if candidate is None:
        return None
    service.verify_source(db,row)
    if db.execute('SELECT 1 FROM '+table+' WHERE parent_export_id=%s',(row['id'],)).fetchone():
        raise StorageError('task_transition_invalid','此导出已有后继版本，不能恢复旧候选。',409)
    # Keep the original creation request key and child idempotency namespace.
    if db.execute('SELECT 1 FROM '+table+' WHERE project_id=%s AND user_id=%s AND request_key=%s',
                  (row['project_id'],task['user_id'],key)).fetchone():
        raise StorageError('task_idempotency_conflict','请求标识已用于创建导出。',409)
    digest=sha256(key.encode()).hexdigest()
    receipts=candidate['candidate_json'].get('export_retry_requests',{})
    if digest in receipts:
        if task['status']=='succeeded':
            # Validate the actual artifact without opening a nested transaction.
            value(service.assets.directory,candidate,task)
        return dict(service.view(db,row),recovery_mode='local_candidate',recovery_request_key=key),200
    if task['status']!='failed' or task.get('error_code') not in STORAGE_ERRORS:
        raise StorageError('task_transition_invalid','原候选当前不能恢复。',409)
    authorize(db,service.assets.directory,task)
    revision=task['revision']
    task.update(status='queued',revision=revision+1,reason_code='retry_requested',error_code=None,
        retry_count=0,updated_at=max(now(),task['updated_at']),_retry_reason='manual_retry')
    service.store.update_task(db,task,revision);service.store.append_event(db,task,'requeued');service.store.enqueue(db,task)
    receipts[digest]=dict(revision=task['revision'],attempt_no=task['current_attempt']+1)
    db.execute('UPDATE storage_reservations SET candidate_json=candidate_json || %s WHERE id=%s',
        (Jsonb(dict(export_retry_requests=receipts)),candidate['id']))
    return dict(service.view(db,row),recovery_mode='local_candidate',recovery_request_key=key),202
