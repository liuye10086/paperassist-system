"""Owner-scoped preparation creation, persisted review and explicit decisions."""
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Literal
from urllib.parse import quote
from uuid import UUID, uuid4, uuid5

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.adapters.task_store import TaskStore, source_conflict
from app.adapters.prepared_dataset_objects import PreparedDatasetObjects
from app.core.exceptions import StorageError
from app.domain.analysis_sources import DatasetAnalysisSource, raw_dataset_source, prepared_dataset_source
from app.domain.datasets.service import DatasetService
from app.domain.dataset_preparation.contracts import PreparationRecipe, WORKFLOW_VERSION
from app.domain.dataset_preparation.transform import build_recipe, validate_recipe
from app.domain.tasks.contracts import PreparationInputVersion
from app.domain.tasks.waits import get_open_wait, resolve_open_wait


PREPARATION_NAMESPACE = UUID('d54071a5-8040-4ec6-9201-b3b398e254d8')


class PreparationCreateRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    dataset_id: str = Field(min_length=1,max_length=64)
    recipe: PreparationRecipe


class PreparationDecisionRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    operation: Literal['approve','revise']
    wait_id: str = Field(min_length=1,max_length=64)
    checkpoint_id: str = Field(min_length=1,max_length=64)
    expected_task_revision: int = Field(ge=1,lt=2147483647)
    input_version: PreparationInputVersion
    recipe: PreparationRecipe | None = None

    @model_validator(mode='after')
    def recipe_matches_operation(self):
        if (self.recipe is not None) != (self.operation == 'revise'):
            raise ValueError('Only revise requires a complete recipe.')
        return self


class PreparationSnapshot(BaseModel):
    model_config = ConfigDict(strict=True,extra='forbid')
    schema_version: Literal[1]
    kind: Literal['dataset_preparation']
    project_id: str
    filename: str
    source: DatasetAnalysisSource
    recipe: PreparationRecipe
    workflow_version: Literal['dataset_preparation_v1']


class CandidateReference(BaseModel):
    model_config = ConfigDict(strict=True,extra='forbid')
    id: str
    object_key: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size_bytes: int = Field(gt=0,le=4194304)


class PreparationState(BaseModel):
    model_config = ConfigDict(strict=True,extra='forbid')
    input_version: PreparationInputVersion
    recipe: PreparationRecipe
    recipe_revision: int = Field(ge=1)
    candidate: CandidateReference | None = None
    decision_id: str | None = None
    result_id: str | None = None


def validate_snapshot(task):
    try:
        quality = task.get('workflow_version') in ('dataset_preparation_v2','dataset_preparation_v3')
        from app.domain.dataset_preparation.derivation_workflow import DerivationSnapshot
        from app.domain.dataset_preparation.quality_workflow import QualitySnapshot
        snapshot = (DerivationSnapshot if task.get('workflow_version')=='dataset_preparation_v3' else QualitySnapshot if quality else PreparationSnapshot).model_validate(task['input_snapshot']).model_dump(mode='json')
        material = dict(file_id=snapshot['source']['file_id'],recipe=snapshot['recipe'])
        material['base_dataset_id' if quality else 'dataset_id'] = snapshot['source']['dataset_id']
        if (task['task_type'] != 'prepare_dataset' or task['workflow_version'] != snapshot['workflow_version']
                or snapshot['project_id'] != task['project_id'] or type(task['input_snapshot']['schema_version']) is not int
                or task['input_digest'] != request_digest(material)):
            raise ValueError('Preparation identity changed.')
        return snapshot
    except (KeyError,TypeError,ValueError) as exc:
        raise source_conflict() from exc


def preparation_input_version(task):
    snapshot = validate_snapshot(task)
    return dict(kind='dataset_preparation',source=snapshot['source'],workflow_version=snapshot['workflow_version'])


def state_model(task):
    if task.get('workflow_version') == 'dataset_preparation_v3':
        from app.domain.dataset_preparation.derivation_workflow import DerivationState
        return DerivationState
    if task.get('workflow_version') == 'dataset_preparation_v2':
        from app.domain.dataset_preparation.quality_workflow import QualityState
        return QualityState
    return PreparationState


def decision_model(task):
    if task.get('workflow_version') == 'dataset_preparation_v3':
        from app.domain.dataset_preparation.derivation_workflow import DerivationDecisionRequest
        return DerivationDecisionRequest
    if task.get('workflow_version') == 'dataset_preparation_v2':
        from app.domain.dataset_preparation.quality_workflow import QualityDecisionRequest
        return QualityDecisionRequest
    return PreparationDecisionRequest


def candidate_id(task_id):
    return str(uuid5(PREPARATION_NAMESPACE,task_id))


def request_digest(material):
    return hashlib.sha256(json.dumps(material,ensure_ascii=False,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()


def require_key(key):
    if not isinstance(key,str) or not re.fullmatch(r'[\x21-\x7e]{1,128}',key):
        raise StorageError('task_input_invalid','请求标识无效。',422)


def latest_checkpoint(db,task):
    row = db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
    try:
        state = state_model(task).model_validate(row['state_json']).model_dump(mode='json')
        if state['input_version'] != preparation_input_version(task):
            raise ValueError('Checkpoint input changed.')
        if state['candidate'] and state['candidate']['id'] != candidate_id(task['id']):
            raise ValueError('Checkpoint candidate changed.')
        return {**dict(row),'state_json':state}
    except (KeyError,TypeError,ValueError) as exc:
        raise source_conflict() from exc


def append_checkpoint(db,task,node,next_node,state,previous=None):
    checkpoint = dict(id=str(uuid4()),task_id=task['id'],seq=previous['seq']+1 if previous else 1,
        node=node,next_node=next_node,state_json=state,created_at=task['updated_at'])
    db.execute('''INSERT INTO task_checkpoints(id,task_id,seq,node,next_node,state_json,created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
        (checkpoint['id'],task['id'],checkpoint['seq'],node,next_node,Jsonb(state),task['updated_at']))
    return checkpoint


def require_approval(db,task,state):
    """Validate the accepted decision once at the publication/read boundary."""
    decision = db.execute('SELECT * FROM dataset_preparation_decisions WHERE id=%s AND task_id=%s',
        (state['decision_id'],task['id'])).fetchone()
    try:
        request = decision_model(task).model_validate(decision['request_json']).model_dump(mode='json')
        reviewed = db.execute('SELECT * FROM task_checkpoints WHERE id=%s AND task_id=%s',
            (decision['checkpoint_id'],task['id'])).fetchone()
        wait = db.execute('SELECT * FROM task_waits WHERE id=%s AND task_id=%s',
            (decision['wait_id'],task['id'])).fetchone()
        reviewed_state = state_model(task).model_validate(reviewed['state_json']).model_dump(mode='json')
        if (decision['operation'] != 'approve' or request['operation'] != 'approve'
                or decision['user_id'] != task['user_id'] or decision['project_id'] != task['project_id']
                or request['input_version'] != preparation_input_version(task)
                or decision['request_digest'] != request_digest(request)
                or request['checkpoint_id'] != reviewed['id'] or reviewed['next_node'] != 'await_confirmation'
                or request['wait_id'] != wait['id'] or wait['status'] != 'resolved'
                or wait['kind'] != 'dataset_preparation_confirmation' or wait['user_id'] != task['user_id']
                or wait['project_id'] != task['project_id'] or wait['input_version'] != request['input_version']
                or wait['task_revision'] != request['expected_task_revision']
                or wait['resolved_task_revision'] != request['expected_task_revision']+1
                or decision['response_json']['id'] != task['id']
                or decision['response_json']['revision'] != wait['resolved_task_revision']
                or reviewed_state['input_version'] != state['input_version']
                or reviewed_state['candidate'] != state['candidate'] or reviewed_state['recipe'] != state['recipe']
                or reviewed_state['recipe_revision'] != state['recipe_revision']):
            raise ValueError('Saved approval differs from its reviewed candidate.')
        return decision
    except (KeyError,TypeError,ValueError) as exc:
        raise StorageError('dataset_changed','整理确认记录与发布来源不一致。',409) from exc


class DatasetPreparationService:
    def __init__(self,project_store):
        self.assets = project_store
        self.store = TaskStore(project_store.owner_id,project_store.db_config)
        self.datasets = DatasetService(project_store)
        self.objects = PreparedDatasetObjects(project_store.directory)

    def require_raw(self,source,project_id):
        row,_,sheet = self.datasets.dataset(project_id,source['file_id'],source['dataset_id'])
        if raw_dataset_source(row,sheet,source['file_id']) != source:
            raise source_conflict()
        return row,sheet

    def defaults(self,project,file,raw_id,header_row=1,data_range=None):
        row,_,sheet = self.datasets.dataset(project,file,raw_id)
        return dict(source=raw_dataset_source(row,sheet,file),
            recipe=build_recipe(sheet,header_row=header_row,data_range=data_range).model_dump(mode='json'))

    def create(self,project,file,request,key):
        require_key(key)
        request = PreparationCreateRequest.model_validate(request.model_dump() if isinstance(request,PreparationCreateRequest) else request)
        digest = request_digest(dict(file_id=file,**request.model_dump(mode='json')))
        # Replay does not rebuild a candidate and remains the same task after completion.
        with self.store.connection() as db:
            self.datasets.require_file(db,project,file)
            existing = self.store.find_request(db,project,'prepare_dataset',key)
            if existing:
                if existing['input_digest'] != digest:
                    raise StorageError('task_idempotency_conflict','同一请求标识已用于不同输入。',409)
                return self.store.public_task(existing),200
        row,_,sheet = self.datasets.dataset(project,file,request.dataset_id)
        source = raw_dataset_source(row,sheet,file)
        # Validate the complete selected rectangle before accepting work.
        validate_recipe(sheet,request.recipe)
        with self.store.connection(write=True) as db:
            file_row = self.datasets.require_file(db,project,file)
            existing = self.store.find_request(db,project,'prepare_dataset',key)
            if existing:
                if existing['input_digest'] != digest:
                    raise StorageError('task_idempotency_conflict','同一请求标识已用于不同输入。',409)
                return self.store.public_task(existing),200
            now = datetime.now(timezone.utc)
            snapshot = PreparationSnapshot(schema_version=1,kind='dataset_preparation',project_id=project,
                filename=file_row['filename'],source=source,recipe=request.recipe,workflow_version=WORKFLOW_VERSION).model_dump(mode='json')
            task = dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='prepare_dataset',
                idempotency_key=key,input_digest=digest,input_snapshot=snapshot,workflow_version=WORKFLOW_VERSION,
                status='queued',phase='plan',revision=1,current_attempt=0,reason_code=None,created_at=now,updated_at=now)
            self.store.insert_task(db,task)
            state = PreparationState(input_version=preparation_input_version(task),recipe=request.recipe,recipe_revision=1).model_dump(mode='json')
            append_checkpoint(db,task,'prepare_preview','prepare_preview',state)
            self.store.append_event(db,task,'created')
            self.store.enqueue(db,task)
            return self.store.public_task(task),202

    def read_candidate(self,task,checkpoint):
        state = checkpoint['state_json']
        if state['candidate'] is None:
            return None,None
        content,obj = self.objects.read(state['candidate'])
        if (obj.parent_source.model_dump(mode='json') != state['input_version']['source']
                or obj.recipe.model_dump(mode='json') != state['recipe']):
            raise source_conflict()
        return content,obj

    def get_task(self,task_id):
        with self.store.connection() as db:
            task = self.store.require_task(db,task_id)
            snapshot = validate_snapshot(task)
            checkpoint = latest_checkpoint(db,task)
            wait = get_open_wait(db,task)
            result_row = db.execute('SELECT id FROM prepared_dataset_versions WHERE task_id=%s',(task_id,)).fetchone()
        if task['workflow_version'] == 'dataset_preparation_v3':
            from app.domain.dataset_preparation.derivation_service import DerivationPreparationService
            return DerivationPreparationService(self.assets).get_task(task_id)
        if task['workflow_version'] == 'dataset_preparation_v2':
            from app.domain.dataset_preparation.quality_service import QualityPreparationService
            return QualityPreparationService(self.assets).get_task(task_id)
        self.require_raw(snapshot['source'],task['project_id'])
        _,obj = self.read_candidate(task,checkpoint)
        result = self.get_version(task['project_id'],snapshot['source']['file_id'],result_row['id']) if result_row else None
        return dict(task=self.store.public_task(task),source=snapshot['source'],wait=wait,checkpoint_id=checkpoint['id'],
            recipe_revision=checkpoint['state_json']['recipe_revision'],recipe=checkpoint['state_json']['recipe'],
            preview=obj.summary.model_dump(mode='json') if obj else None,
            changes=[change.model_dump(mode='json') for change in obj.changes] if obj else [],
            preview_download_url=f'/api/v1/tasks/{quote(task_id,safe="")}/dataset-preparation/preview/download' if obj else None,
            result=result)

    def decide(self,task_id,request,key):
        require_key(key)
        with self.store.connection() as db:
            task = self.store.require_task(db,task_id)
        if task['workflow_version'] == 'dataset_preparation_v3' and type(self) is DatasetPreparationService:
            from app.domain.dataset_preparation.derivation_service import DerivationPreparationService
            return DerivationPreparationService(self.assets).decide(task_id,request,key)
        if task['workflow_version'] == 'dataset_preparation_v2' and type(self) is DatasetPreparationService:
            from app.domain.dataset_preparation.quality_service import QualityPreparationService
            return QualityPreparationService(self.assets).decide(task_id,request,key)
        request = decision_model(task).model_validate(request.model_dump() if isinstance(request,BaseModel) else request)
        material = request.model_dump(mode='json')
        digest = request_digest(material)
        with self.store.connection(write=True) as db:
            task = self.store.require_task(db,task_id)
            snapshot = validate_snapshot(task)
            existing = db.execute('''SELECT * FROM dataset_preparation_decisions
                WHERE task_id=%s AND user_id=%s AND idempotency_key=%s''',(task_id,self.store.user_id,key)).fetchone()
            if existing:
                if existing['request_digest'] != digest:
                    raise StorageError('task_idempotency_conflict','同一确认标识已用于不同输入。',409)
                return existing['response_json']
            if task['revision'] != request.expected_task_revision:
                raise StorageError('task_revision_conflict','任务已更新，请重新读取。',409)
            if material['input_version'] != preparation_input_version(task):
                raise source_conflict()
            checkpoint = latest_checkpoint(db,task)
            wait = get_open_wait(db,task)
            if (task['status'] != 'waiting_confirmation' or checkpoint['next_node'] != 'await_confirmation'
                    or checkpoint['id'] != request.checkpoint_id or not wait or wait['id'] != request.wait_id
                    or wait['kind'] != 'dataset_preparation_confirmation' or wait['task_revision'] != task['revision']
                    or wait['input_version'] != material['input_version']):
                raise StorageError('task_revision_conflict','待确认内容已更新，请重新读取。',409)
            _,sheet = self.require_raw(snapshot['source'],task['project_id'])
            _, candidate = self.read_candidate(task,checkpoint)
            state = dict(checkpoint['state_json'])
            decision_id = str(uuid4())
            if request.operation == 'revise':
                if task['workflow_version'] == 'dataset_preparation_v3':
                    from app.domain.dataset_preparation.filter_transform import validate_filter_recipe
                    from app.domain.dataset_preparation.quality_transform import validate_quality_recipe
                    from app.domain.dataset_preparation.filter_contracts import FilterRecipe
                    if (snapshot['operation']=='population_filter') != isinstance(request.recipe,FilterRecipe):
                        raise StorageError('preparation_invalid','修订不得更换操作类型。',422)
                    (validate_filter_recipe if snapshot['operation']=='population_filter' else validate_quality_recipe)(sheet,request.recipe)
                elif task['workflow_version'] == 'dataset_preparation_v2':
                    from app.domain.dataset_preparation.quality_transform import validate_quality_recipe
                    validate_quality_recipe(sheet,request.recipe)
                else:
                    validate_recipe(sheet,request.recipe)
                state.update(recipe=material['recipe'],recipe_revision=state['recipe_revision']+1,candidate=None,decision_id=None)
                next_node = 'prepare_preview'
            else:
                if task['workflow_version'] in ('dataset_preparation_v2','dataset_preparation_v3') and (candidate is None or candidate.sheet.row_count == 0):
                    raise StorageError('preparation_invalid','当前策略排除了全部记录，请修订后再确认。',422)
                state['decision_id'] = decision_id
                next_node = 'publish'
            previous_revision = task['revision']
            task.update(status='queued',phase='plan' if next_node == 'prepare_preview' else 'verify',
                revision=previous_revision+1,updated_at=max(datetime.now(timezone.utc),task['updated_at']),
                reason_code='confirmation_received',error_code=None)
            self.store.update_task(db,task,previous_revision)
            resolve_open_wait(db,task,status='superseded' if request.operation == 'revise' else 'resolved')
            response = self.store.public_task(task)
            db.execute('''INSERT INTO dataset_preparation_decisions
                (id,task_id,user_id,project_id,wait_id,checkpoint_id,idempotency_key,request_digest,operation,request_json,response_json,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (decision_id,task_id,task['user_id'],task['project_id'],request.wait_id,request.checkpoint_id,key,
                 digest,request.operation,Jsonb(material),Jsonb(response),task['updated_at']))
            append_checkpoint(db,task,request.operation,next_node,state,checkpoint)
            self.store.append_event(db,task,'requeued')
            self.store.enqueue(db,task)
            return response

    def preview_download(self,task_id):
        with self.store.connection() as db:
            task = self.store.require_task(db,task_id)
            validate_snapshot(task)
            checkpoint = latest_checkpoint(db,task)
        if task['workflow_version'] == 'dataset_preparation_v3' and type(self) is DatasetPreparationService:
            from app.domain.dataset_preparation.derivation_service import DerivationPreparationService
            return DerivationPreparationService(self.assets).preview_download(task_id)
        if task['workflow_version'] == 'dataset_preparation_v2' and type(self) is DatasetPreparationService:
            from app.domain.dataset_preparation.quality_service import QualityPreparationService
            return QualityPreparationService(self.assets).preview_download(task_id)
        self.require_raw(preparation_input_version(task)['source'],task['project_id'])
        content,_ = self.read_candidate(task,checkpoint)
        if content is None:
            raise StorageError('dataset_missing','当前整理预览尚未生成。',404)
        return content

    def load_version(self,project,file,id):
        with self.store.connection() as db:
            self.datasets.require_file(db,project,file)
            row = db.execute('SELECT * FROM prepared_dataset_versions WHERE id=%s AND file_id=%s AND created_by=%s',
                (id,file,self.store.user_id)).fetchone()
            if not row:
                raise StorageError('dataset_missing','整理数据版本不存在。',404)
            row = dict(row)
            task = self.store.require_task(db,row['task_id'])
            snapshot = validate_snapshot(task)
            checkpoint = latest_checkpoint(db,task)
            require_approval(db,task,checkpoint['state_json'])
        if task['workflow_version'] == 'dataset_preparation_v3':
            from app.domain.dataset_preparation.derivation_service import DerivationPreparationService
            return DerivationPreparationService(self.assets).load_derivation_version(project,file,id)
        if task['workflow_version'] == 'dataset_preparation_v2':
            from app.domain.dataset_preparation.quality_service import QualityPreparationService
            return QualityPreparationService(self.assets).load_quality_version(project,file,id)
        self.require_raw(snapshot['source'],project)
        state = checkpoint['state_json']
        content,obj = self.objects.read(row)
        if (task['project_id'] != project or task['status'] != 'succeeded' or row['created_by'] != task['user_id']
                or row['id'] != candidate_id(task['id']) or row['file_id'] != snapshot['source']['file_id']
                or row['parent_dataset_id'] != snapshot['source']['dataset_id']
                or checkpoint['next_node'] != 'done' or checkpoint['node'] != 'done' or state['result_id'] != row['id']
                or state['decision_id'] != row['decision_id'] or state['candidate'] != {k:row[k] for k in CandidateReference.model_fields}
                or obj.parent_source.model_dump(mode='json') != snapshot['source']
                or obj.recipe.model_dump(mode='json') != row['recipe_json'] or row['recipe_json'] != state['recipe']
                or obj.summary.model_dump(mode='json') != row['summary_json']):
            raise StorageError('dataset_changed','整理数据版本来源与确认记录不一致。',409)
        return row,content,obj

    @staticmethod
    def version_summary(project,row,obj):
        if obj.schema_version == 3:
            from app.domain.dataset_preparation.derivation_service import DerivationPreparationService
            return DerivationPreparationService.version_summary(project,row,obj)
        if obj.schema_version == 2:
            from app.domain.dataset_preparation.quality_service import quality_version_summary
            return quality_version_summary(project,row,obj)
        prefix = '/api/v1/projects/{}/files/{}/prepared-dataset-versions/{}'.format(*[quote(str(v),safe='') for v in (project,row['file_id'],row['id'])])
        parent_source = obj.parent_source.model_dump(mode='json')
        return dict(id=row['id'],file_id=row['file_id'],parent_dataset_id=row['parent_dataset_id'],
            parent_dataset_version=parent_source['dataset_version'],version=row['version'],created_at=row['created_at'].isoformat(),
            task_id=row['task_id'],source=prepared_dataset_source(row,parent_source),recipe=row['recipe_json'],
            summary=row['summary_json'],download_url=prefix+'/download')

    def get_version(self,project,file,id):
        row,_,obj = self.load_version(project,file,id)
        return self.version_summary(project,row,obj)

    def list_versions(self,project,file,page=1,page_size=5):
        if type(page) is not int or not 1<=page<=1000000 or type(page_size) is not int or page_size != 5:
            raise StorageError('task_input_invalid','整理数据分页参数无效。',422)
        with self.store.connection() as db:
            self.datasets.require_file(db,project,file)
            total = db.execute('SELECT count(*) AS n FROM prepared_dataset_versions WHERE file_id=%s AND created_by=%s',(file,self.store.user_id)).fetchone()['n']
            rows = db.execute('''SELECT id FROM prepared_dataset_versions WHERE file_id=%s AND created_by=%s
                ORDER BY created_at DESC,version DESC,id DESC LIMIT %s OFFSET %s''',(file,self.store.user_id,page_size,(page-1)*page_size)).fetchall()
        return dict(items=[self.get_version(project,file,row['id']) for row in rows],total=total,page=page,page_size=page_size)

    def rows(self,project,file,id,start_row=None,limit=20):
        from openpyxl.utils.cell import range_boundaries
        row,_,obj = self.load_version(project,file,id)
        _,first,_,last = range_boundaries(obj.sheet.data_range)
        start = first if start_row is None else start_row
        if type(start) is not int or not first<=start<=100000 or type(limit) is not int or limit != 20:
            raise StorageError('task_input_invalid','整理数据行查询参数无效。',422)
        if obj.schema_version in (2,3):
            active = [r for r in obj.sheet.active_source_rows if r >= start]
            selected = active[:limit]
            cells = {}
            for cell in obj.sheet.cells:
                if cell.row in selected: cells.setdefault(cell.row,[]).append(cell.model_dump(mode='json'))
            return dict(dataset=self.version_summary(project,row,obj),start_row=start,limit=limit,total_rows=obj.sheet.row_count,
                has_more=len(active)>limit,next_start_row=active[limit] if len(active)>limit else None,
                rows=[dict(row=r,cells=cells.get(r,[])) for r in selected])
        end = min(last,start+limit-1)
        cells = {}
        for cell in obj.sheet.cells:
            if start<=cell.row<=end:
                cells.setdefault(cell.row,[]).append(cell.model_dump(mode='json'))
        return dict(dataset=self.version_summary(project,row,obj),start_row=start,limit=limit,total_rows=obj.sheet.row_count,
            has_more=end<last,rows=[dict(row=r,cells=cells.get(r,[])) for r in range(start,end+1)])


def retry_preparation_in_transaction(store,db,task,expected_revision):
    from app.domain.storage_governance.deterministic import STORAGE_RETRY_CODES, authorize_checkpoint_rebuild
    if (task['task_type'] != 'prepare_dataset' or task['status'] != 'failed'
            or task.get('error_code') not in STORAGE_RETRY_CODES):
        raise StorageError('task_transition_invalid','当前整理任务不能安全重试。',409)
    if task['revision'] != expected_revision:
        raise StorageError('task_revision_conflict','任务已更新，请重新读取。',409)
    store.require_project(db,task['project_id'])
    checkpoint=latest_checkpoint(db,task)  # Retry keeps the persisted node and revised recipe.
    from app.adapters.task_store import DatasetTaskAssets
    from app.core.config import get_data_dir
    model=DatasetPreparationService
    if task['workflow_version']=='dataset_preparation_v2':
        from app.domain.dataset_preparation.quality_service import QualityPreparationService
        model=QualityPreparationService
    elif task['workflow_version']=='dataset_preparation_v3':
        from app.domain.dataset_preparation.derivation_service import DerivationPreparationService
        model=DerivationPreparationService
    service=model(DatasetTaskAssets(task['user_id'],store.config,get_data_dir()))
    authorize_checkpoint_rebuild(db,get_data_dir(),task,checkpoint,service)
    task.update(status='queued',revision=expected_revision+1,error_code=None,reason_code='retry_requested',
        _retry_reason='manual_retry',retry_count=0,updated_at=max(datetime.now(timezone.utc),task['updated_at']))
    store.update_task(db,task,expected_revision)
    store.append_event(db,task,'requeued')
    store.enqueue(db,task)
    return store.public_task(task)


def retry_preparation_task(store,task_id,expected_revision):
    with store.connection(write=True) as db:
        task = store.require_task(db,task_id)
        repeated = db.execute("SELECT seq FROM task_events WHERE task_id=%s AND seq=%s AND event_type='requeued' AND reason_code='retry_requested'",(task_id,expected_revision+1)).fetchone()
        if repeated:
            return store.public_task(task)
        return retry_preparation_in_transaction(store,db,task,expected_revision)
