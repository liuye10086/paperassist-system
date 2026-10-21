"""Validated current inputs become immutable, locally formatted citation versions."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from app.domain.literature_evidence.service import LiteratureEvidenceService, invalid, iso, request_data, validate_request_row
from app.domain.literature_evidence.contracts import ReviewRequest
from app.domain.literature_citations.contracts import MetadataRequest, MaterialConfirmationRequest, DraftRequest, DraftVersionRequest
from app.domain.literature_citations.metadata import extract_metadata, metadata_gaps
from app.domain.literature_citations.formatter import render_paragraphs


def conflict(message='引用来源或版本已变化，请重新核对。'):
    return StorageError('literature_citation_conflict',message,409)


def not_found():
    return StorageError('literature_not_found','引用记录不存在。',404)


class LiteratureCitationService:
    def __init__(self,assets):
        self.evidence=LiteratureEvidenceService(assets)
        self.store=self.evidence.store
        self.literature=self.evidence.literature

    def config(self,project):
        with self.store.connection() as db:
            self.store.require_project(db,project)
        return dict(project_id=project,format='nlm_numeric_journal_v1',page_size=10,
            supported_article_types=['journal'],material_completeness=['full_paper','fragment','unconfirmed'],
            manual_metadata_requires_confirmation=True,real_model_calls=False)

    def rows(self,db,table,project,where='',args=()):
        return db.execute('SELECT * FROM '+table+' WHERE project_id=%s AND user_id=%s'+where+' ORDER BY created_at DESC,id DESC',
            (project,self.store.user_id,*args)).fetchall()

    def row(self,db,table,project,identity):
        self.store.require_project(db,project)
        row=db.execute('SELECT * FROM '+table+' WHERE id=%s AND project_id=%s AND user_id=%s',
            (identity,project,self.store.user_id)).fetchone()
        if not row:
            raise not_found()
        self.validate(row)
        return row

    def validate(self,row):
        validate_request_row(row)
        if 'snapshot_json' in row and digest(row['snapshot_json'])!=row['snapshot_sha256']:
            raise source_conflict()

    def replay(self,db,table,project,key,body,draft_id=None):
        where=' AND idempotency_key=%s';args=[key]
        if draft_id is not None:
            where+=' AND draft_id=%s';args.append(draft_id)
        rows=self.rows(db,table,project,where,args)
        row=rows[0] if rows else None
        if row:
            self.validate(row)
            if row['request_digest']!=digest(body):
                raise StorageError('task_idempotency_conflict','请求标识已用于不同输入。',409)
        return row

    def insert(self,db,table,project,key,body,snapshot=None,**fields):
        if snapshot is not None:
            fields.update(snapshot_json=snapshot,snapshot_sha256=digest(snapshot))
        return self.evidence.insert(db,table,project,key,body,id=str(uuid4()),**fields)

    def actual_receipt(self,db,project,reference,search_id):
        """Read exactly the saved EFetch object and compare the unchanged bookkeeping."""
        from app.adapters.ncbi import parse_fetch, NcbiError
        _,search=self.literature.require_search(db,project,search_id)
        hit=db.execute('''SELECT * FROM literature_search_hits WHERE task_id=%s AND project_reference_id=%s
            AND project_id=%s AND user_id=%s''',(search_id,reference['id'],project,self.store.user_id)).fetchone()
        if not hit:
            raise invalid('所选已保存检索不含此文献。')
        receipt=db.execute("SELECT * FROM literature_fetch_receipts WHERE id=%s AND status='succeeded' AND operation='efetch'",(hit['receipt_id'],)).fetchone()
        if not receipt or receipt['project_id']!=project or receipt['user_id']!=self.store.user_id or receipt['task_id']!=search_id:
            raise source_conflict()
        request=receipt['request_json'];pmids=search['pmids_json']
        if (digest(request)!=receipt['request_digest'] or set(request)!={'operation','pmids'}
                or request['operation']!='efetch' or request['pmids'] not in [pmids[n:n+20] for n in range(0,len(pmids),20)]):
            raise source_conflict()
        if receipt['cached_from_id']:
            original=db.execute('SELECT * FROM literature_fetch_receipts WHERE id=%s',(receipt['cached_from_id'],)).fetchone()
            if (not original or original['cached_from_id'] is not None or original['status']!='succeeded'
                    or any(receipt[k]!=original[k] for k in ('project_id','user_id','operation','request_digest',
                        'source_kind','object_key','sha256','size_bytes','attempted_at'))):
                raise source_conflict()
        raw=self.literature.objects.read(receipt)
        try:
            records={r['pmid']:r for r in parse_fetch(raw,request['pmids']).records}
        except NcbiError as exc:
            raise source_conflict() from exc
        identity=db.execute('SELECT pmid FROM literature_records WHERE id=%s',(reference['reference_id'],)).fetchone()
        record=records.get(identity['pmid']) if identity else None
        if (not record or record!=hit['record_json'] or hit['reference_id']!=reference['reference_id']
                or not 1<=hit['ordinal']<=len(pmids) or pmids[hit['ordinal']-1]!=identity['pmid']):
            raise source_conflict()
        source=dict(search_id=search_id,receipt_id=receipt['id'],sha256=receipt['sha256'],record_sha256=digest(record),
            source_kind=receipt['source_kind'],pmid=identity['pmid'],
            source_download_url=self.literature.reference_view(db,reference,search_id)['source']['source_download_url'])
        return raw,source

    def metadata_actual(self,db,project,row):
        self.validate(row)
        reference=self.literature.require_reference(db,project,row['project_reference_id'])
        snapshot=row['snapshot_json'];body=row['request_json']
        req=request_data(MetadataRequest,{k:v for k,v in body.items() if k!='project_reference_id'})
        raw,source=self.actual_receipt(db,project,reference,req['search_id'])
        if req['material_id']:
            material=self.evidence.material_row(db,project,req['material_id'])
            if material['project_reference_id']!=reference['id']:
                raise source_conflict()
            actual,_=self.evidence.material_actual(project,material)
            source['material']=dict(id=material['id'],source=actual)
        try:
            extracted=extract_metadata(raw,source['pmid'])
            metadata=extracted if req['mode']=='extract' else req['metadata']
        except ValueError as exc:
            raise invalid('已保存回执无法提取此书目。') from exc
        expected=dict(metadata=metadata,source=source,mode=req['mode'],source_description=req['source_description'],
            basis=req['basis'],source_verified=req['mode']=='extract' or req['confirm_source'])
        if (snapshot!=expected or body['project_reference_id']!=reference['id'] or row['reference_id']!=reference['reference_id']
                or metadata['pmid']!=source['pmid'] or metadata['article_type']!=extracted['article_type']
                or row['revision']!=req['expected_revision']+1):
            raise source_conflict()
        return snapshot

    def metadata_view(self,db,project,row,*,verify=False):
        self.validate(row)
        snapshot=row['snapshot_json'];actual=True
        if verify:
            self.metadata_actual(db,project,row)
        else:
            try:
                self.metadata_actual(db,project,row)
            except StorageError:
                actual=False
        gaps=metadata_gaps(snapshot['metadata'])
        return dict(id=row['id'],project_reference_id=row['project_reference_id'],revision=row['revision'],
            **snapshot,gaps=gaps,source_current=actual,usable=actual and snapshot['source_verified'] and not gaps,
            created_at=iso(row['created_at']))

    def create_metadata(self,project,reference_id,request,key):
        require_key(key);body=dict(project_reference_id=reference_id,**request_data(MetadataRequest,request))
        with self.store.connection(write=True) as db:
            self.evidence.lock(db,project)
            reference=self.literature.require_reference(db,project,reference_id)
            replay=self.replay(db,'literature_citation_metadata_versions',project,key,body)
            if replay:
                return self.metadata_view(db,project,replay),200
            rows=self.rows(db,'literature_citation_metadata_versions',project,' AND project_reference_id=%s',(reference_id,))
            revision=max((r['revision'] for r in rows),default=0)
            if revision!=body['expected_revision']:
                raise conflict('引用元数据已更新，请重新读取。')
            raw,source=self.actual_receipt(db,project,reference,body['search_id'])
            if body['material_id']:
                material=self.evidence.material_row(db,project,body['material_id'])
                if material['project_reference_id']!=reference_id:
                    raise invalid('补录来源材料不属于此文献。')
                actual,_=self.evidence.material_actual(project,material)
                source['material']=dict(id=material['id'],source=actual)
            try:
                extracted=extract_metadata(raw,source['pmid'])
                metadata=extracted if body['mode']=='extract' else body['metadata']
            except ValueError as exc:
                raise invalid('已保存回执无法提取此书目。') from exc
            if metadata['pmid']!=source['pmid']:
                raise invalid('书目PMID必须与实际已保存来源一致。')
            if metadata['article_type']!=extracted['article_type']:
                raise invalid('保存来源的实际文献类型不能通过补录更改。')
            snapshot=dict(metadata=metadata,source=source,mode=body['mode'],source_description=body['source_description'],
                basis=body['basis'],source_verified=body['mode']=='extract' or body['confirm_source'])
            row=self.insert(db,'literature_citation_metadata_versions',project,key,body,snapshot,
                project_reference_id=reference_id,reference_id=reference['reference_id'],revision=revision+1)
            return self.metadata_view(db,project,row,verify=True),201

    def metadata_history(self,project,reference_id,page=1):
        with self.store.connection() as db:
            self.literature.require_reference(db,project,reference_id)
            rows=self.rows(db,'literature_citation_metadata_versions',project,' AND project_reference_id=%s',(reference_id,))
            rows=sorted(rows,key=lambda r:r['revision'],reverse=True)
            return dict(items=[self.metadata_view(db,project,r) for r in rows[(page-1)*10:page*10]],total=len(rows),page=page,page_size=10)

    def metadata_source(self,project,identity):
        with self.store.connection() as db:
            row=self.row(db,'literature_citation_metadata_versions',project,identity)
            return self.metadata_view(db,project,row)

    def confirmation_view(self,row):
        self.validate(row)
        return dict(id=row['id'],material_id=row['material_id'],revision=row['revision'],
            project_reference_id=row['project_reference_id'],**row['snapshot_json'],created_at=iso(row['created_at']))

    def create_confirmation(self,project,material_id,request,key):
        require_key(key);body=dict(material_id=material_id,**request_data(MaterialConfirmationRequest,request))
        with self.store.connection(write=True) as db:
            self.evidence.lock(db,project)
            material=self.evidence.material_row(db,project,material_id)
            row=self.replay(db,'literature_material_confirmations',project,key,body)
            if row:
                return self.confirmation_view(row),200
            rows=self.rows(db,'literature_material_confirmations',project,' AND material_id=%s',(material_id,))
            revision=max((r['revision'] for r in rows),default=0)
            if revision!=body['expected_revision']:
                raise conflict('材料确认已更新，请重新读取。')
            source,items=self.evidence.material_actual(project,material)
            snapshot=dict(completeness=body['completeness'],basis=body['basis'],source=source,
                actual_item_count=len(items),confirmed_by=self.store.user_id)
            row=self.insert(db,'literature_material_confirmations',project,key,body,snapshot,
                material_id=material_id,project_reference_id=material['project_reference_id'],revision=revision+1)
            return self.confirmation_view(row),201

    def confirmations(self,project,material_id,page=1):
        with self.store.connection() as db:
            self.evidence.material_row(db,project,material_id)
            rows=self.rows(db,'literature_material_confirmations',project,' AND material_id=%s',(material_id,))
            rows=sorted(rows,key=lambda r:r['revision'],reverse=True)
            return dict(items=[self.confirmation_view(r) for r in rows[(page-1)*10:page*10]],total=len(rows),page=page,page_size=10)

    def latest_review(self,db,project,claim_id,claim_revision,reference_id):
        rows=self.rows(db,'literature_claim_reviews',project,
            ' AND claim_id=%s AND claim_revision=%s AND project_reference_id=%s',(claim_id,claim_revision,reference_id))
        return rows[0] if rows else None

    def resolve_binding(self,db,project,claim,binding):
        review=self.row(db,'literature_claim_reviews',project,binding['review_id'])
        if review['claim_id']!=claim['claim_id'] or review['claim_revision']!=claim['revision']:
            raise invalid('人工决定不属于当前论述修订。')
        latest=self.latest_review(db,project,claim['claim_id'],claim['revision'],review['project_reference_id'])
        if not latest or latest['id']!=review['id'] or review['status']!='supported' or review['relevance']!='related' or not review['evidence_ids_json']:
            raise conflict('请选择当前修订、最新人工确认支持且有实际证据的决定。')
        review_view=self.evidence.review_view(db,project,review)
        metadata=self.row(db,'literature_citation_metadata_versions',project,binding['metadata_version_id'])
        if metadata['project_reference_id']!=review['project_reference_id']:
            raise invalid('元数据版本与人工决定的文献不一致。')
        metadata_view=self.metadata_view(db,project,metadata,verify=True)
        if not metadata_view['usable']:
            raise conflict('引用元数据尚未核验或关键书目字段不完整。')
        evidence=self.evidence.evidence_by_ids(db,project,claim['claim_id'],claim['revision'],review['project_reference_id'],review['evidence_ids_json'])
        self.validate_evidence_receipts(db,project,review['project_reference_id'],evidence)
        return dict(project_reference_id=review['project_reference_id'],reference_id=review['reference_id'],
            review_id=review['id'],metadata_version_id=metadata['id'],metadata_revision=metadata['revision'],
            metadata=deepcopy(metadata_view['metadata']),metadata_source=deepcopy(metadata_view),review=review_view,evidence=evidence)

    def validate_evidence_receipts(self,db,project,reference_id,evidence):
        reference=self.literature.require_reference(db,project,reference_id)
        for item in evidence:
            if item['reading_scope']=='abstract':
                _,source=self.actual_receipt(db,project,reference,item['source']['search_id'])
                if any(source[k]!=item['source'][k] for k in ('receipt_id','sha256','record_sha256','source_kind')):
                    raise source_conflict()

    def resolve(self,db,project,body):
        paragraphs=[]
        for paragraph in body['paragraphs']:
            fragments=[]
            for fragment in paragraph['fragments']:
                if fragment['kind']=='text':
                    fragments.append(deepcopy(fragment));continue
                _,claim=self.evidence.claim_row(db,project,fragment['claim_id'],fragment['claim_revision'],current=True)
                bindings=[self.resolve_binding(db,project,claim,b) for b in fragment['bindings']]
                if len({b['project_reference_id'] for b in bindings})!=len(bindings):
                    raise invalid('同一论述片段不得重复绑定同篇文献。')
                fragments.append(dict(kind='claim',claim_id=claim['claim_id'],claim_revision=claim['revision'],text=claim['content'],bindings=bindings))
            paragraphs.append(dict(id=paragraph['id'],fragments=fragments))
        try:
            output=render_paragraphs(paragraphs)
        except ValueError as exc:
            raise invalid('同篇引用须采用一致、完整的元数据版本。') from exc
        return dict(schema_version=1,project_id=project,title=body['title'],output_language=body['output_language'],
            format=body['format'],paragraphs=paragraphs,output=output)

    def current_changes(self,db,project,snapshot):
        changes=[];seen=set()
        for paragraph in snapshot['paragraphs']:
            for fragment in paragraph['fragments']:
                if fragment['kind']!='claim':
                    continue
                for bound in fragment['bindings']:
                    identity=(paragraph['id'],fragment['claim_id'],bound['review_id'],bound['metadata_version_id'])
                    if identity in seen:
                        continue
                    seen.add(identity);reasons=[]
                    try:
                        root,_=self.evidence.claim_row(db,project,fragment['claim_id'],fragment['claim_revision'])
                        if root['revision']!=fragment['claim_revision']:
                            reasons.append('claim_revision_changed')
                        latest=self.latest_review(db,project,fragment['claim_id'],fragment['claim_revision'],bound['project_reference_id'])
                        if not latest or latest['id']!=bound['review_id']:
                            reasons.append('review_changed')
                        metadata=self.row(db,'literature_citation_metadata_versions',project,bound['metadata_version_id'])
                        self.metadata_actual(db,project,metadata)
                        evidence=self.evidence.evidence_by_ids(db,project,fragment['claim_id'],fragment['claim_revision'],bound['project_reference_id'],bound['review']['evidence_ids'])
                        self.validate_evidence_receipts(db,project,bound['project_reference_id'],evidence)
                        reference=self.literature.require_reference(db,project,bound['project_reference_id'])
                        current=self.literature.reference_view(db,reference)['source']
                        if current['receipt_id']!=bound['metadata_source']['source']['receipt_id']:
                            reasons.append('reference_source_changed')
                        versions=self.rows(db,'literature_citation_metadata_versions',project,' AND project_reference_id=%s',(bound['project_reference_id'],))
                        if max(r['revision'] for r in versions)!=bound['metadata_revision']:
                            reasons.append('metadata_version_changed')
                    except StorageError:
                        reasons.append('source_unavailable_or_changed')
                    if reasons:
                        changes.append(dict(paragraph_id=paragraph['id'],claim_id=fragment['claim_id'],
                            project_reference_id=bound['project_reference_id'],reasons=reasons))
        return changes

    def draft_row(self,db,project,identity,revision=None):
        root=self.row(db,'literature_citation_drafts',project,identity)
        revision=root['revision'] if revision is None else revision
        rows=self.rows(db,'literature_citation_versions',project,' AND draft_id=%s AND revision=%s',(identity,revision))
        if not rows:
            raise not_found()
        row=rows[0];self.validate(row)
        snapshot=row['snapshot_json']
        if snapshot.get('draft_id')!=identity or snapshot.get('revision')!=revision or snapshot.get('version_id')!=row['id'] or snapshot.get('project_id')!=project:
            raise source_conflict()
        return root,row

    def draft_view(self,db,project,root,row):
        return dict(id=root['id'],version_id=row['id'],project_id=project,revision=row['revision'],
            current_revision=root['revision'],is_current=root['revision']==row['revision'],snapshot=row['snapshot_json'],
            current_changes=self.current_changes(db,project,row['snapshot_json']),created_at=iso(row['created_at']))

    def create_draft(self,project,request,key,identity=None):
        with self.store.connection(write=True) as db:
            return self.create_draft_in_transaction(db,project,request,key,identity)

    def create_draft_in_transaction(self,db,project,request,key,identity=None):
        """Reuse the caller's write lock; never open a nested write connection."""
        require_key(key)
        body=request_data(DraftVersionRequest if identity else DraftRequest,request)
        self.evidence.lock(db,project)
        if identity:
            root,_=self.draft_row(db,project,identity)
            replay=self.replay(db,'literature_citation_versions',project,key,body,identity)
            if replay:
                return self.draft_view(db,project,root,replay),200
            if root['revision']!=body['expected_revision']:
                raise conflict('引用样稿已更新，请重新读取。')
            revision=root['revision']+1
        else:
            replay=self.replay(db,'literature_citation_drafts',project,key,body)
            if replay:
                root,version=self.draft_row(db,project,replay['id'],1)
                return self.draft_view(db,project,root,version),200
            revision=1
        snapshot=self.resolve(db,project,body)
        if not identity:
            now=datetime.now(timezone.utc)
            root=self.insert(db,'literature_citation_drafts',project,key,body,revision=1,created_at=now,updated_at=now)
            identity=root['id']
        version_id=str(uuid4())
        snapshot.update(draft_id=identity,revision=revision,version_id=version_id)
        version=self.evidence.insert(db,'literature_citation_versions',project,key,body,id=version_id,
            draft_id=identity,revision=revision,snapshot_json=snapshot,snapshot_sha256=digest(snapshot))
        if revision>1:
            root=db.execute('UPDATE literature_citation_drafts SET revision=%s,updated_at=clock_timestamp() WHERE id=%s RETURNING *',(revision,identity)).fetchone()
        return self.draft_view(db,project,root,version),201

    def draft(self,project,identity,revision=None):
        with self.store.connection() as db:
            root,row=self.draft_row(db,project,identity,revision)
            result=self.draft_view(db,project,root,row)
            versions=self.rows(db,'literature_citation_versions',project,' AND draft_id=%s',(identity,))
            result['versions']=[dict(revision=r['revision'],version_id=r['id'],created_at=iso(r['created_at'])) for r in sorted(versions,key=lambda r:r['revision'],reverse=True)]
            return result

    def drafts(self,project,page=1):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            roots=self.rows(db,'literature_citation_drafts',project)
            items=[]
            for root in roots[(page-1)*10:page*10]:
                _,row=self.draft_row(db,project,root['id'])
                items.append(self.draft_view(db,project,root,row))
            return dict(items=items,total=len(roots),page=page,page_size=10)

    def saved(self,project,identity,revision,source=False):
        with self.store.connection() as db:
            _,row=self.draft_row(db,project,identity,revision)
            snapshot=row['snapshot_json']
            return dict(draft_id=identity,version_id=row['id'],revision=revision,format=snapshot['format'],
                **({'paragraphs':snapshot['paragraphs']} if source else {'output':snapshot['output']}))

    def candidates(self,project,page=1,*,todos=False):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            refs=self.rows(db,'project_references',project)
            items=[]
            for ref in refs:
                view=self.literature.reference_view(db,ref)
                metadata=self.rows(db,'literature_citation_metadata_versions',project,' AND project_reference_id=%s',(ref['id'],))
                latest_meta=max(metadata,key=lambda r:r['revision']) if metadata else None
                meta=self.metadata_view(db,project,latest_meta) if latest_meta else None
                tasks=[]
                if not meta:
                    tasks.append('extract_metadata')
                elif not meta['usable']:
                    tasks.extend(['metadata_missing:'+g for g in meta['gaps']])
                    if not meta['source_verified'] or not meta['source_current']:
                        tasks.append('verify_metadata_source')
                material_rows=self.rows(db,'literature_materials',project,' AND project_reference_id=%s',(ref['id'],))
                materials=[]
                for material in material_rows:
                    history=self.rows(db,'literature_material_confirmations',project,' AND material_id=%s',(material['id'],))
                    latest=max(history,key=lambda r:r['revision']) if history else None
                    actual=True;item_count=None
                    try:
                        checked=self.evidence.material_row(db,project,material['id'])
                        _,source_items=self.evidence.material_actual(project,checked)
                        item_count=len(source_items)
                    except StorageError:
                        actual=False
                    read_items=db.execute('''SELECT id,claim_id,claim_revision,quote,reading_scope,location_json FROM literature_claim_evidence
                        WHERE project_id=%s AND user_id=%s AND source_json->>'material_id'=%s ORDER BY created_at,id''',
                        (project,self.store.user_id,material['id'])).fetchall()
                    materials.append(dict(id=material['id'],file_id=material['file_id'],source_kind=material['source_kind'],
                        version_id=material['version_id'],completeness=latest['snapshot_json']['completeness'] if latest else 'unconfirmed',
                        confirmation=self.confirmation_view(latest) if latest else None,source_current=actual,actual_item_count=item_count,
                        read_items=[dict(id=r['id'],claim_id=r['claim_id'],claim_revision=r['claim_revision'],quote=r['quote'],
                            reading_scope=r['reading_scope'],location=r['location_json']) for r in read_items]))
                has_full=any(m['completeness']=='full_paper' and m['source_current'] for m in materials)
                if not has_full:
                    tasks.append('obtain_or_confirm_full_paper')
                claim_ids=db.execute('''SELECT DISTINCT claim_id FROM literature_claim_reviews WHERE project_id=%s AND user_id=%s AND project_reference_id=%s
                    UNION SELECT DISTINCT claim_id FROM literature_claim_evidence WHERE project_id=%s AND user_id=%s AND project_reference_id=%s''',
                    (project,self.store.user_id,ref['id'],project,self.store.user_id,ref['id'])).fetchall()
                claims=[]
                for c in claim_ids:
                    root,version=self.evidence.claim_row(db,project,c['claim_id'])
                    review=self.latest_review(db,project,root['id'],version['revision'],ref['id'])
                    supplement=db.execute('SELECT round FROM literature_claim_supplements WHERE claim_id=%s',(root['id'],)).fetchone()
                    r=None;review_actual=True
                    if review:
                        try:
                            r=self.evidence.review_view(db,project,review)
                            actual_evidence=self.evidence.evidence_by_ids(db,project,root['id'],version['revision'],ref['id'],review['evidence_ids_json'])
                            self.validate_evidence_receipts(db,project,ref['id'],actual_evidence)
                        except StorageError:
                            review_actual=False
                            # Keep the saved human statement visible while reporting its source as unverified.
                            try:
                                self.validate(review)
                                saved=request_data(ReviewRequest,review['request_json'])
                                r=dict(id=review['id'],claim_id=review['claim_id'],decided_by=review['decided_by'],
                                    created_at=iso(review['created_at']),**saved)
                            except StorageError:
                                r=None
                    if not review_actual:
                        tasks.append('verify_evidence_source')
                    if not r or r['status']=='needs_review':
                        tasks.append('verify_claim')
                    elif r['status']=='partial':
                        tasks.append('narrow_claim_and_confirm')
                    elif r['status']=='unsupported':
                        tasks.append('unsupported_claim')
                    claims.append(dict(id=root['id'],revision=version['revision'],content=version['content'],
                        latest_review=r,review_source_current=review_actual,
                        citation_eligible=bool(r and r['status']=='supported' and r['relevance']=='related' and r['evidence_ids']
                            and review_actual and meta and meta['usable']),
                        supplement_rounds_used=supplement['round'] if supplement else 0))
                item=dict(id=ref['id'],pmid=view['pmid'],record=view['record'],selection=view['selection'],source=view['source'],
                    metadata=meta,materials=materials,has_abstract=bool(view['record']['abstract']),
                    holds_full_paper=has_full,claims=claims,todos=list(dict.fromkeys(tasks)))
                if not todos or item['todos']:
                    items.append(item)
            return dict(items=items[(page-1)*10:page*10],total=len(items),page=page,page_size=10)
