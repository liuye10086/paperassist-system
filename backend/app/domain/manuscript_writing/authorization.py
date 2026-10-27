"""Exact-material consent and admission, all decisions under the existing write lock."""
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.core.exceptions import StorageError
from app.adapters.task_store import source_conflict
from app.domain.literature.service import digest
from app.domain.manuscripts.service import now
from app.domain.manuscripts.sources import changes
from app.domain.dataset_preparation.service import require_key, append_checkpoint
from .bundle import build_bundle, validate_bundle
from .live_contracts import PreviewRequest, AuthorizationRequest, LiveWritingRequest, WORKFLOW
from .policy import MAX_POSTS, MAX_CORRECTIONS, TASK_CAP, BATCH_CAP, POLICY_VERSION, capabilities
from .frozen import contract,bundle_contract
from app.domain.admin_configuration.bindings import resolve,bind

def denied():
    return StorageError('manuscript_writing_not_authorized','外发包、逻辑任务或有效授权不匹配。',409)

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
            if configuration is not None or 'execution_contract' in result:
                if configuration is None or result.get('execution_contract')!=contract(configuration):raise ValueError('Bundle binding mismatch')
        except (ValueError,KeyError,TypeError): raise source_conflict() from None
        return result

    def current(self,db,bundle):
        version=self.manuscripts.version(db,bundle['project_id'],bundle['manuscript_id'],bundle['request_json']['base_revision'])
        root=self.manuscripts.root(db,bundle['project_id'],bundle['manuscript_id'])
        if (root['current_revision']!=bundle['request_json']['base_revision'] or version['id']!=bundle['base_version_id']
            or version['snapshot_json']!=bundle['base_snapshot'] or changes(self.manuscripts,bundle['project_id'],bundle['base_snapshot'])): raise source_conflict()

    @staticmethod
    def bundle_view(bundle):
        return {k:v for k,v in bundle.items() if k not in ('base_snapshot','request_key','request_digest','user_id')}

    def preview(self,project,identity,request,key):
        require_key(key);body=PreviewRequest.model_validate(request).model_dump(mode='json') if isinstance(request,dict) else request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            root=self.manuscripts.root(db,project,identity)
            if self.store.require_project(db,project)['project_type']=='thesis': raise StorageError('manuscript_writing_not_authorized','学校稿本批仅支持受控等待；真实模型授权尚未开放。',422)
            old=db.execute('SELECT id,request_digest FROM manuscript_writing_bundles WHERE project_id=%s AND user_id=%s AND request_key=%s',(project,self.store.user_id,key)).fetchone()
            request_digest=digest(dict(manuscript_id=identity,input=body))
            if old:
                if old['request_digest']!=request_digest: raise StorageError('task_idempotency_conflict','预览标识已用于其他材料。',409)
                return self.bundle_view(self.bundle(db,project,old['id'])),200
            version=self.manuscripts.version(db,project,identity,body['base_revision'])
            if root['current_revision']!=body['base_revision'] or self.store.require_task(db,version['task_id'])['status']!='succeeded': raise source_conflict()
            if changes(self.manuscripts,project,version['snapshot_json']): raise source_conflict()
            if body['mode']=='rewrite_section' and not version['snapshot_json'].get('sections'): raise StorageError('manuscript_writing_base_incomplete','重写需要已发布完整稿。',409)
            configuration=resolve(db)
            data=build_bundle(version['snapshot_json'],body,execution_contract=contract(configuration) if configuration else None)
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
            return dict(items=[self.bundle_view(self.bundle(db,project,r['id'])) for r in rows],capabilities=capabilities(resolve(db)))

    def authorization(self,db,project,identity):
        self.store.require_project(db,project)
        row=db.execute('SELECT * FROM manuscript_writing_authorizations WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row: raise denied()
        if digest(row['manifest_json'])!=row['manifest_sha256']: raise source_conflict()
        return row

    def authorize(self,project,request,key):
        require_key(key);body=AuthorizationRequest.model_validate(request).model_dump(mode='json') if isinstance(request,dict) else request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            if self.store.require_project(db,project)['project_type']=='thesis': raise StorageError('manuscript_writing_not_authorized','学校稿真实模型授权尚未开放。',422)
            old=db.execute('SELECT * FROM manuscript_writing_authorizations WHERE project_id=%s AND user_id=%s AND request_key=%s',(project,self.store.user_id,key)).fetchone()
            if old:
                if old['request_digest']!=digest(body): raise StorageError('task_idempotency_conflict','授权标识已用于不同清单。',409)
                return self.auth_view(db,old),200
            materials=[];limits=[]
            for task in body['tasks']:
                for ref in task['bundles']:
                    bundle=self.bundle(db,project,ref['bundle_id']);self.current(db,bundle)
                    if bundle['bundle_sha256']!=ref['bundle_sha256']: raise denied()
                    limits.append(bundle_contract(bundle))
                    materials.append(dict(logical_task_id=task['logical_task_id'],bundle_id=bundle['id'],bundle_sha256=bundle['bundle_sha256'],
                        wire_bytes=bundle['wire_bytes'],input_token_allowance=bundle['input_token_allowance'],reserved_micro_usd=bundle['reserved_micro_usd'],policy=bundle['policy_json']))
            caps={key:min(value[key] for value in limits) for key in ('batch_max_posts','max_corrections','batch_cap_micro_usd','task_limit_micro_usd')}
            manifest=dict(schema_version=2,confirmed=True,tasks=body['tasks'],materials=materials,
                endpoint='https://api.openai.com/v1/responses',background=True,store=True,service_tier='default',
                external_storage_notice='OpenAI stores background responses; selected material is transmitted externally.',
                max_posts=caps['batch_max_posts'],max_corrections=caps['max_corrections'],cap_micro_usd=caps['batch_cap_micro_usd'],logical_task_cap_micro_usd=caps['task_limit_micro_usd'])
            identity=str(uuid4());timestamp=now()
            db.execute('INSERT INTO manuscript_writing_authorizations(id,project_id,user_id,request_key,request_digest,manifest_json,manifest_sha256,status,revision,max_posts,cap_micro_usd,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,\'active\',1,%s,%s,%s)',
                (identity,project,self.store.user_id,key,digest(body),Jsonb(manifest),digest(manifest),manifest['max_posts'],manifest['cap_micro_usd'],timestamp))
            for task in body['tasks']:
                db.execute('INSERT INTO manuscript_writing_authorized_tasks(authorization_id,logical_task_id,project_id,user_id,bundles_json,cap_micro_usd) VALUES (%s,%s,%s,%s,%s,%s)',(identity,task['logical_task_id'],project,self.store.user_id,Jsonb(task['bundles']),manifest['logical_task_cap_micro_usd']))
            return self.auth_view(db,self.authorization(db,project,identity)),201

    def auth_view(self,db,row):
        counts,occupied=usage(db,row['id'])
        return dict(id=row['id'],project_id=row['project_id'],status=row['status'],revision=row['revision'],
            manifest=row['manifest_json'],manifest_sha256=row['manifest_sha256'],created_at=row['created_at'],closed_at=row['closed_at'],
            occupied_posts=sum(counts.values()),occupied_micro_usd=sum(occupied.values()),logical_task_usage=[dict(logical_task_id=t['logical_task_id'],occupied_posts=counts.get(t['logical_task_id'],0),occupied_micro_usd=occupied.get(t['logical_task_id'],0)) for t in row['manifest_json']['tasks']])

    def list_authorizations(self,project):
        with self.store.connection() as db:
            if self.store.require_project(db,project)['project_type']=='thesis': raise StorageError('manuscript_writing_not_authorized','学校稿真实模型授权尚未开放。',422)
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
        grant=db.execute('SELECT * FROM manuscript_writing_authorized_tasks WHERE authorization_id=%s AND logical_task_id=%s',(auth['id'],request['logical_task_id'])).fetchone()
        ref=dict(bundle_id=bundle['id'],bundle_sha256=bundle['bundle_sha256'])
        if auth['status']!='active' or not grant or ref not in grant['bundles_json'] or request['bundle_sha256']!=bundle['bundle_sha256']: raise denied()
        expected=next((t for t in auth['manifest_json']['tasks'] if t['logical_task_id']==request['logical_task_id']),None)
        manifest=auth['manifest_json']
        if (not expected or expected['bundles']!=grant['bundles_json'] or grant['cap_micro_usd']!=manifest['logical_task_cap_micro_usd']
            or auth['max_posts']!=manifest['max_posts'] or auth['cap_micro_usd']!=manifest['cap_micro_usd']): raise source_conflict()
        if current: self.current(db,bundle)
        return auth,grant

    def create(self,project,identity,request,key):
        require_key(key);execution=LiveWritingRequest.model_validate(request).model_dump(mode='json') if isinstance(request,dict) else request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.manuscripts.root(db,project,identity)
            if self.store.require_project(db,project)['project_type']=='thesis': raise StorageError('manuscript_writing_not_authorized','学校稿真实模型授权尚未开放。',422)
            old=self.store.find_request(db,project,'manuscript_writing',key)
            if old:
                if old['input_snapshot'].get('execution')!=execution or old['input_snapshot']['manuscript_id']!=identity: raise StorageError('task_idempotency_conflict','写作标识冲突。',409)
                request_id=old['id'];status=200
            else:
                bundle=self.bundle(db,project,execution['bundle_id'])
                if bundle['manuscript_id']!=identity: raise denied()
                self.require_authorized(db,project,execution,bundle)
                request_id=str(uuid4());timestamp=now()
                snap=dict(schema_version=2,project_id=project,workflow_version=WORKFLOW,input=bundle['request_json'],execution=execution,
                    base_snapshot=bundle['base_snapshot'],base_version_id=bundle['base_version_id'],manuscript_id=identity,
                    prompt_version='sci-writing-v2',policy_version=POLICY_VERSION,request_id=request_id)
                task=dict(id=request_id,project_id=project,user_id=self.store.user_id,task_type='manuscript_writing',idempotency_key=key,input_digest=digest(snap),input_snapshot=snap,workflow_version=WORKFLOW,status='queued',phase='write',revision=1,current_attempt=0,reason_code=None,created_at=timestamp,updated_at=timestamp)
                self.store.insert_task(db,task)
                configuration=resolve(db,kind='writing_bundle',object_id=bundle['id'])
                bind(db,kind='task',object_id=request_id,version=configuration)
                if configuration:
                    db.execute("INSERT INTO model_budgets(id,user_id,scope_type,scope_key,project_id,task_id,limit_micro_usd,revision,created_at,updated_at) VALUES (%s,%s,'task',%s,%s,%s,%s,1,%s,%s)",
                        (str(uuid4()),self.store.user_id,request_id,project,request_id,bundle_contract(bundle)['task_limit_micro_usd'],timestamp,timestamp))
                db.execute('INSERT INTO manuscript_writing_requests(task_id,project_id,user_id,manuscript_id,base_version_id,request_json,input_snapshot,input_digest,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(request_id,project,self.store.user_id,identity,bundle['base_version_id'],Jsonb(bundle['request_json']),Jsonb(snap),digest(snap),timestamp,timestamp))
                append_checkpoint(db,task,'check','check',dict(schema_version=2,input_digest=task['input_digest']))
                self.store.append_event(db,task,'created');self.store.enqueue(db,task);status=202
        return self.writing.get(project,identity,request_id),status

def usage(db,authorization_id):
    from app.domain.model_usage.accounting import accounting_projection
    counts={};occupied={}
    for row in db.execute("SELECT * FROM manuscript_writing_call_admissions WHERE authorization_id=%s AND status<>'released'",(authorization_id,)):
        call=db.execute('SELECT * FROM model_calls WHERE id=%s',(row['model_call_id'],)).fetchone()
        reserve=db.execute('SELECT * FROM budget_reservations WHERE call_id=%s LIMIT 1',(call['id'],)).fetchone()
        amount=sum(accounting_projection(call,reserve));logical=row['logical_task_id']
        counts[logical]=counts.get(logical,0)+1;occupied[logical]=occupied.get(logical,0)+amount
    return counts,occupied

def admission_context(store,db,task):
    from app.domain.report_collections.service import scoped_store
    from .service import require_snapshot
    snap=require_snapshot(task)
    service=LiveWritingService(scoped_store(store.user_id,store.config))
    bundle=service.bundle(db,task['project_id'],snap['execution']['bundle_id'])
    if bundle['manuscript_id']!=snap['manuscript_id'] or bundle['base_snapshot']!=snap['base_snapshot'] or bundle['request_json']!=snap['input']: raise source_conflict()
    auth,grant=service.require_authorized(db,task['project_id'],snap['execution'],bundle)
    return bundle,auth,grant

def reserve_admission(store,db,task,request,reserved):
    bundle,auth,grant=admission_context(store,db,task)
    expected=bundle['policy_json']
    if request.policy.model_dump(mode='json')!=expected or request.input_digest!=bundle['gateway_digest'] or request.input_token_allowance!=bundle['input_token_allowance'] or reserved!=bundle['reserved_micro_usd'] or request.tool_reserve_micro_usd!=0: raise denied()
    counts,occupied=usage(db,auth['id']);logical=grant['logical_task_id']
    next_counts={**counts,logical:counts.get(logical,0)+1}
    if (sum(next_counts.values())>auth['max_posts'] or sum(max(n-1,0) for n in next_counts.values())>auth['manifest_json']['max_corrections']
        or sum(occupied.values())+reserved>auth['cap_micro_usd'] or occupied.get(logical,0)+reserved>grant['cap_micro_usd']):
        raise StorageError('model_budget_exceeded','本批授权次数、修正次数或逻辑任务累计预算不足。',409)
    return bundle,auth,grant

def insert_admission(db,call,context,reserved):
    bundle,auth,grant=context
    db.execute("INSERT INTO manuscript_writing_call_admissions(model_call_id,bundle_id,authorization_id,logical_task_id,project_id,user_id,reserved_micro_usd,status,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'reserved',%s)",
        (call['id'],bundle['id'],auth['id'],grant['logical_task_id'],call['project_id'],call['user_id'],reserved,now()))

def begin_admission(store,db,task,call):
    bundle,auth,grant=admission_context(store,db,task)
    row=db.execute('SELECT * FROM manuscript_writing_call_admissions WHERE model_call_id=%s',(call['id'],)).fetchone()
    if not row or row['status']!='reserved' or row['bundle_id']!=bundle['id'] or row['authorization_id']!=auth['id'] or row['logical_task_id']!=grant['logical_task_id']: raise denied()
    db.execute("UPDATE manuscript_writing_call_admissions SET status='submission_started',submission_started_at=%s WHERE model_call_id=%s",(now(),call['id']))
