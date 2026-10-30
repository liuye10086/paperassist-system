"""Bio batch admission on the existing ledger and serialized writer transaction.

No object bytes are written here. Admission inserts provisional rows before one
aggregate quota/disk check; any rejection rolls back the complete transaction.
Settlement retains every immutable identity/hash/deletion check, and its caller
publishes business records in that same transaction.
"""
import re
from pathlib import Path
from uuid import uuid4
from . import service as s
from .deterministic import explicit_retry


def _scope(task):
    if task['task_type']=='bio_import':return 'bio_dataset'
    if task['task_type'] not in ('bio_analysis','bio_figure'):raise s.invalid()
    return task['task_type']


def admit_bio_manifest(db,root,task,entries,*,progress):
    kind=_scope(task);progress()
    # Import preserves up to 256 original members plus six derived indexes and
    # the manifest/candidate pair; analysis and figure retain their own bound.
    limit=task['input_snapshot']['settings']['max_members']+8 if kind=='bio_dataset' else 258
    if not 1<=len(entries)<=limit:raise s.invalid()
    if s.reconcile_intents(db,root,progress=progress):raise s.invalid()
    recovering=explicit_retry(db,task);project=s._project(db,task['project_id'])
    rows=[];operations=set()
    for entry_kind,operation,record in entries:
        progress()
        size=record['size_bytes'];sha=record['sha256'];key=s._key(root,Path(root)/record['object_key'])
        if (entry_kind!=kind or type(size) is not int or not 0<size<=268435456 or type(sha) is not str
                or not re.fullmatch('[a-f0-9]{64}',sha) or not isinstance(operation,str)
                or not 1<=len(operation)<=512 or operation in operations):raise s.invalid()
        operations.add(operation)
        s.require_publication_allowed(db,task['project_id'],key,task_id=task['id'])
        s._require_no_candidate_controller(db,key);s._require_object_identity(db,key,size,sha)
        existing=db.execute('SELECT * FROM storage_reservations WHERE namespace=%s AND project_id=%s AND operation_key=%s',
            (s.NAMESPACE,task['project_id'],operation)).fetchone()
        if existing:
            row=dict(existing)
            if any(row[k]!=value for k,value in dict(object_key=key,size_bytes=size,sha256=sha,
                task_id=task['id'],owner_id=task['user_id'],kind=kind).items()) or row['capacity_bytes'] is not None:
                raise s.invalid()
            if row['state'] not in ('reserved','settled'):raise s.invalid()
            if row['state']=='settled':
                try:
                    if s._digest(Path(root)/key)!=(size,sha):raise s.invalid()
                except OSError:raise s.invalid() from None
        else:
            registered=db.execute('SELECT * FROM storage_objects WHERE namespace=%s AND object_key=%s',(s.NAMESPACE,key)).fetchone()
            if registered and (registered['size_bytes']!=size or registered['sha256']!=sha or registered['state']!='present'):raise s.invalid()
            row=dict(id=str(uuid4()),namespace=s.NAMESPACE,project_id=task['project_id'],owner_id=project['owner_id'],
                operation_key=operation,object_key=key,size_bytes=size,state='reserved',kind=kind,task_id=task['id'],sha256=sha)
            if row['owner_id']!=task['user_id']:raise s.invalid()
            s._insert_reservation(db,row)
        rows.append(row);progress()
    # All provisional holds are visible to this transaction. Existing ledger
    # accounting deduplicates physical keys across operations and owner scopes.
    s._scope_check(db,project,0,allow_attributed_unknown=recovering)
    progress();s._disk_guard(db,root,0,progress=progress);progress()
    for row in rows:s._journal(db,root,row);progress()
    return rows


def settle_bio_manifest(db,root,task,rows,*,progress):
    kind=_scope(task);progress();recovering=explicit_retry(db,task)
    if recovering and s.reconcile_intents(db,root,progress=progress):raise s.invalid()
    s._scope_check(db,s._project(db,task['project_id']),0,allow_attributed_unknown=recovering)
    progress()
    for expected in rows:
        progress()
        row=db.execute('SELECT * FROM storage_reservations WHERE id=%s',(expected['id'],)).fetchone()
        if (not row or row['capacity_bytes'] is not None or row['state'] not in (('reserved','unknown','settled') if recovering else ('reserved','settled'))
                or row['kind']!=kind or row['task_id']!=task['id'] or row['project_id']!=task['project_id'] or row['owner_id']!=task['user_id']
                or any(row[k]!=expected[k] for k in ('namespace','project_id','owner_id','task_id','kind','operation_key','object_key','size_bytes','sha256'))):raise s.invalid()
        s._settle_verified(db,root,row)
        progress()
    progress()
