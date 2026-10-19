"""Actual saved sources, stable claims, and explicitly manual immutable decisions."""
from datetime import datetime, timezone
from uuid import uuid4

from psycopg.types.json import Jsonb
from pydantic import ValidationError

from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.external_evidence.service import ExternalEvidenceService
from app.domain.literature.contracts import SearchRequest
from app.domain.literature.service import LiteratureService, digest
from app.domain.literature_evidence.contracts import (ClaimRequest, ClaimVersionRequest, MaterialRequest,
    QuoteRequest, ReviewRequest, SupplementRequest)


def invalid(message='来源或摘录无效。'):
    return StorageError('task_input_invalid', message, 422)


def revision_conflict():
    return StorageError('literature_revision_conflict', '论述已更新，请重新读取当前版本。', 409)


def iso(value):
    return value.astimezone(timezone.utc).isoformat()


def request_data(model, value):
    try:
        return model.model_validate(value, strict=True).model_dump(mode='json') if isinstance(value, dict) else value.model_dump(mode='json')
    except ValidationError as exc:
        raise invalid('请求字段无效。') from exc


def validate_request_row(row):
    if digest(row['request_json']) != row['request_digest']:
        raise source_conflict()


class LiteratureEvidenceService:
    def __init__(self, assets):
        self.assets = assets
        self.store = TaskStore(assets.owner_id, assets.db_config)
        self.literature = LiteratureService(assets)
        self.external = ExternalEvidenceService(assets)

    def lock(self, db, project):
        self.store.require_project(db, project)
        db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE', (project,)).fetchone()

    def config(self, project):
        with self.store.connection() as db:
            self.store.require_project(db, project)
        return dict(project_id=project, full_text_mode='user_upload', real_model_calls=False,
                    supplement_round_limit=1, supplement_candidate_limit=20)

    def replay(self, db, table, project, key, body, claim_id=None):
        # All names come from fixed call sites, never from request data.
        sql = 'SELECT * FROM '+table+' WHERE project_id=%s AND user_id=%s AND idempotency_key=%s'
        args = [project, self.store.user_id, key]
        if claim_id is not None:
            sql += ' AND claim_id=%s'; args.append(claim_id)
        row = db.execute(sql, tuple(args)).fetchone()
        if row:
            validate_request_row(row)
            if row['request_digest'] != digest(body):
                raise StorageError('task_idempotency_conflict', '请求标识已用于不同输入。', 409)
        return row

    def insert(self, db, table, project, key, body, **fields):
        created = fields.pop('created_at', None) or datetime.now(timezone.utc)
        row = dict(project_id=project, user_id=self.store.user_id, idempotency_key=key,
            request_digest=digest(body), request_json=body, created_at=created, **fields)
        columns = ','.join(row)
        values = tuple(Jsonb(v) if isinstance(v, (dict, list)) else v for v in row.values())
        return db.execute('INSERT INTO '+table+' ('+columns+') VALUES ('+','.join(['%s']*len(row))+') RETURNING *', values).fetchone()

    def material_options(self, project, page=1):
        with self.store.connection() as db:
            self.store.require_project(db, project)
            total = db.execute("SELECT count(*) AS n FROM files WHERE project_id=%s AND file_type IN ('docx','pdf','png','jpeg')", (project,)).fetchone()['n']
            files = db.execute("SELECT * FROM files WHERE project_id=%s AND file_type IN ('docx','pdf','png','jpeg') ORDER BY uploaded_at DESC,id LIMIT 10 OFFSET %s", (project, (page-1)*10)).fetchall()
            items = []
            for file in files:
                versions = db.execute("""SELECT 'document_version' AS kind,r.id AS version_id,r.version FROM file_parse_results r
                    JOIN tasks t ON t.id=r.task_id WHERE r.file_id=%s AND t.project_id=%s AND t.user_id=%s
                    AND t.status='succeeded' AND r.result_json IS NOT NULL ORDER BY r.version DESC""", (file['id'], project, self.store.user_id)).fetchall()
                reviews = db.execute("""SELECT 'ocr_review_version' AS kind,r.id AS version_id,r.version FROM ocr_review_versions r
                    JOIN tasks t ON t.id=r.task_id WHERE r.file_id=%s AND t.project_id=%s AND t.user_id=%s
                    AND t.status='succeeded' AND r.created_by=%s ORDER BY r.created_at DESC""", (file['id'], project, self.store.user_id, self.store.user_id)).fetchall()
                items.append(dict(file_id=file['id'], filename=file['filename'], file_type=file['file_type'],
                    versions=[dict(v, label=('OCR核对' if v['kind']=='ocr_review_version' else '文档解析')+f" v{v['version']}") for v in [*reviews, *versions]]))
            return dict(items=items, total=total, page=page, page_size=10)

    def material_row(self, db, project, identity):
        self.store.require_project(db, project)
        row = db.execute('SELECT * FROM literature_materials WHERE id=%s AND project_id=%s AND user_id=%s', (identity, project, self.store.user_id)).fetchone()
        if not row:
            raise StorageError('literature_not_found', '文献材料不存在。', 404)
        validate_request_row(row)
        reference = self.literature.require_reference(db, project, row['project_reference_id'])
        if reference['reference_id'] != row['reference_id'] or any(row[k] != row['request_json'][k] for k in ('file_id','source_kind','version_id','project_reference_id','source_description','match_note')):
            raise source_conflict()
        return row

    def material_actual(self, project, row):
        source, items = self.external.source(project, row['file_id'], row['source_kind'], row['version_id'])
        if source != row['source_json']:
            raise source_conflict()
        return source, items

    def material_view(self, project, row):
        source, _ = self.material_actual(project, row)
        return dict(id=row['id'], project_reference_id=row['project_reference_id'], source=source,
            source_description=row['source_description'], match_note=row['match_note'], created_at=iso(row['created_at']))

    def create_material(self, project, request, key):
        require_key(key); body = request_data(MaterialRequest, request)
        with self.store.connection(write=True) as db:
            self.lock(db, project)
            row = self.replay(db, 'literature_materials', project, key, body)
            status = 200 if row else 201
            if not row:
                reference = self.literature.require_reference(db, project, body['project_reference_id'])
                source, _ = self.external.source(project, body['file_id'], body['source_kind'], body['version_id'])
                row = self.insert(db, 'literature_materials', project, key, body, id=str(uuid4()),
                    reference_id=reference['reference_id'], source_json=source, **body)
            return self.material_view(project, row), status

    def materials(self, project, page=1, project_reference_id=None):
        with self.store.connection() as db:
            self.store.require_project(db, project)
            if project_reference_id:
                self.literature.require_reference(db, project, project_reference_id)
            where = 'project_id=%s AND user_id=%s AND (%s::text IS NULL OR project_reference_id=%s)'
            args = (project, self.store.user_id, project_reference_id, project_reference_id)
            total = db.execute('SELECT count(*) AS n FROM literature_materials WHERE '+where, args).fetchone()['n']
            rows = db.execute('SELECT id FROM literature_materials WHERE '+where+' ORDER BY created_at DESC,id LIMIT 10 OFFSET %s', (*args,(page-1)*10)).fetchall()
            items = [self.material_view(project, self.material_row(db, project, row['id'])) for row in rows]
        return dict(items=items, total=total, page=page, page_size=10)

    def material_source(self, project, identity, page=1):
        with self.store.connection() as db:
            row = self.material_row(db, project, identity)
        source, items = self.material_actual(project, row)
        return dict(source=source, items=items[(page-1)*20:page*20], total=len(items), page=page, page_size=20)

    def claim_row(self, db, project, identity, revision=None, current=False):
        self.store.require_project(db, project)
        row = db.execute('SELECT * FROM literature_claims WHERE id=%s AND project_id=%s AND user_id=%s', (identity, project, self.store.user_id)).fetchone()
        if not row:
            raise StorageError('literature_not_found', '论述不存在。', 404)
        validate_request_row(row)
        revision = row['revision'] if revision is None else revision
        if current and revision != row['revision']:
            raise revision_conflict()
        version = db.execute('SELECT * FROM literature_claim_versions WHERE claim_id=%s AND revision=%s AND project_id=%s AND user_id=%s', (identity, revision, project, self.store.user_id)).fetchone()
        if not version:
            raise StorageError('literature_not_found', '论述版本不存在。', 404)
        validate_request_row(version)
        if any(version[k] != version['request_json'][k] for k in ('content','context','output_language')):
            raise source_conflict()
        return row, version

    def claim_view(self, db, project, identity, revision=None, detail=True):
        row, version = self.claim_row(db, project, identity, revision)
        result = dict(id=identity, project_id=project, revision=version['revision'], content=version['content'],
            context=version['context'], output_language=version['output_language'], created_at=iso(row['created_at']), updated_at=iso(row['updated_at']))
        supplement = db.execute('SELECT task_id,round,candidate_limit FROM literature_claim_supplements WHERE claim_id=%s', (identity,)).fetchone()
        result['supplement'] = dict(task_id=supplement['task_id'], round=supplement['round'], limit=supplement['candidate_limit']) if supplement else None
        if detail:
            versions = db.execute('SELECT * FROM literature_claim_versions WHERE claim_id=%s ORDER BY revision DESC', (identity,)).fetchall()
            result.update(is_current=version['revision']==row['revision'], versions=[dict(revision=v['revision'], content=v['content'], output_language=v['output_language'], created_at=iso(v['created_at'])) for v in versions])
        return result

    def create_claim(self, project, request, key):
        require_key(key); body = request_data(ClaimRequest, request)
        with self.store.connection(write=True) as db:
            self.lock(db, project)
            row = self.replay(db, 'literature_claims', project, key, body)
            if row:
                return self.claim_view(db, project, row['id'], 1), 200
            now = datetime.now(timezone.utc); identity = str(uuid4())
            self.insert(db, 'literature_claims', project, key, body, id=identity, revision=1, created_at=now, updated_at=now)
            self.insert(db, 'literature_claim_versions', project, key, body, claim_id=identity, revision=1, **body)
            return self.claim_view(db, project, identity), 201

    def version_claim(self, project, identity, request, key):
        require_key(key); body = request_data(ClaimVersionRequest, request)
        with self.store.connection(write=True) as db:
            self.lock(db, project)
            self.claim_row(db, project, identity)
            row = self.replay(db, 'literature_claim_versions', project, key, body, identity)
            if row:
                return self.claim_view(db, project, identity, row['revision']), 200
            self.claim_row(db, project, identity, body['expected_revision'], current=True)
            revision = body['expected_revision']+1
            self.insert(db, 'literature_claim_versions', project, key, body, claim_id=identity, revision=revision,
                **{k:body[k] for k in ('content','context','output_language')})
            db.execute('UPDATE literature_claims SET revision=%s,updated_at=clock_timestamp() WHERE id=%s', (revision, identity))
            return self.claim_view(db, project, identity), 201

    def claim(self, project, identity, revision=None):
        with self.store.connection() as db:
            return self.claim_view(db, project, identity, revision)

    def claims(self, project, page=1):
        with self.store.connection() as db:
            self.store.require_project(db, project)
            total = db.execute('SELECT count(*) AS n FROM literature_claims WHERE project_id=%s AND user_id=%s', (project, self.store.user_id)).fetchone()['n']
            rows = db.execute('SELECT id FROM literature_claims WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id LIMIT 10 OFFSET %s', (project, self.store.user_id, (page-1)*10)).fetchall()
            return dict(items=[self.claim_view(db, project, r['id'], detail=False) for r in rows], total=total, page=page, page_size=10)

    def quote_source(self, db, project, body):
        reference = self.literature.require_reference(db, project, body['project_reference_id'])
        quote = body['quote']
        if body['source_kind'] == 'pmc':
            from app.domain.literature_pmc.service import LiteraturePmcService
            pmc = LiteraturePmcService(self.assets)
            row = pmc.row(db, project, body['pmc_receipt_id'])
            if row['project_reference_id'] != reference['id']:
                raise invalid('PMC回执不属于此文献。')
            snapshot = pmc.actual(db, project, row)
            if row['status'] != 'succeeded': raise invalid('未取得许可正文，不能建立全文证据。')
            item = next((i for i in snapshot['parsed']['items'] if i['id'] == body['item_id']), None)
            if not item or quote not in item['text']: raise invalid('摘录必须来自实际PMC正文片段。')
            start = item['text'].index(quote)
            obj = snapshot['responses'][1]['object']
            return reference, 'pmc_fulltext', dict(kind='pmc', pmc_receipt_id=row['id'],
                source_kind=row['source_kind'], sha256=obj['sha256'], pmcid=row['pmcid'], pmid=row['pmid'],
                license=snapshot['parsed']['license'], scope=snapshot['parsed']['scope'],
                source_download_url=f'/api/v1/projects/{project}/literature/pmc/receipts/{row["id"]}/raw/1'), dict(
                item['location'], item_id=item['id'], start=start, end=start+len(quote))
        if body['source_kind'] == 'abstract':
            search_id = body['search_id']
            self.literature.require_search(db, project, search_id)
            hit = db.execute('''SELECT * FROM literature_search_hits WHERE task_id=%s AND project_reference_id=%s
                AND project_id=%s AND user_id=%s''', (search_id, reference['id'], project, self.store.user_id)).fetchone()
            if not hit:
                raise invalid('该检索不包含此文献。')
            receipt = db.execute('SELECT * FROM literature_fetch_receipts WHERE id=%s AND status=\'succeeded\'', (hit['receipt_id'],)).fetchone()
            if not receipt or receipt['operation'] != 'efetch':
                raise source_conflict()
            from app.adapters.ncbi import parse_fetch, NcbiError
            raw = self.literature.objects.read(receipt)
            try:
                fetched = parse_fetch(raw, receipt['request_json']['pmids'])
            except NcbiError as exc:
                # Saved-source validation failures are provenance conflicts, not live provider failures.
                raise source_conflict() from exc
            actual = {r['pmid']:r for r in fetched.records}
            identity = db.execute('SELECT pmid FROM literature_records WHERE id=%s', (reference['reference_id'],)).fetchone()
            record = actual.get(identity['pmid']) if identity else None
            if record != hit['record_json'] or hit['reference_id'] != reference['reference_id']:
                raise source_conflict()
            for index, abstract in enumerate(record['abstract']):
                if quote in abstract['text']:
                    start = abstract['text'].index(quote)
                    source = dict(kind='abstract', search_id=search_id, receipt_id=receipt['id'],
                        source_kind=receipt['source_kind'], sha256=receipt['sha256'], record_sha256=digest(record),
                        source_download_url=self.literature.reference_view(db, reference, search_id)['source']['source_download_url'])
                    return reference, 'abstract', source, dict(abstract_index=index, label=abstract['label'], start=start, end=start+len(quote))
            raise invalid('摘录必须是此检索实际摘要中的精确片段。')
        material = self.material_row(db, project, body['material_id'])
        if material['project_reference_id'] != reference['id']:
            raise invalid('材料不属于此文献。')
        source, items = self.material_actual(project, material)
        item = next((i for i in items if i['id']==body['item_id']), None)
        text = item.get('text') or (item.get('value') or {}).get('typed') if item else None
        if not item or not isinstance(text, str) or quote not in text:
            raise invalid('摘录必须是所选实际文本片段的精确子串。')
        if item.get('review_action') == 'unreadable' or 'unreadable' in item.get('uncertainties', []):
            raise invalid('不可读OCR片段不能作为文字证据。')
        start = text.index(quote)
        return reference, 'user_material', dict(source, material_id=material['id']), dict(item['location'], item_id=item['id'], start=start, end=start+len(quote))

    def evidence_view(self, db, project, row):
        validate_request_row(row)
        body = request_data(QuoteRequest, row['request_json'])
        self.claim_row(db, project, row['claim_id'], row['claim_revision'])
        reference, scope, source, location = self.quote_source(db, project, body)
        frozen = dict(quote=row['quote'], reading_scope=row['reading_scope'], source=row['source_json'], location=row['location_json'])
        if (body['claim_revision'] != row['claim_revision'] or reference['id'] != row['project_reference_id'] or reference['reference_id'] != row['reference_id']
            or digest(frozen) != row['snapshot_sha256'] or frozen != dict(quote=body['quote'], reading_scope=scope, source=source, location=location)):
            raise source_conflict()
        return dict(id=row['id'], claim_id=row['claim_id'], claim_revision=row['claim_revision'],
            project_reference_id=row['project_reference_id'], created_at=iso(row['created_at']), **frozen)

    def evidence_by_ids(self, db, project, identity, revision, reference_id, ids):
        result = []
        for evidence_id in ids:
            row = db.execute('''SELECT * FROM literature_claim_evidence WHERE id=%s AND project_id=%s AND user_id=%s
                AND claim_id=%s AND claim_revision=%s AND project_reference_id=%s''', (evidence_id, project, self.store.user_id, identity, revision, reference_id)).fetchone()
            if not row:
                raise invalid('证据不属于此论述版本和文献。')
            result.append(self.evidence_view(db, project, row))
        return result

    def create_evidence(self, project, identity, request, key):
        require_key(key); body = request_data(QuoteRequest, request)
        with self.store.connection(write=True) as db:
            self.lock(db, project); self.claim_row(db, project, identity)
            row = self.replay(db, 'literature_claim_evidence', project, key, body, identity)
            status = 200 if row else 201
            if not row:
                self.claim_row(db, project, identity, body['claim_revision'], current=True)
                reference, scope, source, location = self.quote_source(db, project, body)
                frozen = dict(quote=body['quote'], reading_scope=scope, source=source, location=location)
                row = self.insert(db, 'literature_claim_evidence', project, key, body, id=str(uuid4()), claim_id=identity,
                    claim_revision=body['claim_revision'], project_reference_id=reference['id'], reference_id=reference['reference_id'],
                    quote=body['quote'], reading_scope=scope, source_json=source, location_json=location, snapshot_sha256=digest(frozen))
            return self.evidence_view(db, project, row), status

    def review_view(self, db, project, row):
        validate_request_row(row)
        body = request_data(ReviewRequest, row['request_json'])
        if any(row[k] != body[k] for k in ('claim_revision','project_reference_id','status','relevance','reason','narrowed_statement','limitations')) or row['evidence_ids_json'] != body['evidence_ids'] or row['decided_by'] != self.store.user_id:
            raise source_conflict()
        self.evidence_by_ids(db, project, row['claim_id'], row['claim_revision'], row['project_reference_id'], body['evidence_ids'])
        return dict(id=row['id'], claim_id=row['claim_id'], decided_by=row['decided_by'], created_at=iso(row['created_at']), **body)

    def create_review(self, project, identity, request, key):
        require_key(key); body = request_data(ReviewRequest, request)
        with self.store.connection(write=True) as db:
            self.lock(db, project); self.claim_row(db, project, identity)
            row = self.replay(db, 'literature_claim_reviews', project, key, body, identity)
            status = 200 if row else 201
            if not row:
                self.claim_row(db, project, identity, body['claim_revision'], current=True)
                reference = self.literature.require_reference(db, project, body['project_reference_id'])
                self.evidence_by_ids(db, project, identity, body['claim_revision'], reference['id'], body['evidence_ids'])
                row = self.insert(db, 'literature_claim_reviews', project, key, body, id=str(uuid4()), claim_id=identity,
                    reference_id=reference['reference_id'], evidence_ids_json=body['evidence_ids'], decided_by=self.store.user_id,
                    **{k:v for k,v in body.items() if k!='evidence_ids'})
            return self.review_view(db, project, row), status

    def history(self, project, identity, revision=None, page=1, *, reviews=False):
        table = 'literature_claim_reviews' if reviews else 'literature_claim_evidence'
        with self.store.connection() as db:
            _, version = self.claim_row(db, project, identity, revision)
            args = (project, self.store.user_id, identity, version['revision'])
            where = 'project_id=%s AND user_id=%s AND claim_id=%s AND claim_revision=%s'
            total = db.execute('SELECT count(*) AS n FROM '+table+' WHERE '+where, args).fetchone()['n']
            if reviews:
                rows = db.execute('SELECT * FROM '+table+' WHERE '+where+' ORDER BY created_at DESC,id LIMIT 10 OFFSET %s', (*args,(page-1)*10)).fetchall()
                items = [self.review_view(db, project, row) for row in rows]
            else:
                # Resolve bibliography for this evidence page in one bounded read.
                # Abstracts prefer their own saved search; other sources use the first saved record.
                rows = db.execute('''SELECT e.*, b.pmid AS bibliography_pmid,
                    h.title AS bibliography_title, h.hit_pmid AS bibliography_hit_pmid
                    FROM (SELECT * FROM literature_claim_evidence WHERE '''+where+''' ORDER BY created_at DESC,id LIMIT 10 OFFSET %s) e
                    JOIN literature_records b ON b.id=e.reference_id
                    LEFT JOIN LATERAL (
                        SELECT s.record_json->>'title' AS title, s.record_json->>'pmid' AS hit_pmid
                        FROM literature_search_hits s
                        WHERE s.project_reference_id=e.project_reference_id AND s.project_id=e.project_id
                          AND s.user_id=e.user_id AND s.reference_id=e.reference_id
                        ORDER BY (s.task_id=e.source_json->>'search_id') DESC, s.created_at ASC,s.id ASC LIMIT 1
                    ) h ON TRUE ORDER BY e.created_at DESC,e.id''', (*args,(page-1)*10)).fetchall()
                items = []
                for row in rows:
                    view = self.evidence_view(db, project, row)
                    if row['bibliography_hit_pmid'] != row['bibliography_pmid']:
                        raise source_conflict()
                    view['bibliography'] = dict(title=row['bibliography_title'] or '', pmid=row['bibliography_pmid'])
                    items.append(view)
            return dict(items=items, total=total, page=page, page_size=10)

    def supplement(self, project, identity, request, key):
        require_key(key); body = request_data(SupplementRequest, request)
        with self.store.connection(write=True) as db:
            self.lock(db, project)
            self.claim_row(db, project, identity)
            existing = db.execute('SELECT * FROM literature_claim_supplements WHERE claim_id=%s', (identity,)).fetchone()
            if existing:
                validate_request_row(existing)
                if existing['idempotency_key'] != key or existing['request_digest'] != digest(body):
                    raise StorageError('literature_supplement_limit', '此论述已创建一轮补搜，最多20篇；请继续既有任务。', 409)
                task = self.store.require_task(db, existing['task_id'])
                return dict(task=self.store.public_task(task), round=1, limit=20), 200
            _, version = self.claim_row(db, project, identity, body['claim_revision'], current=True)
            project_row = self.store.require_project(db, project)
            topic = project_row.get('research_topic') or version['content'][:2000]
            search = SearchRequest(research_topic=topic, source_context=dict(kind='section', label='Claim supplement', text=version['content']),
                query=body['query'], limit=20, output_language=version['output_language'])
            task, _ = self.literature.create_in_transaction(db, project, search, 'claim-supplement:'+identity)
            self.insert(db, 'literature_claim_supplements', project, key, body, claim_id=identity, claim_revision=version['revision'], task_id=task['id'], round=1, candidate_limit=20)
            return dict(task=task, round=1, limit=20), 202

    def assistance_snapshot(self, project, request):
        ids = request.get('evidence_ids')
        if not isinstance(ids, list) or not 1<=len(ids)<=20 or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise invalid('请选择实际证据。')
        with self.store.connection() as db:
            _, version = self.claim_row(db, project, request['claim_id'], request['claim_revision'], current=True)
            reference = self.literature.require_reference(db, project, request['project_reference_id'])
            evidence = self.evidence_by_ids(db, project, request['claim_id'], version['revision'], reference['id'], ids)
            # Freeze the same retrieval history as the first abstract; material references use latest saved bibliography.
            search = next((e['source']['search_id'] for e in evidence if e['reading_scope']=='abstract'), None)
            reference_view = self.literature.reference_view(db, reference, search)
            return dict(project_id=project, claim=dict(id=request['claim_id'], revision=version['revision'],
                **{k:version[k] for k in ('content','context','output_language')}), project_reference_id=reference['id'],
                # Saved context is display metadata, outside the frozen assistance source contract.
                reference=dict(id=reference['id'], record=reference_view['record'], source={k:iso(v) if isinstance(v, datetime) else v for k,v in reference_view['source'].items() if k != 'source_context'}),
                evidence=evidence, output_language=request['output_language'])

    def assert_assistance_inputs_current(self, project, snapshot):
        try:
            request = dict(claim_id=snapshot['claim']['id'], claim_revision=snapshot['claim']['revision'],
                project_reference_id=snapshot['project_reference_id'], evidence_ids=[e['id'] for e in snapshot['evidence']],
                output_language=snapshot['output_language'])
            if snapshot['project_id'] != project or self.assistance_snapshot(project, request) != snapshot:
                raise source_conflict()
        except (KeyError, TypeError, ValueError) as exc:
            raise source_conflict() from exc

    def comparison_snapshot(self, project, request):
        ids=request['evidence_ids']
        if not 2<=len(ids)<=20 or len(set(ids))!=len(ids): raise invalid('多来源比较需要不同证据。')
        with self.store.connection() as db:
            _,version=self.claim_row(db,project,request['claim_id'],request['claim_revision'],current=True)
            evidence=[];references={}
            for identity in ids:
                row=db.execute('''SELECT * FROM literature_claim_evidence WHERE id=%s AND project_id=%s AND user_id=%s
                    AND claim_id=%s AND claim_revision=%s''',(identity,project,self.store.user_id,request['claim_id'],version['revision'])).fetchone()
                if not row: raise invalid('证据不属于此项目和论述版本。')
                actual=self.evidence_view(db,project,row)
                evidence.append(actual)
                ref=actual['project_reference_id']
                if ref not in references:
                    # All selected quote sources are reconstructed above; freeze a
                    # concise bibliography instead of repeating every abstract.
                    search=actual['source'].get('search_id')
                    r=self.literature.reference_view(db,self.literature.require_reference(db,project,ref),search)
                    references[ref]=dict(id=ref,record={k:v for k,v in r['record'].items() if k!='abstract'},
                        bibliography_source=dict(search_id=r['source']['search_id'],receipt_id=r['source']['receipt_id'],source_kind=r['source']['source_kind']))
            if len(references)<2: raise invalid('比较至少需要两个不同项目引用的实际证据。')
            return dict(project_id=project,claim=dict(id=request['claim_id'],revision=version['revision'],
                **{k:version[k] for k in ('content','context','output_language')}),references=list(references.values()),
                evidence=evidence,output_language=request['output_language'])

    def assert_comparison_inputs_current(self, project, snapshot):
        try:
            request=dict(claim_id=snapshot['claim']['id'],claim_revision=snapshot['claim']['revision'],
                evidence_ids=[e['id'] for e in snapshot['evidence']],output_language=snapshot['output_language'])
            if snapshot['project_id']!=project or self.comparison_snapshot(project,request)!=snapshot: raise source_conflict()
        except (KeyError,TypeError,ValueError) as exc: raise source_conflict() from exc
