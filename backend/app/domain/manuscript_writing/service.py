"""Frozen offline writing requests and explicit immutable candidate publication."""
from copy import deepcopy
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key,append_checkpoint
from app.domain.literature.service import digest
from app.domain.manuscripts.service import ManuscriptService,now
from .contracts import WritingRequest,WORKFLOW,SECTION_IDS


def require_snapshot(task):
    if task.get('workflow_version')=='manuscript_writing_v2':
        from .live_execution import require_live_snapshot
        return require_live_snapshot(task)
    try:
        snap=task['input_snapshot']
        if (task['task_type']!='manuscript_writing' or task['workflow_version']!=WORKFLOW
            or digest(snap)!=task['input_digest'] or snap['project_id']!=task['project_id']
            or type(snap['schema_version']) is not int or snap['schema_version']!=1
            or snap['workflow_version']!=WORKFLOW or snap['request_id']!=task['id']
            or snap['prompt_version']!='sci-writing-v1' or snap['policy_version']!='offline-only-v1'
            or set(snap)!={'schema_version','project_id','workflow_version','input','base_snapshot','base_version_id','manuscript_id','prompt_version','policy_version','request_id'}
            or snap['input']!=WritingRequest.model_validate(snap['input']).model_dump(mode='json')):
            raise ValueError('Frozen writing request mismatch')
        return snap
    except (KeyError,TypeError,ValueError) as exc:
        raise source_conflict() from exc


def input_version(task):
    snap=require_snapshot(task)
    return dict(kind='manuscript_writing',base_version_id=snap['base_version_id'],base_revision=snap['input']['base_revision'],output_language=snap['input'].get('output_language',snap['base_snapshot']['output_language']),workflow_version=task['workflow_version'])


def checkpoint(db,task):
    row=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
    if not row or row['state_json'].get('input_digest')!=task['input_digest']: raise source_conflict()
    return dict(row)


class WritingService:
    def __init__(self,assets):
        self.assets=assets;self.manuscripts=ManuscriptService(assets);self.store=self.manuscripts.store

    def row(self,db,project,identity,request_id):
        self.manuscripts.root(db,project,identity)
        row=db.execute('SELECT * FROM manuscript_writing_requests WHERE task_id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s',(request_id,identity,project,self.store.user_id)).fetchone()
        if not row: raise StorageError('task_not_found','写作请求不存在。',404)
        task=self.store.require_task(db,request_id);snap=require_snapshot(task)
        if row['input_snapshot']!=snap or row['input_digest']!=digest(snap) or row['request_json']!=snap['input'] or row['base_version_id']!=snap['base_version_id']: raise source_conflict()
        if row['candidate_json'] is not None:
            from .context import validate_candidate
            if row['candidate_sha256']!=digest(row['candidate_json']): raise source_conflict()
            model_call_id=row['candidate_json'].get('writing_provenance',{}).get('model_call_id')
            if snap['schema_version']==2 and not model_call_id: raise source_conflict()
            if model_call_id:
                call=db.execute('SELECT task_id,project_id,user_id,provider_state FROM model_calls WHERE id=%s',(model_call_id,)).fetchone()
                if not call or any(call[k]!=task[k] for k in ('project_id','user_id')) or call['task_id']!=task['id']: raise source_conflict()
                if snap['schema_version']==2:
                    admission=db.execute('SELECT * FROM manuscript_writing_call_admissions WHERE model_call_id=%s',(model_call_id,)).fetchone()
                    if (not admission or admission['status']!='submission_started'
                        or any(admission[k]!=snap['execution'][k] for k in ('bundle_id','authorization_id','logical_task_id'))
                        or (call['provider_state'] or {}).get('writing_provider_provenance')!=row['candidate_json']['writing_provenance']['provider_provenance']): raise source_conflict()
            try:
                if snap['schema_version']==2:
                    from .authorization import LiveWritingService
                    from .live_execution import validate_live_candidate
                    bundle=LiveWritingService(self.assets).bundle(db,project,snap['execution']['bundle_id'])
                    validate_live_candidate(row['candidate_json'],snap,bundle)
                else: validate_candidate(row['candidate_json'],snap)
            except (ValueError,TypeError,KeyError) as exc: raise source_conflict() from exc
        return row,task

    def assert_current(self,db,task):
        snap=require_snapshot(task);row,_=self.row(db,task['project_id'],snap['manuscript_id'],task['id'])
        version=self.manuscripts.version(db,task['project_id'],snap['manuscript_id'],snap['input']['base_revision'])
        root=self.manuscripts.root(db,task['project_id'],snap['manuscript_id'])
        if version['id']!=snap['base_version_id'] or version['snapshot_json']!=snap['base_snapshot'] or root['current_revision']!=snap['input']['base_revision'] or self.manuscripts.source_changes(task['project_id'],snap['base_snapshot']): raise source_conflict()
        return row

    def create(self,project,identity,request,key):
        if getattr(request,'schema_version',None)==2 or isinstance(request,dict) and request.get('schema_version')==2:
            from .authorization import LiveWritingService
            return LiveWritingService(self.assets).create(project,identity,request,key)
        require_key(key);request=WritingRequest.model_validate(request) if isinstance(request,dict) else request
        body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            root=self.manuscripts.root(db,project,identity)
            db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            root=self.manuscripts.root(db,project,identity)
            old=self.store.find_request(db,project,'manuscript_writing',key)
            if old:
                snap=require_snapshot(old)
                if snap['input']!=body or snap['manuscript_id']!=identity: raise StorageError('task_idempotency_conflict','请求标识已用于不同写作输入。',409)
                request_id=old['id'];status=200
            else:
                version=self.manuscripts.version(db,project,identity,request.base_revision)
                if root['current_revision']!=request.base_revision or self.store.require_task(db,version['task_id'])['status']!='succeeded': raise StorageError('manuscript_revision_conflict','请选择当前已发布基础版本。',409)
                valid_ids=[c['id'] for c in version['snapshot_json'].get('thesis_context',{}).get('chapters',[])] or list(SECTION_IDS)
                if request.mode=='rewrite_section' and request.target_section not in valid_ids: raise StorageError('task_input_invalid','重写目标不是当前冻结章节。',422)
                if request.mode=='rewrite_section' and not version['snapshot_json'].get('sections'): raise StorageError('manuscript_writing_base_incomplete','请先完成并发布完整七部分写作，再指定章节重写。',409)
                if self.manuscripts.source_changes(project,version['snapshot_json']): raise source_conflict()
                request_id=str(uuid4());timestamp=now()
                snap=dict(schema_version=1,project_id=project,workflow_version=WORKFLOW,input=body,base_snapshot=version['snapshot_json'],base_version_id=version['id'],manuscript_id=identity,prompt_version='sci-writing-v1',policy_version='offline-only-v1',request_id=request_id)
                task=dict(id=request_id,project_id=project,user_id=self.store.user_id,task_type='manuscript_writing',idempotency_key=key,input_digest=digest(snap),input_snapshot=snap,workflow_version=WORKFLOW,status='queued',phase='write',revision=1,current_attempt=0,reason_code=None,created_at=timestamp,updated_at=timestamp)
                self.store.insert_task(db,task)
                db.execute('INSERT INTO manuscript_writing_requests(task_id,project_id,user_id,manuscript_id,base_version_id,request_json,input_snapshot,input_digest,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(request_id,project,self.store.user_id,identity,version['id'],Jsonb(body),Jsonb(snap),digest(snap),timestamp,timestamp))
                append_checkpoint(db,task,'check','check',dict(schema_version=1,input_digest=task['input_digest']))
                self.store.append_event(db,task,'created');self.store.enqueue(db,task);status=202
        return self.get(project,identity,request_id),status

    def view(self,db,project,identity,request_id):
        from app.domain.literature_assistance.service import saved_calls
        row,task=self.row(db,project,identity,request_id)
        calls=saved_calls(db,task);live=task['input_snapshot']['schema_version']==2
        if live:
            from .policy import capabilities
            rows=db.execute('SELECT c.id,c.provider_state,a.bundle_id,a.authorization_id,a.logical_task_id FROM model_calls c JOIN manuscript_writing_call_admissions a ON a.model_call_id=c.id WHERE c.task_id=%s ORDER BY c.created_at,c.id',(task['id'],)).fetchall()
            if len(rows)!=len(calls): raise source_conflict()
            for call,saved in zip(calls,rows):
                provenance=(saved['provider_state'] or {}).get('writing_provider_provenance','not_submitted')
                call.update(id=saved['id'],provider_provenance=provenance,provenance=provenance,
                    bundle_id=saved['bundle_id'],authorization_id=saved['authorization_id'],logical_task_id=saved['logical_task_id'])
        return dict(id=request_id,project_id=project,manuscript_id=identity,base_revision=row['request_json']['base_revision'],task=self.store.public_task(task),input=row['request_json'],candidate=row['candidate_json'],published_revision=row['published_revision'],model_calls=calls,schema_version=task['input_snapshot']['schema_version'],real_calls_enabled=capabilities()['real_calls_enabled'] if live else False,preservation_check=dict(non_target_sections_preserved=True) if row['candidate_json'] else None)

    def get(self,project,identity,request_id):
        with self.store.connection() as db: return self.view(db,project,identity,request_id)

    def list(self,project,identity):
        with self.store.connection() as db:
            self.manuscripts.root(db,project,identity)
            rows=db.execute('SELECT task_id FROM manuscript_writing_requests WHERE manuscript_id=%s AND project_id=%s AND user_id=%s ORDER BY created_at DESC,task_id',(identity,project,self.store.user_id)).fetchall()
            return dict(items=[self.view(db,project,identity,r['task_id']) for r in rows])

    def publish(self,project,identity,request_id,expected_revision,key,review_request=None):
        if review_request is not None:
            from .live_publish import publish
            return publish(self,project,identity,request_id,review_request,key)
        require_key(key)
        with self.store.connection(write=True) as db:
            db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            row,task=self.row(db,project,identity,request_id)
            if task['input_snapshot']['schema_version']==2:
                raise StorageError('manuscript_writing_review_required','v2候选必须完成精确文本科学审核和全文语言审核后才能发布。',409)
            if row['published_revision']:
                if row['publish_key']!=key or expected_revision!=row['request_json']['base_revision']: raise StorageError('task_idempotency_conflict','候选已由不同发布请求处理。',409)
                status=200
            else:
                self.assert_current(db,task)
                if row['candidate_json'] and row['candidate_json'].get('school_content_report',{}).get('can_publish') is False: raise StorageError('manuscript_review_blocked','学校内容检查存在不可豁免问题。',409)
                if task['status']!='succeeded' or row['candidate_json'] is None: raise StorageError('task_revision_conflict','写作候选尚未成功。',409)
                if expected_revision!=row['request_json']['base_revision']: raise StorageError('manuscript_revision_conflict','基础版本已变化。',409)
                base=self.manuscripts.version(db,project,identity,expected_revision);revision=expected_revision+1
                candidate=deepcopy(row['candidate_json']);version_id=str(uuid4());timestamp=now()
                body=deepcopy(base['request_json']);body['expected_revision']=expected_revision;body['title']=candidate['title']
                snap=dict(project_id=project,manuscript_id=identity,manuscript_version_id=version_id,revision=revision,output_language=candidate['output_language'],workflow_version=base['snapshot_json']['workflow_version'],snapshot_sha256=digest(candidate))
                producer=self.manuscripts.task(db,project,'manuscript_draft',snap,'manuscript:'+version_id)
                db.execute('INSERT INTO manuscript_versions(id,project_id,user_id,idempotency_key,request_json,request_digest,manuscript_id,revision,parent_version_id,task_id,snapshot_json,snapshot_sha256,created_at,school_confirmation_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(version_id,project,self.store.user_id,'writing:'+request_id,Jsonb(body),digest(body),identity,revision,base['id'],producer['id'],Jsonb(candidate),digest(candidate),timestamp,base.get('school_confirmation_id')))
                for table in ('manuscript_sources','manuscript_citations'):
                    for original in db.execute('SELECT * FROM '+table+' WHERE version_id=%s',(base['id'],)).fetchall():
                        fields=dict(original);fields.update(id=str(uuid4()),version_id=version_id)
                        fields={k:Jsonb(v) if isinstance(v,(dict,list)) else v for k,v in fields.items()}
                        db.execute('INSERT INTO '+table+'('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))
                db.execute('UPDATE manuscripts SET current_revision=%s,title=%s,updated_at=%s WHERE id=%s',(revision,candidate['title'],timestamp,identity))
                db.execute('UPDATE manuscript_writing_requests SET published_revision=%s,publish_key=%s,updated_at=%s WHERE task_id=%s',(revision,key,timestamp,request_id));status=201
        return self.manuscripts.get(project,identity),status

def recovery_actions(db,task):
    from app.domain.literature_assistance.service import last_call
    from app.domain.tasks.waits import get_open_wait
    if task['status']=='waiting_confirmation' and task['reason_code']=='budget_exceeded':
        wait=get_open_wait(db,task)
        return ['resume'] if wait and wait['kind']=='budget_confirmation' and wait['task_revision']==task['revision'] else []
    call=last_call(db,task['id'])
    if task['status']=='failed' and task.get('error_code') in ('storage_unavailable','task_worker_interrupted','model_provider_unavailable'):
        return ['retry'] if not call or call.get('provider_response_id') else []
    return []


def retry_in_transaction(store,db,task,expected_revision):
    from app.domain.tasks.waits import resolve_open_wait
    from app.domain.report_collections.service import scoped_store
    if task['revision']!=expected_revision or not recovery_actions(db,task): raise StorageError('task_transition_invalid','当前写作任务不能恢复。',409)
    WritingService(scoped_store(store.user_id,store.config)).assert_current(db,task)
    previous=checkpoint(db,task);revision=task['revision'];timestamp=now()
    task.update(status='queued',revision=revision+1,retry_count=0,reason_code='retry_requested',error_code=None,updated_at=max(timestamp,task['updated_at']),_retry_reason='manual_retry')
    if previous['next_node']=='await_confirmation': append_checkpoint(db,task,'check','check',previous['state_json'],previous)
    store.update_task(db,task,revision);resolve_open_wait(db,task);store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)
