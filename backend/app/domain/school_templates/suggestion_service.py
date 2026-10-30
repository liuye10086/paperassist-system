"""Frozen-note previews, owner-scoped model requests, and immutable advice reads."""
from copy import deepcopy
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key,append_checkpoint
from app.domain.literature.service import digest
from .service import SchoolTemplateService,now
from .suggestion_contracts import WORKFLOW,SuggestionPreview,SuggestionRequest
from .suggestion_validation import material,validate_output
from .suggestion_policy import bundle

def input_version(task):
    snap=task['input_snapshot']
    if task['task_type']!='school_rule_suggestion' or task['workflow_version']!=WORKFLOW or snap['workflow_version']!=WORKFLOW or digest(snap)!=task['input_digest'] or snap['project_id']!=task['project_id']:raise source_conflict()
    return dict(kind='school_rule_suggestion',suggestion_id=snap['suggestion_id'],template_version_id=snap['template_version_id'],analysis_sha256=snap['analysis_sha256'],bundle_sha256=snap['bundle']['bundle_sha256'],workflow_version=WORKFLOW)

def artifact_sha(row,result,raw,call_id):
    return digest(dict(input_digest=row['input_digest'],raw_output=raw,result=result,model_call_id=call_id))

class SuggestionService(SchoolTemplateService):
    def preview_in(self,db,project,identity,request):
        row=self.row(db,project,identity);_,task=self.require_current(db,row)
        if task['status']!='succeeded' or row['analysis_sha256']!=request.analysis_sha256:raise source_conflict()
        confirmation=self.confirmation(db,row)
        from .suggestion_eligibility import IdentitySourceSelected
        try:frozen=material(row['analysis_json'],request.note_ids,front_matter=confirmation.get('front_matter') if confirmation else None);outbound=bundle(frozen)
        except IdentitySourceSelected as exc:raise StorageError('task_input_invalid','所选说明包含已识别的身份字段来源；如同段含格式规则，请单独补充规范文字。',422) from exc
        except ValueError as exc:raise StorageError('task_input_invalid','请选择固定解析中可用的规范文字。',422) from exc
        notes={n['id']:n for n in row['analysis_json']['notes']}
        local=[dict(id=identity,alias='n'+str(i+1),text=notes[identity]['text'],source=deepcopy(notes[identity]['source']),sha256=digest(notes[identity])) for i,identity in enumerate(request.note_ids)]
        return outbound|dict(schema_version=1,template_version_id=row['id'],analysis_sha256=row['analysis_sha256'],notes=local)

    def preview(self,project,identity,request):
        with self.store.connection() as db:return self.preview_in(db,project,identity,request)

    def create_suggestion(self,project,identity,request,key):
        require_key(key);body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.project(db,project,True)
            old=db.execute('SELECT id,request_digest FROM school_rule_suggestions WHERE template_version_id=%s AND idempotency_key=%s',(identity,key)).fetchone()
            if old:
                if old['request_digest']!=digest(body):raise StorageError('task_idempotency_conflict','请求标识已用于不同规范文字。',409)
                return self.suggestion_view(db,self.suggestion_row(db,project,old['id'])),200
            row=self.row(db,project,identity)
            if self.confirmation(db,row):raise StorageError('task_input_invalid','此版本已确认；请基于原冻结资料新建子版本。',409)
            preview=self.preview_in(db,project,identity,request)
            if preview['bundle_sha256']!=request.bundle_sha256:raise source_conflict()
            suggestion_id=str(uuid4());timestamp=now()
            snap=dict(schema_version=1,kind='school_rule_suggestion',workflow_version=WORKFLOW,project_id=project,suggestion_id=suggestion_id,template_version_id=identity,
                analysis_sha256=row['analysis_sha256'],request=body,bundle=preview,confirmed_by=self.store.user_id)
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='school_rule_suggestion',idempotency_key='school-suggestion:'+suggestion_id,
                input_digest=digest(snap),input_snapshot=snap,workflow_version=WORKFLOW,status='queued',phase='interpret',revision=1,current_attempt=0,reason_code=None,created_at=timestamp,updated_at=timestamp)
            self.store.insert_task(db,task);self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            from app.domain.admin_configuration.bindings import bind,resolve
            bind(db,kind='task',object_id=task['id'],version=resolve(db))
            db.execute('''INSERT INTO school_rule_suggestions(id,project_id,user_id,template_version_id,task_id,idempotency_key,request_json,request_digest,input_snapshot,input_digest,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(suggestion_id,project,self.store.user_id,identity,task['id'],key,Jsonb(body),digest(body),Jsonb(snap),digest(snap),timestamp))
            append_checkpoint(db,task,'check','check',dict(input_digest=task['input_digest']))
            return self.suggestion_view(db,self.suggestion_row(db,project,suggestion_id)),202

    def suggestion_row(self,db,project,identity):
        self.project(db,project)
        row=db.execute('SELECT * FROM school_rule_suggestions WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row:raise StorageError('not_found','学校规范建议不存在。',404)
        task=self.store.require_task(db,row['task_id']);input_version(task)
        if row['request_digest']!=digest(row['request_json']) or row['input_digest']!=digest(row['input_snapshot']) or row['input_snapshot']!=task['input_snapshot'] or row['input_digest']!=task['input_digest']:raise source_conflict()
        snap=row['input_snapshot']
        request=SuggestionRequest.model_validate(row['request_json']).model_dump(mode='json')
        if snap['request']!=request or request['bundle_sha256']!=snap['bundle']['bundle_sha256'] or request['analysis_sha256']!=snap['analysis_sha256']:raise source_conflict()
        if snap['template_version_id']!=row['template_version_id'] or snap['suggestion_id']!=row['id'] or snap['confirmed_by']!=row['user_id']:raise source_conflict()
        template=self.row(db,project,row['template_version_id']);self.validate(db,template)
        if template['analysis_sha256']!=snap['analysis_sha256']:raise source_conflict()
        notes={note['id']:note for note in template['analysis_json']['notes']}
        if [n['id'] for n in snap['bundle']['notes']]!=request['note_ids']:raise source_conflict()
        for note in snap['bundle']['notes']:
            original=notes.get(note['id'])
            if not original or digest(original)!=note['sha256'] or original['source']!=note['source'] or original['text']!=note['text']:raise source_conflict()
        if snap['bundle']['material']['notes']!=[{k:n[k] for k in ('alias','text')} for n in snap['bundle']['notes']]:raise source_conflict()
        if row['result_json'] is not None:
            if row['result_json'].get('validation_status')=='invalid':rebuilt=dict(candidates=[],validation_status='invalid')
            else:
                rebuilt=validate_output(row['raw_output_json'],snap['bundle']['material'])
                for candidate in rebuilt['candidates']:
                    candidate['source']=deepcopy(next(n['source'] for n in snap['bundle']['notes'] if n['alias']==candidate['note_alias']))
            if rebuilt!=row['result_json'] or artifact_sha(row,rebuilt,row['raw_output_json'],row['model_call_id'])!=row['artifact_sha256']:raise source_conflict()
            call=db.execute('SELECT task_id FROM model_calls WHERE id=%s AND project_id=%s AND user_id=%s',(row['model_call_id'],project,self.store.user_id)).fetchone()
            if not call or call['task_id']!=task['id']:raise source_conflict()
        return row

    def suggestion_view(self,db,row):
        from app.domain.model_usage.provenance import public_provider_provenance
        task=self.store.require_task(db,row['task_id'])
        calls=db.execute('SELECT * FROM model_calls WHERE task_id=%s ORDER BY created_at,id',(task['id'],)).fetchall()
        return dict(schema_version=1,id=row['id'],template_version_id=row['template_version_id'],analysis_sha256=row['input_snapshot']['analysis_sha256'],task=self.store.public_task(task),
            bundle_sha256=row['input_snapshot']['bundle']['bundle_sha256'],artifact_sha256=row['artifact_sha256'],result=row['result_json'],
            model_calls=[{k:c[k] for k in ('id','model','status','estimated_cost_micro_usd')}|dict(provider_provenance=public_provider_provenance(c,task)) for c in calls])

    def get_suggestion(self,project,identity):
        with self.store.connection() as db:return self.suggestion_view(db,self.suggestion_row(db,project,identity))

    def list_suggestions(self,project,identity):
        with self.store.connection() as db:
            self.row(db,project,identity)
            rows=db.execute('SELECT id FROM school_rule_suggestions WHERE template_version_id=%s AND project_id=%s AND user_id=%s ORDER BY created_at,id',(identity,project,self.store.user_id)).fetchall()
            return dict(items=[self.suggestion_view(db,self.suggestion_row(db,project,r['id'])) for r in rows])

    def fork(self,project,identity,key):
        from .contracts import TemplateRequest
        with self.store.connection() as db:
            row=self.row(db,project,identity);self.require_current(db,row)
            request=deepcopy(row['request_json']);request.update(previous_version_id=identity,name=row['name'][:293]+' 规范建议版')
        return self.create(project,TemplateRequest.model_validate(request),key)
