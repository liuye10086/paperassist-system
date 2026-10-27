"""Bounded candidate stages on the existing reservation ledger.

No connection ownership: all operations use the caller's serialized writer.
Allocation and capture journals are immutable and contain no research content.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4
from psycopg.types.json import Jsonb
from app.core.exceptions import StorageError
from . import service as s

PNG_LIMIT=12*1024*1024
DESCRIPTOR_LIMIT=8*1024*1024
FIGURE_CAPACITY=PNG_LIMIT+DESCRIPTOR_LIMIT
FIGURE_DESCRIPTOR_FORMAT='figure-v1'


def _path(root,key):
    if not isinstance(key,str) or '\\' in key or ':' in key or key.startswith('/'):
        raise s.invalid()
    parts=key.split('/')
    if any(p in ('','.','..') for p in parts):raise s.invalid()
    path=Path(root).joinpath(*parts)
    if s._key(root,path)!=key:raise s.invalid()
    return path


def _row(db,identifier):
    row=db.execute('SELECT * FROM storage_reservations WHERE id=%s',(identifier,)).fetchone()
    if not row or row['capacity_bytes'] is None or row['state']=='released':raise s.invalid()
    return dict(row)


def _present(root,row):
    if not row['sha256']:return []
    locations=(row.get('candidate_json') or {}).get('locations',[row['object_key']])
    found=[]
    for key in locations:
        path=_path(root,key)
        try:size,digest=s._digest(path)
        except FileNotFoundError:continue
        except OSError:raise s.invalid() from None
        if (size,digest)!=(row['size_bytes'],row['sha256']):raise s.invalid()
        found.append(path)
    return found


def _disk_guard(db,root,increment,*,key=None):
    """Current schema, all owners/projects, max by physical key; never zero on failure."""
    pending={}
    for raw in db.execute("SELECT * FROM storage_reservations WHERE state IN ('reserved','unknown')"):
        row=dict(raw);charge=row['size_bytes']
        if row['capacity_bytes'] is not None:
            charge=row['capacity_bytes'] if row['sha256'] is None else row['size_bytes']
            if row['sha256']:
                try:
                    if _present(root,row):charge=0
                except StorageError:pass
            descriptor=(row.get('candidate_json') or {}).get('descriptor')
            if descriptor:
                try:present=s._digest(_path(root,descriptor['object_key']))==(descriptor['size_bytes'],descriptor['sha256'])
                except (OSError,StorageError):present=False
                if not present:charge+=descriptor['size_bytes']
        else:
            try:
                size,digest=s._digest(_path(root,row['object_key']))
                if size==row['size_bytes'] and row['sha256'] is not None and digest==row['sha256']:charge=0
            except (OSError,StorageError):pass
        identity=(row['namespace'],row['object_key'])
        pending[identity]=max(pending.get(identity,0),charge)
    # A second reference to an existing physical key is not a second write.
    if key is not None and (s.NAMESPACE,key) in pending:increment=0
    if key is not None:
        obj=db.execute("SELECT * FROM storage_objects WHERE namespace=%s AND object_key=%s AND state='present'",(s.NAMESPACE,key)).fetchone()
        if obj:
            try:
                if s._digest(_path(root,key))==(obj['size_bytes'],obj['sha256']):increment=0
            except OSError:pass
    disk=s.disk_status(root)
    if disk['status']!='sufficient' or disk['free_bytes']-sum(pending.values())-increment<disk['threshold_bytes']:
        raise StorageError('storage_disk_insufficient','磁盘可用空间不足或测量失败，请检查存储后显式恢复。',507,
            params={k:disk[k] for k in ('free_bytes','threshold_bytes','total_bytes') if disk[k] is not None})


def _journal(db,root,row,stage):
    payload={k:row[k] for k in ('id','namespace','project_id','owner_id','operation_key','object_key','kind','task_id','capacity_bytes')}
    payload.update(version=2,stage=stage,source_identity=row['candidate_json']['source_identity'])
    payload.update(schema=db.config.schema,database=db.config.url.database)
    if stage in ('capture','complete'):
        payload.update(size_bytes=row['size_bytes'],sha256=row['sha256'],locations=row['candidate_json']['locations'])
        if row['candidate_json'].get('descriptor'):payload['descriptor']=row['candidate_json']['descriptor']
        if row['candidate_json'].get('descriptor_format'):payload['descriptor_format']=row['candidate_json']['descriptor_format']
    directory=Path(root)/'.storage-intents';s._key(root,directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/(row['id']+'.'+stage+'.json');s._key(root,path)
    raw=json.dumps(payload,sort_keys=True,ensure_ascii=True).encode()
    if len(raw)>8192:raise s.invalid()
    try:
        with path.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    except FileExistsError:
        with path.open('rb') as stream:previous=stream.read(8193)
        try:previous=json.loads(previous)
        except (ValueError,TypeError):raise s.invalid() from None
        if any(previous.get(k)!=v for k,v in payload.items() if k not in ('schema','database')):raise s.invalid()


def admit_candidate(db,root,project_id,operation_key,path,max_bytes,*,task_id,source_identity,kind='figure'):
    if type(max_bytes) is not int or not 0<max_bytes<=2**63-1 or not isinstance(source_identity,str) or not 1<=len(source_identity)<=512:raise s.invalid()
    if s.reconcile_intents(db,root):raise s.invalid()
    key=s._key(root,path);s.require_publication_allowed(db,project_id,key,task_id=task_id)
    prior=db.execute('SELECT * FROM storage_reservations WHERE namespace=%s AND project_id=%s AND operation_key=%s',(s.NAMESPACE,project_id,operation_key)).fetchone()
    if prior:
        row=_row(db,prior['id'])
        if (row['object_key'],row['capacity_bytes'],row['task_id'],row['kind'],row['candidate_json']['source_identity'])!=(key,max_bytes,task_id,kind,source_identity):raise s.invalid()
        if row['state']=='unknown':raise s.invalid()
        return row
    if db.execute("SELECT 1 FROM storage_reservations WHERE namespace=%s AND object_key=%s AND state<>'released'",(s.NAMESPACE,key)).fetchone():raise s.invalid()
    project=s._project(db,project_id);_disk_guard(db,root,max_bytes,key=key)
    s._scope_check(db,project,max_bytes,object_key=key)
    row=dict(id=str(uuid4()),namespace=s.NAMESPACE,project_id=project_id,owner_id=project['owner_id'],operation_key=operation_key,
        object_key=key,size_bytes=0,sha256=None,state='reserved',kind=kind,task_id=task_id,capacity_bytes=max_bytes,
        candidate_json={'source_identity':source_identity})
    s._insert_reservation(db,row)
    db.execute('UPDATE storage_reservations SET capacity_bytes=%s,candidate_json=%s WHERE id=%s',(max_bytes,Jsonb(row['candidate_json']),row['id']))
    _journal(db,root,row,'allocation')
    return row


def capture_candidate(db,root,identifier,content,locations,*,source_identity,descriptor=None,descriptor_path=None,write_path=None,descriptor_format=None):
    row=_row(db,identifier)
    if row['candidate_json']['source_identity']!=source_identity or type(content) is not bytes or len(content)>row['capacity_bytes']:raise s.invalid()
    keys=list(dict.fromkeys([s._key(root,p) for p in locations]+[row['object_key']]))
    if len(keys)>4:raise s.invalid()
    for key in keys:s.require_publication_allowed(db,row['project_id'],key,task_id=row.get('task_id'))
    size=len(content);digest=hashlib.sha256(content).hexdigest()
    if row['sha256'] is not None and (row['size_bytes']!=size or row['sha256']!=digest or row['candidate_json']['locations']!=keys):raise s.invalid()
    row.update(size_bytes=size,sha256=digest,candidate_json={**row['candidate_json'],'locations':keys})
    if descriptor is not None:
        if type(descriptor) is not bytes:raise s.invalid()
        if descriptor_format not in (None,FIGURE_DESCRIPTOR_FORMAT):raise s.invalid()
        if row['candidate_json'].get('descriptor'):
            if row['candidate_json'].get('descriptor_format')!=descriptor_format:raise s.invalid()
            # Completed evidence may never be silently replaced after deletion.
            if _descriptor_completed(root,row):read_descriptor(root,row)
        if len(descriptor)>DESCRIPTOR_LIMIT or size+len(descriptor)>row['capacity_bytes']:
            # Preserve the already-paid bounded PNG, but never claim a missing
            # complete descriptor is locally recoverable.
            if s._key(root,write_path) not in keys:raise s.invalid()
            _journal(db,root,row,'capture');_write_immutable(write_path,content)
            raise s.invalid()
        key=s._key(root,descriptor_path)
        if key in keys or s._key(root,write_path) not in keys:raise s.invalid()
        s.require_publication_allowed(db,row['project_id'],key,task_id=row.get('task_id'))
        companion={'object_key':key,'size_bytes':len(descriptor),'sha256':hashlib.sha256(descriptor).hexdigest()}
        if row['candidate_json'].get('descriptor') not in (None,companion):raise s.invalid()
        row['candidate_json']['descriptor']=companion
        if descriptor_format:row['candidate_json']['descriptor_format']=descriptor_format
    _journal(db,root,row,'capture')
    # These two immutable research objects are covered by the precommitted
    # allocation. They precede SQL capture: rollback cannot erase the only
    # complete PNG or the business descriptor needed for local-only recovery.
    if descriptor is not None:
        _write_immutable(write_path,content)
        _write_immutable(descriptor_path,descriptor)
        # Durable completion evidence precedes SQL capture. Missing or corrupt
        # completed descriptors cannot be reclassified as a first-write failure.
        _journal(db,root,row,'complete')
        row['candidate_json']['descriptor_complete']=True
    db.execute('UPDATE storage_reservations SET size_bytes=%s,sha256=%s,candidate_json=%s WHERE id=%s',(size,digest,Jsonb(row['candidate_json']),identifier))
    return row


def _write_immutable(path,content):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    try:
        with path.open('xb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
    except FileExistsError:
        if s._digest(path)!=(len(content),hashlib.sha256(content).hexdigest()):raise s.invalid()


def read_descriptor(root,row):
    descriptor=row['candidate_json'].get('descriptor')
    if not descriptor or not 0<=descriptor['size_bytes']<=DESCRIPTOR_LIMIT:raise s.invalid()
    path=_path(root,descriptor['object_key'])
    try:
        with path.open('rb') as stream:raw=stream.read(DESCRIPTOR_LIMIT+1)
    except OSError:raise s.invalid() from None
    if len(raw)!=descriptor['size_bytes'] or hashlib.sha256(raw).hexdigest()!=descriptor['sha256']:raise s.invalid()
    try:return json.loads(raw)
    except (ValueError,TypeError):raise s.invalid() from None


def _descriptor_completed(root,row):
    return bool(row['candidate_json'].get('descriptor_complete')) or _path(root,'.storage-intents/'+row['id']+'.complete.json').exists()


def candidate_recovery_mode(root,row,*,business_candidate=False):
    """Read-only physical capability; callers separately validate source and receipt."""
    if not row['sha256']:return 'original_response'
    try:
        if len(_present(root,row))!=1:return 'blocked'
        read_descriptor(root,row)
        return 'local_candidate'
    except StorageError:
        metadata=row['candidate_json'];descriptor=metadata.get('descriptor')
        if (not business_candidate and descriptor and metadata.get('descriptor_format')==FIGURE_DESCRIPTOR_FORMAT
                and not _descriptor_completed(root,row) and not _path(root,descriptor['object_key']).exists()):
            # No complete descriptor ever became authoritative. Only absence is
            # repairable; partial/corrupt files remain preserved for inspection.
            try:return 'original_response' if len(_present(root,row))==1 else 'blocked'
            except StorageError:pass
        return 'blocked'


def task_recovery_mode(db,root,task):
    row=task_hold(db,task)
    if not row:return 'original_response'
    mode=candidate_recovery_mode(root,row,business_candidate=task.get('figure_candidate') is not None)
    if mode=='original_response' and row['sha256']:
        if not db.execute('SELECT 1 FROM model_calls WHERE task_id=%s AND provider_response_id IS NOT NULL',(task['id'],)).fetchone():return 'blocked'
    return mode


def _reconcile_candidates(db,root):
    directory=Path(root)/'.storage-intents';unknown=0
    for stage in ('allocation','capture','complete'):
        for path in directory.glob('*.'+stage+'.json'):
            try:
                s._key(root,path)
                with path.open('rb') as stream:raw=stream.read(8193)
                if len(raw)>8192:raise s.invalid()
                value=json.loads(raw)
                if value['version']!=2 or value['stage']!=stage or value['namespace']!=s.NAMESPACE or path.name!=str(UUID(value['id']))+'.'+stage+'.json':raise s.invalid()
                _path(root,value['object_key'])
                project=s._project(db,value['project_id'])
                if project['owner_id']!=value['owner_id'] or type(value['capacity_bytes']) is not int or not 0<value['capacity_bytes']<=2**63-1:raise s.invalid()
                row=db.execute('SELECT * FROM storage_reservations WHERE id=%s',(value['id'],)).fetchone()
                if not row:
                    row={**value,'size_bytes':0,'sha256':None,'state':'unknown','candidate_json':{'source_identity':value['source_identity']}}
                    s._insert_reservation(db,row)
                    db.execute('UPDATE storage_reservations SET capacity_bytes=%s,candidate_json=%s WHERE id=%s',(value['capacity_bytes'],Jsonb(row['candidate_json']),value['id']))
                row=dict(row)
                if any(row[k]!=value[k] for k in ('namespace','project_id','owner_id','operation_key','object_key','kind','task_id','capacity_bytes')) or row['candidate_json']['source_identity']!=value['source_identity']:raise s.invalid()
                if stage in ('capture','complete'):
                    if type(value['size_bytes']) is not int or not 0<=value['size_bytes']<=value['capacity_bytes'] or len(value['sha256'])!=64 or not 1<=len(value['locations'])<=4 or value['object_key'] not in value['locations']:raise s.invalid()
                    for key in value['locations']:_path(root,key)
                    descriptor=value.get('descriptor')
                    descriptor_format=value.get('descriptor_format')
                    if descriptor_format not in (None,FIGURE_DESCRIPTOR_FORMAT) or descriptor_format and not descriptor:raise s.invalid()
                    if descriptor:
                        _path(root,descriptor['object_key'])
                        if descriptor['object_key'] in value['locations'] or type(descriptor['size_bytes']) is not int or not 0<=descriptor['size_bytes']<=DESCRIPTOR_LIMIT or value['size_bytes']+descriptor['size_bytes']>value['capacity_bytes'] or len(descriptor['sha256'])!=64:raise s.invalid()
                    if row['sha256'] is None:
                        if stage=='complete':raise s.invalid()
                        row.update(size_bytes=value['size_bytes'],sha256=value['sha256'],state='unknown',candidate_json={**row['candidate_json'],'locations':value['locations']})
                        if descriptor:row['candidate_json']['descriptor']=descriptor
                        if descriptor_format:row['candidate_json']['descriptor_format']=descriptor_format
                        db.execute("UPDATE storage_reservations SET size_bytes=%s,sha256=%s,state='unknown',candidate_json=%s WHERE id=%s",(row['size_bytes'],row['sha256'],Jsonb(row['candidate_json']),row['id']))
                    elif row['size_bytes']!=value['size_bytes'] or row['sha256']!=value['sha256'] or row['candidate_json']['locations']!=value['locations']:raise s.invalid()
                    if row['candidate_json'].get('descriptor')!=descriptor:raise s.invalid()
                    if row['candidate_json'].get('descriptor_format')!=descriptor_format:raise s.invalid()
                    if stage=='complete':
                        if not descriptor:raise s.invalid()
                        db.execute('UPDATE storage_reservations SET candidate_json=candidate_json || %s WHERE id=%s',(Jsonb({'descriptor_complete':True}),row['id']))
                    if row['state'] in s.ACTIVE:
                        found=_present(root,row)
                        if len(found)>1:
                            db.execute("UPDATE storage_reservations SET state='unknown',candidate_json=candidate_json || %s WHERE id=%s",(Jsonb({'copies':len(found)}),row['id']))
            except (OSError,ValueError,KeyError,TypeError,StorageError):unknown+=1
    return unknown


def publish_candidate(db,root,identifier,*,explicit_recovery=False):
    if s.reconcile_intents(db,root):raise s.invalid()
    row=_row(db,identifier)
    if row['state']=='unknown' and not explicit_recovery:raise s.invalid()
    if row['sha256'] is None:raise s.invalid()
    paths=_present(root,row)
    if len(paths)!=1:raise s.invalid()
    target=_path(root,row['object_key'])
    for key in row['candidate_json']['locations']:s.require_publication_allowed(db,row['project_id'],key,task_id=row.get('task_id'))
    descriptor=row['candidate_json'].get('descriptor')
    if descriptor:
        read_descriptor(root,row)
        s.require_publication_allowed(db,row['project_id'],descriptor['object_key'],task_id=row.get('task_id'))
    if row['state']!='settled':s._scope_check(db,s._project(db,row['project_id']),0,allow_attributed_unknown=explicit_recovery)
    if paths[0]!=target:
        target.parent.mkdir(parents=True,exist_ok=True)
        # No writer can create the target between this check and rename under
        # the application writer fence. Existing targets are never overwritten.
        if target.exists():raise s.invalid()
        os.replace(paths[0],target)
    identifier=s._settle_verified(db,root,row)
    if descriptor:
        s._require_object_identity(db,descriptor['object_key'],descriptor['size_bytes'],descriptor['sha256'])
        s._register(db,{**row,'object_key':descriptor['object_key'],'kind':'candidate_descriptor'},descriptor['size_bytes'],descriptor['sha256'])
    return identifier


def task_hold(db,task):
    row=db.execute('SELECT * FROM storage_reservations WHERE namespace=%s AND project_id=%s AND operation_key=%s',
        (s.NAMESPACE,task['project_id'],'figure-task:'+task['id'])).fetchone()
    if row and (row['task_id']!=task['id'] or row['owner_id']!=task['user_id'] or row['candidate_json']['source_identity']!=task['input_digest']):raise s.invalid()
    return dict(row) if row else None


def authorize_task_recovery(db,root,task):
    if s.reconcile_intents(db,root):raise s.invalid()
    row=task_hold(db,task)
    if not row:return
    s._scope_check(db,s._project(db,task['project_id']),0,allow_attributed_unknown=True)
    s.require_publication_allowed(db,task['project_id'],row['object_key'],task_id=task['id'])
    if row['sha256'] and len(_present(root,row))!=1:raise s.invalid()
    mode=task_recovery_mode(db,root,task)
    if mode=='blocked':raise s.invalid()
    if mode=='original_response':_disk_guard(db,root,0)
    if row['sha256'] and mode=='local_candidate':
        saved=read_descriptor(root,row)
        if any(saved.get(k)!=task[k] for k in ('id','project_id','user_id','input_digest','task_type')):raise s.invalid()
        if not isinstance(saved.get('candidate'),dict):raise s.invalid()
        if task.get('figure_candidate') is not None and task['figure_candidate']!=saved['candidate']:raise s.invalid()
        db.execute('UPDATE tasks SET figure_candidate=%s WHERE id=%s',(Jsonb(saved['candidate']),task['id']))
    # Explicit user action only; recovery scans must never mint this permission.
    authorization={'recovery_revision':task['revision']+1,'recovery_attempt':task['current_attempt']+1}
    if not row['sha256']:
        _disk_guard(db,root,0)
        db.execute("UPDATE storage_reservations SET state='reserved' WHERE id=%s",(row['id'],))
    db.execute('UPDATE storage_reservations SET candidate_json=candidate_json || %s WHERE id=%s',(Jsonb(authorization),row['id']))


def task_recovery_authorized(row,task,lease):
    metadata=row['candidate_json']
    return metadata.get('recovery_attempt')==lease.attempt_no and type(metadata.get('recovery_revision')) is int and metadata['recovery_revision']<task['revision']
