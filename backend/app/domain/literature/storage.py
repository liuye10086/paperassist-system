"""Durable bounded E-utilities responses on the shared candidate ledger."""
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID,uuid5
from psycopg.types.json import Jsonb

from app.domain.storage_governance import service as s, candidates as c, local_candidates as local
from app.domain.storage_governance.export_candidates import authorized
from .service import digest,require_snapshot,latest_checkpoint

CAPACITY=8*1024*1024+64*1024
NAMESPACE=UUID('099856cd-ebca-473a-b37c-b628f3e89db2')


def identity(task,operation,request,source_kind):
    operation_key='literature-task:'+task['id']+':'+digest(request)
    source=task['input_digest']+':'+digest([operation,request,source_kind])
    key='literature/'+str(uuid5(NAMESPACE,operation_key))+'/'+digest(request)+('.json' if operation=='esearch' else '.xml')
    return operation_key,source,key


def admit(db,root,task,lease,operation,request,source_kind):
    op,source,key=identity(task,operation,request,source_kind)
    row=local.lookup(db,root,task['project_id'],op,kind='literature',task_id=task['id'])
    if row:
        if row['candidate_json']['source_identity']!=source or row['object_key']!=key:
            raise s.invalid()
        if row['state']=='unknown' and not authorized(db,row,task,lease):
            raise s.invalid()
        if row['sha256']:
            value,raw=local.read(root,row,source)
            if (value['operation']!=operation or value['request']!=request or value['source_kind']!=source_kind
                    or (value['attempt_no']!=lease.attempt_no and not authorized(db,row,task,lease))):
                raise s.invalid()
            return row,(raw,dict(object_key=key,sha256=row['sha256'],size_bytes=row['size_bytes'],
                attempted_at=datetime.fromisoformat(value['attempted_at']),_storage_id=row['id']))
    row=s.admit_candidate(db,root,task['project_id'],op,Path(root)/key,CAPACITY,
        task_id=task['id'],source_identity=source,kind='literature')
    return row,None


def capture(db,root,task,lease,row,raw,operation,request,source_kind,attempted_at):
    op,source,key=identity(task,operation,request,source_kind)
    if type(raw) is not bytes or not 1<=len(raw)<=8*1024*1024:
        raise s.invalid()
    envelope=local.encode(dict(schema_version=1,kind='literature',project_id=task['project_id'],owner_id=task['user_id'],
        operation_key=op,task_id=task['id'],source_identity=source,
        value=dict(operation=operation,request=request,source_kind=source_kind,attempt_no=lease.attempt_no,attempted_at=attempted_at.isoformat())))
    if len(envelope)>64*1024:
        raise s.invalid()
    s.capture_candidate(db,root,row['id'],raw,[Path(root)/key],source_identity=source,descriptor=envelope,
        descriptor_path=Path(root)/'storage-candidates'/(row['id']+'.json'),write_path=Path(root)/key)
    return dict(object_key=key,sha256=sha256(raw).hexdigest(),size_bytes=len(raw),attempted_at=attempted_at,_storage_id=row['id'])


def publish(db,root,task,lease,evidence):
    if evidence.get('_storage_id'):
        row=c._row(db,evidence['_storage_id'])
        if (row['project_id'],row['owner_id'],row['task_id'],row['kind'])!=(task['project_id'],task['user_id'],task['id'],'literature'):
            raise s.invalid()
        s.publish_candidate(db,root,row['id'],explicit_recovery=authorized(db,row,task,lease))
    else:
        # Existing scoped cache bytes are already attributable from the receipt.
        # This also closes admission gaps for old typed cache objects before A2e scan.
        if (evidence['project_id'],evidence['user_id'])!=(task['project_id'],task['user_id']):
            raise s.invalid()
        path=Path(root)/evidence['object_key'];s._key(root,path)
        if s._digest(path)!=(evidence['size_bytes'],evidence['sha256']):raise s.invalid()
        s._require_no_candidate_controller(db,evidence['object_key'])
        s.require_publication_allowed(db,task['project_id'],evidence['object_key'])
        s._register(db,dict(object_key=evidence['object_key'],project_id=task['project_id'],owner_id=task['user_id'],kind='literature'),evidence['size_bytes'],evidence['sha256'])


def authorize(db,root,task):
    require_snapshot(task);latest_checkpoint(db,task)
    if s.reconcile_intents(db,root):raise s.invalid()
    rows=db.execute("SELECT * FROM storage_reservations WHERE task_id=%s AND kind='literature' AND state IN ('reserved','unknown')",(task['id'],)).fetchall()
    for raw in rows:
        row=dict(raw)
        if (row['project_id'],row['owner_id'])!=(task['project_id'],task['user_id']) or not row['operation_key'].startswith('literature-task:'+task['id']+':') or not row['candidate_json']['source_identity'].startswith(task['input_digest']+':'):
            raise s.invalid()
        if row['sha256']:
            value,_=local.read(root,row,row['candidate_json']['source_identity'])
            if identity(task,value['operation'],value['request'],value['source_kind'])!=(row['operation_key'],row['candidate_json']['source_identity'],row['object_key']):raise s.invalid()
        else:
            c._disk_guard(db,root,0)
        s.require_publication_allowed(db,task['project_id'],row['object_key'])
    s._scope_check(db,s._project(db,task['project_id']),0,allow_attributed_unknown=True)
    for row in rows:
        db.execute("UPDATE storage_reservations SET state=CASE WHEN sha256 IS NULL THEN 'reserved' ELSE state END,candidate_json=candidate_json || %s WHERE id=%s",
            (Jsonb(dict(recovery_revision=task['revision']+1,recovery_attempt=task['current_attempt']+1)),row['id']))
