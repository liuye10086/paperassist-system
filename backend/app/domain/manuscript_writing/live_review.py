"""Immutable manual science artifacts and a fail-closed language publication seam."""
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from app.domain.literature_evidence.service import request_data
from app.domain.manuscripts.service import now
from .service import WritingService
from .authorization import LiveWritingService
from .live_review_contracts import ScientificReviewRequest
from .live_review_candidate import body_digest,claim_context,prepare,citation_body,finish,target_ids
from .context import WritingCitationScopeError
from .numeric_review import NUMERIC_VERSION,validation_version

def require_language_review(db,service,project,review,request=None,*,for_admission=False):
    from .language_service import LanguageReviewService
    if request is None or not request.language_review_id or not request.language_review_sha256:
        raise StorageError('manuscript_writing_language_required','审后候选尚未完成全文语言核验。',409)
    languages=LanguageReviewService(service.assets)
    row=languages.language_row(db,project,review['manuscript_id'],review['request_id'],request.language_review_id,for_admission=for_admission)
    if row['review_id']!=review['id'] or row['review_sha256']!=review['review_sha256'] or row['artifact_sha256']!=request.language_review_sha256: raise source_conflict()
    return row['candidate_json']


def invalid(exc):
    return StorageError('manuscript_writing_review_invalid','科学审核缺失、文本不匹配、数值未绑定或非目标内容发生变化。',422)

def artifact_sha(request_id,raw_sha,body,candidate,report):
    return digest(dict(request_id=request_id,candidate_sha256=raw_sha,request=body,candidate=candidate,report=report))

class LiveReviewService:
    def __init__(self,assets):
        self.assets=assets;self.writing=WritingService(assets);self.store=self.writing.store
        self.manuscripts=self.writing.manuscripts;self.citations=self.manuscripts.citations

    def raw(self,db,project,identity,request_id):
        row,task=self.writing.row(db,project,identity,request_id)
        if task['input_snapshot']['schema_version']!=2 or task['status']!='succeeded' or row['candidate_json'] is None:
            raise StorageError('manuscript_writing_review_required','需要成功的v2原始候选。',409)
        return row,task

    def context(self,project,identity,request_id):
        with self.store.connection() as db:
            row,task=self.raw(db,project,identity,request_id);snap=task['input_snapshot']
            bundle=LiveWritingService(self.assets).bundle(db,project,snap['execution']['bundle_id'])
            reviews=db.execute('SELECT id FROM manuscript_writing_reviews WHERE request_id=%s ORDER BY created_at,id',(request_id,)).fetchall()
            return dict(schema_version=2,request_id=request_id,candidate=row['candidate_json'],candidate_sha256=row['candidate_sha256'],
                body_sha256=body_digest(row['candidate_json']),required_paragraph_ids=sorted(target_ids(row['candidate_json'],snap)),
                claim_contexts={pid:claim_context(request_id,row['candidate_sha256'],pid) for pid in target_ids(row['candidate_json'],snap)},
                local_manifest=bundle['local_manifest'],base_revision=snap['input']['base_revision'],
                reviews=[self.view(self.row(db,project,identity,request_id,r['id'])) for r in reviews],language_status='pending')

    def resolve_claim(self,db,project,request_id,raw_sha,decision,text,language):
        claim=decision['claim'];_,version=self.citations.evidence.claim_row(db,project,claim['claim_id'],claim['claim_revision'],current=True)
        if (version['content']!=text or version['output_language']!=language or
            version['context']!=claim_context(request_id,raw_sha,decision['paragraph_id'])):
            raise ValueError('New exact claim and candidate-bound context required')
        bindings=[self.citations.resolve_binding(db,project,version,b) for b in claim['bindings']]
        if len({b['project_reference_id'] for b in bindings})!=len(bindings): raise ValueError('Duplicate reference')
        return dict(kind='claim',claim_id=claim['claim_id'],claim_revision=claim['claim_revision'],text=text,bindings=bindings)

    def row(self,db,project,identity,request_id,review_id):
        self.manuscripts.root(db,project,identity)
        row=db.execute('SELECT * FROM manuscript_writing_reviews WHERE id=%s AND request_id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s',
            (review_id,request_id,identity,project,self.store.user_id)).fetchone()
        if not row: raise StorageError('task_not_found','审后版本不存在。',404)
        body=request_data(ScientificReviewRequest,row['request_json'])
        if (body!=row['request_json'] or digest(body)!=row['request_digest'] or row['candidate_sha256']!=body['candidate_sha256']
            or digest(row['reviewed_candidate_json'])!=row['reviewed_candidate_sha256']
            or row['review_sha256']!=artifact_sha(request_id,row['candidate_sha256'],body,row['reviewed_candidate_json'],row['report_json'])
            or row['reviewed_candidate_json']['writing_provenance']['review_id']!=row['id']): raise source_conflict()
        return row

    def view(self,row):
        return dict(id=row['id'],request_id=row['request_id'],candidate_sha256=row['candidate_sha256'],review_sha256=row['review_sha256'],
            reviewed_candidate_sha256=row['reviewed_candidate_sha256'],candidate=row['reviewed_candidate_json'],report=row['report_json'],
            request=row['request_json'],decided_by=row['user_id'],created_at=row['created_at'].isoformat())

    def get(self,project,identity,request_id,review_id):
        with self.store.connection() as db:
            row=self.row(db,project,identity,request_id,review_id)
            self.validate_frozen(db,project,identity,request_id,row)
            return self.view(row)

    def validate_frozen(self,db,project,identity,request_id,review,*,strict_numeric=False,seen=None):
        """Reconstruct historical science without inheriting today's support decisions."""
        raw,task=self.raw(db,project,identity,request_id);snap=task['input_snapshot']
        if raw['candidate_sha256']!=review['candidate_sha256'] or raw['base_version_id']!=review['base_version_id']: raise source_conflict()
        bundle=LiveWritingService(self.assets).bundle(db,project,snap['execution']['bundle_id'])
        citation=review['reviewed_candidate_json']['citation_snapshot']
        fragments={p['id']:p['fragments'] for p in citation['paragraphs']} if citation else {}
        if citation:
            _,saved=self.citations.draft_row(db,project,citation['draft_id'],citation['revision'])
            if saved['snapshot_json']!=citation: raise source_conflict()
        def frozen_claim(decision,text):
            parts=fragments.get('p_'+digest(decision['paragraph_id']),[])
            if len(parts)!=1 or parts[0]['kind']!='claim': raise source_conflict()
            part=parts[0];claim=decision['claim']
            if any(part[k]!=claim[k] for k in ('claim_id','claim_revision')) or [{k:b[k] for k in ('review_id','metadata_version_id')} for b in part['bindings']]!=claim['bindings']: raise source_conflict()
            _,version=self.citations.evidence.claim_row(db,project,claim['claim_id'],claim['claim_revision'])
            if version['content']!=text or version['output_language']!=raw['candidate_json']['output_language'] or version['context']!=claim_context(request_id,raw['candidate_sha256'],decision['paragraph_id']): raise source_conflict()
            return part
        try:
            version=validation_version(review['report_json'].get('numeric_validation_version',1))
            candidate,parts=prepare(raw['candidate_json'],snap,bundle,review['request_json'],frozen_claim,numeric_version=NUMERIC_VERSION if strict_numeric else version)
            _,mapping=citation_body(candidate,parts)
            rebuilt,report=finish(candidate,raw['candidate_json'],snap,review['request_json'],citation,mapping,review['id'],numeric_version=version)
            if rebuilt!=review['reviewed_candidate_json'] or report!=review['report_json']: raise source_conflict()
            if strict_numeric:
                seen=set(seen or ())
                if request_id in seen:raise source_conflict()
                seen.add(request_id)
                self.assert_inherited_numeric_safe(db,project,identity,snap,seen)
        except (ValueError,KeyError,TypeError) as exc: raise source_conflict() from exc

    def assert_inherited_numeric_safe(self,db,project,identity,snapshot,seen):
        """New approval cannot inherit unsafe old science or language edits.

        Ancestors are frozen dependencies, not current requests: reconstruct their
        exact historical claims while applying today's numeric safety policy.
        """
        base=snapshot['base_snapshot'];provenance=base.get('writing_provenance',{})
        if provenance.get('schema_version')!=2:return
        request_id=provenance['request_id']
        if request_id in seen:raise source_conflict()
        if provenance.get('language_review_id'):
            from .language_service import LanguageReviewService
            row=LanguageReviewService(self.assets).language_row(db,project,identity,request_id,provenance['language_review_id'],for_admission=True,seen=seen)
            if row['candidate_json']!=base:raise source_conflict()
        else:
            row=self.row(db,project,identity,request_id,provenance['review_id'])
            self.validate_frozen(db,project,identity,request_id,row,strict_numeric=True,seen=seen)
            if row['reviewed_candidate_json']!=base:raise source_conflict()

    def create(self,project,identity,request_id,request,key):
        require_key(key);body=request_data(ScientificReviewRequest,request)
        with self.store.connection(write=True) as db:
            self.citations.evidence.lock(db,project)
            raw,task=self.raw(db,project,identity,request_id)
            old=db.execute('SELECT id,request_digest FROM manuscript_writing_reviews WHERE request_id=%s AND request_key=%s',(request_id,key)).fetchone()
            if old:
                if old['request_digest']!=digest(body): raise StorageError('task_idempotency_conflict','审核标识已用于不同输入。',409)
                return self.view(self.row(db,project,identity,request_id,old['id'])),200
            self.writing.assert_current(db,task);snap=task['input_snapshot']
            bundle=LiveWritingService(self.assets).bundle(db,project,snap['execution']['bundle_id']);review_id=str(uuid4())
            try:
                self.assert_inherited_numeric_safe(db,project,identity,snap,{request_id})
                candidate,fragments=prepare(raw['candidate_json'],snap,bundle,body,
                    lambda decision,text:self.resolve_claim(db,project,request_id,raw['candidate_sha256'],decision,text,raw['candidate_json']['output_language']))
                citation_input,mapping=citation_body(candidate,fragments)
                citation=self.citations.create_draft_in_transaction(db,project,citation_input,'writing-review:'+review_id)[0]['snapshot'] if citation_input['paragraphs'] else None
                if citation and self.citations.current_changes(db,project,citation): raise source_conflict()
                candidate,report=finish(candidate,raw['candidate_json'],snap,body,citation,mapping,review_id)
            except WritingCitationScopeError as exc:
                raise StorageError('manuscript_writing_citation_scope','单章重写不能更改非目标章节或引用表；请改为全稿处理并重新审核。',409) from exc
            except (ValueError,KeyError,TypeError) as exc: raise invalid(exc) from exc
            sha=artifact_sha(request_id,raw['candidate_sha256'],body,candidate,report)
            db.execute('''INSERT INTO manuscript_writing_reviews(id,request_id,manuscript_id,base_version_id,project_id,user_id,request_key,request_json,request_digest,candidate_sha256,reviewed_candidate_json,reviewed_candidate_sha256,report_json,review_sha256,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (review_id,request_id,identity,raw['base_version_id'],project,self.store.user_id,key,Jsonb(body),digest(body),raw['candidate_sha256'],Jsonb(candidate),digest(candidate),Jsonb(report),sha,now()))
            return self.view(self.row(db,project,identity,request_id,review_id)),201

    def assert_current(self,db,project,identity,request_id,review):
        raw,task=self.raw(db,project,identity,request_id)
        self.writing.assert_current(db,task)
        if raw['candidate_sha256']!=review['candidate_sha256'] or raw['base_version_id']!=review['base_version_id']: raise source_conflict()
        snap=task['input_snapshot'];bundle=LiveWritingService(self.assets).bundle(db,project,snap['execution']['bundle_id'])
        try:
            candidate,fragments=prepare(raw['candidate_json'],snap,bundle,review['request_json'],
                lambda decision,text:self.resolve_claim(db,project,request_id,raw['candidate_sha256'],decision,text,raw['candidate_json']['output_language']))
            citation_input,mapping=citation_body(candidate,fragments);citation=review['reviewed_candidate_json']['citation_snapshot']
            if citation:
                root,saved=self.citations.draft_row(db,project,citation['draft_id'],citation['revision'])
                if root['revision']!=citation['revision'] or saved['snapshot_json']!=citation or self.citations.current_changes(db,project,citation): raise source_conflict()
                rebuilt=self.citations.resolve(db,project,citation_input)
                rebuilt.update(**{k:citation[k] for k in ('draft_id','version_id','revision')})
                if rebuilt!=citation: raise source_conflict()
            elif citation_input['paragraphs']: raise source_conflict()
            rebuilt,report=finish(candidate,raw['candidate_json'],snap,review['request_json'],citation,mapping,review['id'],numeric_version=validation_version(review['report_json'].get('numeric_validation_version',1)))
            if rebuilt!=review['reviewed_candidate_json'] or report!=review['report_json']: raise source_conflict()
            self.assert_inherited_numeric_safe(db,project,identity,snap,{request_id})
        except (ValueError,KeyError,TypeError) as exc: raise invalid(exc) from exc
        return raw,task
