"""Transaction-bound quota ledger and immutable local publication evidence.

Callers MUST hold the existing serialized writer transaction. Paths remain
internal. The namespace is portable across host/container mount paths; the DB
schema is the ledger boundary. Intents recover attribution after DB rollback.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4, UUID

from app.core.exceptions import StorageError

GIB=1024**3
NAMESPACE='local:assets-v1'
LIMITS={'project':GIB,'user':5*GIB}
ACTIVE=('reserved','unknown')

# Candidate stages share this module's ledger and policy implementation.
from .candidates import (admit_candidate,capture_candidate,publish_candidate,
                         _disk_guard,_reconcile_candidates)


def invalid():
    return StorageError('storage_accounting_unknown','存储归属或预留状态未知，请先核对已有安全产物。',409)


def initialize_policy(db,scope_type,scope_id,*,legacy=False):
    if scope_type not in LIMITS:raise invalid()
    db.execute('''INSERT INTO storage_policies(scope_type,scope_id,mode,limit_bytes)
        VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
        (scope_type,scope_id,'observe_only' if legacy else 'enforced',LIMITS[scope_type]))


def set_policy(db,scope_type,scope_id,limit_bytes,mode,*,expected_revision=None,actor_user_id=None,reason='Trusted local policy change'):
    if scope_type not in LIMITS or mode not in ('observe_only','enforced') or type(limit_bytes) is not int or not 0<=limit_bytes<=2**63-1:
        raise StorageError('storage_policy_invalid','存储配额参数无效。',422)
    table={'project':'projects','user':'users'}[scope_type]
    if not db.execute('SELECT id FROM '+table+' WHERE id=%s',(scope_id,)).fetchone():
        raise StorageError('not_found','配额对象不存在。',404)
    if not isinstance(reason,str) or not 5<=len(reason.strip())<=500:
        raise StorageError('storage_policy_invalid','配额修改必须说明原因。',422)
    initialize_policy(db,scope_type,scope_id,legacy=True)
    prior=db.execute('SELECT * FROM storage_policies WHERE scope_type=%s AND scope_id=%s',(scope_type,scope_id)).fetchone()
    if expected_revision is not None and (type(expected_revision) is not int or prior['revision']!=expected_revision):
        raise StorageError('storage_policy_revision_conflict','配额已更新，请重新载入后确认。',409)
    if actor_user_id is not None:
        from app.domain.admin_operations import require_identity
        require_identity(db,actor_user_id)
    db.execute('''INSERT INTO storage_policies(scope_type,scope_id,limit_bytes,mode) VALUES(%s,%s,%s,%s)
        ON CONFLICT(scope_type,scope_id) DO UPDATE SET limit_bytes=excluded.limit_bytes,mode=excluded.mode,revision=storage_policies.revision+1,updated_at=clock_timestamp()''',
        (scope_type,scope_id,limit_bytes,mode))
    revision=prior['revision']+1
    db.execute('''INSERT INTO storage_policy_events(id,scope_type,scope_id,revision,actor_user_id,reason,
        before_limit_bytes,after_limit_bytes,before_mode,after_mode) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (str(uuid4()),scope_type,scope_id,revision,actor_user_id,reason.strip(),prior['limit_bytes'],limit_bytes,prior['mode'],mode))
    return dict(scope_type=scope_type,scope_id=scope_id,limit_bytes=limit_bytes,mode=mode,revision=revision)


def disk_status(root):
    measured=datetime.now(timezone.utc).isoformat()
    try:
        value=shutil.disk_usage(Path(root))
        threshold=max(10*GIB,(value.total+9)//10)
        return dict(total_bytes=value.total,free_bytes=value.free,threshold_bytes=threshold,
                    status='sufficient' if value.free>=threshold else 'insufficient',measured_at=measured)
    except OSError:
        return dict(total_bytes=None,free_bytes=None,threshold_bytes=None,status='unknown',measured_at=measured)


def _key(root,path):
    root=Path(root).absolute();path=Path(path).absolute()
    try:relative=path.relative_to(root)
    except ValueError:raise invalid() from None
    if not relative.parts or any(part in ('.','..') or ':' in part or '\\' in part for part in relative.parts):raise invalid()
    for item in (root,*[root.joinpath(*relative.parts[:i]) for i in range(1,len(relative.parts)+1)]):
        if item.is_symlink() or (hasattr(item,'is_junction') and item.is_junction()):raise invalid()
    if not path.resolve().is_relative_to(root.resolve()):raise invalid()
    return relative.as_posix()


def _project(db,project_id):
    row=db.execute('SELECT id,owner_id FROM projects WHERE id=%s',(project_id,)).fetchone()
    if not row:raise StorageError('project_not_found','项目不存在。',404)
    return row


def require_publication_allowed(db,project_id,object_key,*,task_id=None):
    """Deletion module extends this guard; existing retained originals are readable."""
    _project(db,project_id)
    from .guards import require_scope_open
    task=db.execute('SELECT * FROM tasks WHERE id=%s',(task_id,)).fetchone() if task_id else None
    require_scope_open(db,project_id,task=task,object_key=object_key)
    row=db.execute('SELECT state FROM storage_objects WHERE namespace=%s AND object_key=%s',(NAMESPACE,object_key)).fetchone()
    if row and row['state']=='deleted':raise invalid()


def usage(db,*,user_id=None,project_id=None):
    condition='';args=()
    if project_id is not None:condition=' AND r.project_id=%s';args=(project_id,)
    elif user_id is not None:condition=' AND r.owner_id=%s';args=(user_id,)
    rows=db.execute('''SELECT DISTINCT o.id,o.size_bytes,o.state,o.namespace,o.object_key FROM storage_objects o
        JOIN storage_references r ON r.object_id=o.id WHERE o.state<>'deleted' '''+condition,args).fetchall()
    where=' WHERE state IN (\'reserved\',\'unknown\')'
    if project_id is not None:where+=' AND project_id=%s'
    elif user_id is not None:where+=' AND owner_id=%s'
    reservations=db.execute('SELECT * FROM storage_reservations'+where,args).fetchall()
    known={(row['namespace'],row['object_key']) for row in rows}
    pending={}
    for row in reservations:
        key=(row['namespace'],row['object_key'])
        metadata=row.get('candidate_json') or {}
        charge=row['capacity_bytes'] if row['capacity_bytes'] is not None and row['sha256'] is None else row['size_bytes']*metadata.get('copies',1)
        # Registration of the primary does not register its companion or extra copies.
        charge=max(0,charge-(row['size_bytes'] if key in known else 0))
        if charge:pending[key]=max(pending.get(key,0),charge)
        descriptor=metadata.get('descriptor')
        if descriptor:
            companion=(row['namespace'],descriptor['object_key'])
            if companion not in known:pending[companion]=max(pending.get(companion,0),descriptor['size_bytes'])
    size=sum(row['size_bytes'] for row in rows);reserved=sum(pending.values())
    scope='project' if project_id is not None else 'user' if user_id is not None else None
    policy=db.execute('SELECT mode,limit_bytes,updated_at,revision FROM storage_policies WHERE scope_type=%s AND scope_id=%s',
        (scope,project_id if project_id is not None else user_id)).fetchone() if scope else None
    quota=dict(policy) if policy else dict(mode='observe_only',limit_bytes=LIMITS[scope] if scope else None,updated_at=None,revision=0)
    limit=quota['limit_bytes'];unknown=sum(r['state']=='unknown' for r in reservations)+sum(r['state']!='present' for r in rows)
    status='unknown' if unknown else 'exceeded' if limit is not None and size+reserved>=limit else 'warning' if limit and (size+reserved)*5>=limit*4 else 'normal'
    return dict(usage_scope='registered_asset_objects',usage_bytes=size,reserved_bytes=reserved,object_count=len(rows),reservation_count=len(reservations),
        unknown_reservation_count=sum(r['state']=='unknown' for r in reservations),unknown_object_count=sum(r['state']!='present' for r in rows),
        unverified_object_count=sum(r['state'] in ('changed','unknown') for r in rows),missing_object_count=sum(r['state']=='missing' for r in rows),
        quota=quota,status=status,warning_ratio=0.8,deny_ratio=1.0,retention_policy='retain_all',cleanup_status='disabled',
        worker_concurrency=None,worker_concurrency_status='see_admin_runtime_status')


def _scope_check(db,project,increment,*,object_key=None,allow_attributed_unknown=False):
    for scope,identifier in (('project',project['id']),('user',project['owner_id'])):
        if identifier is None:continue
        value=usage(db,**({'project_id':identifier} if scope=='project' else {'user_id':identifier}))
        # Last-known size bounds a proven missing object conservatively, but
        # cannot bound changed/unreadable bytes. Recovery may retain sibling
        # attributed intent holds, never bypass this physical uncertainty.
        if value['unverified_object_count']:raise invalid()
        if value['unknown_reservation_count'] and not allow_attributed_unknown:raise invalid()
        delta=increment
        if object_key is not None:
            column='project_id' if scope=='project' else 'owner_id'
            known=db.execute('SELECT 1 FROM storage_objects o JOIN storage_references r ON r.object_id=o.id '
                +'WHERE o.namespace=%s AND o.object_key=%s AND o.state<>\'deleted\' AND r.'+column+'=%s',
                (NAMESPACE,object_key,identifier)).fetchone()
            pending=db.execute("SELECT 1 FROM storage_reservations WHERE namespace=%s AND object_key=%s AND state IN ('reserved','unknown') AND "+column+'=%s',
                (NAMESPACE,object_key,identifier)).fetchone()
            if known or pending:delta=0
        if value['quota']['mode']=='enforced' and value['usage_bytes']+value['reserved_bytes']+delta>value['quota']['limit_bytes']:
            raise StorageError('storage_quota_exceeded','存储配额不足；已有成果仍可查看下载，请调整配额后显式恢复。',409)


def _require_object_identity(db,key,size_bytes,digest):
    # A physical key is immutable across operations/projects, including before
    # the first write. Unknown hashes cannot defeat known hashes at settlement.
    rows=list(db.execute("SELECT size_bytes,sha256 FROM storage_reservations WHERE namespace=%s AND object_key=%s AND state<>'released' AND (capacity_bytes IS NULL OR sha256 IS NOT NULL)",(NAMESPACE,key)))
    rows.extend(db.execute('SELECT size_bytes,sha256 FROM storage_objects WHERE namespace=%s AND object_key=%s',(NAMESPACE,key)))
    if any(row['size_bytes']!=size_bytes or (digest is not None and row['sha256'] is not None and row['sha256']!=digest) for row in rows):
        raise StorageError('storage_reservation_conflict','同一存储对象的尺寸或内容身份不一致。',409)


def reserve(db,root,project_id,operation_key,path,size_bytes,*,kind='derived',task_id=None,sha256=None,allow_attributed_unknown=False):
    if reconcile_intents(db,root):raise invalid()
    if type(size_bytes) is not int or not 0<=size_bytes<=2**63-1 or not isinstance(operation_key,str) or not 1<=len(operation_key)<=512:
        raise invalid()
    key=_key(root,path)
    require_publication_allowed(db,project_id,key,task_id=task_id)
    _require_no_candidate_controller(db,key)
    _require_object_identity(db,key,size_bytes,sha256)
    project=_project(db,project_id)
    existing=db.execute('SELECT * FROM storage_reservations WHERE namespace=%s AND project_id=%s AND operation_key=%s',
        (NAMESPACE,project_id,operation_key)).fetchone()
    if existing:
        if existing['object_key']!=key or existing['size_bytes']!=size_bytes or (sha256 is not None and existing['sha256'] not in (None,sha256)):
            raise StorageError('storage_reservation_conflict','存储操作身份与已有产物不一致。',409)
        if existing['state']=='unknown':raise invalid()
        if existing['state']!='released':return dict(existing)
        # Release is terminal. A retry uses a new explicit operation identity.
        raise StorageError('storage_reservation_conflict','存储预留已释放，请使用新的操作身份。',409)
    _disk_guard(db,root,size_bytes,key=key)
    registered=db.execute('SELECT id,size_bytes,state FROM storage_objects WHERE namespace=%s AND object_key=%s',(NAMESPACE,key)).fetchone()
    increment=size_bytes
    if registered:
        if registered['size_bytes']!=size_bytes or registered['state']!='present':raise invalid()
        if db.execute('SELECT 1 FROM storage_references WHERE object_id=%s AND project_id=%s',(registered['id'],project_id)).fetchone():increment=0
    _scope_check(db,project,increment,object_key=key,allow_attributed_unknown=allow_attributed_unknown)
    row=dict(id=str(uuid4()),namespace=NAMESPACE,project_id=project_id,owner_id=project['owner_id'],operation_key=operation_key,
             object_key=key,size_bytes=size_bytes,state='reserved',kind=kind,task_id=task_id,sha256=sha256)
    _insert_reservation(db,row)
    return row


def _insert_reservation(db,row):
    fields=('id','namespace','project_id','owner_id','operation_key','object_key','size_bytes','state','kind','task_id','sha256')
    db.execute('INSERT INTO storage_reservations('+','.join(fields)+') VALUES('+','.join(['%s']*len(fields))+')',tuple(row[k] for k in fields))


def _digest(path):
    digest=hashlib.sha256();size=0
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block);size+=len(block)
    return size,digest.hexdigest()


def _register(db,row,size,digest,*,state='present'):
    if state=='present':require_publication_allowed(db,row['project_id'],row['object_key'],task_id=row.get('task_id'))
    obj=db.execute('SELECT * FROM storage_objects WHERE namespace=%s AND object_key=%s',(NAMESPACE,row['object_key'])).fetchone()
    if obj and (obj['size_bytes']!=size or obj['sha256']!=digest or obj['state']=='deleted'):raise invalid()
    identifier=obj['id'] if obj else str(uuid4())
    db.execute('''INSERT INTO storage_objects(id,namespace,object_key,size_bytes,sha256,state) VALUES(%s,%s,%s,%s,%s,%s)
        ON CONFLICT(namespace,object_key) DO UPDATE SET state=excluded.state,scanned_at=clock_timestamp()''',
        (identifier,NAMESPACE,row['object_key'],size,digest,state))
    db.execute('''INSERT INTO storage_references(object_id,project_id,owner_id,kind) VALUES(%s,%s,%s,%s)
        ON CONFLICT(object_id,project_id) DO NOTHING''',(identifier,row['project_id'],row['owner_id'],row['kind']))
    return identifier


def settle(db,root,reservation_id):
    row=db.execute('SELECT * FROM storage_reservations WHERE id=%s',(reservation_id,)).fetchone()
    if not row or row['state'] in ('released','unknown'):raise invalid()
    if row.get('capacity_bytes') is not None:raise invalid()
    if row['state']!='settled':_scope_check(db,_project(db,row['project_id']),0)
    return _settle_verified(db,root,row)


def _settle_verified(db,root,row):
    if row.get('capacity_bytes') is None:_require_no_candidate_controller(db,row['object_key'])
    require_publication_allowed(db,row['project_id'],row['object_key'],task_id=row.get('task_id'))
    path=Path(root)/row['object_key'];_key(root,path)
    try:size,digest=_digest(path)
    except OSError:raise invalid() from None
    if size!=row['size_bytes'] or (row['sha256'] and row['sha256']!=digest):raise invalid()
    _require_object_identity(db,row['object_key'],size,digest)
    identifier=_register(db,row,size,digest)
    db.execute("UPDATE storage_reservations SET state='settled',sha256=%s WHERE id=%s",(digest,row['id']))
    return identifier


def _require_no_candidate_controller(db,key):
    # Both primary and companion belong to the active v2 publication, including
    # restored v1 rows that predate this admission check. Settled references dedup.
    if db.execute("""SELECT 1 FROM storage_reservations WHERE namespace=%s
        AND (object_key=%s OR candidate_json->'descriptor'->>'object_key'=%s OR candidate_json->'locations' ? %s)
        AND capacity_bytes IS NOT NULL AND state IN ('reserved','unknown')""",(NAMESPACE,key,key,key)).fetchone():
        raise StorageError('storage_reservation_conflict','此存储位置由尚未完成发布的有界候选管理。',409)


def release(db,reservation_id,*,unknown=False):
    # Only an orchestrator that has proved no bytes exist may request release.
    db.execute("UPDATE storage_reservations SET state=%s WHERE id=%s AND state IN ('reserved','unknown')",
        ('unknown' if unknown else 'released',reservation_id))


def _journal(db,root,row):
    directory=Path(root)/'.storage-intents';_key(root,directory)
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/(row['id']+'.json');_key(root,path)
    payload={k:row[k] for k in ('id','namespace','project_id','owner_id','operation_key','object_key','size_bytes','kind','task_id','sha256')}
    payload.update(schema=db.config.schema,database=db.config.url.database)
    raw=json.dumps(payload,ensure_ascii=True,sort_keys=True).encode()
    if len(raw)>8192:raise invalid()
    try:
        with path.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    except FileExistsError:
        with path.open('rb') as stream:previous=stream.read(8193)
        try:
            saved=json.loads(previous)
            # Restored schemas/host mounts preserve immutable origin metadata.
            if len(previous)>8192 or any(saved[k]!=payload[k] for k in payload if k not in ('schema','database')):raise invalid()
        except (ValueError,KeyError,TypeError):raise invalid() from None


def reconcile_intents(db,root,*,progress=None):
    directory=Path(root)/'.storage-intents'
    if not directory.exists():return 0
    _key(root,directory);unknown=_reconcile_candidates(db,root,progress=progress)
    for path in directory.glob('*.json'):
        if progress is not None:progress()
        if path.name.endswith(('.allocation.json','.capture.json','.complete.json')):continue
        try:
            _key(root,path)
            with path.open('rb') as stream:raw=stream.read(8193)
            if len(raw)>8192:raise invalid()
            row=json.loads(raw)
            if row['namespace']!=NAMESPACE or str(UUID(row['id']))+'.json'!=path.name:raise invalid()
            persisted=db.execute('SELECT * FROM storage_reservations WHERE id=%s',(row['id'],)).fetchone()
            if persisted:
                if any(persisted[k]!=row[k] for k in ('project_id','owner_id','operation_key','object_key','size_bytes','kind','task_id')):raise invalid()
                continue
            _key(root,Path(root)/row['object_key'])
            project=_project(db,row['project_id'])
            if row['owner_id']!=project['owner_id']:raise invalid()
            if type(row['size_bytes']) is not int or not 0<=row['size_bytes']<=2**63-1:raise invalid()
            row['state']='unknown';_insert_reservation(db,row)
        except (OSError,ValueError,KeyError,TypeError,StorageError):unknown+=1
    return unknown


def recover_reservation(db,root,reservation_id):
    """Explicit local-only recovery; verifies original identity and bytes, no provider call."""
    if reconcile_intents(db,root):raise invalid()
    row=db.execute('SELECT * FROM storage_reservations WHERE id=%s',(reservation_id,)).fetchone()
    if not row or row['state'] not in ('unknown','reserved','settled'):raise invalid()
    if row.get('capacity_bytes') is not None:raise invalid()
    if row['state']=='settled':return settle(db,root,reservation_id)
    # Exclude this hold, then recheck tightened policy before publication.
    db.execute("UPDATE storage_reservations SET state='released' WHERE id=%s",(reservation_id,))
    try:_scope_check(db,_project(db,row['project_id']),row['size_bytes'],object_key=row['object_key'],allow_attributed_unknown=True)
    finally:db.execute('UPDATE storage_reservations SET state=%s WHERE id=%s',(row['state'],reservation_id))
    return _settle_verified(db,root,row)


@contextmanager
def publication(db,root,project_id,operation_key,path,content,*,kind='derived',task_id=None,recover=False):
    if reconcile_intents(db,root):raise invalid()
    digest=hashlib.sha256(content).hexdigest()
    prior=db.execute('SELECT * FROM storage_reservations WHERE namespace=%s AND project_id=%s AND operation_key=%s',
        (NAMESPACE,project_id,operation_key)).fetchone() if recover else None
    if prior and prior['state']=='unknown':
        if (prior['object_key']!=_key(root,path) or prior['size_bytes']!=len(content) or prior['sha256']!=digest
                or prior['task_id']!=task_id or prior['kind']!=kind):raise invalid()
        if Path(path).exists():
            recover_reservation(db,root,prior['id'])
        else:
            # Explicit replay of identical original bytes after a proved absent
            # target. Paid producer retries must NOT opt in implicitly.
            _disk_guard(db,root,0)
            db.execute("UPDATE storage_reservations SET state='released' WHERE id=%s",(prior['id'],))
            try:_scope_check(db,_project(db,project_id),len(content),object_key=prior['object_key'],allow_attributed_unknown=True)
            finally:db.execute("UPDATE storage_reservations SET state='unknown' WHERE id=%s",(prior['id'],))
            db.execute("UPDATE storage_reservations SET state='reserved' WHERE id=%s",(prior['id'],))
        row=dict(db.execute('SELECT * FROM storage_reservations WHERE id=%s',(prior['id'],)).fetchone())
    else:
        row=reserve(db,root,project_id,operation_key,path,len(content),kind=kind,task_id=task_id,sha256=digest)
    _journal(db,root,row)
    try:
        yield row
        if recover:recover_reservation(db,root,row['id'])
        else:settle(db,root,row['id'])
    except BaseException:
        # Caller may roll back; journal remains and prevents lost attribution.
        release(db,row['id'],unknown=True)
        raise


def inventory(db,root):
    """Read-only filesystem scan; governance rows only, never business row mutation."""
    from .inventory import scan
    return scan(db,root)
