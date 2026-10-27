"""Persistent scan evidence for typed legacy assets and controlled candidates."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat

from psycopg.types.json import Jsonb
from app.core.exceptions import StorageError
from . import historical, service as s


def scan(db,root):
    root=Path(root).absolute();errors=set();failures=set();typed_errors={};coverage={}
    # No walk or journal read through an unsafe root, including a root symlink.
    try:
        s._key(root,root/'.inventory-root-check')
        if not root.is_dir():raise s.invalid()
        safe_root=True
    except (OSError,StorageError):
        safe_root=False;errors.add(('root',));failures.add(('root',))
    control=root/'.storage-intents'
    if safe_root and (control.is_symlink() or (hasattr(control,'is_junction') and control.is_junction())):
        # This fixed preflight happens before reconciliation can mutate the
        # ledger. Commit only the refusal receipt, never partial reconciliation.
        previous=db.execute('SELECT summary FROM storage_inventory_scans WHERE id=1').fetchone()
        prior=previous['summary'] if previous else {}
        successful=prior if prior.get('status')=='complete' else prior.get('last_successful_scan')
        summary=dict(scanned_at=datetime.now(timezone.utc).isoformat(),status='unknown',coverage='not_started',
            error_code='storage_control_directory_unsafe',scan_failure_count=1,unknown_count=1,
            physical_bytes=None,physical_object_count=None,unknown_bytes=None,typed_coverage={},
            last_successful_scan=successful,last_successful_scanned_at=successful['scanned_at'] if successful else None,
            database_bytes='not_in_asset_quota',automatic_deletion=False)
        db.execute('INSERT INTO storage_inventory_scans(id,summary) VALUES(1,%s) ON CONFLICT(id) DO UPDATE SET summary=excluded.summary',(Jsonb(summary),))
        return summary
    intent_unknown=s.reconcile_intents(db,root) if safe_root else 0
    def typed_failure(kind):typed_errors[kind]=typed_errors.get(kind,0)+1
    pending={};controllers={};control_names=set()
    for row in db.execute('SELECT * FROM storage_reservations WHERE namespace=%s',(s.NAMESPACE,)):
        names=[row['id']+'.json'] if row['capacity_bytes'] is None else [row['id']+'.'+stage+'.json' for stage in ('allocation','capture','complete')]
        control_names.update(names)
        if row['state'] not in s.ACTIVE:continue
        metadata=row['candidate_json'] or {}
        keys=metadata.get('locations',[row['object_key']]) if row['capacity_bytes'] is not None else [row['object_key']]
        if row['capacity_bytes'] is not None:
            for key in keys:controllers[key]=row
            controllers[row['object_key']]=row
            if metadata.get('descriptor'):controllers[metadata['descriptor']['object_key']]=row
        if row['sha256']:
            present=0
            for key in keys:
                pending[key]=(row['size_bytes'],row['sha256'])
                if safe_root:
                    try:
                        s._key(root,root/key);actual=s._digest(root/key)
                        if actual!=pending[key]:errors.add(('object',key))
                        else:present+=1
                    except FileNotFoundError:pass  # Other allowed location may own the one primary.
                    except (OSError,StorageError):errors.add(('object',key));failures.add(('object',key))
            if not present:errors.add(('pending',row['id']))
            descriptor=metadata.get('descriptor')
            if descriptor:
                key=descriptor['object_key'];pending[key]=(descriptor['size_bytes'],descriptor['sha256'])
                if safe_root:
                    try:
                        s._key(root,root/key)
                        if s._digest(root/key)!=pending[key]:errors.add(('object',key))
                    except FileNotFoundError:errors.add(('object',key))
                    except (OSError,StorageError):errors.add(('object',key));failures.add(('object',key))

    for row in historical.references(db,root,typed_failure,coverage):
        key=row['object_key']
        try:
            from .guards import disposed_identity
            if disposed_identity(db,key,row['size_bytes'],row['sha256']):continue
            controller=controllers.get(key)
            if controller:
                # Preserve all active v2 ownership even when a trusted old SQL
                # row already names the final key. Inventory cannot publish it.
                if controller['project_id']!=row['project_id'] or controller['owner_id']!=row['owner_id']:
                    raise s.invalid()
                expected=pending.get(key)
                if expected and expected!=(row['size_bytes'],row['sha256']):raise s.invalid()
                continue
            s._register(db,row,row['size_bytes'],row['sha256'],state='unknown')
        except (StorageError,ValueError,TypeError):typed_failure(row['kind'])

    registered=list(db.execute("SELECT * FROM storage_objects WHERE namespace=%s AND state<>'deleted'",(s.NAMESPACE,)))
    known={row['object_key'] for row in registered}
    for row in registered:
        key=row['object_key']
        try:
            if not safe_root:raise s.invalid()
            s._key(root,root/key);size,digest=s._digest(root/key)
            state='present' if (size,digest)==(row['size_bytes'],row['sha256']) else 'changed'
        except FileNotFoundError:state='missing'
        except (OSError,StorageError):state='unknown'
        if state!='present':errors.add(('object',key))
        if state=='unknown':failures.add(('object',key))
        db.execute('UPDATE storage_objects SET state=%s,scanned_at=clock_timestamp() WHERE id=%s',(state,row['id']))

    total=0;count=0;unknown_bytes=0;pending_bytes=0;pending_count=0;control_bytes=0
    def failed_walk(exc):
        token=('walk',getattr(exc,'filename',None));errors.add(token);failures.add(token)
    for directory,dirs,files in os.walk(root,followlinks=False,onerror=failed_walk) if safe_root else []:
        kept=[]
        for name in dirs:
            path=Path(directory)/name
            try:s._key(root,path);kept.append(name)
            except (OSError,StorageError):errors.add(('entry',str(path)));failures.add(('entry',str(path)))
        dirs[:]=kept
        for name in files:
            path=Path(directory)/name
            try:
                key=s._key(root,path);info=path.stat()
                if not stat.S_ISREG(info.st_mode):raise s.invalid()
                # Only bounded recognized evidence is excluded from asset bytes;
                # arbitrary files in the control directory remain unknown assets.
                if path.parent==root/'.storage-intents' and name in control_names and info.st_size<=8192:
                    try:
                        with path.open('rb') as stream:value=json.loads(stream.read(8193))
                        if value['namespace']==s.NAMESPACE and value['id']==name.split('.')[0]:
                            control_bytes+=info.st_size;continue
                    except (ValueError,KeyError,TypeError):pass
                size=info.st_size;total+=size;count+=1
                if key in pending:
                    pending_bytes+=size;pending_count+=1
                if key not in known and key not in pending:
                    errors.add(('object',key));unknown_bytes+=size
            except (OSError,StorageError):errors.add(('entry',str(path)));failures.add(('entry',str(path)))
    metadata_failures=sum(typed_errors.values())
    summary=dict(scanned_at=datetime.now(timezone.utc).isoformat(),physical_bytes=total,physical_object_count=count,
        unknown_count=len(errors)+intent_unknown+metadata_failures,unknown_bytes=unknown_bytes,scan_failure_count=len(failures),
        typed_metadata_failure_count=metadata_failures,typed_metadata_errors=typed_errors,typed_coverage=coverage,
        pending_physical_bytes=pending_bytes,pending_physical_object_count=pending_count,control_journal_bytes=control_bytes,
        status='unknown' if errors or intent_unknown or metadata_failures else 'complete',coverage='asset_files',
        database_bytes='not_in_asset_quota',renderer_temporary_bytes='separate_tmpfs',installed_model_bytes='outside_asset_root',
        attribution='typed_sql_and_verified_candidate_ledger',automatic_deletion=False)
    db.execute('INSERT INTO storage_inventory_scans(id,summary) VALUES(1,%s) ON CONFLICT(id) DO UPDATE SET summary=excluded.summary',(Jsonb(summary),))
    return summary
