"""Exact-material consent and admission, all decisions under the existing write lock."""
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.core.exceptions import StorageError
from app.adapters.task_store import source_conflict
from app.domain.literature.service import digest
from app.domain.manuscripts.service import now
from app.domain.manuscripts.sources import require_visible_snapshot, writing_changes as changes
from app.domain.dataset_preparation.service import require_key, append_checkpoint
from .bundle import build_bundle, require_current_source_projection, validate_bundle
from .live_contracts import PreviewRequest, AuthorizationRequest, LiveWritingRequest, WORKFLOW,preview_data
from .policy import POLICY_VERSION, ENDPOINT, EXTERNAL_STORAGE_NOTICE, capabilities
from .frozen import contract,bundle_contract,execution_settings,SCI_ARTICLE_PROSE_REVISION
from app.domain.admin_configuration.bindings import resolve,bind
from app.domain.manuscripts.delivery_context import resolve_document_context

def denied():
    return StorageError('manuscript_writing_not_authorized','外发包、逻辑任务或有效授权不匹配。',409)


def revisable_draft(row, task):
    candidate, original = row['candidate_json'], row['request_json']
    if (task['status'] != 'succeeded' or not candidate or row['published_revision'] is not None
            or original['mode'] != 'full_draft'):
        return False
    if candidate.get('thesis_context'):
        return original.get('schema_version') == 3
    return (original.get('schema_version') in (2, 4)
            and candidate.get('article_type', 'research') in ('research', 'narrative_review'))

class LiveWritingService:
    def __init__(self, assets):
        from .service import WritingService
        self.writing=WritingService(assets);self.manuscripts=self.writing.manuscripts;self.store=self.writing.store

    def bundle(self,db,project,bundle_id):
        self.store.require_project(db,project)
        row=db.execute('SELECT * FROM manuscript_writing_bundles WHERE id=%s AND project_id=%s AND user_id=%s',(bundle_id,project,self.store.user_id)).fetchone()
        if not row: raise denied()
        result={**row['bundle_json'],**{k:v for k,v in row.items() if k!='bundle_json'}}
        try:
            validate_bundle(result)
            configuration=resolve(db,kind='writing_bundle',object_id=bundle_id)
            frozen=result.get('execution_contract')
            if configuration is not None:
                if frozen is None:
                    raise ValueError('Bundle binding mismatch')
                bound = contract(configuration,schema_version=frozen['schema_version'],
                    instruction_revision=frozen.get('instruction_revision'),document_kind=frozen.get('document_kind','sci'),
                    article_instruction_revision=frozen.get('article_instruction_revision'),
                    source_selection_version=frozen.get('source_selection_version'),
                    school_presentation_version=frozen.get('school_presentation_version'))
                if execution_settings(frozen) != execution_settings(bound):
                    raise ValueError('Bundle binding mismatch')
            elif frozen is not None:
                if frozen.get('schema_version') not in (2,3,4) or frozen.get('origin')!='installed':raise ValueError('Bundle binding mismatch')
        except (ValueError,KeyError,TypeError): raise source_conflict() from None
        require_visible_snapshot(self.manuscripts.assets, db, project, result['base_snapshot'])
        return result

    def current(self,db,bundle):
        version=self.manuscripts.version(db,bundle['project_id'],bundle['manuscript_id'],bundle['request_json']['base_revision'])
        root=self.manuscripts.root(db,bundle['project_id'],bundle['manuscript_id'])
        if (root['current_revision']!=bundle['request_json']['base_revision'] or version['id']!=bundle['base_version_id']
            or version['snapshot_json']!=bundle['base_snapshot'] or changes(self.manuscripts,bundle['project_id'],bundle['base_snapshot'])): raise source_conflict()
        self.require_customer_writing_input(db, bundle['project_id'], bundle['request_json'], bundle['base_snapshot'])
        if bundle['request_json'].get('revision_of_request_id'):
            sections = self.revision_sections(db, bundle['project_id'], bundle['manuscript_id'],
                                              version['id'], bundle['request_json'])
            if sections != bundle['revision_sections']:
                raise source_conflict()
        require_current_source_projection(bundle)

    def revision_sections(self, db, project, identity, version_id, request):
        """Recover the exact successful parent within its original owner/project/manuscript scope."""
        from .bundle import safe_text
        row, task = self.writing.row(db, project, identity, request['revision_of_request_id'])
        candidate, original = row['candidate_json'], row['request_json']
        school = bool(candidate and candidate.get('thesis_context'))
        if (not revisable_draft(row, task) or row['base_version_id'] != version_id
                or school != (request['schema_version'] == 3)
                or not school and candidate.get('article_type', 'research') != request.get('article_type')
                or any(original.get(key) != request.get(key) for key in
                       ('selected_source_ids', 'selected_evidence_ids', 'output_language', 'base_revision',
                        'document_context_version', 'keywords', 'acknowledgements', 'brief_limits'))
                or original.get('validation_source_ids', []) != request.get('validation_source_ids', [])):
            raise source_conflict()
        def paragraph(p):
            return dict(text=safe_text(p['text']), source_aliases=p.get('suggested_source_aliases', []),
                        evidence_aliases=p.get('suggested_evidence_aliases', []))
        if school:
            from .school_live import WRITABLE
            return [dict(id=f'chapter{i}', paragraphs=[paragraph(p) for p in section['paragraphs']])
                    for i, section in enumerate(candidate['sections'], 1) if section['purpose'] in WRITABLE]
        return [dict(id=section['id'], paragraphs=[paragraph(p) for p in section['paragraphs']])
                for section in candidate['sections'] if section['id'] != 'references' and section['paragraphs']]

    def require_customer_writing_input(self, db, project, request, snapshot):
        if not self.manuscripts.assets.customer:
            return
        if snapshot.get('thesis_context'):
            if request['schema_version'] != 3:
                raise StorageError('customer_operation_forbidden', '毕业论文须使用已确认学校章节的受控写作流程。', 403)
            return
        kind = request.get('article_type')
        if request['schema_version'] != 4 or request.get('document_kind') != 'sci' or kind not in ('research', 'narrative_review'):
            raise StorageError('customer_operation_forbidden', 'SCI 客户写作须使用受控的研究型论文或综述流程。', 403)
        plan = snapshot.get('paper_plan')
        if plan:
            expected = plan['kind']
        else:
            intake = db.execute('SELECT sci_settings_json FROM research_intakes WHERE project_id=%s', (project,)).fetchone()
            settings = intake['sci_settings_json'] if intake else None
            expected = settings['article_type'] if settings else kind
        if expected != kind:
            raise StorageError('manuscript_article_type_changed', '论文类型与项目资料不一致，请重新准备写作预览。', 422)
        if kind == 'narrative_review':
            from app.domain.manuscripts.paper_plan import require_review_heading_language
            require_review_heading_language(plan, request['output_language'])
            if not request['selected_evidence_ids']:
                raise StorageError('manuscript_writing_evidence_required', '综述须选择至少一项已核验文献证据。', 422)
            return
        selected = set(request['selected_source_ids'])
        from .paper_context import is_note
        supported_result = any(
            paragraph['source_ids'] and set(paragraph['source_ids']) <= selected
            for group in snapshot['results_groups'] for paragraph in group['paragraphs']
            if (paragraph['origin'] == 'computed_result' or paragraph['id'] == 'results:reported'
                or snapshot.get('paper_plan', {}).get('kind') == 'research' and is_note(paragraph))
        )
        from app.domain.manuscripts.research_sources import KINDS
        fixed_research = any(source['id'] in selected and source['kind'] in KINDS and source['content'].get('facts')
                             for source in snapshot['sources'])
        findings = {section['id']: section['text'] for section in (plan or {}).get('sections', []) if section['text'].strip()}
        project_finding = any(
            paragraph['origin'] == 'user_provided' and not paragraph['source_ids']
            and paragraph['id'] == 'paper-finding:' + group['id'] and paragraph['text'] == findings[group['id']]
            for group in snapshot['results_groups'] if group['id'] in findings for paragraph in group['paragraphs']
        )
        if not (supported_result or fixed_research or project_finding):
            raise StorageError('manuscript_writing_evidence_required', '请在项目信息中补充主要结果。', 422)

    @staticmethod
    def bundle_view(bundle):
        return {k:v for k,v in bundle.items() if k not in ('base_snapshot','request_key','request_digest','user_id','revision_sections')}

    def preview(self,project,identity,request,key):
        require_key(key);body=preview_data(request)
        with self.store.connection(write=True) as db:
            root=self.manuscripts.root(db,project,identity)
            school=resolve_document_context(db,project,self.store.user_id,manuscript_id=identity)['document_kind']=='thesis'
            requested_school=body.get('document_kind')=='thesis' if body['schema_version']==4 else body['schema_version']==3
            if school!=requested_school:raise StorageError('manuscript_writing_not_authorized','文章协议与文稿根类型不匹配。',422)
            old=db.execute('SELECT id,request_digest FROM manuscript_writing_bundles WHERE project_id=%s AND user_id=%s AND request_key=%s',(project,self.store.user_id,key)).fetchone()
            request_digest=digest(dict(manuscript_id=identity,input=body))
            if old:
                if old['request_digest']!=request_digest: raise StorageError('task_idempotency_conflict','预览标识已用于其他材料。',409)
                return self.bundle_view(self.bundle(db,project,old['id'])),200
            version=self.manuscripts.version(db,project,identity,body['base_revision'])
            if root['current_revision']!=body['base_revision'] or self.store.require_task(db,version['task_id'])['status']!='succeeded': raise source_conflict()
            if changes(self.manuscripts,project,version['snapshot_json']): raise source_conflict()
            self.require_customer_writing_input(db, project, body, version['snapshot_json'])
            if body['mode']=='rewrite_section' and not version['snapshot_json'].get('sections'): raise StorageError('manuscript_writing_base_incomplete','重写需要已发布完整稿。',409)
            configuration=resolve(db)
            schema_version=4 if body['schema_version']==4 else (3 if school else 2)
            prose_revision=SCI_ARTICLE_PROSE_REVISION if schema_version==4 and not school else None
            from .school_presentation import PRESENTATION_VERSION
            presentation = (PRESENTATION_VERSION if schema_version == 3 and body['mode'] == 'full_draft'
                            and body.get('document_context_version') == 'selected-text-v1' else None)
            sections = self.revision_sections(db, project, identity, version['id'], body) if body.get('revision_of_request_id') else None
            try:
                frozen=contract(configuration,schema_version=schema_version,document_kind='thesis' if school else 'sci',
                                article_instruction_revision=prose_revision,source_selection_version=2,
                                school_presentation_version=presentation)
                data=build_bundle(version['snapshot_json'],body,execution_contract=frozen,revision_sections=sections)
            except (ValueError,KeyError,TypeError) as exc:
                if not school:raise StorageError('manuscript_writing_selection_invalid','文章结构、写作范围或所选证据与冻结基础稿不匹配。',422) from exc
                raise StorageError('manuscript_writing_selection_invalid','学校章节、语言或所选用途与冻结确认不匹配；受保护章节不能请求模型生成。',422) from exc
            data.update(base_snapshot=version['snapshot_json'],request_json=body)
            identity_id=str(uuid4());timestamp=now()
            db.execute('INSERT INTO manuscript_writing_bundles(id,project_id,user_id,manuscript_id,base_version_id,request_key,request_digest,bundle_sha256,bundle_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (identity_id,project,self.store.user_id,identity,version['id'],key,request_digest,data['bundle_sha256'],Jsonb(data),timestamp))
            bind(db,kind='writing_bundle',object_id=identity_id,version=configuration)
            return self.bundle_view(self.bundle(db,project,identity_id)),201

    def get_preview(self,project,identity,bundle_id):
        with self.store.connection() as db:
            self.manuscripts.root(db,project,identity);bundle=self.bundle(db,project,bundle_id)
            if bundle['manuscript_id']!=identity: raise denied()
            return self.bundle_view(bundle)

    def list_previews(self,project,identity):
        with self.store.connection() as db:
            self.manuscripts.root(db,project,identity)
            rows=db.execute('SELECT id FROM manuscript_writing_bundles WHERE project_id=%s AND user_id=%s AND manuscript_id=%s ORDER BY created_at DESC,id',(project,self.store.user_id,identity)).fetchall()
            items=[]
            for row in rows:
                try:
                    items.append(self.bundle_view(self.bundle(db,project,row['id'])))
                except StorageError as exc:
                    if exc.code!='manuscript_source_not_visible': raise
            return dict(items=items,capabilities=capabilities(resolve(db)))

    def authorization(self,db,project,identity):
        self.store.require_project(db,project)
        row=db.execute('SELECT * FROM manuscript_writing_authorizations WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row: raise denied()
        if digest(row['manifest_json'])!=row['manifest_sha256']: raise source_conflict()
        return row

    def authorize(self,project,request,key):
        require_key(key);body=AuthorizationRequest.model_validate(request).model_dump(mode='json') if isinstance(request,dict) else request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            old=db.execute('SELECT * FROM manuscript_writing_authorizations WHERE project_id=%s AND user_id=%s AND request_key=%s',(project,self.store.user_id,key)).fetchone()
            if old:
                if old['request_digest']!=digest(body): raise StorageError('task_idempotency_conflict','授权标识已用于不同清单。',409)
                return self.auth_view(db,old),200
            materials=[];limits=[]
            for task in body['tasks']:
                for ref in task['bundles']:
                    bundle=self.bundle(db,project,ref['bundle_id']);self.current(db,bundle)
                    if bundle['bundle_sha256']!=ref['bundle_sha256']: raise denied()
                    frozen=bundle_contract(bundle)
                    expected_thesis=frozen['schema_version']==3 or (frozen['schema_version']==4 and frozen.get('document_kind')=='thesis')
                    if (resolve_document_context(db,project,self.store.user_id,manuscript_id=bundle['manuscript_id'])['document_kind']=='thesis')!=expected_thesis:raise denied()
                    limits.append(frozen)
                    materials.append(dict(logical_task_id=task['logical_task_id'],bundle_id=bundle['id'],bundle_sha256=bundle['bundle_sha256'],
                        wire_bytes=bundle['wire_bytes'],input_token_allowance=bundle['input_token_allowance'],reserved_micro_usd=bundle['reserved_micro_usd'],policy=bundle['policy_json']))
            if len(body['tasks'])!=4 and any(value['schema_version']==1 for value in limits):
                raise StorageError('manuscript_writing_not_authorized','包含旧协议请求包时仍需四个明确逻辑任务；新数值协议可只选择实际需要的任务。',422)
            caps={key:min(value[key] for value in limits) for key in ('batch_max_posts','max_corrections')}
            manifest=dict(schema_version=2,confirmed=True,tasks=body['tasks'],materials=materials,
                endpoint=ENDPOINT,background=True,store=True,service_tier='default',
                external_storage_notice=EXTERNAL_STORAGE_NOTICE,
                max_posts=caps['batch_max_posts'],max_corrections=caps['max_corrections'])
            identity=str(uuid4());timestamp=now()
            # Historical tables require non-null cap columns. New grants use only the signed call counts.
            db.execute('INSERT INTO manuscript_writing_authorizations(id,project_id,user_id,request_key,request_digest,manifest_json,manifest_sha256,status,revision,max_posts,cap_micro_usd,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,\'active\',1,%s,%s,%s)',
                (identity,project,self.store.user_id,key,digest(body),Jsonb(manifest),digest(manifest),manifest['max_posts'],0,timestamp))
            for task in body['tasks']:
                db.execute('INSERT INTO manuscript_writing_authorized_tasks(authorization_id,logical_task_id,project_id,user_id,bundles_json,cap_micro_usd) VALUES (%s,%s,%s,%s,%s,%s)',(identity,task['logical_task_id'],project,self.store.user_id,Jsonb(task['bundles']),0))
            return self.auth_view(db,self.authorization(db,project,identity)),201

    def auth_view(self,db,row):
        counts,occupied=usage(db,row['id'])
        return dict(id=row['id'],project_id=row['project_id'],status=row['status'],revision=row['revision'],
            manifest=row['manifest_json'],manifest_sha256=row['manifest_sha256'],created_at=row['created_at'],closed_at=row['closed_at'],
            occupied_posts=sum(counts.values()),occupied_micro_usd=sum(occupied.values()),logical_task_usage=[dict(logical_task_id=t['logical_task_id'],occupied_posts=counts.get(t['logical_task_id'],0),occupied_micro_usd=occupied.get(t['logical_task_id'],0)) for t in row['manifest_json']['tasks']])

    def list_authorizations(self,project):
        with self.store.connection() as db:
            return dict(items=[self.auth_view(db,r) for r in db.execute('SELECT * FROM manuscript_writing_authorizations WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id',(project,self.store.user_id))])

    def get_authorization(self,project,identity):
        with self.store.connection() as db: return self.auth_view(db,self.authorization(db,project,identity))

    def close(self,project,identity):
        with self.store.connection(write=True) as db:
            row=self.authorization(db,project,identity)
            if row['status']=='active': db.execute("UPDATE manuscript_writing_authorizations SET status='closed',revision=revision+1,closed_at=%s WHERE id=%s",(now(),identity))
            return self.auth_view(db,self.authorization(db,project,identity))

    def require_authorized(self,db,project,request,bundle,*,current=True):
        auth=self.authorization(db,project,request['authorization_id'])
        if auth['status']!='active':
            raise StorageError('manuscript_writing_authorization_closed','写作授权已关闭，请重新读取并选择有效授权。',409)
        grant=db.execute('SELECT * FROM manuscript_writing_authorized_tasks WHERE authorization_id=%s AND logical_task_id=%s',(auth['id'],request['logical_task_id'])).fetchone()
        ref=dict(bundle_id=bundle['id'],bundle_sha256=bundle['bundle_sha256'])
        if not grant or ref not in grant['bundles_json'] or request['bundle_sha256']!=bundle['bundle_sha256']: raise denied()
        expected=next((t for t in auth['manifest_json']['tasks'] if t['logical_task_id']==request['logical_task_id']),None)
        manifest=auth['manifest_json']
        if not expected or expected['bundles']!=grant['bundles_json'] or auth['max_posts']!=manifest['max_posts']:
            raise source_conflict()
        if current: self.current(db,bundle)
        return auth,grant

    def create(self,project,identity,request,key):
        require_key(key);execution=LiveWritingRequest.model_validate(request).model_dump(mode='json') if isinstance(request,dict) else request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.manuscripts.root(db,project,identity)
            old=self.store.find_request(db,project,'manuscript_writing',key)
            if old:
                if old['input_snapshot'].get('execution')!=execution or old['input_snapshot']['manuscript_id']!=identity: raise StorageError('task_idempotency_conflict','写作标识冲突。',409)
                request_id=old['id'];status=200
            else:
                bundle=self.bundle(db,project,execution['bundle_id'])
                if bundle['manuscript_id']!=identity: raise denied()
                frozen=bundle_contract(bundle);expected_thesis=frozen['schema_version']==3 or (frozen['schema_version']==4 and frozen.get('document_kind')=='thesis')
                if (resolve_document_context(db,project,self.store.user_id,manuscript_id=identity)['document_kind']=='thesis')!=expected_thesis:raise denied()
                self.require_authorized(db,project,execution,bundle)
                request_id=str(uuid4());timestamp=now()
                snap=dict(schema_version=2,project_id=project,workflow_version=WORKFLOW,input=bundle['request_json'],execution=execution,
                    base_snapshot=bundle['base_snapshot'],base_version_id=bundle['base_version_id'],manuscript_id=identity,
                    prompt_version='sci-writing-v2',policy_version=POLICY_VERSION,request_id=request_id)
                task=dict(id=request_id,project_id=project,user_id=self.store.user_id,task_type='manuscript_writing',idempotency_key=key,input_digest=digest(snap),input_snapshot=snap,workflow_version=WORKFLOW,status='queued',phase='write',revision=1,current_attempt=0,reason_code=None,created_at=timestamp,updated_at=timestamp)
                self.store.insert_task(db,task)
                configuration=resolve(db,kind='writing_bundle',object_id=bundle['id'])
                bind(db,kind='task',object_id=request_id,version=configuration)
                db.execute('INSERT INTO manuscript_writing_requests(task_id,project_id,user_id,manuscript_id,base_version_id,request_json,input_snapshot,input_digest,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(request_id,project,self.store.user_id,identity,bundle['base_version_id'],Jsonb(bundle['request_json']),Jsonb(snap),digest(snap),timestamp,timestamp))
                append_checkpoint(db,task,'check','check',dict(schema_version=2,input_digest=task['input_digest']))
                self.store.append_event(db,task,'created');self.store.enqueue(db,task);status=202
        return self.writing.get(project,identity,request_id),status

def usage(db,authorization_id):
    from app.domain.model_usage.accounting import accounting_projection
    counts={};occupied={}
    for call in db.execute('''SELECT c.*, a.logical_task_id FROM manuscript_writing_call_admissions a
            JOIN model_calls c ON c.id=a.model_call_id
            WHERE a.authorization_id=%s AND a.status<>'released' ''', (authorization_id,)):
        amount, _ = accounting_projection(call, None)
        logical = call['logical_task_id']
        counts[logical]=counts.get(logical,0)+1;occupied[logical]=occupied.get(logical,0)+amount
    return counts,occupied

def admission_context(store,db,task):
    from app.domain.report_collections.service import scoped_store
    from .service import require_snapshot
    snap=require_snapshot(task)
    assets=scoped_store(store.user_id,store.config)
    user=db.execute('SELECT role FROM users WHERE id=%s',(store.user_id,)).fetchone()
    assets.customer=bool(user and user['role']=='customer')
    service=LiveWritingService(assets)
    bundle=service.bundle(db,task['project_id'],snap['execution']['bundle_id'])
    if bundle['manuscript_id']!=snap['manuscript_id'] or bundle['base_snapshot']!=snap['base_snapshot'] or bundle['request_json']!=snap['input']: raise source_conflict()
    auth,grant=service.require_authorized(db,task['project_id'],snap['execution'],bundle)
    return bundle,auth,grant

def reserve_admission(store,db,task,request):
    bundle,auth,grant=admission_context(store,db,task)
    expected=bundle['policy_json']
    if request.policy.model_dump(mode='json')!=expected or request.input_digest!=bundle['gateway_digest'] or request.input_token_allowance!=bundle['input_token_allowance']: raise denied()
    counts = {row['logical_task_id']: row['posts'] for row in db.execute(
        "SELECT logical_task_id,count(*) AS posts FROM manuscript_writing_call_admissions "
        "WHERE authorization_id=%s AND status<>'released' GROUP BY logical_task_id", (auth['id'],))}
    logical = grant['logical_task_id']
    next_counts={**counts,logical:counts.get(logical,0)+1}
    if (sum(next_counts.values())>auth['max_posts'] or sum(max(n-1,0) for n in next_counts.values())>auth['manifest_json']['max_corrections']):
        raise StorageError('manuscript_writing_not_authorized','本次写作超出已确认的调用次数或修正次数，请核对授权。',409)
    return bundle,auth,grant

def insert_admission(db,call,context):
    bundle,auth,grant=context
    db.execute("INSERT INTO manuscript_writing_call_admissions(model_call_id,bundle_id,authorization_id,logical_task_id,project_id,user_id,reserved_micro_usd,status,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'reserved',%s)",
        (call['id'],bundle['id'],auth['id'],grant['logical_task_id'],call['project_id'],call['user_id'],0,now()))

def begin_admission(store,db,task,call):
    bundle,auth,grant=admission_context(store,db,task)
    row=db.execute('SELECT * FROM manuscript_writing_call_admissions WHERE model_call_id=%s',(call['id'],)).fetchone()
    if not row or row['status']!='reserved' or row['bundle_id']!=bundle['id'] or row['authorization_id']!=auth['id'] or row['logical_task_id']!=grant['logical_task_id']: raise denied()
    db.execute("UPDATE manuscript_writing_call_admissions SET status='submission_started',submission_started_at=%s WHERE model_call_id=%s",(now(),call['id']))
