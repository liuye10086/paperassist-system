"""Frozen originals, parsed evidence, immutable analysis and explicit rule binding."""
from copy import deepcopy
from datetime import datetime,timezone
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from .contracts import WORKFLOW,PARSER_VERSION,PROFILE_FIELDS,TemplateRequest,ConfirmRequest

def now(): return datetime.now(timezone.utc)
def invalid(message,status=409): return StorageError('task_input_invalid',message,status)


def input_version(task):
    snap=task['input_snapshot']
    if (task['task_type']!='school_template_parse' or task['workflow_version']!=WORKFLOW
        or digest(snap)!=task['input_digest'] or snap.get('project_id')!=task['project_id']
        or snap.get('workflow_version')!=WORKFLOW or snap.get('parser_version')!=PARSER_VERSION): raise source_conflict()
    return dict(kind='school_template',template_version_id=snap['template_version_id'],parser_version=snap['parser_version'],workflow_version=WORKFLOW)


class SchoolTemplateService:
    def __init__(self,assets):
        self.assets=assets;self.store=TaskStore(assets.owner_id,assets.db_config)

    def project(self,db,project,lock=False):
        row=self.store.require_project(db,project)
        if row['project_type']!='thesis': raise invalid('学校模板仅用于毕业论文项目。',422)
        if lock: db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
        return row

    def profile_view(self,db,project):
        row=db.execute('SELECT * FROM thesis_profiles WHERE project_id=%s AND user_id=%s',(project,self.store.user_id)).fetchone()
        return ({k:row[k] for k in ('revision',*PROFILE_FIELDS,'bound_confirmation_id')} if row else
            dict(revision=0,**{k:'' for k in PROFILE_FIELDS},bound_confirmation_id=None))

    def profile(self,project):
        with self.store.connection() as db:
            self.project(db,project);return self.profile_view(db,project)

    def save_profile(self,project,request):
        with self.store.connection(write=True) as db:
            self.project(db,project,True);old=self.profile_view(db,project)
            if old['revision']!=request.expected_revision: raise StorageError('task_revision_conflict','学校资料已更新，请刷新。',409)
            values={k:getattr(request,k) for k in PROFILE_FIELDS}
            self._profile(db,project,old,values,old['bound_confirmation_id'])
            return self.profile_view(db,project)

    def _profile(self,db,project,old,values,binding):
        db.execute('''INSERT INTO thesis_profiles(project_id,user_id,revision,school,department,major,degree_type,education_level,applicable_version,bound_confirmation_id,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(project_id) DO UPDATE SET
            revision=EXCLUDED.revision,school=EXCLUDED.school,department=EXCLUDED.department,major=EXCLUDED.major,
            degree_type=EXCLUDED.degree_type,education_level=EXCLUDED.education_level,applicable_version=EXCLUDED.applicable_version,
            bound_confirmation_id=EXCLUDED.bound_confirmation_id,updated_at=EXCLUDED.updated_at''',
            (project,self.store.user_id,old['revision']+1,*(values[k] for k in PROFILE_FIELDS),binding,now()))

    def freeze_source(self,db,project,file_id,role):
        file=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(file_id,project)).fetchone()
        if not file: raise StorageError('file_not_found','来源文件不存在。',404)
        file=dict(file)
        if role=='template' and file['file_type']!='docx': raise invalid('学校模板须为DOCX文件。',422)
        if role=='supplement' and file['file_type'] not in ('docx','pdf'): raise invalid('补充规范文件须为DOCX或PDF，可在文本框直接填写其他规范。',422)
        self.assets.original(file)
        snapshot={k:file[k] for k in ('id','filename','sha256','size_bytes','file_type','storage_backend','object_key')}
        evidence=[];version_id=None;evidence_sha=None
        if role=='supplement':
            row=db.execute("""SELECT v.id FROM file_parse_results v JOIN tasks t ON t.id=v.task_id
                WHERE v.file_id=%s AND t.project_id=%s AND t.user_id=%s AND t.status='succeeded' AND v.result_json IS NOT NULL
                ORDER BY v.version DESC LIMIT 1""",(file_id,project,self.store.user_id)).fetchone()
            if not row: raise invalid('补充规范尚未完成文档解析，请先处理解析任务再创建模板。')
            from app.domain.external_evidence.service import ExternalEvidenceService
            source,evidence=ExternalEvidenceService(self.assets).source(project,file_id,'document_version',row['id'])
            version_id=row['id'];evidence_sha=source['sha256']
        return dict(id=str(uuid4()),role=role,file_id=file_id,filename=file['filename'],sha256=file['sha256'],size_bytes=file['size_bytes'],
            download_url=f'/api/v1/projects/{project}/files/{file_id}/download',document_version_id=version_id,evidence_sha256=evidence_sha,evidence=evidence,file=snapshot)

    def create(self,project,request,key):
        require_key(key);body=request.model_dump(mode='json')
        if request.previous_version_id is None:body.pop('previous_version_id',None)
        hashed=digest(body)
        with self.store.connection(write=True) as db:
            self.project(db,project,True)
            replay=db.execute('SELECT * FROM school_template_versions WHERE project_id=%s AND user_id=%s AND idempotency_key=%s',(project,self.store.user_id,key)).fetchone()
            if replay:
                if replay['request_digest']!=hashed: raise StorageError('task_idempotency_conflict','请求标识已用于不同输入。',409)
                return self.view(db,replay),200
            if request.previous_version_id:self.validate(db,self.row(db,project,request.previous_version_id))
            sources=[self.freeze_source(db,project,request.template_file_id,'template')]
            sources.extend(self.freeze_source(db,project,f,'supplement') for f in request.supplement_file_ids)
            sources.extend(self.freeze_source(db,project,f,'manuscript') for f in request.manuscript_file_ids)
            identity=str(uuid4());timestamp=now();sources_sha=digest(sources)
            snapshot=dict(kind='school_template',project_id=project,template_version_id=identity,parser_version=PARSER_VERSION,workflow_version=WORKFLOW,sources_sha256=sources_sha)
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='school_template_parse',idempotency_key='school-template:'+identity,
                input_digest=digest(snapshot),input_snapshot=snapshot,workflow_version=WORKFLOW,status='queued',phase='parse',revision=1,current_attempt=0,
                reason_code=None,created_at=timestamp,updated_at=timestamp)
            self.store.insert_task(db,task);self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            db.execute('''INSERT INTO school_template_versions(id,project_id,user_id,idempotency_key,request_json,request_digest,name,school,version_label,task_id,sources_sha256,created_at,previous_version_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(identity,project,self.store.user_id,key,Jsonb(body),hashed,request.name,request.school,request.version_label,task['id'],sources_sha,timestamp,request.previous_version_id))
            for source in sources:
                db.execute('''INSERT INTO school_template_sources(id,project_id,user_id,template_version_id,file_id,role,source_json,sha256,document_version_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(source['id'],project,self.store.user_id,identity,source['file_id'],source['role'],Jsonb(source),digest(source),source['document_version_id']))
            row=self.row(db,project,identity)
            return self.view(db,row),202

    def row(self,db,project,identity):
        self.project(db,project)
        row=db.execute('SELECT * FROM school_template_versions WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row: raise StorageError('not_found','学校模板版本不存在。',404)
        return row

    def validate(self,db,row):
        body=TemplateRequest.model_validate(row['request_json'])
        if digest(row['request_json'])!=row['request_digest'] or any(row[k]!=getattr(body,k) for k in ('name','school','version_label')): raise source_conflict()
        if row.get('previous_version_id')!=body.previous_version_id:raise source_conflict()
        if body.previous_version_id:self.row(db,row['project_id'],body.previous_version_id)
        task=self.store.require_task(db,row['task_id']);version=input_version(task)
        if version['template_version_id']!=row['id'] or task['input_snapshot']['sources_sha256']!=row['sources_sha256']: raise source_conflict()
        rows=db.execute('SELECT * FROM school_template_sources WHERE template_version_id=%s',(row['id'],)).fetchall()
        by_id={s['file_id']:s for s in rows};sources=[]
        for role,ids in (('template',[body.template_file_id]),('supplement',body.supplement_file_ids),('manuscript',body.manuscript_file_ids)):
            for file_id in ids:
                source=by_id.get(file_id)
                if not source or source['role']!=role or digest(source['source_json'])!=source['sha256']: raise source_conflict()
                snap=source['source_json']
                if (snap['id']!=source['id'] or snap['file_id']!=file_id or snap['role']!=role or snap['document_version_id']!=source['document_version_id']
                    or snap['sha256']!=snap['file']['sha256'] or snap['filename']!=snap['file']['filename']): raise source_conflict()
                sources.append(snap)
        if len(rows)!=len(sources) or digest(sources)!=row['sources_sha256']: raise source_conflict()
        if row['analysis_json'] is not None and digest(row['analysis_json'])!=row['analysis_sha256']: raise source_conflict()
        return sources,task

    def current_changes(self,db,row,sources):
        changes=[]
        for source in sources:
            try:
                file=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(source['file_id'],row['project_id'])).fetchone()
                if not file or any(file[k]!=v for k,v in source['file'].items()): raise source_conflict()
                self.assets.original(dict(file))
                if source['document_version_id']:
                    from app.domain.external_evidence.service import ExternalEvidenceService
                    current,items=ExternalEvidenceService(self.assets).source(row['project_id'],source['file_id'],'document_version',source['document_version_id'])
                    if current['sha256']!=source['evidence_sha256'] or items!=source['evidence']: raise source_conflict()
            except StorageError as exc:
                if exc.code in ('storage_unavailable','database_configuration'): raise
                changes.append(dict(file_id=source['file_id'],reason='source_unavailable_or_changed'))
        return changes

    def require_current(self,db,row):
        sources,task=self.validate(db,row)
        if self.current_changes(db,row,sources): raise source_conflict()
        return sources,task

    def confirmation(self,db,row):
        saved=db.execute('SELECT * FROM school_template_confirmations WHERE template_version_id=%s',(row['id'],)).fetchone()
        if not saved:return None
        snap=saved['snapshot_json']
        if (digest(snap)!=saved['snapshot_sha256'] or digest(saved['request_json'])!=saved['request_digest']
            or saved['analysis_sha256']!=row['analysis_sha256'] or snap['id']!=saved['id']
            or snap['template_version_id']!=row['id'] or snap['analysis_sha256']!=saved['analysis_sha256']): raise source_conflict()
        return snap

    def text_options(self,db,row):
        from .text_decisions import options
        from app.domain.manuscripts.school_export import REAL_TEMPLATE_SHA256
        previous=self.row(db,row['project_id'],row['previous_version_id']) if row.get('previous_version_id') else None
        confirmation=self.confirmation(db,previous) if previous else None
        sources=self.validate(db,previous)[0] if previous else []
        return options(row['analysis_json'],previous['analysis_json'] if previous else None,confirmation,any(s['role']=='template' and s['sha256']==REAL_TEMPLATE_SHA256 for s in sources))

    def view(self,db,row):
        sources,task=self.validate(db,row)
        return {k:row[k] for k in ('id','name','school','version_label','created_at','analysis_sha256')} | dict(task=self.store.public_task(task),
            previous_version_id=row.get('previous_version_id'),text_decision_options=self.text_options(db,row),analysis=row['analysis_json'],confirmation=self.confirmation(db,row),sources=[{k:v for k,v in source.items() if k!='file'} for source in sources],
            supplement_text=row['request_json']['supplement_text'],current_changes=self.current_changes(db,row,sources))

    def list(self,project):
        with self.store.connection() as db:
            self.project(db,project)
            rows=db.execute('SELECT * FROM school_template_versions WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id',(project,self.store.user_id)).fetchall()
            return dict(items=[self.view(db,row) for row in rows])

    def confirm(self,project,identity,request,key):
        require_key(key);body=request.model_dump(mode='json')
        if not request.text_decisions:body.pop('text_decisions',None)
        with self.store.connection(write=True) as db:
            self.project(db,project,True);row=self.row(db,project,identity)
            existing=db.execute('SELECT * FROM school_template_confirmations WHERE template_version_id=%s',(identity,)).fetchone()
            if existing:
                if existing['idempotency_key']==key and existing['request_digest']==digest(body): return self.confirmation(db,row),200
                raise invalid('此模板版本已确认；确认版本不可覆盖。')
            _,task=self.require_current(db,row)
            if task['status']!='succeeded' or not row['analysis_json'] or row['analysis_sha256']!=request.analysis_sha256: raise invalid('解析未完成或版本已变化，请刷新。')
            text_options={o['id']:o for o in self.text_options(db,row)}
            choices={d.id:d for d in request.text_decisions}
            if len(choices)!=len(request.text_decisions) or set(choices)!=set(text_options):raise invalid('请明确选择两项文字规范的本次决定。',422)
            for identity_,choice in choices.items():
                option=text_options[identity_]
                if choice.source_sha256!=option['source_sha256'] or choice.choice not in option['choices']:raise invalid('文字规范来源或选项已变化。')
            analysis=row['analysis_json'];conflicts={c['id']:c for c in analysis['conflicts']};decisions={d.conflict_id:d.option_id for d in request.decisions}
            if set(decisions)!=set(conflicts): raise invalid('须明确解决每一项冲突。')
            rules=deepcopy(analysis['rules'])
            for conflict_id,option_id in decisions.items():
                conflict=conflicts[conflict_id];option=next((o for o in conflict['options'] if o['id']==option_id),None)
                if not option: raise invalid('冲突选项不存在。',422)
                matches=[r for r in rules if r['id']==conflict['rule_id']]
                if len(matches)!=1: raise source_conflict()
                matches[0].update(value=option['value'],source=option['source'])
            timestamp=now();cid=str(uuid4())
            snap=dict(id=cid,template_version_id=identity,analysis_sha256=row['analysis_sha256'],decisions=body['decisions'],chapters=body['chapters'],rules=rules,
                missing=deepcopy(analysis['missing']),unsupported=deepcopy(analysis['unsupported']),created_at=timestamp.isoformat())
            if request.text_decisions:snap['text_decisions']=[d.model_dump()|dict(evidence=text_options[d.id]) for d in request.text_decisions]
            db.execute('''INSERT INTO school_template_confirmations(id,project_id,user_id,idempotency_key,request_json,request_digest,template_version_id,analysis_sha256,snapshot_json,snapshot_sha256,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(cid,project,self.store.user_id,key,Jsonb(body),digest(body),identity,row['analysis_sha256'],Jsonb(snap),digest(snap),timestamp))
            return snap,201

    def bind(self,project,request):
        with self.store.connection(write=True) as db:
            self.project(db,project,True);old=self.profile_view(db,project)
            if old['revision']!=request.expected_revision: raise StorageError('task_revision_conflict','学校资料已更新，请刷新。',409)
            confirmation=db.execute('SELECT * FROM school_template_confirmations WHERE id=%s AND project_id=%s AND user_id=%s',(request.confirmation_id,project,self.store.user_id)).fetchone()
            if not confirmation: raise StorageError('not_found','确认版本不存在。',404)
            row=self.row(db,project,confirmation['template_version_id']);self.require_current(db,row);self.confirmation(db,row)
            self._profile(db,project,old,old,confirmation['id']);return self.profile_view(db,project)

    def retry(self,project,identity):
        with self.store.connection(write=True) as db:
            self.project(db,project,True);row=self.row(db,project,identity);_,task=self.require_current(db,row)
            retry_in_transaction(self.store,db,task,task['revision'],assets=self.assets)
            return self.view(db,row)


def retry_in_transaction(store,db,task,expected_revision,*,assets=None):
    from app.domain.report_collections.service import scoped_store
    service=SchoolTemplateService(assets or scoped_store(task['user_id'],store.config))
    if task['task_type']!='school_template_parse' or task['status']!='failed' or task['revision']!=expected_revision: raise invalid('仅能重试当前失败解析任务。')
    row=service.row(db,task['project_id'],task['input_snapshot']['template_version_id']);service.require_current(db,row)
    if row['analysis_json'] is not None: raise source_conflict()
    task.update(status='queued',revision=expected_revision+1,reason_code='retry_requested',error_code=None,updated_at=max(now(),task['updated_at']),_retry_reason='manual_retry')
    store.update_task(db,task,expected_revision);store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)
