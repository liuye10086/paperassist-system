"""Immutable draft versions plus task-backed publication and local export intents."""
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from app.domain.literature_citations.service import LiteratureCitationService
from .contracts import ManuscriptRequest,METHOD_FIELDS,WORKFLOW,ExportRequest,SchoolExportOptions
from .draft import freeze
from .sources import changes,read_source

def now(): return datetime.now(timezone.utc)
def missing(): return StorageError('manuscript_not_found','事实稿或版本不存在。',404)

class ManuscriptService:
    def __init__(self,assets):
        self.assets=assets;self.store=TaskStore(assets.owner_id,assets.db_config)
        self.citations=LiteratureCitationService(assets)
        self.directory=Path(assets.directory)/'manuscript_exports'

    def require_project(self,db,project):
        value=self.store.require_project(db,project)
        return value

    def config(self,project):
        with self.store.connection() as db:
            value=self.require_project(db,project)
            from .school_binding import readiness
            thesis=readiness(self,db,project) if value['project_type']=='thesis' else None
        return dict(project_id=project,project_type=value['project_type'],thesis=thesis,workflow_version=WORKFLOW,real_model_calls=False,pdf_status='not_requested',output_languages=['zh-CN','en'])

    def candidates(self,project):
        items=[]
        with self.store.connection() as db:
            self.require_project(db,project)
            files=db.execute('SELECT * FROM files WHERE project_id=%s ORDER BY uploaded_at DESC,id',(project,)).fetchall()
            for file in files:
                prefix=f'/api/v1/projects/{project}/files/{file["id"]}'
                def item(kind,identity,label,version=None,roles=None,url=None):
                    items.append(dict(kind=kind,id=identity,file_id=file['id'],label=label,version=version,
                        allowed_roles=roles or ['methods','user_results','literature','image_observation'],download_url=url or prefix+'/download'))
                item('original',file['id'],file['filename'],roles=['methods','user_results','literature']+(['image_observation'] if file['file_type'] in ('png','jpeg') else []))
                for kind,table in (('document_version','file_parse_results'),('ocr_review_version','ocr_review_versions')):
                    rows=db.execute('SELECT v.id,v.version FROM '+table+" v JOIN tasks t ON t.id=v.task_id WHERE v.file_id=%s AND t.user_id=%s AND t.project_id=%s AND t.status='succeeded' ORDER BY v.version DESC",(file['id'],self.store.user_id,project)).fetchall()
                    for row in rows: item(kind,row['id'],file['filename']+' — '+('文档解析 / Parsed document' if kind=='document_version' else '人工核对 / Human reviewed')+' v'+str(row['version']),row['version'])
                for row in db.execute("SELECT id,snapshot_json->>'title' AS title,version FROM external_evidence_versions WHERE file_id=%s AND project_id=%s AND user_id=%s ORDER BY version DESC",(file['id'],project,self.store.user_id)).fetchall(): item('external_evidence_version',row['id'],row['title'],row['version'])
                for row in db.execute('SELECT id,setup_revision,engine_version FROM analysis_runs WHERE file_id=%s ORDER BY completed_at DESC,id',(file['id'],)).fetchall():
                    item('analysis_run',row['id'],file['filename']+' — 统计结果 / Statistical result v'+str(row['setup_revision']),row['setup_revision'],['computed_results'],prefix+'/analysis-runs/'+row['id'])
                for row in db.execute('SELECT f.id,f.figure_json FROM figures f JOIN analysis_runs a ON a.id=f.analysis_run_id WHERE a.file_id=%s ORDER BY f.id',(file['id'],)).fetchall():
                    import json
                    figure=json.loads(row['figure_json']);item('figure',row['id'],figure['title'],roles=['image_observation'])
                for row in db.execute('SELECT id,snapshot_json FROM manuscript_figure_language_versions WHERE file_id=%s AND project_id=%s AND user_id=%s ORDER BY created_at,id',(file['id'],project,self.store.user_id)).fetchall():
                    figure=row['snapshot_json']
                    item('figure_language_version',row['id'],figure['title']+' ['+figure['output_language']+']',roles=['image_observation'],
                        url=f"/api/v1/projects/{project}/manuscript-figure-language-versions/{row['id']}/download")
            drafts=[]
            for root in self.citations.rows(db,'literature_citation_drafts',project):
                _,row=self.citations.draft_row(db,project,root['id'])
                snap=row['snapshot_json']
                drafts.append(dict(id=root['id'],revision=row['revision'],title=snap['title'],usable=not bool(self.citations.current_changes(db,project,snap))))
        config=self.config(project)
        excluded=set((config['thesis'] or {}).get('template_source_file_ids',[]))
        return dict(items=[s for s in items if s['file_id'] not in excluded],citation_drafts=drafts,methods_fields=list(METHOD_FIELDS),project_type=config['project_type'],thesis=config['thesis'])

    def preview(self,project,request):
        request=ManuscriptRequest.model_validate(request) if isinstance(request,dict) else request
        self.validate_request_project(project,request)
        return freeze(self,project,request)

    def freeze_school_context(self,project,request):
        from .school_binding import freeze_context
        return freeze_context(self,project,request)

    def validate_request_project(self,project,request):
        with self.store.connection() as db: value=self.require_project(db,project)
        if (value['project_type']=='thesis') != (request.thesis is not None):
            raise StorageError('task_input_invalid','毕业论文须选择学校配置，SCI不得混用学校配置。',422)
        if request.thesis:self.freeze_school_context(project,request)

    def source_changes(self,project,snapshot):
        from .school_binding import current_changes
        return changes(self,project,snapshot)+current_changes(self,project,snapshot)

    def root(self,db,project,identity):
        self.require_project(db,project)
        row=db.execute('SELECT * FROM manuscripts WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row: raise missing()
        if digest(row['request_json'])!=row['request_digest']: raise source_conflict()
        return row

    def version(self,db,project,identity,revision):
        self.root(db,project,identity)
        row=db.execute('SELECT * FROM manuscript_versions WHERE manuscript_id=%s AND revision=%s AND project_id=%s AND user_id=%s',(identity,revision,project,self.store.user_id)).fetchone()
        if not row: raise missing()
        self.validate_version(db,row)
        return row

    def validate_version(self,db,row):
        snap=row['snapshot_json']
        from .school_binding import validate_frozen
        validate_frozen(self,db,row)
        if digest(snap)!=row['snapshot_sha256'] or digest(row['request_json'])!=row['request_digest']: raise source_conflict()
        request=ManuscriptRequest.model_validate(row['request_json'])
        if snap['title']!=request.title or snap['output_language']!=request.output_language or request.expected_revision!=row['revision']-1: raise source_conflict()
        if [{k:s[k] for k in ('kind','id','file_id','role')} for s in snap['sources']]!=[s.model_dump() for s in request.sources]: raise source_conflict()
        if request.citation_draft and (not snap.get('citation_snapshot') or any(snap['citation_snapshot'][k]!=v for k,v in (('draft_id',request.citation_draft.id),('revision',request.citation_draft.revision)))): raise source_conflict()
        # Historical output is sealed by independent snapshot/request/source/task
        # hashes. Never regenerate it using a future wording/formatting function.
        if (snap.get('schema_version')!=1 or type(snap.get('schema_version')) is not int
            or not isinstance(snap.get('notice'),str)
            or any(not isinstance(snap.get(k),list) for k in ('methods','results_groups','references','issues','sources'))): raise source_conflict()
        for paragraph in [*snap['methods'],*[p for group in snap['results_groups'] for p in group.get('paragraphs',[])]]:
            if (not isinstance(paragraph,dict) or not isinstance(paragraph.get('id'),str) or not isinstance(paragraph.get('text'),str)
                or paragraph.get('origin') not in ('user_provided','computed_result','literature','image_observation')
                or not isinstance(paragraph.get('source_ids'),list) or not isinstance(paragraph.get('citations'),list)): raise source_conflict()
        if snap.get('illustration_check_version') is not None:
            from .illustrations import check_bindings
            if snap['illustration_check_version']!=1 or check_bindings(snap['results_groups'],snap['output_language']): raise source_conflict()
        if snap.get('school_change_provenance') is not None:
            from .school_changes import validate_school_change_version
            validate_school_change_version(self,db,row)
        elif snap.get('review_provenance') is not None:
            from app.domain.manuscript_review.service import validate_review_version
            validate_review_version(self,db,row)
        elif snap.get('writing_provenance') is not None:
            from app.domain.manuscript_writing.context import validate_candidate
            provenance=snap['writing_provenance']
            writing=db.execute('SELECT * FROM manuscript_writing_requests WHERE task_id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s',(provenance.get('request_id'),row['manuscript_id'],row['project_id'],row['user_id'])).fetchone()
            if not writing: raise source_conflict()
            if provenance.get('schema_version')==2:
                from app.domain.manuscript_writing.live_publish import validate_published
                validate_published(self,db,row,writing)
            else:
                if writing['published_revision']!=row['revision'] or writing['candidate_json']!=snap or writing['base_version_id']!=row['parent_version_id']: raise source_conflict()
                try: validate_candidate(snap,writing['input_snapshot'])
                except (ValueError,TypeError,KeyError) as exc: raise source_conflict() from exc
        producer=db.execute('SELECT * FROM tasks WHERE id=%s',(row['task_id'],)).fetchone()
        if (not producer or producer['task_type']!='manuscript_draft' or producer['project_id']!=row['project_id'] or producer['user_id']!=row['user_id']
            or producer['input_digest']!=digest(producer['input_snapshot']) or producer['input_snapshot'].get('snapshot_sha256')!=row['snapshot_sha256']
            or producer['input_snapshot'].get('manuscript_version_id')!=row['id']): raise source_conflict()
        if snap['project_id']!=row['project_id'] or snap['workflow_version']!=WORKFLOW: raise source_conflict()
        source_rows=db.execute('SELECT * FROM manuscript_sources WHERE version_id=%s',(row['id'],)).fetchall()
        by_id={s['source_id']:s for s in source_rows}
        if len(by_id)!=len(snap['sources']): raise source_conflict()
        for source in snap['sources']:
            bound=by_id.get(source['id'])
            if not bound or bound['source_json']!=source or bound['sha256']!=digest(source) or any(bound[k]!=source[v] for k,v in (('kind','kind'),('file_id','file_id'),('role','role'))): raise source_conflict()
        parent=db.execute('SELECT revision FROM manuscript_versions WHERE id=%s AND manuscript_id=%s',(row['parent_version_id'],row['manuscript_id'])).fetchone() if row['parent_version_id'] else None
        if row['revision']>1 and (not parent or (not 1<=parent['revision']<row['revision'] if snap.get('school_change_provenance') else parent['revision']!=row['revision']-1)): raise source_conflict()
        expected=[]
        citation=snap.get('citation_snapshot')
        if citation:
            original=db.execute('SELECT snapshot_json,snapshot_sha256 FROM literature_citation_versions WHERE id=%s AND project_id=%s AND user_id=%s',(citation['version_id'],row['project_id'],row['user_id'])).fetchone()
            if not original or original['snapshot_json']!=citation or original['snapshot_sha256']!=digest(citation): raise source_conflict()
            for paragraph in citation['paragraphs']:
                for fragment in paragraph['fragments']:
                    if fragment['kind']=='claim':
                        for binding in fragment['bindings']: expected.append(('literature:'+paragraph['id'],fragment['claim_id'],fragment['claim_revision'],binding['review_id'],binding['metadata_version_id'],binding['project_reference_id'],binding))
        actual=db.execute('SELECT * FROM manuscript_citations WHERE version_id=%s',(row['id'],)).fetchall()
        actual=[(r['paragraph_id'],r['claim_id'],r['claim_revision'],r['review_id'],r['metadata_version_id'],r['project_reference_id'],r['binding_json']) for r in actual]
        if sorted(actual,key=str)!=sorted(expected,key=str): raise source_conflict()

    def task(self,db,project,task_type,snapshot,key):
        timestamp=now()
        task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type=task_type,
            idempotency_key=key,input_digest=digest(snapshot),input_snapshot=snapshot,workflow_version=WORKFLOW,
            status='queued',phase='write' if task_type=='manuscript_draft' else 'export',revision=1,current_attempt=0,
            reason_code=None,created_at=timestamp,updated_at=timestamp)
        self.store.insert_task(db,task);self.store.append_event(db,task,'created');self.store.enqueue(db,task)
        return task

    def create(self,project,request,key,identity=None):
        require_key(key);request=ManuscriptRequest.model_validate(request) if isinstance(request,dict) else request
        body=request.model_dump(mode='json')
        if request.thesis is None: body.pop('thesis',None)
        hashed=digest(body)
        with self.store.connection(write=True) as db:
            self.require_project(db,project)
            db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            if identity:
                root=self.root(db,project,identity)
                replay=db.execute('SELECT * FROM manuscript_versions WHERE manuscript_id=%s AND idempotency_key=%s',(identity,key)).fetchone()
            else:
                replay=db.execute('SELECT * FROM manuscripts WHERE project_id=%s AND user_id=%s AND idempotency_key=%s',(project,self.store.user_id,key)).fetchone()
            if replay:
                if replay['request_digest']!=hashed: raise StorageError('task_idempotency_conflict','请求标识已用于不同输入。',409)
                identity=replay['manuscript_id'] if identity else replay['id'];status=200
            else:
                revision=root['current_revision']+1 if identity else 1
                if request.expected_revision!=(revision-1): raise StorageError('manuscript_revision_conflict','事实稿已有新版本，请刷新。',409)
                parent=self.version(db,project,identity,revision-1)['id'] if identity else None
                self.validate_request_project(project,request)
                snapshot=freeze(self,project,request);timestamp=now()
                if not identity:
                    identity=str(uuid4())
                    db.execute('''INSERT INTO manuscripts(id,project_id,user_id,idempotency_key,request_json,request_digest,current_revision,title,created_at,updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,1,%s,%s,%s)''',(identity,project,self.store.user_id,key,Jsonb(body),hashed,request.title,timestamp,timestamp))
                version_id=str(uuid4())
                task_snapshot=dict(project_id=project,manuscript_id=identity,manuscript_version_id=version_id,revision=revision,
                    output_language=request.output_language,workflow_version=WORKFLOW,snapshot_sha256=digest(snapshot))
                task=self.task(db,project,'manuscript_draft',task_snapshot,'manuscript:'+version_id)
                db.execute('''INSERT INTO manuscript_versions(id,project_id,user_id,idempotency_key,request_json,request_digest,manuscript_id,revision,parent_version_id,task_id,snapshot_json,snapshot_sha256,created_at,school_confirmation_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(version_id,project,self.store.user_id,key,Jsonb(body),hashed,identity,revision,parent,task['id'],Jsonb(snapshot),digest(snapshot),timestamp,request.thesis.confirmation_id if request.thesis else None))
                for source in snapshot['sources']:
                    foreign={'document_version':'document_version_id','ocr_review_version':'ocr_review_version_id','external_evidence_version':'external_evidence_version_id','analysis_run':'analysis_run_id','figure':'figure_id','figure_language_version':'figure_language_version_id'}.get(source['kind'])
                    fields=dict(id=str(uuid4()),version_id=version_id,file_id=source['file_id'],kind=source['kind'],source_id=source['id'],role=source['role'],source_json=Jsonb(source),sha256=digest(source))
                    if foreign: fields[foreign]=source['id']
                    db.execute('INSERT INTO manuscript_sources('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))
                citation=snapshot['citation_snapshot']
                if citation:
                    for paragraph in citation['paragraphs']:
                        for fragment in paragraph['fragments']:
                            if fragment['kind']!='claim': continue
                            for binding in fragment['bindings']:
                                db.execute('''INSERT INTO manuscript_citations(id,version_id,citation_version_id,paragraph_id,claim_id,claim_revision,review_id,metadata_version_id,project_reference_id,binding_json)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(str(uuid4()),version_id,citation['version_id'],'literature:'+paragraph['id'],fragment['claim_id'],fragment['claim_revision'],binding['review_id'],binding['metadata_version_id'],binding['project_reference_id'],Jsonb(binding)))
                if revision>1: db.execute('UPDATE manuscripts SET current_revision=%s,title=%s,updated_at=%s WHERE id=%s',(revision,request.title,timestamp,identity))
                status=201
        return self.get(project,identity),status

    def version_view(self,db,row):
        self.validate_version(db,row)
        task=self.store.require_task(db,row['task_id'])
        status='published' if task['status']=='succeeded' else 'failed' if task['status']=='failed' else 'pending'
        exports=db.execute('SELECT id FROM manuscript_exports WHERE version_id=%s ORDER BY created_at DESC,id',(row['id'],)).fetchall()
        return dict(id=row['id'],revision=row['revision'],parent_version_id=row['parent_version_id'],task_id=row['task_id'],status=status,
            created_at=row['created_at'].isoformat(),input=row['request_json'],snapshot=row['snapshot_json'],current_changes=self.source_changes(row['project_id'],row['snapshot_json']),
            exports=[self.export_view(db,row,r['id']) for r in exports])

    def get(self,project,identity,revision=None):
        with self.store.connection() as db:
            root=self.root(db,project,identity)
            if revision is not None: return self.version_view(db,self.version(db,project,identity,revision))
            versions=db.execute('SELECT * FROM manuscript_versions WHERE manuscript_id=%s ORDER BY revision DESC',(identity,)).fetchall()
            return {k:root[k] for k in ('id','project_id','title','current_revision','created_at','updated_at')} | dict(versions=[self.version_view(db,r) for r in versions])

    def list(self,project):
        with self.store.connection() as db:
            self.require_project(db,project)
            ids=db.execute('SELECT id FROM manuscripts WHERE project_id=%s AND user_id=%s ORDER BY updated_at DESC,id',(project,self.store.user_id)).fetchall()
        return dict(items=[self.get(project,r['id']) for r in ids])

    def verify_task(self,db,task,*,current=False):
        snap=task['input_snapshot']
        if task['task_type'] not in ('manuscript_draft','manuscript_docx') or task['workflow_version']!=WORKFLOW or digest(snap)!=task['input_digest'] or snap['project_id']!=task['project_id']: raise source_conflict()
        row=self.version(db,task['project_id'],snap['manuscript_id'],snap['revision'])
        if row['id']!=snap['manuscript_version_id'] or row['snapshot_sha256']!=snap['snapshot_sha256'] or row['snapshot_json']['output_language']!=snap['output_language']: raise source_conflict()
        if task['task_type']=='manuscript_draft' and row['task_id']!=task['id']: raise source_conflict()
        if task['task_type']=='manuscript_docx':
            export=db.execute('SELECT * FROM manuscript_exports WHERE id=%s AND version_id=%s AND task_id=%s',(snap['export_id'],row['id'],task['id'])).fetchone()
            if not export: raise source_conflict()
            self.verify_school_export(db,row,export,task,current=current)
            published=db.execute("SELECT status FROM tasks WHERE id=%s",(row['task_id'],)).fetchone()
            if published['status']!='succeeded': raise StorageError('task_revision_conflict','事实稿尚未发布。',409)
        if current:
            if task['task_type']=='manuscript_draft' and row['snapshot_json'].get('school_change_provenance'):
                from .school_changes import validate_school_change_version
                validate_school_change_version(self,db,row,current=True)
            if task['task_type']=='manuscript_draft' and not row['snapshot_json'].get('school_change_provenance') and row['snapshot_json'].get('thesis_context') and self.source_changes(row['project_id'],row['snapshot_json']): raise source_conflict()
            if task['task_type']=='manuscript_draft' and row['snapshot_json'].get('review_provenance'):
                from app.domain.manuscript_review.service import ReviewService
                reviews=ReviewService(self.assets)
                review=reviews.row(db,task['project_id'],row['manuscript_id'],row['snapshot_json']['review_provenance']['review_id'])
                reviews.assert_source_state(db,review)
            # Configuration/newer versions are surfaced separately; frozen actual bytes remain usable.
            for source in row['snapshot_json']['sources']:
                actual=read_source(self,task['project_id'],{k:source[k] for k in ('kind','id','file_id','role')})
                if actual!=source: raise source_conflict()
            if task['task_type']=='manuscript_draft' and row['snapshot_json'].get('citation_snapshot'):
                citation=row['snapshot_json']['citation_snapshot']
                _,original=self.citations.draft_row(db,task['project_id'],citation['draft_id'],citation['revision'])
                resolved=self.citations.resolve(db,task['project_id'],original['request_json'])
                if self.citations.current_changes(db,task['project_id'],citation) or any(citation[k]!=v for k,v in resolved.items()): raise source_conflict()
        return row

    def school_options(self,version,request):
        request=ExportRequest.model_validate(request) if isinstance(request,dict) else request
        request=request or ExportRequest()
        context=version['snapshot_json'].get('thesis_context')
        if not context:
            if 'school' in request.model_fields_set:
                raise StorageError('task_input_invalid','SCI导出不得携带学校配置。',422)
            return None
        options=(request.school or SchoolExportOptions()).model_dump(mode='json')
        chapters={c['id']:c for c in context['chapters']}
        for field,purpose in (('manual_chapters','manual'),('keywords','abstract')):
            if any(item['chapter_id'] not in chapters or chapters[item['chapter_id']]['purpose']!=purpose for item in options[field]):
                raise StorageError('task_input_invalid','人工正文和关键词只能对应冻结版指定用途章节。',422)
            # Ordering is semantic only through fixed chapter identities.
            options[field].sort(key=lambda item:list(chapters).index(item['chapter_id']))
        return options

    def school_analysis(self,db,version,*,current=True):
        from app.domain.school_templates.service import SchoolTemplateService
        context=version['snapshot_json']['thesis_context']
        schools=SchoolTemplateService(self.assets)
        template=schools.row(db,version['project_id'],context['template_version_id'])
        sources,task=schools.require_current(db,template) if current else schools.validate(db,template)
        if (task['status']!='succeeded' or sources!=context['source_files']
            or template['analysis_sha256']!=context['confirmation']['analysis_sha256']
            or digest(template['analysis_json'])!=template['analysis_sha256']):raise source_conflict()
        return template['analysis_json']

    def compile_school_intent(self,db,version,options):
        from .school_export import compile_school_export,validate_school_export
        plan=compile_school_export(version['snapshot_json'],self.school_analysis(db,version),options)
        validate_school_export(plan,version['snapshot_json'])
        if plan.get('options')!=options:raise source_conflict()
        return dict(schema_version=1,request=dict(school=options),plan=plan)

    def verify_school_export(self,db,version,export,task,*,current=False):
        intent=export.get('school_input_json');hashed=export.get('school_input_sha256')
        if task['input_digest']!=digest(task['input_snapshot']):raise source_conflict()
        if intent is None:
            if hashed is not None or 'school_input_sha256' in task['input_snapshot'] or version['snapshot_json'].get('thesis_context'):raise source_conflict()
            return None
        if (not version['snapshot_json'].get('thesis_context') or intent.get('schema_version')!=1
            or digest(intent)!=hashed or task['input_snapshot'].get('school_input_sha256')!=hashed):raise source_conflict()
        from .school_export import validate_school_export
        from pydantic import ValidationError
        try:
            options=self.school_options(version,ExportRequest.model_validate(intent['request']))
            if intent['request']!={'school':options} or intent['plan']['options']!=options:raise source_conflict()
            validate_school_export(intent['plan'],version['snapshot_json'])
        except (ValidationError,ValueError,KeyError,TypeError) as exc:raise source_conflict() from exc
        analysis=self.school_analysis(db,version,current=current)
        if intent['plan']['analysis_sha256']!=digest(analysis):raise source_conflict()
        if current:
            for source in version['snapshot_json']['sources']:
                if read_source(self,version['project_id'],{k:source[k] for k in ('kind','id','file_id','role')})!=source:raise source_conflict()
        return intent

    def preview_export(self,project,identity,revision,request=None):
        with self.store.connection() as db:
            version=self.version(db,project,identity,revision)
            options=self.school_options(version,request)
            if options is None:raise StorageError('task_input_invalid','此预览仅用于学校导出。',422)
            intent=self.compile_school_intent(db,version,options)
            return dict(schema_version=1,school=intent['plan'])

    def create_export(self,project,identity,revision,key,request=None):
        require_key(key)
        with self.store.connection(write=True) as db:
            self.root(db,project,identity);db.execute('SELECT id FROM manuscripts WHERE id=%s FOR UPDATE',(identity,)).fetchone()
            version=self.version(db,project,identity,revision)
            options=self.school_options(version,request)
            existing=db.execute('SELECT * FROM manuscript_exports WHERE version_id=%s AND idempotency_key=%s',(version['id'],key)).fetchone()
            if existing:
                sealed=existing.get('school_input_json')
                if (sealed is None)!=(options is None) or sealed is not None and sealed['request']!={'school':options}:
                    raise StorageError('task_idempotency_conflict','请求标识已用于不同导出输入。',409)
                export_id=existing['id'];status=200
            else:
                if self.store.require_task(db,version['task_id'])['status']!='succeeded': raise StorageError('task_revision_conflict','请等待事实稿发布后导出。',409)
                intent=self.compile_school_intent(db,version,options) if options is not None else None
                if intent is not None and not intent['plan']['report']['can_export']:
                    raise StorageError('task_input_invalid','学校导出存在必须修正的问题，请检查预览。',422)
                export_id=str(uuid4());snapshot=dict(project_id=project,manuscript_id=identity,manuscript_version_id=version['id'],revision=revision,
                    output_language=version['snapshot_json']['output_language'],workflow_version=WORKFLOW,snapshot_sha256=version['snapshot_sha256'],export_id=export_id)
                if intent is not None:snapshot['school_input_sha256']=digest(intent)
                task=self.task(db,project,'manuscript_docx',snapshot,'manuscript-export:'+export_id)
                db.execute('INSERT INTO manuscript_exports(id,version_id,task_id,idempotency_key,created_at,school_input_json,school_input_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                    (export_id,version['id'],task['id'],key,now(),Jsonb(intent) if intent is not None else None,digest(intent) if intent is not None else None));status=201
            return self.export_view(db,version,export_id),status

    def export_view(self,db,version,export_id):
        row=db.execute('SELECT * FROM manuscript_exports WHERE id=%s AND version_id=%s',(export_id,version['id'])).fetchone()
        if not row: raise missing()
        task=self.store.require_task(db,row['task_id']);metadata=row['metadata_json'] or {}
        intent=self.verify_school_export(db,version,row,task)
        school={}
        if intent is not None:
            saved=metadata.get('school')
            if task['status']=='succeeded' and (not saved or saved.get('plan')!=intent['plan'] or saved.get('report')!=intent['plan']['report']):raise source_conflict()
            if saved and saved.get('field_update',{}).get('status')!=('updated' if intent['plan']['toc']['enabled'] else 'not_requested'):raise source_conflict()
            school['school']=saved or dict(plan=intent['plan'],report=intent['plan']['report'],field_update=dict(status='pending'))
        return dict(id=row['id'],version_id=row['version_id'],task_id=row['task_id'],status=task['status'],pdf_status='not_requested',error_code=task.get('error_code'),
            filename=metadata.get('filename'),sha256=metadata.get('sha256'),size_bytes=metadata.get('size_bytes'),created_at=row['created_at'],
            download_url=f"/api/v1/projects/{version['project_id']}/manuscripts/{version['manuscript_id']}/exports/{export_id}/download" if metadata and task['status']=='succeeded' else None,**school)

    def exports(self,project,identity,revision):
        with self.store.connection() as db:
            version=self.version(db,project,identity,revision)
            rows=db.execute('SELECT id FROM manuscript_exports WHERE version_id=%s ORDER BY created_at DESC,id',(version['id'],)).fetchall()
            return dict(items=[self.export_view(db,version,r['id']) for r in rows],pdf_status='not_requested')

    def export(self,project,identity,export_id,download=False):
        with self.store.connection() as db:
            self.root(db,project,identity)
            version=db.execute('SELECT v.* FROM manuscript_versions v JOIN manuscript_exports e ON e.version_id=v.id WHERE e.id=%s AND v.manuscript_id=%s',(export_id,identity)).fetchone()
            if not version: raise missing()
            self.validate_version(db,version);view=self.export_view(db,version,export_id)
            if not download: return view
            row=db.execute('SELECT * FROM manuscript_exports WHERE id=%s',(export_id,)).fetchone()
            task=self.store.require_task(db,row['task_id']);self.verify_task(db,task,current=bool(version['snapshot_json'].get('thesis_context')))
            metadata=row['metadata_json']
            if not metadata or task['status']!='succeeded': raise StorageError('task_revision_conflict','导出尚未成功。',409)
            if metadata.get('input_sha256')!=version['snapshot_sha256']: raise source_conflict()
        try: raw=(self.directory/(export_id+'.docx')).read_bytes()
        except FileNotFoundError as exc: raise StorageError('report_missing','导出文件缺失。',410) from exc
        if len(raw)!=metadata['size_bytes'] or sha256(raw).hexdigest()!=metadata['sha256']: raise StorageError('report_changed','导出文件内容已变化。',409)
        return metadata,raw

    def recover(self,project,identity):
        from .execution import retry_in_transaction
        count=0;skipped=[]
        with self.store.connection(write=True) as db:
            self.root(db,project,identity)
            db.execute('SELECT id FROM manuscripts WHERE id=%s FOR UPDATE',(identity,)).fetchone()
            rows=db.execute("SELECT t.* FROM tasks t WHERE t.project_id=%s AND t.user_id=%s AND t.task_type IN ('manuscript_draft','manuscript_docx') AND t.status='failed' AND t.input_snapshot->>'manuscript_id'=%s ORDER BY t.created_at,t.id",(project,self.store.user_id,identity)).fetchall()
            for task in rows:
                if count>=20: break
                try:
                    retry_in_transaction(self.store,db,dict(task),task['revision'],assets=self.assets);count+=1
                except StorageError as exc:
                    if exc.status not in (404,409,410,422): raise
                    skipped.append(dict(task_id=task['id'],error_code=exc.code))
        return dict(requeued=count,skipped=skipped)

def input_version(task):
    return dict(kind='manuscript',manuscript_version_id=task['input_snapshot']['manuscript_version_id'],output_language=task['input_snapshot']['output_language'],workflow_version=WORKFLOW)
