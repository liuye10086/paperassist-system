"""Owner-scoped cloud requests; immutable identities precede remote effects."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.adapters.task_store import TaskStore
from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import digest
from .settings import load_settings
from .provider import ProviderError, BioCloudProvider
from .requests import PART_SIZE, CloudInputVersion


def create_provider(settings) -> BioCloudProvider:
    from app.adapters.bio_cloud.aws import AwsBioProvider
    return AwsBioProvider(settings)


def error(code, message, status=409):
    return StorageError('bio_cloud_' + code, message, status)


def now():
    return datetime.now(timezone.utc)


def require_key(key):
    from app.domain.bioinformatics.service import require_key as validate
    validate(key)


class CloudService:
    def __init__(self, assets):
        self.assets = assets
        self.store = TaskStore(assets.owner_id, assets.db_config)

    def settings(self):
        try:
            return load_settings()
        except ProviderError:
            raise error('configuration_invalid', '云计算配置无效，请管理员核对配置。') from None

    def ready_settings(self):
        settings = self.settings()
        if not settings.enabled:
            raise error('disabled', '尚未启用外部生信计算；请先完成账号和流程核验。')
        return settings

    @contextmanager
    def provider(self, settings=None):
        instance = None
        try:
            instance = create_provider(settings or self.ready_settings())
            yield instance
        except ProviderError:
            raise error('provider_unavailable', '云服务请求未完成，请保留当前记录并核对状态。', 503) from None
        finally:
            if instance is not None:
                instance.close()

    def require_upload(self, db, project, identifier):
        self.store.require_project(db, project)
        row = db.execute('SELECT * FROM bio_cloud_uploads WHERE id=%s AND project_id=%s AND owner_id=%s', (identifier, project, self.store.user_id)).fetchone()
        if row is None:
            raise error('not_found', '云上传记录不存在。', 404)
        return dict(row)

    def require_run(self, db, project, identifier):
        self.store.require_project(db, project)
        row = db.execute('SELECT * FROM bio_cloud_runs WHERE id=%s AND project_id=%s', (identifier, project)).fetchone()
        if row is None:
            raise error('not_found', '云计算记录不存在。', 404)
        return dict(row)

    def capabilities(self, project):
        with self.store.connection() as db:
            self.store.require_project(db, project)
        try:
            settings = self.settings()
        except StorageError:
            return dict(provider='aws_healthomics', enabled=False, profiles=[], blockers=['configuration_invalid'], evidence=dict(documentation_supported=True, code_integrated=True, real_data_verified=False))
        profiles = [dict(id=p.id, name=p.name, species=p.species, chemistries=p.chemistries, engine=p.engine, reference_id=p.reference_id,
                         account_verified=p.account_verified, max_input_bytes=p.max_input_bytes,estimated_run_cost_usd=p.estimated_run_cost_usd) for p in settings.profiles]
        blockers = []
        if not settings.enabled:
            blockers.append('cloud_not_enabled')
        if not any(p.account_verified for p in settings.profiles):
            blockers.append('workflow_not_verified')
        return dict(provider='aws_healthomics', region=settings.region, enabled=settings.enabled, profiles=profiles,
                    blockers=blockers, part_size=PART_SIZE,
                    evidence=dict(documentation_supported=True, code_integrated=True, real_data_verified=False))

    @staticmethod
    def public_upload(row):
        return {**{k:row[k] for k in ('id','filename','size_bytes','status','error_code','created_at','updated_at')}, 'part_size':PART_SIZE}

    def public_run(self, db, row):
        request = row['snapshot_json']['request']
        task = self.store.require_task(db, row['task_id'])
        outputs = db.execute('''SELECT o.role,o.file_id,o.size_bytes,o.sha256,f.filename FROM bio_cloud_outputs o
            JOIN files f ON f.id=o.file_id AND f.project_id=o.project_id WHERE o.run_id=%s ORDER BY o.role''', (row['id'],)).fetchall()
        return {**{k:row[k] for k in ('id','status','provider_run_id','provider_state','error_code','cancel_requested','created_at','updated_at')},
                'sample_id':request['sample_id'], 'library_id':request['library_id'], 'profile_id':request['profile_id'],
                'engine':row['snapshot_json']['profile']['engine'], 'task':self.store.public_task(task),
                'outputs':[dict(o) for o in outputs], 'verification':'remote_provider_not_independently_validated'}

    def list_runs(self, project):
        with self.store.connection() as db:
            self.store.require_project(db, project)
            rows = db.execute('SELECT * FROM bio_cloud_runs WHERE project_id=%s ORDER BY created_at DESC LIMIT 50', (project,)).fetchall()
            return {'items':[self.public_run(db, r) for r in rows]}

    def get(self, project, identifier):
        with self.store.connection() as db:
            return self.public_run(db, self.require_run(db, project, identifier))

    def lookup(self, project, key, kind):
        require_key(key)
        table = {'run':'bio_cloud_runs','upload':'bio_cloud_uploads'}[kind]
        with self.store.connection() as db:
            self.store.require_project(db, project)
            row = db.execute(f'SELECT * FROM {table} WHERE project_id=%s AND request_key=%s', (project,key)).fetchone()
            if row is None:
                raise error('not_found', '原请求暂未查到；请继续核对，不生成新的请求标识。', 404)
            return self.public_run(db,row) if kind == 'run' else self.public_upload(row)

    def create(self, project, request, key):
        require_key(key)
        material = request.model_dump(mode='json')
        request_hash = digest(material)
        settings = self.ready_settings()
        with self.store.connection(write=True) as db:
            self.store.require_project(db, project)
            existing = db.execute('SELECT * FROM bio_cloud_runs WHERE project_id=%s AND request_key=%s', (project,key)).fetchone()
            if existing:
                if existing['request_digest'] != request_hash:
                    raise error('idempotency_conflict', '此请求标识已用于不同的云计算参数。')
                return self.public_run(db, existing)
            profiles = [p for p in settings.profiles if p.id == request.profile_id and p.account_verified]
            if len(profiles) != 1:
                raise error('profile_unverified', '请选择已在目标账号和地域核验过的工作流。')
            profile = profiles[0]
            if profile.species != request.species or request.chemistry not in profile.chemistries:
                raise error('profile_mismatch', '物种或建库方案不在该工作流已核验的范围内。')
            if profile.estimated_run_cost_usd is None:
                raise error('price_unverified','此流程的当前分析费用尚未核实，请管理员核对报价。')
            if request.budget_limit_usd < Decimal(str(profile.estimated_run_cost_usd)):
                raise error('budget_exceeded','已确认预算低于核实的预计单次分析费；未提交计算。')
            if db.execute("SELECT 1 FROM bio_cloud_runs WHERE project_id=%s AND status NOT IN ('completed','failed','cancelled') LIMIT 1", (project,)).fetchone():
                raise error('active_run', '当前项目已有未结束或待核实的云任务，请先处理已有任务。')
            uploads = []
            for source in sorted(request.fastqs, key=lambda f:(f.lane,f.chunk,f.read)):
                upload = self.require_upload(db, project, source.upload_id)
                if upload['status'] != 'completed' or not upload['receipt_json']:
                    raise error('input_not_ready', '所有 FASTQ 必须先完成上传和完整性核对。')
                if (upload['region'],upload['bucket']) != (settings.region,settings.input_bucket):
                    raise error('configuration_changed', '上传地域或存储与当前配置不一致，请管理员核对。')
                uploads.append({**source.model_dump(), **{k:upload[k] for k in ('filename','size_bytes','object_key','bucket','region','receipt_json')}})
            if sum(u['size_bytes'] for u in uploads) > profile.max_input_bytes:
                raise error('input_limit', '输入总量超过该工作流允许的上限。', 413)
            if len(uploads)>2 and any('{fastq_r' in value for value in profile.parameters.values()):
                raise error('profile_mismatch', '多 lane 数据需要已核验的样本清单参数，不能套用单文件对参数。')
            identifier, task_id = str(uuid4()), str(uuid4())
            frozen = dict(kind='bio_cloud_run', project_id=project, run_id=identifier, request=material,
                profile=profile.model_dump(mode='json'), inputs=uploads,
                cloud={k:getattr(settings,k) for k in ('region','input_bucket','output_bucket','role_arn')},
                output_prefix=f'paperassist/{project}/bio-cloud/{identifier}/outputs/',
                samplesheet_key=f'paperassist/{project}/bio-cloud/{identifier}/samplesheet.csv')
            frozen['input_version'] = CloudInputVersion(run_id=identifier,profile_id=profile.id,sample_id=request.sample_id,input_sha256=digest(frozen)).model_dump()
            timestamp = now()
            task = dict(id=task_id, project_id=project,user_id=self.store.user_id,task_type='bio_cloud_run',idempotency_key='bio_cloud:'+key,
                input_digest=digest(frozen),input_snapshot=frozen,workflow_version='bio_cloud_run_v1',status='queued',phase='compute',revision=1,current_attempt=0,
                reason_code=None,created_at=timestamp,updated_at=timestamp)
            self.store.insert_task(db,task,validated_file_ids=[])
            db.execute('''INSERT INTO bio_cloud_runs(id,project_id,task_id,request_key,request_digest,request_token,status,snapshot_json,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s)''', (identifier,project,task_id,key,request_hash,str(uuid4()),Jsonb(frozen),timestamp,timestamp))
            for source in request.fastqs:
                db.execute('INSERT INTO bio_cloud_run_inputs(run_id,upload_id,project_id) VALUES(%s,%s,%s)',(identifier,source.upload_id,project))
            self.store.append_event(db,task,'created')
            self.store.enqueue(db,task,validated_file_ids=[])
            return self.public_run(db, self.require_run(db,project,identifier))

    def cancel(self, project, identifier):
        with self.store.connection(write=True) as db:
            row = self.require_run(db,project,identifier)
            if row['status'] in ('completed','cancelled') or row['provider_state'] in ('FAILED','CANCELLED','DELETED'):
                return self.public_run(db,row)
            db.execute('UPDATE bio_cloud_runs SET cancel_requested=true,updated_at=%s WHERE id=%s',(now(),identifier))
            task = self.store.require_task(db,row['task_id'])
            if task['status']=='failed' and (row['provider_run_id'] or row['submitted_at'] is None):
                # A terminal local polling attempt does not mean remote compute
                # stopped. Wake the same identity to cancel/read it, never StartRun.
                revision = task['revision']
                task.update(status='queued',revision=revision+1,reason_code='retry_requested',error_code=None,updated_at=now())
                self.store.update_task(db,task,revision)
                self.store.append_event(db,task,'requeued')
                self.store.enqueue(db,task,validated_file_ids=[])
                db.execute("UPDATE bio_cloud_runs SET poll_failures=0 WHERE id=%s",(identifier,))
            # Let the same fenced executor finish cancellation, including a queued run.
            db.execute('UPDATE task_outbox SET available_at=clock_timestamp() WHERE task_id=%s AND published_at IS NULL',(row['task_id'],))
            return self.public_run(db,self.require_run(db,project,identifier))

    def retry(self, project, identifier):
        with self.store.connection(write=True) as db:
            row = self.require_run(db,project,identifier)
            task = self.store.require_task(db,row['task_id'])
            if row['status']=='submission_unknown' or (not row['provider_run_id'] and row['submitted_at'] is not None) or row['provider_state'] in ('FAILED','CANCELLED','DELETED'):
                raise error('retry_requires_review', '此状态不能自动重新计算。请先核实远端任务；新的付费分析需要重新确认。')
            if task['status']=='failed' and row['status'] in ('blocked','failed'):
                revision = task['revision']
                task.update(status='queued',revision=revision+1,reason_code='retry_requested',error_code=None,updated_at=now())
                self.store.update_task(db,task,revision)
                self.store.append_event(db,task,'requeued')
                self.store.enqueue(db,task,validated_file_ids=[])
                db.execute("UPDATE bio_cloud_runs SET status='pending',poll_failures=0,error_code=NULL WHERE id=%s",(identifier,))
            return self.public_run(db,self.require_run(db,project,identifier))

    def reconcile(self, project, identifier, provider_run_id):
        from app.adapters.task_execution_store import TaskExecutionStore
        from .execution import run_parameters, receipt
        with self.store.connection() as db:
            row = self.require_run(db,project,identifier)
            if row['provider_run_id']:
                if row['provider_run_id']!=provider_run_id:
                    raise error('reconciliation_invalid','此本地任务已关联不同的远端任务。')
                return self.public_run(db,row)
            if row['status']!='submission_unknown':
                raise error('reconciliation_invalid','只有提交结果未知的任务需要查回关联。')
        settings = self.ready_settings()
        snapshot = row['snapshot_json']
        if any(getattr(settings,k)!=v for k,v in snapshot['cloud'].items()):
            raise error('configuration_changed','查回必须使用原任务的地域和账号资源配置。')
        with self.provider(settings) as provider:
            remote = provider.get_run(provider_run_id)
        profile = snapshot['profile']
        expected = dict(run_id=provider_run_id,name=row['task_id'],workflow_id=profile['workflow_id'],
                        workflow_type=profile['workflow_type'],workflow_version=profile['workflow_version'],parameters_sha256=digest(run_parameters(snapshot)))
        if any(remote.get(k)!=value for k,value in expected.items()):
            raise error('reconciliation_invalid','远端任务名、工作流版本或参数摘要与原请求不一致，未建立关联。')
        repository = TaskExecutionStore(config=self.store.config,directory=self.assets.directory)
        receipt(repository,row,remote)
        with self.store.connection(write=True) as db:
            row = self.require_run(db,project,identifier)
            task = self.store.require_task(db,row['task_id'])
            if task['status']=='waiting_confirmation':
                revision = task['revision']
                task.update(status='queued',revision=revision+1,reason_code='confirmation_received',error_code=None,updated_at=now())
                self.store.update_task(db,task,revision)
                self.store.append_event(db,task,'requeued')
                self.store.enqueue(db,task,validated_file_ids=[])
            return self.public_run(db,row)


def recover_receipts(db):
    """Resume known late receipts without ever re-submitting a paid run."""
    rows = db.execute("""SELECT t.* FROM tasks t JOIN bio_cloud_runs r ON r.task_id=t.id
        WHERE t.task_type='bio_cloud_run' AND t.status='waiting_confirmation'
        AND t.reason_code='submission_unknown' AND r.provider_run_id IS NOT NULL
        ORDER BY t.updated_at LIMIT 20""").fetchall()
    for value in rows:
        task = dict(value)
        revision = task['revision']
        task.update(status='queued',revision=revision+1,reason_code='confirmation_received',error_code=None,updated_at=now())
        TaskStore.update_task(db,task,revision)
        TaskStore.append_event(db,task,'requeued')
        TaskStore.enqueue(db,task,validated_file_ids=[])
