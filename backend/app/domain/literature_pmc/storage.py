"""PMC's original receipt and bounded response bodies, without a second ledger."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID,uuid5

from app.domain.storage_governance import service as s,candidates as c,local_candidates as local

LIMIT=8*1024*1024
NAMESPACE=UUID('105f5041-9d12-4b40-96e9-988e7105fbe2')


def operation(project,user,key):
    return 'pmc-sync:'+sha256(local.encode([project,user,key])).hexdigest()


def admit(db,root,project,user,key,body_digest):
    op=operation(project,user,key)
    rows=[]
    for suffix in ('receipt','0','1'):
        stable=op+':'+suffix
        path=Path(root)/'literature'/str(uuid5(NAMESPACE,stable))/(body_digest+('.json' if suffix=='receipt' else '.xml'))
        row=local.lookup(db,root,project,stable,kind='literature_pmc')
        if row and row['candidate_json']['source_identity']!=body_digest:
            from app.core.exceptions import StorageError
            raise StorageError('task_idempotency_conflict','请求标识已用于不同输入。',409)
        if row and row['object_key']!=s._key(root,path):raise s.invalid()
        rows.append(row or dict(pending_path=path,pending_operation=stable))
    complete=rows[0].get('sha256') is not None
    if complete:
        return rows,read(db,root,rows,body_digest)
    # A captured response without its receipt cannot be silently refetched.
    if any(row.get('sha256') for row in rows):raise s.invalid()
    old=[row for row in rows if 'id' in row]
    if old:
        s._scope_check(db,s._project(db,project),0,allow_attributed_unknown=True)
        c._disk_guard(db,root,0)
        for row in old:
            if (Path(root)/row['object_key']).exists():raise s.invalid()
            db.execute("UPDATE storage_reservations SET state='reserved' WHERE id=%s",(row['id'],))
    admitted=[]
    for row in rows:
        if 'id' in row:
            admitted.append(row)
        else:
            admitted.append(s.admit_candidate(db,root,project,row['pending_operation'],row['pending_path'],LIMIT,
                task_id=None,source_identity=body_digest,kind='literature_pmc'))
    return admitted,None


def read(db,root,rows,source):
    control=rows[0]
    paths=c._present(root,control)
    if len(paths)!=1 or control['size_bytes']>LIMIT:raise s.invalid()
    try:fields=json.loads(paths[0].read_bytes())
    except (ValueError,OSError):raise s.invalid() from None
    if (fields['project_id'],fields['user_id'],fields['request_digest'])!=(control['project_id'],control['owner_id'],source):raise s.invalid()
    if fields['id']!=str(uuid5(NAMESPACE,control['operation_key'])):raise s.invalid()
    for index,response in enumerate(fields['snapshot_json']['responses']):
        obj=response['object'];row=rows[index+1]
        if obj is None:continue
        if ('id' not in row or obj!={k:row[k] for k in ('object_key','sha256','size_bytes')}|{'operation':'pmc_oai'}
                or len(c._present(root,row))!=1):raise s.invalid()
    return fields


def capture(db,root,rows,fields,raws):
    result=fields['snapshot_json']
    for index,response in enumerate(result['responses']):
        raw=raws[index];row=rows[index+1]
        if raw is None:
            response['object']=None
        else:
            if type(raw) is not bytes or len(raw)>LIMIT:raise s.invalid()
            response['object']=dict(object_key=row['object_key'],sha256=sha256(raw).hexdigest(),size_bytes=len(raw),operation='pmc_oai')
    from app.domain.literature.service import digest
    fields['snapshot_sha256']=digest(result)
    for index,raw in enumerate(raws):
        if raw is None:continue
        row=rows[index+1];path=Path(root)/row['object_key']
        s.capture_candidate(db,root,row['id'],raw,[path],source_identity=fields['request_digest'])
        c._write_immutable(path,raw)
    # Already received bounded responses must survive an oversized or failed
    # receipt envelope. Without that envelope recovery remains explicitly blocked.
    control=local.encode(fields)
    row=rows[0];path=Path(root)/row['object_key']
    s.capture_candidate(db,root,row['id'],control,[path],source_identity=fields['request_digest'])
    c._write_immutable(path,control)
    return fields


def publish(db,root,rows,fields):
    captured=[]
    responses=fields['snapshot_json']['responses']
    for index,row in enumerate(rows):
        current=c._row(db,row['id'])
        if current['sha256'] is None:
            # The complete receipt proves this exact response slot was unused.
            # Release it before checking actual-byte publication quota.
            if (index==0 or (index<=len(responses) and responses[index-1]['object'] is not None)
                    or (Path(root)/current['object_key']).exists()):raise s.invalid()
            s.release(db,current['id'])
        else:
            captured.append(row['id'])
    for reservation_id in captured:
        s.publish_candidate(db,root,reservation_id,explicit_recovery=True)


def fields(rows,project,user,reference,view,pmcid,key,body,hashed,result):
    return dict(id=str(uuid5(NAMESPACE,rows[0]['operation_key'])),project_id=project,user_id=user,
        project_reference_id=reference['id'],reference_id=reference['reference_id'],pmcid=pmcid,pmid=view['pmid'],
        source_kind=result['source_kind'],status=result['status'],idempotency_key=key,request_digest=hashed,
        request_json=body,snapshot_json=result,created_at=datetime.now(timezone.utc).isoformat())
