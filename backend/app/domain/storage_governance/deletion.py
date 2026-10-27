"""Explicit new synthetic fixtures only; retain all other bytes and histories."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from psycopg.types.json import Jsonb
from app.core.exceptions import StorageError
from app.domain.admin_operations import require_identity
from app.domain.file_lifecycle.contracts import ACTIVE,digest
from app.domain.file_lifecycle.references import read_references
from . import service as storage

POLICY='stage10_batch03_registered_synthetic_v1'
ACCEPTANCE_SCHEMA='pa_test_c417a97aa52946e1baf4483f150f5145'
_NEW_TEST_SCHEMAS=set()


def current_utc():
    return datetime.now(timezone.utc)


def register_new_test_schema(schema):
    """Called only by the existing per-test schema creator, never an HTTP route."""
    _NEW_TEST_SCHEMAS.add(schema)


def error(code):
    messages={'storage_deletion_not_authorized':'该环境或资料未在创建时登记为可处置合成夹具，继续保留。',
              'storage_deletion_plan_changed':'对象或引用范围已变化，请重新预览并确认。',
              'storage_deletion_blocked':'仍有在途、未知或待核对事项，不能执行处置。',
              'storage_deletion_identity_changed':'登记对象的存储身份无法核实，已保留。',
              'storage_deletion_idempotency_conflict':'同一删除标识与原确认不一致。'}
    return StorageError(code,messages.get(code,'删除请求无效。'),409)


def _allowed(config,root):
    if config.environment!='test' or config.url.database!='paperassist_system_test':return False
    if config.schema in _NEW_TEST_SCHEMAS:return True
    return config.schema==ACCEPTANCE_SCHEMA and Path(root).name=='assets-'+ACCEPTANCE_SCHEMA.removeprefix('pa_test_')


def create_disposable_fixture(store,*,evidence_directory,originals=(),temporary=()):
    """Create a NEW project and exact bytes atomically registered with its receipt.

    Inputs are copied outside assets BEFORE writing any primary byte. No existing
    project, file, path, object ID or enrollment flag can be supplied.
    """
    root=Path(store.directory).absolute()
    if not _allowed(store.db_config,root):raise error('storage_deletion_not_authorized')
    evidence=Path(evidence_directory).absolute()
    if evidence.resolve().is_relative_to(root.resolve()):raise error('storage_deletion_not_authorized')
    identifier=str(uuid4());pid=str(uuid4());now=datetime.now(timezone.utc).isoformat()
    evidence=evidence/identifier;evidence.mkdir(parents=True,exist_ok=False)
    inputs=[dict(kind='original',name=name,content=content) for name,content in originals]
    inputs += [dict(kind='temporary',name=None,content=content) for content in temporary]
    if not inputs or any(type(i['content']) is not bytes or not i['content'] for i in inputs):raise ValueError('Nonempty synthetic bytes required')
    for index,item in enumerate(inputs):
        with (evidence/f'{index}.source').open('xb') as stream:stream.write(item['content'])
    receipt=dict(batch_id='stage10-batch03',fixture_id=identifier,project_id=pid,owner_id=store.owner_id,
        schema=store.db_config.schema,database=store.db_config.url.database,root=str(root.resolve()),created_at=now,
        sources=[dict(index=i,kind=x['kind'],size_bytes=len(x['content']),sha256=hashlib.sha256(x['content']).hexdigest()) for i,x in enumerate(inputs)])
    receipt_path=evidence/'creation.json'
    receipt_path.write_text(json.dumps(receipt,sort_keys=True),encoding='utf-8')
    members=[];files=[];temps=[]
    with store.connection(write=True) as db:
        require_identity(db,store.owner_id,admin=False)
        db.execute('''INSERT INTO projects(id,name,research_topic,project_type,created_at,updated_at,owner_id)
            VALUES(%s,'Disposable synthetic fixture','stage10-batch03 synthetic inputs','sci',%s,%s,%s)''',(pid,now,now,store.owner_id))
        storage.initialize_policy(db,'project',pid)
        for index,item in enumerate(inputs):
            content=item['content'];file_id=None
            if item['kind']=='original':
                extension=item['name'].rsplit('.',1)[-1]
                obj=store.objects.put_original(pid,str(uuid4()),extension,content,db=db)
                file_id=obj.id
                db.execute('''INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status,
                    uploader_id,storage_backend,object_key) VALUES(%s,%s,%s,%s,%s,%s,%s,'failed',%s,'local',%s)''',
                    (obj.id,pid,item['name'],extension,obj.size_bytes,obj.sha256,now,store.owner_id,obj.object_key))
                key=obj.object_key
            else:
                key=f'disposable-temporary/{identifier}/{uuid4()}.bin'
                target=root/key
                with storage.publication(db,root,pid,'fixture:'+str(uuid4()),target,content,kind='registered_temporary'):
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with target.open('xb') as stream:stream.write(content)
            row=db.execute('SELECT * FROM storage_objects WHERE namespace=%s AND object_key=%s',(storage.NAMESPACE,key)).fetchone()
            member=dict(object_id=row['id'],object_key=key,kind=item['kind'],file_id=file_id,size_bytes=row['size_bytes'],sha256=row['sha256'],
                        terminal_at=now if item['kind']=='temporary' else None)
            members.append(member)
            (files if file_id else temps).append(dict(member,id=file_id or row['id']))
        manifest={**receipt,'members':members,'receipt_path':str(receipt_path),'receipt_sha256':hashlib.sha256(receipt_path.read_bytes()).hexdigest()}
        # Immutable exact registry is committed with NEW project/files only.
        db.execute('INSERT INTO storage_disposable_fixtures(id,project_id,owner_id,manifest,manifest_sha256) VALUES(%s,%s,%s,%s,%s)',
                   (identifier,pid,store.owner_id,Jsonb(manifest),digest(manifest)))
        (evidence/'registry.json').write_text(json.dumps(manifest,sort_keys=True),encoding='utf-8')
    return dict(fixture_id=identifier,project_id=pid,files=files,temporary=temps,receipt_path=str(receipt_path))


def file_object_keys(db,refs):
    """Physical members of the existing validated file lineage, never a path scan."""
    from .historical import mapping
    keys=set();groups=refs['public_groups']
    for kind in ('dataset_versions','prepared_dataset_versions','ocr_review_versions'):
        keys.update(r['object_key'] for r in groups[kind])
    for kind in ('prepared_dataset_derivations','prepared_dataset_derivations_v3'):
        keys.update(r['manifest_object_key'] for r in groups.get(kind,[]))
    for row in groups['parse_versions']:
        if row['result_json'] is not None:
            result=mapping(row['result_json'])
            if 'object' in result:
                keys.add(result['object']['object_key'])
                keys.update(i['object_key'] for i in result['images'])
    for kind,suffix in (('figures','.png'),('reports','.docx'),('collection_reports','.docx'),('manuscript_figure_language_versions','.png')):
        keys.update(kind+'/'+r['id']+suffix for r in groups.get(kind,[]))
    task_ids=[t['id'] for t in refs['tasks']]
    for row in db.execute('SELECT object_key,candidate_json FROM storage_reservations WHERE task_id=ANY(%s)',(task_ids,)):
        keys.add(row['object_key']);candidate=row['candidate_json'] or {}
        keys.update(candidate.get('locations',[]))
        if candidate.get('descriptor'):keys.add(candidate['descriptor']['object_key'])
    # Old exports without reservations still have typed task/metadata identities.
    for table,column in (('manuscript_exports','metadata_json'),('pdf_exports','metadata_json'),('layout_exports','metadata_json'),('review_document_exports','artifact_json')):
        for row in db.execute(f'SELECT id,{column} FROM {table} WHERE task_id=ANY(%s) AND {column} IS NOT NULL',(task_ids,)):
            value=mapping(row[column])
            keys.add(table+'/'+(row['id']+'.docx' if table=='manuscript_exports' else value['object_name']))
    return keys


class DeletionService:
    def __init__(self,store):self.store=store

    def _owner(self,db,pid):
        require_identity(db,self.store.owner_id,admin=False)
        if not db.execute('SELECT 1 FROM projects WHERE id=%s AND owner_id=%s',(pid,self.store.owner_id)).fetchone():
            raise StorageError('project_not_found','项目不存在。',404)

    def _registry(self,db,pid):
        row=db.execute('SELECT * FROM storage_disposable_fixtures WHERE project_id=%s',(pid,)).fetchone()
        if not row:return None
        value=row['manifest'];root=Path(self.store.directory)
        if (not _allowed(db.config,root) or value['schema']!=db.config.schema
            or value['database']!=db.config.url.database or value['root']!=str(root.resolve())
            or row['owner_id']!=self.store.owner_id or digest(value)!=row['manifest_sha256']):
            raise error('storage_deletion_not_authorized')
        receipt=Path(value['receipt_path'])
        if receipt.resolve().is_relative_to(root.resolve()):raise error('storage_deletion_not_authorized')
        try:actual=hashlib.sha256(receipt.read_bytes()).hexdigest()
        except OSError:raise error('storage_deletion_not_authorized') from None
        if actual!=value['receipt_sha256']:raise error('storage_deletion_not_authorized')
        return value

    def _facts(self,db,pid,scope_kind,file_id):
        registry=self._registry(db,pid);members={m['object_id']:m for m in registry['members']} if registry else {}
        rows=list(db.execute('''SELECT o.*,r.kind FROM storage_objects o JOIN storage_references r ON r.object_id=o.id
            WHERE r.project_id=%s ORDER BY o.id''',(pid,)))
        files=list(db.execute('SELECT * FROM files WHERE project_id=%s ORDER BY id',(pid,)))
        if scope_kind=='file' and not any(f['id']==file_id for f in files):raise StorageError('file_not_found','文件不存在。',404)
        blockers=set();reference_facts={};protected_files=set();file_refs={}
        for file in files:
            refs=read_references(db,file,self.store.owner_id)
            reference_facts[file['id']]=refs['facts'];file_refs[file['id']]=refs
            if scope_kind!='file' or file['id']==file_id:
                blockers.update(r for r in refs['reasons'] if not r.endswith('_retained'))
            # Published/immutable dependent graphs retain their original reader
            # roots. Never delete source bytes needed by a retained export.
            if any(refs['groups'].values()) or refs['tasks'] or refs['legacy']:protected_files.add(file['id'])
        tasks=[dict(r) for r in db.execute('SELECT id,status,revision,input_digest,figure_candidate FROM tasks WHERE project_id=%s ORDER BY id',(pid,))]
        if scope_kind=='file':
            ids={t['id'] for t in file_refs[file_id]['tasks']};tasks=[t for t in tasks if t['id'] in ids]
        task_ids=[t['id'] for t in tasks]
        calls=[dict(r) for r in db.execute('SELECT id,status,usage_status,reconciliation_revision FROM model_calls WHERE project_id=%s ORDER BY id',(pid,))]
        budgets=[dict(r) for r in db.execute('''SELECT b.* FROM budget_reservations b JOIN model_calls c ON c.id=b.call_id
            WHERE c.project_id=%s ORDER BY b.call_id,b.budget_id''',(pid,))]
        reservations=[dict(r) for r in db.execute('SELECT * FROM storage_reservations WHERE project_id=%s ORDER BY id',(pid,))]
        attempts=[dict(r) for r in db.execute('SELECT * FROM task_attempts WHERE task_id=ANY(%s) ORDER BY id',(task_ids,))]
        outbox=[dict(r) for r in db.execute('SELECT * FROM task_outbox WHERE task_id=ANY(%s) ORDER BY id',(task_ids,))]
        if any(t['status'] in ACTIVE for t in tasks) or any(a['status']=='running' for a in attempts):blockers.add('active_tasks')
        if any(c['status'] in ('reserved','submitting','submitted','submission_unknown') or c['usage_status'] in ('unknown','pending') for c in calls):blockers.add('external_work_unresolved')
        if any(b['status']=='held' for b in budgets):blockers.add('budget_reservations_held')
        if any(r['state'] in storage.ACTIVE for r in reservations):blockers.add('storage_work_unresolved')
        if any(t['figure_candidate'] and t['status']!='succeeded' for t in tasks):blockers.add('recoverable_candidates')
        scoped_keys=set()
        if scope_kind=='file':
            try:scoped_keys=file_object_keys(db,file_refs[file_id])
            except (KeyError,TypeError,ValueError,StorageError):blockers.add('integrity_unknown')
        items=[]
        for row in rows:
            member=members.get(row['id']);fid=member['file_id'] if member else next((f['id'] for f in files if (f['object_key'] or f"files/{f['id']}.xlsx")==row['object_key']),None)
            if scope_kind=='file' and fid!=file_id:
                if row['object_key'] not in scoped_keys:continue
                fid=file_id
            if scope_kind=='temporary' and not(member and member['kind']=='temporary'):continue
            refs=[dict(r) for r in db.execute('SELECT project_id,owner_id,kind FROM storage_references WHERE object_id=%s ORDER BY project_id',(row['id'],))]
            reasons=[]
            if not member:reasons.append('not_registered_at_creation')
            if member and member['kind']=='temporary' and (current_utc()-datetime.fromisoformat(member['terminal_at'])).total_seconds()<=86400:
                reasons.append('temporary_retention_period')
                if scope_kind=='temporary':blockers.add('temporary_retention_period')
            if any(r['project_id']!=pid for r in refs):reasons.append('shared_reference')
            if fid in protected_files:reasons.append('retained_dependency_graph')
            if row['state']=='deleted':reasons.append('already_disposed')
            if not reasons:
                if any(row[k]!=member[k] for k in ('object_key','size_bytes','sha256')):blockers.add('registered_identity_changed')
                try:
                    path=Path(self.store.directory)/row['object_key'];storage._key(self.store.directory,path)
                    if path.stat().st_nlink!=1 or storage._digest(path)!=(row['size_bytes'],row['sha256']):raise OSError()
                except (OSError,StorageError):blockers.add('registered_identity_changed')
            items.append(dict(object_id=row['id'],object_key=row['object_key'],kind=row['kind'],file_id=fid,
                sha256=row['sha256'],size_bytes=row['size_bytes'],references=refs,
                action='retain' if reasons else 'delete',reason_codes=reasons))
        facts=dict(policy_version=POLICY,project_id=pid,scope_kind=scope_kind,file_id=file_id,
                   registry_digest=digest(registry) if registry else None,items=items,blockers=sorted(blockers),
                   reference_digest=digest(reference_facts),work_digest=digest([tasks,calls,budgets,reservations,attempts,outbox]),
                   retention_policy='synthetic_registered' if registry else 'retain_all',
                   database_status='retained_immutable_history',backup_status='retained_indefinitely',provider_status='not_executed',
                   control_evidence_status='retained',all_deleted=False)
        return facts

    def preview(self,pid,*,scope_kind,reason,file_id=None):
        if scope_kind not in ('project','file','temporary') or (scope_kind=='file')!=(file_id is not None) or not isinstance(reason,str) or not 1<=len(reason.strip())<=500:
            raise StorageError('storage_deletion_input_invalid','删除范围或理由无效。',422)
        with self.store.connection(write=True) as db:
            self._owner(db,pid)
            unknown=storage.reconcile_intents(db,self.store.directory)
            facts=self._facts(db,pid,scope_kind,file_id)
            if unknown:facts['blockers']=sorted(set(facts['blockers'])|{'unattributed_control_evidence'})
            identifier=str(uuid4())
            db.execute('''INSERT INTO storage_deletion_operations(id,project_id,owner_id,file_id,scope_kind,reason,manifest,manifest_sha256,state)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'preview')''',(identifier,pid,self.store.owner_id,file_id,scope_kind,reason.strip(),Jsonb(facts),digest(facts)))
            return self._view(db,self._operation(db,pid,identifier))

    def _operation(self,db,pid,identifier):
        self._owner(db,pid)
        row=db.execute('SELECT * FROM storage_deletion_operations WHERE id=%s AND project_id=%s AND owner_id=%s',(identifier,pid,self.store.owner_id)).fetchone()
        if not row:raise StorageError('not_found','删除计划不存在。',404)
        return row

    def _view(self,db,row):
        states={i['object_id']:dict(i) for i in db.execute('SELECT * FROM storage_deletion_items WHERE operation_id=%s',(row['id'],))}
        value={k:v for k,v in row['manifest'].items() if k not in ('registry_digest','reference_digest','work_digest','items')}
        items=[]
        for item in row['manifest']['items']:
            state=states.get(item['object_id'],{})
            items.append({**{k:v for k,v in item.items() if k!='object_key'},'state':state.get('state','planned'),
                          'attempt_no':state.get('attempt_no',0),'error_code':state.get('error_code')})
        return dict(value,id=row['id'],state=row['state'],reason=row['reason'],requested_by=row['owner_id'],
                    manifest_sha256=row['manifest_sha256'],items=items,
                    physical_deletion_available=value['retention_policy']=='synthetic_registered' and not value['blockers'] and any(i['action']=='delete' for i in items),
                    deleted_object_count=sum(i['state']=='deleted' for i in items),
                    deleted_bytes=sum(i['size_bytes'] for i in items if i['state']=='deleted'))

    def status(self,pid,identifier):
        with self.store.connection() as db:return self._view(db,self._operation(db,pid,identifier))

    def _event(self,db,operation,state,reason,object_id=None,attempt=0):
        db.execute('INSERT INTO storage_deletion_events(id,operation_id,object_id,state,reason_code,attempt_no) VALUES(%s,%s,%s,%s,%s,%s)',
                   (str(uuid4()),operation,object_id,state,reason,attempt))

    def execute(self,pid,identifier,*,confirmed_manifest_sha256,confirmation,key):
        return self._execute(pid,identifier,confirmed_manifest_sha256,confirmation,key,retry=False)

    def retry(self,pid,identifier,*,confirmed_manifest_sha256,confirmation,key):
        return self._execute(pid,identifier,confirmed_manifest_sha256,confirmation,key,retry=True)

    def _execute(self,pid,identifier,confirmed,confirmation,key,*,retry):
        if confirmation!='delete_registered_synthetic_objects' or not isinstance(key,str) or not re.fullmatch(r'[!-~]{1,128}',key):
            raise StorageError('storage_deletion_input_invalid','须明确确认处置范围并提供操作标识。',422)
        with self.store.connection(write=True) as db:
            row=self._operation(db,pid,identifier)
            if row['manifest_sha256']!=confirmed or row['idempotency_key'] not in (None,key):raise error('storage_deletion_idempotency_conflict')
            if not self._registry(db,pid):raise error('storage_deletion_not_authorized')
            other=db.execute('SELECT id FROM storage_deletion_operations WHERE project_id=%s AND owner_id=%s AND idempotency_key=%s',(pid,self.store.owner_id,key)).fetchone()
            if other and other['id']!=identifier:raise error('storage_deletion_idempotency_conflict')
            if row['state']!='preview':
                if not retry:return self._view(db,row)
                if row['state']=='partial_retained':return self._view(db,row)
            else:
                if retry:raise error('storage_deletion_idempotency_conflict')
                unknown=storage.reconcile_intents(db,self.store.directory)
                current=self._facts(db,pid,row['scope_kind'],row['file_id'])
                if unknown or current['blockers']:raise error('storage_deletion_blocked')
                if digest(current)!=confirmed:raise error('storage_deletion_plan_changed')
                if db.execute("SELECT 1 FROM storage_deletion_operations WHERE project_id=%s AND state IN ('running','partial_failed')",(pid,)).fetchone():raise error('storage_deletion_blocked')
                for item in current['items']:
                    state='pending' if item['action']=='delete' else 'retained'
                    db.execute('INSERT INTO storage_deletion_items(operation_id,object_id,state) VALUES(%s,%s,%s)',(identifier,item['object_id'],state))
            db.execute("UPDATE storage_deletion_operations SET state='running',idempotency_key=%s WHERE id=%s",(key,identifier))
            self._event(db,identifier,'running','explicit_retry' if retry else 'explicit_confirmation')
        # Each intent is committed before bounded single-file IO. The persisted
        # operation holds the writer barrier across requests/crashes.
        for item in row['manifest']['items']:
            if item['action']=='retain':continue
            with self.store.connection(write=True) as db:
                state=db.execute('SELECT * FROM storage_deletion_items WHERE operation_id=%s AND object_id=%s',(identifier,item['object_id'])).fetchone()
                if state['state']=='deleted':continue
                continuing=state['state']=='processing'
                attempt=state['attempt_no']+1
                db.execute("UPDATE storage_deletion_items SET state='processing',attempt_no=%s,error_code=NULL WHERE operation_id=%s AND object_id=%s",(attempt,identifier,item['object_id']))
                self._event(db,identifier,'processing','durable_delete_intent',item['object_id'],attempt)
            removal_started=False
            path=Path(self.store.directory)/item['object_key']
            try:
                with self.store.connection(write=True) as db:
                    self._owner(db,pid);self._registry(db,pid)
                    if db.execute('SELECT state FROM storage_deletion_items WHERE operation_id=%s AND object_id=%s',(identifier,item['object_id'])).fetchone()['state']=='deleted':continue
                    # Full safety recheck per retry, without comparing changing
                    # deletion item state to the immutable original plan.
                    if storage.reconcile_intents(db,self.store.directory):raise error('storage_deletion_blocked')
                    fresh=self._facts(db,pid,row['scope_kind'],row['file_id'])
                    if set(fresh['blockers'])-{'registered_identity_changed'}:raise error('storage_deletion_blocked')
                    selected=next((x for x in fresh['items'] if x['object_id']==item['object_id']),None)
                    if not selected or selected['action']!='delete':raise error('storage_deletion_plan_changed')
                    storage._key(self.store.directory,path)
                    if path.exists():
                        if path.stat().st_nlink!=1 or storage._digest(path)!=(item['size_bytes'],item['sha256']):raise error('storage_deletion_identity_changed')
                        removal_started=True
                        path.unlink()
                    elif not continuing:raise error('storage_deletion_identity_changed')
                    if path.exists():raise OSError('Primary removal not observed')
                    db.execute("UPDATE storage_objects SET state='deleted' WHERE id=%s",(item['object_id'],))
                    db.execute("UPDATE storage_deletion_items SET state='deleted',disposed_at=clock_timestamp() WHERE operation_id=%s AND object_id=%s",(identifier,item['object_id']))
                    self._event(db,identifier,'deleted','reconciled_absent' if continuing else 'primary_absent',item['object_id'],attempt)
            except (OSError,StorageError) as exc:
                with self.store.connection(write=True) as db:
                    code=exc.code if isinstance(exc,StorageError) else 'storage_deletion_io_failed'
                    # Unknown commit/IO acknowledgement must keep its durable
                    # intent. A retry can prove absence without a second unlink.
                    state='processing' if removal_started and not path.exists() else 'failed'
                    if db.execute('SELECT state FROM storage_deletion_items WHERE operation_id=%s AND object_id=%s',(identifier,item['object_id'])).fetchone()['state']=='deleted':continue
                    db.execute('UPDATE storage_deletion_items SET state=%s,error_code=%s WHERE operation_id=%s AND object_id=%s',(state,code,identifier,item['object_id']))
                    self._event(db,identifier,state,code,item['object_id'],attempt)
        with self.store.connection(write=True) as db:
            failed=db.execute("SELECT 1 FROM storage_deletion_items WHERE operation_id=%s AND state IN ('failed','pending','processing')",(identifier,)).fetchone()
            state='partial_failed' if failed else 'partial_retained'
            db.execute('UPDATE storage_deletion_operations SET state=%s WHERE id=%s',(state,identifier))
            self._event(db,identifier,state,'immutable_history_and_backups_retained')
            return self._view(db,self._operation(db,pid,identifier))
