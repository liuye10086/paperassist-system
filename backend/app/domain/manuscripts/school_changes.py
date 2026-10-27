"""Explicit, sealed school inputs publish through the existing manuscript engine."""
from copy import deepcopy
from hashlib import sha256
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from app.domain.school_templates.service import SchoolTemplateService
from .service import ManuscriptService,now
from .contracts import WORKFLOW
from .school import pending,school_content_report,validate_chapters
from .school_return import extract,apply_return,issue


def invalid(message,code='school_change_invalid',status=409):return StorageError(code,message,status)


class SchoolChangeService:
    def __init__(self,assets):
        self.assets=assets;self.manuscripts=ManuscriptService(assets);self.store=self.manuscripts.store;self.schools=SchoolTemplateService(assets)

    def base(self,db,project,identity,revision):
        self.schools.project(db,project)
        row=self.manuscripts.version(db,project,identity,revision)
        if not row['snapshot_json'].get('thesis_context'):raise invalid('仅学校稿支持此输入。',status=422)
        task=self.store.require_task(db,row['task_id'])
        if task['status']!='succeeded':raise invalid('父稿尚未发布。')
        return row

    def confirmation(self,db,project,identity):
        saved=db.execute('SELECT * FROM school_template_confirmations WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not saved:raise invalid('确认版本不存在。','not_found',404)
        template=self.schools.row(db,project,saved['template_version_id'])
        sources,task=self.schools.require_current(db,template)
        if task['status']!='succeeded':raise source_conflict()
        confirmation=self.schools.confirmation(db,template)
        return saved,template,sources,confirmation

    def document(self,project,request):
        from app.domain.documents.service import DocumentService
        service=DocumentService(self.assets)
        row=service.load(project,request['file_id'],request['document_version_id'],True)
        if row['input_snapshot']['kind']!='docx_document':raise invalid('回传仅支持DOCX。',status=422)
        raw=self.assets.original(row['input_snapshot']['file'])
        parsed,document=service.read(row)
        source=dict(file_id=request['file_id'],document_version_id=request['document_version_id'],base_export_id=request.get('base_export_id'),
            sha256=sha256(raw).hexdigest(),filename=row['input_snapshot']['file']['filename'])
        return source,raw,dict(manifest_sha256=digest(row['result_json']),parsed_sha256=sha256(parsed).hexdigest(),file=row['input_snapshot']['file']),document.model_dump()

    def register(self,project,identity,revision,request,key):
        require_key(key);body=request.model_dump(exclude_none=True)
        with self.store.connection(write=True) as db:
            self.schools.project(db,project,True)
            self.manuscripts.root(db,project,identity)
            replay=db.execute('SELECT * FROM manuscript_school_changes WHERE manuscript_id=%s AND idempotency_key=%s',(identity,key)).fetchone()
            if replay:
                if replay['request_digest']!=digest(body) or replay['input_json']['base_revision']!=revision:raise invalid('请求标识已用于不同输入。','task_idempotency_conflict')
                return self.view(db,replay),200
            base=self.base(db,project,identity,revision);snapshot=base['snapshot_json']
            frozen=dict(schema_version=1,base_revision=revision,base_snapshot_sha256=base['snapshot_sha256'],source={},target_context=deepcopy(snapshot['thesis_context']),issues=[])
            if request.kind=='template_migration':
                saved,template,sources,confirmation=self.confirmation(db,project,request.target_confirmation_id)
                context=frozen['target_context'];old={s['id']:s for s in context['chapters']};chapters=[]
                for c in confirmation['chapters']:
                    matching=old.get(c['id']) or next((s for s in old.values() if s['title']==c['title']),None)
                    chapters.append(deepcopy(c)|dict(purpose=matching['purpose'] if matching else 'other',output_language=matching['output_language'] if matching else snapshot['output_language'],result_group_ids=matching['result_group_ids'] if matching else []))
                context.update(template_version_id=template['id'],confirmation_id=saved['id'],confirmation_sha256=saved['snapshot_sha256'],confirmation=confirmation,source_files=sources,chapters=chapters)
                # Explicit migration uses the profile visible at registration, not future bindings.
                context['profile']=self.schools.profile_view(db,project)
                frozen['source']=dict(target_confirmation_id=saved['id'])
                inputs=[]
                for s in snapshot['sections']:
                    candidates=[c['id'] for c in chapters if c['id']==s['id']] or [c['id'] for c in chapters if c['title']==s['title']]
                    inputs.append(dict(id=s['id'],title=s['title'],paragraphs=[p['text'] for p in s['paragraphs']],suggested_chapter_id=candidates[0] if len(candidates)==1 else None,match_method='title' if len(candidates)==1 else 'ambiguous' if candidates else 'none',candidate_chapter_ids=candidates))
                frozen['sections']=inputs
            else:
                source,raw,parse,document=self.document(project,body);baseline_raw=None
                if request.base_export_id:
                    export=db.execute('SELECT * FROM manuscript_exports WHERE id=%s AND version_id=%s',(request.base_export_id,base['id'])).fetchone()
                    if not export:raise invalid('导出不属于选定父稿。','not_found',404)
                    metadata,baseline_raw=self.manuscripts.export(project,identity,request.base_export_id,True)
                    frozen['base_export_sha256']=sha256(baseline_raw).hexdigest()
                extracted=extract(raw,source['filename'],snapshot,baseline_raw,document=document)
                frozen.update(source=source,parse=parse,sections=extracted['sections'],issues=extracted['issues'],retained_nonbody=extracted['retained_nonbody'])
            change_id=str(uuid4())
            fields=dict(id=change_id,project_id=project,user_id=self.store.user_id,manuscript_id=identity,base_version_id=base['id'],kind=request.kind,
                target_confirmation_id=request.target_confirmation_id,file_id=request.file_id,document_version_id=request.document_version_id,base_export_id=request.base_export_id,
                idempotency_key=key,request_json=Jsonb(body),request_digest=digest(body),input_json=Jsonb(frozen),input_sha256=digest(frozen),created_at=now())
            db.execute('INSERT INTO manuscript_school_changes('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))
            return self.view(db,self.row(db,project,identity,change_id)),201

    def row(self,db,project,identity,change_id):
        self.manuscripts.root(db,project,identity)
        row=db.execute('SELECT * FROM manuscript_school_changes WHERE id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s',(change_id,identity,project,self.store.user_id)).fetchone()
        if not row:raise invalid('变更输入不存在。','not_found',404)
        self.validate(db,row)
        return row

    def validate(self,db,row):
        frozen=row['input_json']
        if digest(frozen)!=row['input_sha256'] or digest(row['request_json'])!=row['request_digest']:raise source_conflict()
        if row['kind']!=row['request_json']['kind']:raise source_conflict()
        for key in ('target_confirmation_id','file_id','document_version_id','base_export_id'):
            if row[key]!=row['request_json'].get(key):raise source_conflict()
        base=db.execute('SELECT * FROM manuscript_versions WHERE id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s',(row['base_version_id'],row['manuscript_id'],row['project_id'],row['user_id'])).fetchone()
        if not base or base['revision']!=frozen['base_revision'] or base['snapshot_sha256']!=frozen['base_snapshot_sha256'] or digest(base['snapshot_json'])!=base['snapshot_sha256']:raise source_conflict()
        if row['adopted_revision'] is not None:
            if digest(row['adopt_json'])!=row['adopt_sha256'] or digest(row['candidate_json'])!=row['candidate_sha256']:raise source_conflict()
        return base

    def assert_current(self,db,row,base):
        frozen=row['input_json'];context=frozen['target_context']
        template=self.schools.row(db,row['project_id'],context['template_version_id']);self.schools.require_current(db,template)
        if self.schools.confirmation(db,template)!=context['confirmation']:raise source_conflict()
        from .sources import read_source
        for source in base['snapshot_json']['sources']:
            if read_source(self.manuscripts,row['project_id'],{k:source[k] for k in ('kind','id','file_id','role')})!=source:raise source_conflict()
        citation=base['snapshot_json'].get('citation_snapshot')
        if citation and self.manuscripts.citations.current_changes(db,row['project_id'],citation):raise source_conflict()
        if row['kind']=='docx_return':
            source,raw,parse,_=self.document(row['project_id'],row['request_json'])
            if source!=frozen['source'] or parse!=frozen['parse']:raise source_conflict()

    def candidate(self,db,row,mappings):
        base=self.validate(db,row);frozen=row['input_json'];snapshot=deepcopy(base['snapshot_json']);problems=deepcopy(frozen['issues']);differences=[]
        ids={s['id'] for s in frozen['sections']};targets={c['id'] for c in frozen['target_context']['chapters']}
        valid=(len({m['input_section_id'] for m in mappings})==len(mappings) and len({m['chapter_id'] for m in mappings})==len(mappings)
            and {m['input_section_id'] for m in mappings}==ids and all(m['chapter_id'] in targets for m in mappings))
        if not valid:problems.append(issue('mapping_required','每个输入章节必须明确且唯一分配到固定学校章节；不能丢弃未分配内容。'))
        for section in frozen['sections']:
            if section['id'] not in {m['input_section_id'] for m in mappings}:
                differences.append(dict(kind='chapter_removed' if row['kind']=='template_migration' else 'chapter_added',location=section['id'],message='此输入章节尚未分配，须明确匹配。',before=section['title'] if row['kind']=='template_migration' else '',after=section['title'] if row['kind']=='docx_return' else ''))
        try:self.assert_current(db,row,base)
        except StorageError as exc:
            if exc.code in ('storage_unavailable','database_configuration'):raise
            problems.append(issue('source_changed','固定输入、父稿研究来源或学校模板来源已变化。'))
        if valid and row['kind']=='template_migration':
            snapshot['thesis_context']=deepcopy(frozen['target_context']);old={s['id']:s for s in snapshot['sections']};assigned={m['chapter_id']:old[m['input_section_id']] for m in mappings};sections=[]
            for c in snapshot['thesis_context']['chapters']:
                original=assigned.get(c['id'])
                if original:
                    if c['title']!=original['title']:differences.append(dict(kind='template_changed',location=c['id'],message='学校章节标题改变。',before=original['title'],after=c['title']))
                    if c['level']!=original['level']:differences.append(dict(kind='template_changed',location=c['id'],message='学校章节层级改变。',before=str(original['level']),after=str(c['level'])))
                    c.update(purpose=original['purpose'],output_language=original['output_language'],result_group_ids=original['result_group_ids'])
                    section=deepcopy(c)|dict(paragraphs=deepcopy(original['paragraphs']))
                else:
                    c['result_group_ids']=[]
                    section=deepcopy(c)|dict(paragraphs=[pending(c)])
                    differences.append(dict(kind='chapter_added',location=c['id'],message='新增学校章节，正文待补充。',before='',after=c['title']))
                sections.append(section)
            old_order=[s['id'] for s in base['snapshot_json']['sections']]
            new_order=[assigned[c['id']]['id'] for c in snapshot['thesis_context']['chapters'] if c['id'] in assigned]
            if old_order!=new_order: differences.append(dict(kind='template_changed',location='chapter_order',message='学校章节顺序改变。',before=' → '.join(s['title'] for s in base['snapshot_json']['sections']),after=' → '.join(s['title'] for s in sections)))
            snapshot['sections']=sections
            differences.append(dict(kind='template_changed',location='school',message='显式采用新学校确认，父稿保持原样。',before=base['snapshot_json']['thesis_context']['confirmation_id'],after=snapshot['thesis_context']['confirmation_id']))
        elif valid:
            snapshot,differences,new_problems=apply_return(snapshot,frozen['sections'],mappings);problems.extend(new_problems)
        # This is a new source kind, never a review or model-writing candidate.
        if snapshot.get('review'):
            snapshot.setdefault('review_history',[]).append(dict(provenance=deepcopy(snapshot.get('review_provenance',{})),review=deepcopy(snapshot['review']),applies_to_current_text=False,status='historical_requires_recheck'))
        for key in ('review_provenance','writing_provenance','review','school_change_provenance'):snapshot.pop(key,None)
        if valid:
            try:validate_chapters(snapshot['thesis_context'],{g['id'] for g in snapshot['results_groups']})
            except ValueError:problems.append(issue('chapter_mapping_invalid','目标学校章节及结果组分配不一致，不能采用。'))
            report=school_content_report(snapshot);snapshot['school_content_report']=report
            for item in report['issues']:
                if item['severity']=='error':problems.append(issue('manuscript_check',item['message'],item.get('location','')))
        for p in problems:
            if p['code'] in ('illustration_changed','citation_changed') and not any(d['kind']==p['code'] for d in differences):differences.append(dict(kind=p['code'],location=p['location'],message=p['message'],before='',after=''))
        return snapshot,differences,problems

    def view(self,db,row,mappings=None):
        frozen=row['input_json']
        if mappings is None:mappings=[dict(input_section_id=s['id'],chapter_id=s['suggested_chapter_id']) for s in frozen['sections'] if s['suggested_chapter_id']]
        snapshot,differences,problems=self.candidate(db,row,mappings)
        preview=digest(dict(input_sha256=row['input_sha256'],mappings=mappings,candidate_sha256=digest(snapshot),differences=differences,issues=problems))
        return dict(id=row['id'],kind=row['kind'],manuscript_id=row['manuscript_id'],base_version_id=row['base_version_id'],base_revision=frozen['base_revision'],created_at=row['created_at'].isoformat(),
            input_sha256=row['input_sha256'],source=frozen['source'],original_download_url=f"/api/v1/projects/{row['project_id']}/files/{row['file_id']}/download" if row['file_id'] else None,
            input_sections=[{k:v for k,v in s.items() if k!='paragraph_items'} for s in frozen['sections']],target_chapters=frozen['target_context']['chapters'],
            mappings=mappings,differences=differences,issues=problems,can_adopt=not any(p['severity']=='error' for p in problems),preview_sha256=preview,adopted_revision=row['adopted_revision'])

    def get(self,project,identity,change_id,request=None):
        with self.store.connection() as db:return self.view(db,self.row(db,project,identity,change_id),[m.model_dump() for m in request.mappings] if request else None)

    def list(self,project,identity):
        with self.store.connection() as db:
            self.manuscripts.root(db,project,identity)
            rows=db.execute('SELECT * FROM manuscript_school_changes WHERE manuscript_id=%s ORDER BY created_at DESC,id',(identity,)).fetchall()
            return dict(items=[self.view(db,self.row(db,project,identity,r['id'])) for r in rows])

    def adopt(self,project,identity,change_id,request,key):
        require_key(key);body=request.model_dump();mappings=body['mappings']
        with self.store.connection(write=True) as db:
            self.schools.project(db,project,True);root=self.manuscripts.root(db,project,identity);row=self.row(db,project,identity,change_id)
            if row['adopted_revision'] is not None:
                if row['adopt_key']!=key or row['adopt_sha256']!=digest(body):raise invalid('此输入已采用，不能再次覆盖。','task_idempotency_conflict')
                status=200
            else:
                if request.expected_revision!=root['current_revision']:raise invalid('稿件已有新版本，请刷新。','manuscript_revision_conflict')
                if db.execute('SELECT id FROM manuscript_versions WHERE manuscript_id=%s AND idempotency_key=%s',(identity,key)).fetchone():raise invalid('采用请求标识已使用。','task_idempotency_conflict')
                view=self.view(db,row,mappings)
                if view['preview_sha256']!=request.preview_sha256:raise invalid('差异预览已变化，请重新查看。','school_change_preview_conflict')
                if not view['can_adopt']:raise invalid('输入仍有硬错误；已保留本次输入及原稿。','school_change_blocked')
                base=self.validate(db,row);self.assert_current(db,row,base);snapshot,_,_=self.candidate(db,row,mappings)
                revision=root['current_revision']+1;version_id=str(uuid4());timestamp=now();context=snapshot['thesis_context']
                provenance=dict(schema_version=1,change_id=row['id'],kind=row['kind'],base_version_id=base['id'],base_revision=base['revision'],input_sha256=row['input_sha256'],source=deepcopy(row['input_json']['source']),mappings=mappings,preview_sha256=view['preview_sha256'])
                snapshot['school_change_provenance']=provenance
                request_json=deepcopy(base['request_json']);request_json['expected_revision']=revision-1
                request_json['thesis']=dict(confirmation_id=context['confirmation_id'],profile_revision=context['profile']['revision'],chapter_mappings=[dict(chapter_id=c['id'],purpose=c['purpose'],output_language=c['output_language'],result_group_ids=c['result_group_ids']) for c in context['chapters']])
                task=self.manuscripts.task(db,project,'manuscript_draft',dict(project_id=project,manuscript_id=identity,manuscript_version_id=version_id,revision=revision,output_language=snapshot['output_language'],workflow_version=WORKFLOW,snapshot_sha256=digest(snapshot)),'manuscript:'+version_id,validated_sources=snapshot['sources'])
                from app.domain.admin_configuration.rule_consumption import inherit_task
                inherit_task(db,task,confirmation_id=context['confirmation_id'])
                fields=dict(id=version_id,project_id=project,user_id=self.store.user_id,idempotency_key=key,request_json=Jsonb(request_json),request_digest=digest(request_json),manuscript_id=identity,revision=revision,parent_version_id=base['id'],task_id=task['id'],snapshot_json=Jsonb(snapshot),snapshot_sha256=digest(snapshot),created_at=timestamp,school_confirmation_id=context['confirmation_id'])
                db.execute('INSERT INTO manuscript_versions('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))
                for table in ('manuscript_sources','manuscript_citations'):
                    for original in db.execute('SELECT * FROM '+table+' WHERE version_id=%s',(base['id'],)).fetchall():
                        values=dict(original);values.update(id=str(uuid4()),version_id=version_id);values={k:Jsonb(v) if isinstance(v,(dict,list)) else v for k,v in values.items()}
                        db.execute('INSERT INTO '+table+'('+','.join(values)+') VALUES ('+','.join(['%s']*len(values))+')',tuple(values.values()))
                db.execute('UPDATE manuscripts SET current_revision=%s,updated_at=%s WHERE id=%s',(revision,timestamp,identity))
                db.execute('UPDATE manuscript_school_changes SET adopted_revision=%s,adopt_key=%s,adopt_json=%s,adopt_sha256=%s,candidate_json=%s,candidate_sha256=%s WHERE id=%s',(revision,key,Jsonb(body),digest(body),Jsonb(snapshot),digest(snapshot),row['id']))
                status=201
        return self.manuscripts.get(project,identity),status


def validate_school_change_version(manuscripts,db,version,current=False):
    provenance=version['snapshot_json']['school_change_provenance'];service=SchoolChangeService(manuscripts.assets)
    row=service.row(db,version['project_id'],version['manuscript_id'],provenance.get('change_id'))
    base=service.validate(db,row)
    if (row['adopted_revision']!=version['revision'] or row['candidate_json']!=version['snapshot_json'] or row['candidate_sha256']!=version['snapshot_sha256']
        or row['base_version_id']!=version['parent_version_id'] or provenance['input_sha256']!=row['input_sha256'] or provenance['mappings']!=row['adopt_json']['mappings']
        or provenance['preview_sha256']!=row['adopt_json']['preview_sha256'] or provenance['source']!=row['input_json']['source'] or provenance['kind']!=row['kind']
        or provenance['base_revision']!=base['revision'] or provenance['base_version_id']!=base['id']):raise source_conflict()
    if current:service.assert_current(db,row,base)
