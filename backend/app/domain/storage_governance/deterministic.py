"""Known local manifests on the existing ledger, never a second task state machine.

Admission commits before the caller's immutable byte writer; settlement uses its
publication transaction. Only an explicit retry of unchanged local input may
authorize rebuilding an absent reserved object with its original key/hash.
"""
import re
from pathlib import Path

from . import service as s

STORAGE_RETRY_CODES = frozenset({'storage_unavailable', 'task_worker_interrupted',
    'storage_quota_exceeded', 'storage_disk_insufficient', 'storage_accounting_unknown'})


def explicit_retry(db, task):
    return bool(db.execute("""SELECT 1 FROM task_events WHERE task_id=%s AND seq=%s
        AND event_type='requeued' AND reason_code='retry_requested' AND retry_reason='manual_retry'""",
        (task['id'], task['revision']-1)).fetchone())


def admit_manifest(db, root, task, entries):
    """entries = (kind, stable operation, {object_key,size_bytes,sha256})."""
    if s.reconcile_intents(db, root):
        raise s.invalid()
    recovering = explicit_retry(db, task)
    # Recheck even when every operation already owns a durable reservation.
    s._scope_check(db, s._project(db, task['project_id']), 0, allow_attributed_unknown=recovering)
    s._disk_guard(db, root, 0)
    rows = []
    for kind, operation, record in entries:
        row = s.reserve(db, root, task['project_id'], operation, Path(root)/record['object_key'],
            record['size_bytes'], sha256=record['sha256'], kind=kind, task_id=task['id'],
            allow_attributed_unknown=recovering)
        if (row['task_id'], row['kind'], row['owner_id']) != (task['id'], kind, task['user_id']):
            raise s.invalid()
        if row['state']=='settled':
            # Published history is never implicitly repaired by a byte writer.
            try:
                if s._digest(Path(root)/row['object_key']) != (row['size_bytes'], row['sha256']):
                    raise s.invalid()
            except OSError:
                raise s.invalid() from None
        rows.append(row)
    # No journal or object bytes until the complete manifest is admitted.
    for row in rows:
        s._journal(db, root, row)
    return rows


def settle_manifest(db, root, task, rows):
    recovering = explicit_retry(db, task)
    for expected in rows:
        row = db.execute('SELECT * FROM storage_reservations WHERE id=%s', (expected['id'],)).fetchone()
        if not row or any(row[k] != expected[k] for k in (
                'namespace','project_id','owner_id','task_id','kind','operation_key','object_key','size_bytes','sha256')):
            raise s.invalid()
        if recovering:
            s.recover_reservation(db, root, row['id'])
        else:
            s.settle(db, root, row['id'])


def authorize_rebuild(db, root, task, *, allowed, progress=None):
    """Explicit retry only, after caller verifies immutable source/checkpoint.

    allowed maps kind to (object prefix, immutable parse/candidate identifier,
    operation prefixes). Existing complete bytes are verified, absent reserved
    bytes remain charged and can only be rebuilt by exact manifest admission.
    """
    if s.reconcile_intents(db, root, **({'progress':progress} if progress is not None else {})):
        raise s.invalid()
    rows = db.execute("SELECT * FROM storage_reservations WHERE task_id=%s AND state IN ('reserved','unknown')",
        (task['id'],)).fetchall()
    for row in rows:
        if progress is not None:progress()
        if (row['namespace'] != s.NAMESPACE or row['project_id'] != task['project_id']
                or row['owner_id'] != task['user_id'] or row['capacity_bytes'] is not None or row['kind'] not in allowed):
            raise s.invalid()
        prefix, identifier, operations = allowed[row['kind']]
        operation_valid = bool(re.fullmatch(operations,row['operation_key'])) if isinstance(operations,str) else row['operation_key'] in operations
        if (not re.fullmatch(re.escape(prefix+'/'+identifier+'/')+r'[0-9a-f]{64}\.(json|bin)', row['object_key'])
                or row['object_key'].rsplit('/',1)[1].split('.')[0] != row['sha256']
                or not operation_valid):
            raise s.invalid()
        path = Path(root)/row['object_key']
        s._key(root,path); s.require_publication_allowed(db,task['project_id'],row['object_key'],task_id=task['id'])
        s._require_no_candidate_controller(db,row['object_key'])
        try:
            if s._digest(path) != (row['size_bytes'],row['sha256']):
                raise s.invalid()
        except FileNotFoundError:
            pass  # Frozen local input may reconstruct only the exact original bytes.
        except OSError:
            raise s.invalid() from None
    s._scope_check(db,s._project(db,task['project_id']),0,allow_attributed_unknown=True)
    s._disk_guard(db,root,0,**({'progress':progress} if progress is not None else {}))
    for row in rows:
        if progress is not None:progress()
        db.execute("UPDATE storage_reservations SET state='reserved' WHERE id=%s",(row['id'],))


def authorize_checkpoint_rebuild(db,root,task,checkpoint,service,*,ocr=False):
    """Source and accepted/current candidate are verified before ledger recovery."""
    source=checkpoint['state_json']['input_version']['source']
    service.require_raw(source,task['project_id'])
    service.read_candidate(task,checkpoint)
    checkpoints=db.execute('SELECT id FROM task_checkpoints WHERE task_id=%s',(task['id'],)).fetchall()
    identifiers=[row['id'] for row in checkpoints]
    from app.domain.ocr_review.service import candidate_id as ocr_candidate_id
    from app.domain.dataset_preparation.service import candidate_id as prepared_candidate_id
    identifier=(ocr_candidate_id if ocr else prepared_candidate_id)(task['id'])
    if ocr:
        allowed={'ocr_review':('ocr-reviews',identifier,
            {prefix+key for prefix in ('ocr_review:','ocr_review_publish:') for key in identifiers})}
    else:
        allowed={'prepared_dataset':('prepared-datasets',identifier,
            {prefix+key for prefix in ('prepared:','prepared_publish:') for key in identifiers})}
        if task['workflow_version'] in ('dataset_preparation_v2','dataset_preparation_v3'):
            allowed['quality_manifest']=(service.manifests.prefix,identifier,
                {prefix+key for prefix in ('quality_manifest:','quality_manifest_publish:') for key in identifiers})
    authorize_rebuild(db,root,task,allowed=allowed)
