"""Bounded DOCX returns reuse the common parser, matcher and manuscript producer."""
from copy import deepcopy
from hashlib import sha256
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.journals.display import synthetic_input
from app.domain.journals.service import now
from app.domain.literature.service import digest
from app.domain.manuscripts.school_changes import SchoolChangeService
from app.domain.manuscripts.school_return import extract, apply_return, issue
from app.domain.manuscripts.service import ManuscriptService
from app.domain.manuscript_writing.context import normalize_sections
from .return_contracts import RegisterReturn
from .service import ReviewRoundService


def invalid(message, code='review_return_invalid', status=422):
    return StorageError(code, message, status)


def return_base(snapshot):
    """SCI supplies fixed semantic headings to the existing school matcher."""
    result = deepcopy(snapshot)
    sections = normalize_sections(snapshot)
    if not snapshot.get('thesis_context'):
        from app.domain.journals.display import context
        names = context(snapshot)['names']
        sections = [dict(s, title=names[s['id']], purpose=s.get('purpose', s['id'])) for s in sections if s['id']!='title']
    result['sections'] = sections
    return result


def apply_supported_return(base, inputs, mappings):
    candidate, differences, problems = apply_return(base, inputs, mappings)
    # A changed statement is a new, unreviewed user paragraph. Its original
    # decision remains on the fixed parent, never on the new statement.
    for problem in problems:
        if problem['code']=='bound_claim_changed':
            problem['severity']='warning'
    return candidate, differences, problems


def add_provenance(candidate, row, body, preview_sha256):
    result=deepcopy(candidate)
    result['user_return_provenance']=dict(
        schema_version=1, return_id=row['id'], previous_round_id=row['previous_round_id'],
        revision_id=row['revision_id'], base_version_id=row['base_version_id'],
        input_sha256=row['snapshot_sha256'], source=deepcopy(row['snapshot_json']['source']),
        mappings=body['mappings'], preview_sha256=preview_sha256,
    )
    return result


class ReviewReturnService(ReviewRoundService):
    def __init__(self, assets):
        super().__init__(assets)
        self.manuscripts=ManuscriptService(assets)
        self.documents=SchoolChangeService(assets)

    def selected_base(self, db, project, previous, selection, revision_id=None):
        if selection.id!=previous['snapshot_json']['manuscript']['id']:
            raise invalid('回传父稿必须属于明确选定的上一轮稿件。')
        base=self.manuscript(db,project,selection.id,selection.revision)
        if base['id']!=selection.version_id:
            raise source_conflict()
        if revision_id:
            from .revisions import RevisionService
            revisions=RevisionService(self.assets)
            run=revisions.revision_row(db,project,revision_id)
            task=self.store.require_task(db,run['task_id'])
            if run['round_id']!=previous['id'] or task['status']!='succeeded' or not run['result_json']:
                raise invalid('必须明确选择上一轮已成功保存的实际修改结果。')
            if run['output_version_id']!=base['id']:
                raise invalid('实际修改结果与明确选择的公共父稿不匹配。')
        return base

    def register(self, project, previous_id, request, key):
        require_key(key)
        body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.project(db,project,True)
            previous=self.round_row(db,project,previous_id)
            old=db.execute('SELECT * FROM review_round_user_returns WHERE project_id=%s AND user_id=%s AND idempotency_key=%s',(project,self.store.user_id,key)).fetchone()
            if old:
                if old['request_digest']!=digest(body) or old['previous_round_id']!=previous_id:
                    raise invalid('请求标识已用于不同回传。','task_idempotency_conflict',409)
                return self.view_return(db,self.return_row(db,project,old['id'])),200
            base=self.selected_base(db,project,previous,request.manuscript,request.revision_id)
            source,raw,parse,document=self.documents.document(project,body)
            baseline=None
            if request.base_export_id:
                saved=db.execute('SELECT id FROM manuscript_exports WHERE id=%s AND version_id=%s',(request.base_export_id,base['id'])).fetchone()
                if not saved:
                    raise invalid('固定导出不属于明确选定的公共父稿。')
                _,baseline=self.manuscripts.export(project,base['manuscript_id'],request.base_export_id,True)
            extracted=extract(raw,source['filename'],return_base(base['snapshot_json']),baseline,
                              document=document,known_headings_only=not bool(base['snapshot_json'].get('thesis_context')))
            identity=str(uuid4())
            frozen=dict(id=identity,project_id=project,schema_version=1,previous_round_id=previous_id,revision_id=request.revision_id,
                        manuscript=dict(id=base['manuscript_id'],revision=base['revision'],version_id=base['id'],sha256=base['snapshot_sha256']),
                        source=source,parse=parse,base_export_sha256=sha256(baseline).hexdigest() if baseline else None,
                        sections=extracted['sections'],issues=extracted['issues'],retained_nonbody=extracted['retained_nonbody'],
                        synthetic=bool(request.synthetic or previous['snapshot_json']['synthetic'] or synthetic_input(base['snapshot_json'])),
                        real_model_calls=False,real_network_calls=False)
            fields=dict(id=identity,project_id=project,user_id=self.store.user_id,idempotency_key=key,
                        request_json=Jsonb(body),request_digest=digest(body),snapshot_json=Jsonb(frozen),snapshot_sha256=digest(frozen),created_at=now(),
                        previous_round_id=previous_id,revision_id=request.revision_id,manuscript_id=base['manuscript_id'],base_version_id=base['id'],
                        file_id=request.file_id,document_version_id=request.document_version_id,base_export_id=request.base_export_id)
            db.execute('INSERT INTO review_round_user_returns('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))
            return self.view_return(db,self.return_row(db,project,identity)),201

    def return_row(self, db, project, identity, *, lock=False):
        self.project(db,project)
        row=db.execute('SELECT * FROM review_round_user_returns WHERE id=%s AND project_id=%s AND user_id=%s'+(' FOR UPDATE' if lock else ''),(identity,project,self.store.user_id)).fetchone()
        if not row:
            raise StorageError('not_found','用户回传不存在。',404)
        self.validate_return(db,row)
        return row

    def validate_return(self, db, row, *, current=False,_review_candidate=None):
        self.validate(row)
        request=RegisterReturn.model_validate(row['request_json'])
        frozen=row['snapshot_json']
        previous=self.round_row(db,row['project_id'],row['previous_round_id'])
        base=self.selected_base(db,row['project_id'],previous,request.manuscript,request.revision_id)
        if (frozen.get('schema_version')!=1 or frozen['previous_round_id']!=row['previous_round_id']
            or frozen['revision_id']!=row['revision_id'] or frozen['manuscript']!=dict(id=base['manuscript_id'],revision=base['revision'],version_id=base['id'],sha256=base['snapshot_sha256'])
            or row['base_version_id']!=base['id'] or row['manuscript_id']!=base['manuscript_id']
            or any(row[k]!=row['request_json'].get(k) for k in ('revision_id','file_id','document_version_id','base_export_id'))
            or frozen.get('real_model_calls') is not False or frozen.get('real_network_calls') is not False):
            raise source_conflict()
        if row['output_version_id']:
            if digest(row['adopt_json'])!=row['adopt_sha256'] or digest(row['candidate_json'])!=row['candidate_sha256']:
                raise source_conflict()
        if current:
            source,raw,parse,_=self.documents.document(row['project_id'],row['request_json'])
            if source!=frozen['source'] or parse!=frozen['parse']:
                raise source_conflict()
            if row['base_export_id']:
                _,baseline=self.manuscripts.export(row['project_id'],row['manuscript_id'],row['base_export_id'],True)
                if sha256(baseline).hexdigest()!=frozen['base_export_sha256']:
                    raise source_conflict()
            self.manuscripts.verify_task(db,self.store.require_task(db,base['task_id']),current=True,_review_candidate=_review_candidate)
        return base

    def candidate(self, db, row, mappings):
        base=self.validate_return(db,row)
        frozen=row['snapshot_json']
        snapshot=deepcopy(base['snapshot_json'])
        working=return_base(snapshot)
        inputs=frozen['sections']
        problems=deepcopy(frozen['issues'])
        differences=[]
        input_ids={s['id'] for s in inputs}
        target_ids={s['id'] for s in working['sections']}
        valid=(len(mappings)==len(input_ids)==len(target_ids)
               and {m['input_section_id'] for m in mappings}==input_ids
               and {m['chapter_id'] for m in mappings}==target_ids)
        if not valid:
            problems.append(issue('mapping_required','每个输入段落章节与父稿章节必须完整、唯一匹配；不能丢弃歧义或额外正文。'))
        if valid:
            working,differences,new_problems=apply_supported_return(working,inputs,mappings)
            problems.extend(new_problems)
            updated={s['id']:s for s in working['sections']}
            snapshot['sections']=[dict(s,paragraphs=deepcopy(updated[s['id']]['paragraphs'])) if s['id'] in updated else s for s in normalize_sections(snapshot)]
            if not differences:
                problems.append(issue('no_changes','未发现受支持正文变化，无需重复生成相同稿件。'))
        for problem in problems:
            if problem['code'] in ('illustration_changed','citation_changed') and not any(d['kind']==problem['code'] for d in differences):
                differences.append(dict(kind=problem['code'],location=problem['location'],message=problem['message'],before='',after=''))
        if snapshot.get('review'):
            snapshot.setdefault('review_history',[]).append(dict(review=deepcopy(snapshot['review']),provenance=deepcopy(snapshot.get('review_provenance',{})),applies_to_current_text=False,status='historical_requires_recheck'))
        for name in ('user_return_provenance','review_revision_provenance','review_provenance','writing_provenance','school_change_provenance','journal_adaptation_provenance','review'):
            snapshot.pop(name,None)
        snapshot['synthetic']=bool(frozen['synthetic'])
        return snapshot,differences,problems

    def preview_data(self, db, row, mappings):
        snapshot,differences,problems=self.candidate(db,row,mappings)
        preview=digest(dict(input_sha256=row['snapshot_sha256'],mappings=mappings,candidate_sha256=digest(snapshot),differences=differences,issues=problems))
        return snapshot,differences,problems,preview

    def view_return(self, db, row, mappings=None):
        frozen=row['snapshot_json']
        if mappings is None:
            mappings=row['adopt_json']['mappings'] if row['adopt_json'] else [dict(input_section_id=s['id'],chapter_id=s['suggested_chapter_id']) for s in frozen['sections'] if s.get('suggested_chapter_id')]
        _,differences,problems,preview=self.preview_data(db,row,mappings)
        output=None
        if row['output_version_id']:
            version=db.execute('SELECT * FROM manuscript_versions WHERE id=%s',(row['output_version_id'],)).fetchone()
            self.manuscripts.validate_version(db,version)
            task=self.store.require_task(db,version['task_id'])
            output=dict(manuscript_id=version['manuscript_id'],version_id=version['id'],revision=version['revision'],parent_version_id=version['parent_version_id'],task_id=task['id'],status='published' if task['status']=='succeeded' else 'failed' if task['status']=='failed' else 'pending')
        return dict(id=row['id'],previous_round_id=row['previous_round_id'],revision_id=row['revision_id'],synthetic=frozen['synthetic'],
                    manuscript_id=row['manuscript_id'],base_version_id=row['base_version_id'],base_revision=frozen['manuscript']['revision'],
                    source=frozen['source'],original_download_url=f"/api/v1/projects/{row['project_id']}/files/{row['file_id']}/download",
                    input_sections=[{k:v for k,v in s.items() if k!='paragraph_items'} for s in frozen['sections']],
                    target_chapters=[dict(id=s['id'],title=s['title']) for s in return_base(self.validate_return(db,row)['snapshot_json'])['sections']],
                    mappings=mappings,differences=differences,issues=problems,can_adopt=not any(p['severity']=='error' for p in problems),
                    preview_sha256=preview,output=output,created_at=row['created_at'])

    def get(self, project, identity, request=None):
        with self.store.connection() as db:
            return self.view_return(db,self.return_row(db,project,identity),[m.model_dump() for m in request.mappings] if request else None)

    def adopt(self, project, identity, request, key):
        require_key(key)
        body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.project(db,project,True)
            row=self.return_row(db,project,identity,lock=True)
            if row['output_version_id']:
                if row['adopt_key']!=key or row['adopt_sha256']!=digest(body):
                    raise invalid('此回传已采用，不能覆盖已保存稿件。','task_idempotency_conflict',409)
                return self.view_return(db,row),200
            db.execute('SELECT id FROM manuscripts WHERE id=%s FOR UPDATE',(row['manuscript_id'],)).fetchone()
            root=self.manuscripts.root(db,project,row['manuscript_id'])
            if root['current_revision']!=request.expected_current_revision:
                raise invalid('稿件已有新版本，请刷新后明确采用。','manuscript_revision_conflict',409)
            candidate,_,problems,preview=self.preview_data(db,row,body['mappings'])
            if preview!=request.preview_sha256:
                raise invalid('差异预览已变化，请重新查看。','review_return_preview_conflict',409)
            if any(p['severity']=='error' for p in problems):
                raise invalid('回传仍有未解决的受保护内容或匹配问题；原稿与输入均已保留。','review_return_blocked',409)
            base=self.validate_return(db,row,current=True)
            candidate=add_provenance(candidate,row,body,preview)
            output=self.manuscripts.publish_user_return(db,base,candidate,row,body,key)
            db.execute('UPDATE review_round_user_returns SET output_version_id=%s,adopt_key=%s,adopt_json=%s,adopt_sha256=%s,candidate_json=%s,candidate_sha256=%s WHERE id=%s',
                       (output['version_id'],key,Jsonb(body),digest(body),Jsonb(candidate),digest(candidate),row['id']))
            return self.view_return(db,self.return_row(db,project,identity)),201


def validate_user_return_version(manuscripts, db, version, *, current=False,_review_candidate=None):
    provenance=version['snapshot_json']['user_return_provenance']
    service=ReviewReturnService(manuscripts.assets)
    row=service.return_row(db,version['project_id'],provenance.get('return_id'))
    base=service.validate_return(db,row,current=current,_review_candidate=_review_candidate)
    if not row['output_version_id'] or row['output_version_id']!=version['id']:
        raise source_conflict()
    candidate,_,problems,preview=service.preview_data(db,row,row['adopt_json']['mappings'])
    expected=add_provenance(candidate,row,row['adopt_json'],preview)
    if (any(p['severity']=='error' for p in problems) or preview!=row['adopt_json']['preview_sha256']
        or expected!=version['snapshot_json'] or row['candidate_json']!=expected
        or row['candidate_sha256']!=version['snapshot_sha256'] or version['parent_version_id']!=base['id']):
        raise source_conflict()


def user_return_writing_context(manuscripts,db,project,identity,snapshot,*,check_version=2):
    """Keep only exact parent artifacts; new user statements gain no authority."""
    from app.domain.manuscript_review.writing_context import load_writing_context,WritingCheckContext
    service=ReviewReturnService(manuscripts.assets)
    row=service.return_row(db,project,snapshot['user_return_provenance']['return_id'])
    if row['manuscript_id']!=identity or not row['output_version_id'] or row['candidate_json']!=snapshot:
        raise source_conflict()
    version=db.execute('SELECT * FROM manuscript_versions WHERE id=%s',(row['output_version_id'],)).fetchone()
    manuscripts.validate_version(db,version)
    base=service.validate_return(db,row)
    authority=load_writing_context(manuscripts,db,project,identity,base['snapshot_json'],check_version=check_version)
    if authority is None:
        return None
    current={p['id']:p for s in normalize_sections(snapshot) for p in s['paragraphs']}
    paragraphs={pid:deepcopy(saved) for pid,saved in authority.paragraphs.items() if current.get(pid)==saved['paragraph']}
    return WritingCheckContext(paragraphs=paragraphs,sources=deepcopy(authority.sources),tables=deepcopy(authority.tables),check_version=check_version)
