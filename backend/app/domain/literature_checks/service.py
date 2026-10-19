"""Independent, append-only provenance checks; human support remains separate."""
from copy import deepcopy
from app.adapters.doi import DoiClient
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest,require_snapshot
from app.domain.literature_citations.service import LiteratureCitationService
from app.domain.literature_citations.metadata import extract_metadata
from app.domain.literature_checks.contracts import CheckRequest,CheckSnapshot
from app.domain.literature_evidence.contracts import ReviewRequest
from app.domain.literature_evidence.service import request_data,iso

TABLE='literature_check_receipts'
STATUSES={'matched','synthetic_match','source_conflict','needs_review','not_checked','not_applicable',
          'invalid_doi','resolved','not_found','rate_limited','timeout','error'}


class LiteratureCheckService:
    def __init__(self,assets,doi_client=None):
        if doi_client is not None and doi_client.execution_kind=='synthetic_fixture' and assets.db_config.environment!='test':
            raise StorageError('task_input_invalid','离线模拟仅允许在隔离测试环境执行。',422)
        self.citations=LiteratureCitationService(assets)
        self.store=self.citations.store
        self.literature=self.citations.literature
        self.evidence=self.citations.evidence
        self.doi=doi_client if doi_client is not None else DoiClient()

    def config(self,project):
        with self.store.connection() as db: self.store.require_project(db,project)
        available=self.doi.available
        return dict(project_id=project,page_size=10,check_kinds=['saved_record','doi_resolution'],
            doi_check_available=available,doi_network_enabled=available and self.doi.execution_kind=='doi_org',
            doi_execution_kind=self.doi.execution_kind if available else 'disabled',real_model_calls=False)

    def source_row(self,db,project,reference,search_id):
        # Ownership errors remain 404; damaged saved sources are recorded as conflicts later.
        search=db.execute('SELECT * FROM literature_searches WHERE task_id=%s AND project_id=%s AND user_id=%s',
            (search_id,project,self.store.user_id)).fetchone()
        hit=db.execute('''SELECT * FROM literature_search_hits WHERE task_id=%s AND project_reference_id=%s
            AND project_id=%s AND user_id=%s''',(search_id,reference['id'],project,self.store.user_id)).fetchone()
        if not search or not hit:
            raise StorageError('literature_not_found','所选保存来源不存在。',404)
        receipt=db.execute('SELECT * FROM literature_fetch_receipts WHERE id=%s AND task_id=%s AND project_id=%s AND user_id=%s',
            (hit['receipt_id'],search_id,project,self.store.user_id)).fetchone()
        if not receipt: raise source_conflict()
        identity=db.execute('SELECT pmid FROM literature_records WHERE id=%s',(reference['reference_id'],)).fetchone()
        source=dict(search_id=search_id,receipt_id=receipt['id'],source_kind=receipt['source_kind'],
            sha256=receipt['sha256'],record_sha256=digest(hit['record_json']),pmid=identity['pmid'])
        return source,self.saved_language(db,search_id)

    def saved_language(self,db,search_id):
        # Use the digest-validated original task input when search bookkeeping drifts.
        task=self.store.require_task(db,search_id)
        return require_snapshot(task)['input']['output_language']

    def actual(self,db,project,reference,search_id):
        raw,source=self.citations.actual_receipt(db,project,reference,search_id)
        # A mixed real/synthetic retrieval chain must never promote an offline fixture.
        kinds=db.execute('SELECT DISTINCT source_kind FROM literature_fetch_receipts WHERE task_id=%s AND project_id=%s AND user_id=%s',
            (search_id,project,self.store.user_id)).fetchall()
        if any(k['source_kind']!=source['source_kind'] for k in kinds): raise source_conflict()
        source={k:source[k] for k in ('search_id','receipt_id','source_kind','sha256','record_sha256','pmid')}
        return raw,source

    def validate(self,row):
        self.citations.validate(row)
        try:
            body=request_data(CheckRequest,{k:v for k,v in row['request_json'].items() if k!='project_reference_id'})
            snapshot=CheckSnapshot.model_validate(row['snapshot_json'],strict=True).model_dump(mode='json')
            result=snapshot['result'];source=result['source']
            if (set(snapshot)!={'output_language','result'} or snapshot['output_language'] not in ('zh-CN','en')
                or row['request_json']!=dict(project_reference_id=row['project_reference_id'],**body)
                or body['kind']!=row['kind'] or body['search_id']!=row['search_id']
                or source['search_id']!=row['search_id'] or source['receipt_id']!=row['receipt_id']
                or source['source_kind']!=row['source_kind'] or result['status'] not in STATUSES
                or result['execution_kind'] not in ('local','disabled','synthetic_fixture','doi_org')
                or type(result['network_attempted']) is not bool
                or result['network_attempted']!=(result['execution_kind']=='doi_org')
                or (row['kind']=='saved_record' and (result['execution_kind']!='local' or result['status'] not in ('matched','synthetic_match','source_conflict','needs_review')))
                or (result['status']=='matched' and row['source_kind']!='ncbi_eutilities')
                or (result['status']=='synthetic_match' and row['source_kind']!='synthetic_fixture')):
                raise ValueError()
        except (KeyError,TypeError,ValueError,StorageError) as exc:
            raise source_conflict() from exc

    def current(self,db,project,row):
        try:
            reference=self.literature.require_reference(db,project,row['project_reference_id'])
            _,source=self.actual(db,project,reference,row['search_id'])
            _,language=self.source_row(db,project,reference,row['search_id'])
            return source==row['snapshot_json']['result']['source'] and language==row['snapshot_json']['output_language']
        except (StorageError,ValueError,KeyError,TypeError):
            return False

    def view(self,db,project,row):
        self.validate(row)
        reference=self.literature.require_reference(db,project,row['project_reference_id'])
        if reference['reference_id']!=row['reference_id'] or row['project_id']!=project or row['user_id']!=self.store.user_id:
            raise source_conflict()
        receipt=db.execute('SELECT * FROM literature_fetch_receipts WHERE id=%s AND task_id=%s AND project_id=%s AND user_id=%s',
            (row['receipt_id'],row['search_id'],project,self.store.user_id)).fetchone()
        if not receipt: raise source_conflict()
        return dict(id=row['id'],project_reference_id=row['project_reference_id'],kind=row['kind'],search_id=row['search_id'],
            source_kind=row['source_kind'],**deepcopy(row['snapshot_json']),created_at=iso(row['created_at']),
            source_current=self.current(db,project,row))

    def create(self,project,reference_id,request,key):
        require_key(key)
        body=dict(project_reference_id=reference_id,**request_data(CheckRequest,request))
        with self.store.connection(write=True) as db:
            self.evidence.lock(db,project)
            reference=self.literature.require_reference(db,project,reference_id)
            replay=self.citations.replay(db,TABLE,project,key,body)
            if replay: return self.view(db,project,replay),200
            source,language=self.source_row(db,project,reference,body['search_id'])
            result=dict(status='source_conflict',network_attempted=False,execution_kind='local',
                error_code='literature_source_conflict',doi=None,http_status=None,resolution_target=None,source=source)
            try:
                raw,actual=self.actual(db,project,reference,body['search_id'])
                metadata=extract_metadata(raw,source['pmid'])
                if source!=actual: raise source_conflict()
                result.update(status='synthetic_match' if source['source_kind']=='synthetic_fixture' else 'matched',error_code=None)
                if body['kind']=='doi_resolution':
                    result.update(self.doi.resolve(metadata['doi']))
            except (StorageError,ValueError):
                pass
            snapshot=dict(output_language=language,result=result)
            row=self.citations.insert(db,TABLE,project,key,body,snapshot,project_reference_id=reference_id,
                reference_id=reference['reference_id'],search_id=body['search_id'],receipt_id=source['receipt_id'],
                kind=body['kind'],source_kind=source['source_kind'])
            return self.view(db,project,row),201

    def history(self,project,reference_id,page=1):
        with self.store.connection() as db:
            self.literature.require_reference(db,project,reference_id)
            rows=self.citations.rows(db,TABLE,project,' AND project_reference_id=%s',(reference_id,))
            return dict(items=[self.view(db,project,r) for r in rows[(page-1)*10:page*10]],total=len(rows),page=page,page_size=10)

    def support(self,db,project,reference_id):
        ids=db.execute('''SELECT DISTINCT claim_id FROM literature_claim_reviews WHERE project_id=%s AND user_id=%s AND project_reference_id=%s
            UNION SELECT DISTINCT claim_id FROM literature_claim_evidence WHERE project_id=%s AND user_id=%s AND project_reference_id=%s''',
            (project,self.store.user_id,reference_id,project,self.store.user_id,reference_id)).fetchall()
        items=[]
        for identity in ids:
            root,version=self.evidence.claim_row(db,project,identity['claim_id'])
            review=self.citations.latest_review(db,project,root['id'],version['revision'],reference_id)
            latest=None;current=True
            if review:
                try:
                    latest=self.evidence.review_view(db,project,review)
                    evidence=self.evidence.evidence_by_ids(db,project,root['id'],version['revision'],reference_id,review['evidence_ids_json'])
                    self.citations.validate_evidence_receipts(db,project,reference_id,evidence)
                except StorageError:
                    current=False
                    self.citations.validate(review)
                    saved=request_data(ReviewRequest,review['request_json'])
                    latest=dict(id=review['id'],claim_id=review['claim_id'],decided_by=review['decided_by'],created_at=iso(review['created_at']),**saved)
            items.append(dict(claim_id=root['id'],claim_revision=version['revision'],content=version['content'],
                output_language=version['output_language'],latest_review=latest,source_current=current))
        return items

    def candidate(self,db,project,reference):
        hits=db.execute('''SELECT h.*,r.source_kind,s.input_json FROM literature_search_hits h
            JOIN literature_fetch_receipts r ON r.id=h.receipt_id JOIN literature_searches s ON s.task_id=h.task_id
            WHERE h.project_reference_id=%s AND h.project_id=%s AND h.user_id=%s ORDER BY h.created_at DESC,h.id''',
            (reference['id'],project,self.store.user_id)).fetchall()
        if not hits: raise source_conflict()
        sources=[dict(search_id=h['task_id'],receipt_id=h['receipt_id'],source_kind=h['source_kind'],
            output_language=self.saved_language(db,h['task_id'])) for h in hits]
        try:
            view=self.literature.reference_view(db,reference)
        except StorageError:
            identity=db.execute('SELECT pmid FROM literature_records WHERE id=%s',(reference['reference_id'],)).fetchone()
            view=dict(pmid=identity['pmid'],record=hits[0]['record_json'],selection=dict(status=reference['selection_status'],note=reference['selection_note'],revision=reference['revision']),source=sources[0])
        rows=self.citations.rows(db,TABLE,project,' AND project_reference_id=%s',(reference['id'],))
        latest={}
        for row in rows:
            if row['kind'] not in latest: latest[row['kind']]=self.view(db,project,row)
        return dict(id=reference['id'],pmid=view['pmid'],record=view['record'],selection=view['selection'],source=view['source'],
            sources=sources,saved_record=latest.get('saved_record'),doi_resolution=latest.get('doi_resolution'),
            content_support=self.support(db,project,reference['id']))

    def reference(self,project,reference_id):
        with self.store.connection() as db:
            reference=self.literature.require_reference(db,project,reference_id)
            return self.candidate(db,project,reference)

    def candidates(self,project,page=1):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            total=db.execute('SELECT count(*) AS n FROM project_references WHERE project_id=%s AND user_id=%s',(project,self.store.user_id)).fetchone()['n']
            refs=db.execute('SELECT * FROM project_references WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id LIMIT 10 OFFSET %s',
                (project,self.store.user_id,(page-1)*10)).fetchall()
            return dict(items=[self.candidate(db,project,r) for r in refs],total=total,page=page,page_size=10)
