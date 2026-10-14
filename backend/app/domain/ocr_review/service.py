"""Owner-scoped OCR review creation, persisted progress and explicit decisions."""
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
from app.adapters.ocr_review_objects import OcrReviewObjects
from app.core.exceptions import StorageError
from app.domain.ocr_review.contracts import OcrReviewSource, OcrReviewInputVersion, OcrReviewEdit, dump_edits
from app.domain.documents.service import DocumentService
from app.domain.ocr_review.contracts import WORKFLOW_VERSION
from app.domain.ocr_review.transform import review_document

from app.domain.tasks.waits import get_open_wait, resolve_open_wait


REVIEW_NAMESPACE = UUID('25d0e990-20c9-4a28-8bdb-028935be05f8')


class OcrReviewCreateRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    parse_id: str = Field(min_length=1,max_length=64)


class OcrReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    operation: Literal['approve','revise']
    wait_id: str = Field(min_length=1,max_length=64)
    checkpoint_id: str = Field(min_length=1,max_length=64)
    expected_task_revision: int = Field(ge=1,lt=2147483647)
    input_version: OcrReviewInputVersion
    edits: list[OcrReviewEdit] | None = Field(default=None, max_length=20000)

    @model_validator(mode='after')
    def edits_matches_operation(self):
        if (self.edits is not None) != (self.operation == 'revise'):
            raise ValueError('Only revise requires a complete edits.')
        return self


class OcrReviewSnapshot(BaseModel):
    model_config = ConfigDict(strict=True,extra='forbid')
    schema_version: Literal[1]
    kind: Literal['ocr_review']
    project_id: str
    filename: str
    source: OcrReviewSource
    workflow_version: Literal['ocr_review_v1']


class CandidateReference(BaseModel):
    model_config = ConfigDict(strict=True,extra='forbid')
    id: str
    object_key: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size_bytes: int = Field(gt=0,le=16777216)


class OcrReviewState(BaseModel):
    model_config = ConfigDict(strict=True,extra='forbid')
    input_version: OcrReviewInputVersion
    edits: list[OcrReviewEdit]
    edit_revision: int = Field(ge=1)
    candidate: CandidateReference | None = None
    decision_id: str | None = None
    result_id: str | None = None


def validate_snapshot(task):
    try:
        snapshot = OcrReviewSnapshot.model_validate(task['input_snapshot']).model_dump(mode='json')
        if (task['task_type'] != 'review_ocr' or task['workflow_version'] != WORKFLOW_VERSION
                or snapshot['project_id'] != task['project_id'] or type(task['input_snapshot']['schema_version']) is not int
                or task['input_digest'] != request_digest(dict(file_id=snapshot['source']['file_id'],
                    parse_id=snapshot['source']['parse_id']))):
            raise ValueError('OCR review identity changed.')
        return snapshot
    except (KeyError,TypeError,ValueError) as exc:
        raise source_conflict() from exc


def review_input_version(task):
    snapshot = validate_snapshot(task)
    return dict(kind='ocr_review',source=snapshot['source'],workflow_version=WORKFLOW_VERSION)


def candidate_id(task_id):
    return str(uuid5(REVIEW_NAMESPACE,task_id))


def request_digest(material):
    return hashlib.sha256(json.dumps(material,ensure_ascii=False,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()


def require_key(key):
    if not isinstance(key,str) or not re.fullmatch(r'[\x21-\x7e]{1,128}',key):
        raise StorageError('task_input_invalid','请求标识无效。',422)


def latest_checkpoint(db,task):
    row = db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
    try:
        state = OcrReviewState.model_validate(row['state_json']).model_dump(mode='json')
        if state['input_version'] != review_input_version(task):
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
    decision = db.execute('SELECT * FROM ocr_review_decisions WHERE id=%s AND task_id=%s',
        (state['decision_id'],task['id'])).fetchone()
    try:
        request = OcrReviewDecisionRequest.model_validate(decision['request_json']).model_dump(mode='json')
        reviewed = db.execute('SELECT * FROM task_checkpoints WHERE id=%s AND task_id=%s',
            (decision['checkpoint_id'],task['id'])).fetchone()
        wait = db.execute('SELECT * FROM task_waits WHERE id=%s AND task_id=%s',
            (decision['wait_id'],task['id'])).fetchone()
        reviewed_state = OcrReviewState.model_validate(reviewed['state_json']).model_dump(mode='json')
        if (decision['operation'] != 'approve' or request['operation'] != 'approve'
                or decision['user_id'] != task['user_id'] or decision['project_id'] != task['project_id']
                or request['input_version'] != review_input_version(task)
                or decision['request_digest'] != request_digest(request)
                or request['checkpoint_id'] != reviewed['id'] or reviewed['next_node'] != 'await_confirmation'
                or request['wait_id'] != wait['id'] or wait['status'] != 'resolved'
                or wait['kind'] != 'ocr_review_confirmation' or wait['user_id'] != task['user_id']
                or wait['project_id'] != task['project_id'] or wait['input_version'] != request['input_version']
                or wait['task_revision'] != request['expected_task_revision']
                or wait['resolved_task_revision'] != request['expected_task_revision']+1
                or decision['response_json']['id'] != task['id']
                or decision['response_json']['revision'] != wait['resolved_task_revision']
                or reviewed_state['input_version'] != state['input_version']
                or reviewed_state['candidate'] != state['candidate'] or reviewed_state['edits'] != state['edits']
                or reviewed_state['edit_revision'] != state['edit_revision']):
            raise ValueError('Saved approval differs from its reviewed candidate.')
        return decision
    except (KeyError,TypeError,ValueError) as exc:
        raise StorageError('task_source_conflict','OCR 核对确认记录与发布来源不一致。',409) from exc


class OcrReviewService:
    def __init__(self,project_store):
        self.assets = project_store
        self.store = TaskStore(project_store.owner_id,project_store.db_config)
        self.documents = DocumentService(project_store)
        self.objects = OcrReviewObjects(project_store.directory)

    def require_raw(self,source,project_id):
        row = self.documents.load(project_id,source['file_id'],source['parse_id'],True)
        if row['workflow_version'] != 'ocr_document_v1':
            raise StorageError('task_input_invalid','仅已完成的 OCR 版本可以核对。',422)
        _,document = self.documents.read(row)
        if review_source(row,document) != source:
            raise source_conflict()
        return row,document

    def create(self,project,file,request,key):
        require_key(key)
        request = OcrReviewCreateRequest.model_validate(request.model_dump() if isinstance(request,OcrReviewCreateRequest) else request)
        digest = request_digest(dict(file_id=file,**request.model_dump(mode='json')))
        # Replay does not rebuild a candidate and remains the same task after completion.
        with self.store.connection() as db:
            self.documents.file(db,project,file)
            existing = self.store.find_request(db,project,'review_ocr',key)
            if existing:
                if existing['input_digest'] != digest:
                    raise StorageError('task_idempotency_conflict','同一请求标识已用于不同输入。',409)
                return self.store.public_task(existing),200
        row = self.documents.load(project,file,request.parse_id,True)
        if row['workflow_version'] != 'ocr_document_v1':
            raise StorageError('task_input_invalid','仅已完成的 OCR 版本可以核对。',422)
        _,sheet = self.documents.read(row)
        source = review_source(row,sheet)
        try:
            review_document(sheet,source,[])
        except ValueError as exc:
            raise StorageError('task_input_invalid','没有已有文字块可核对。',422) from exc
        with self.store.connection(write=True) as db:
            file_row = self.documents.file(db,project,file)
            db.execute('SELECT id FROM file_parse_results WHERE id=%s FOR UPDATE',(request.parse_id,))
            active = db.execute("SELECT * FROM tasks WHERE user_id=%s AND project_id=%s AND task_type='review_ocr' AND input_snapshot->'source'->>'parse_id'=%s AND status IN ('queued','running','waiting_input','waiting_confirmation','failed') ORDER BY created_at DESC LIMIT 1",(self.store.user_id,project,request.parse_id)).fetchone()
            existing = self.store.find_request(db,project,'review_ocr',key)
            if existing:
                if existing['input_digest'] != digest:
                    raise StorageError('task_idempotency_conflict','同一请求标识已用于不同输入。',409)
                return self.store.public_task(existing),200
            if active:
                raise StorageError('ocr_review_active','此 OCR 版本已有核对进度，请通过任务列表继续。',409)
            now = datetime.now(timezone.utc)
            snapshot = OcrReviewSnapshot(schema_version=1,kind='ocr_review',project_id=project,
                filename=file_row['filename'],source=source,workflow_version=WORKFLOW_VERSION).model_dump(mode='json')
            task = dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='review_ocr',
                idempotency_key=key,input_digest=digest,input_snapshot=snapshot,workflow_version=WORKFLOW_VERSION,
                status='queued',phase='plan',revision=1,current_attempt=0,reason_code=None,created_at=now,updated_at=now)
            self.store.insert_task(db,task)
            state = OcrReviewState(input_version=review_input_version(task),edits=[],edit_revision=1).model_dump(mode='json')
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
                or dump_edits(obj.edits) != state['edits']):
            raise source_conflict()
        return content,obj

    def get_task(self,task_id):
        with self.store.connection() as db:
            task = self.store.require_task(db,task_id)
            snapshot = validate_snapshot(task)
            checkpoint = latest_checkpoint(db,task)
            wait = get_open_wait(db,task)
            result_row = db.execute('SELECT id FROM ocr_review_versions WHERE task_id=%s',(task_id,)).fetchone()
        self.require_raw(snapshot['source'],task['project_id'])
        _,obj = self.read_candidate(task,checkpoint)
        result = self.version_summary(task['project_id'],*self._version_pair(task['project_id'],
            snapshot['source']['file_id'],result_row['id'])) if result_row else None
        return dict(task=self.store.public_task(task),source=snapshot['source'],wait=wait,checkpoint_id=checkpoint['id'],
            edit_revision=checkpoint['state_json']['edit_revision'],edits=checkpoint['state_json']['edits'],
            summary=obj.summary.model_dump(mode='json') if obj else None,
            preview_download_url=f'/api/v1/tasks/{quote(task_id,safe="")}/ocr-review/preview/download' if obj else None,
            result=result)

    def decide(self,task_id,request,key):
        require_key(key)
        request = OcrReviewDecisionRequest.model_validate(request.model_dump() if isinstance(request,OcrReviewDecisionRequest) else request)
        material = request.model_dump(mode='json')
        digest = request_digest(material)
        with self.store.connection(write=True) as db:
            task = self.store.require_task(db,task_id)
            snapshot = validate_snapshot(task)
            existing = db.execute('''SELECT * FROM ocr_review_decisions
                WHERE task_id=%s AND user_id=%s AND idempotency_key=%s''',(task_id,self.store.user_id,key)).fetchone()
            if existing:
                if existing['request_digest'] != digest:
                    raise StorageError('task_idempotency_conflict','同一确认标识已用于不同输入。',409)
                return existing['response_json']
            if task['revision'] != request.expected_task_revision:
                raise StorageError('task_revision_conflict','任务已更新，请重新读取。',409)
            if material['input_version'] != review_input_version(task):
                raise source_conflict()
            checkpoint = latest_checkpoint(db,task)
            wait = get_open_wait(db,task)
            if (task['status'] != 'waiting_confirmation' or checkpoint['next_node'] != 'await_confirmation'
                    or checkpoint['id'] != request.checkpoint_id or not wait or wait['id'] != request.wait_id
                    or wait['kind'] != 'ocr_review_confirmation' or wait['task_revision'] != task['revision']
                    or wait['input_version'] != material['input_version']):
                raise StorageError('task_revision_conflict','待确认内容已更新，请重新读取。',409)
            _,sheet = self.require_raw(snapshot['source'],task['project_id'])
            self.read_candidate(task,checkpoint)
            state = dict(checkpoint['state_json'])
            decision_id = str(uuid4())
            if request.operation == 'revise':
                try:
                    validated = review_document(sheet,snapshot['source'],request.edits)
                except ValueError as exc:
                    raise StorageError('task_input_invalid','核对编辑无效。',422) from exc
                state.update(edits=dump_edits(validated.edits),edit_revision=state['edit_revision']+1,candidate=None,decision_id=None)
                next_node = 'prepare_preview'
            else:
                _,candidate = self.read_candidate(task,checkpoint)
                if candidate is None or candidate.summary.unreviewed_blocks:
                    raise StorageError('task_input_invalid','请明确处理全部已有文字块后发布。',422)
                state['decision_id'] = decision_id
                next_node = 'publish'
            previous_revision = task['revision']
            task.update(status='queued',phase='plan' if next_node == 'prepare_preview' else 'verify',
                revision=previous_revision+1,updated_at=max(datetime.now(timezone.utc),task['updated_at']),
                reason_code='confirmation_received',error_code=None,retry_count=0)
            self.store.update_task(db,task,previous_revision)
            resolve_open_wait(db,task,status='superseded' if request.operation == 'revise' else 'resolved')
            response = self.store.public_task(task)
            db.execute('''INSERT INTO ocr_review_decisions
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
        self.require_raw(review_input_version(task)['source'],task['project_id'])
        content,_ = self.read_candidate(task,checkpoint)
        if content is None:
            raise StorageError('document_version_not_found','当前OCR 核对预览尚未生成。',404)
        return content

    def load_version(self,project,file,id):
        with self.store.connection() as db:
            self.documents.file(db,project,file)
            row = db.execute('SELECT * FROM ocr_review_versions WHERE id=%s AND file_id=%s AND created_by=%s',
                (id,file,self.store.user_id)).fetchone()
            if not row:
                raise StorageError('document_version_not_found','OCR 核对数据版本不存在。',404)
            row = dict(row)
            task = self.store.require_task(db,row['task_id'])
            snapshot = validate_snapshot(task)
            checkpoint = latest_checkpoint(db,task)
            require_approval(db,task,checkpoint['state_json'])
        self.require_raw(snapshot['source'],project)
        state = checkpoint['state_json']
        content,obj = self.objects.read(row)
        if (task['project_id'] != project or task['status'] != 'succeeded' or row['created_by'] != task['user_id']
                or row['id'] != candidate_id(task['id']) or row['file_id'] != snapshot['source']['file_id']
                or row['parent_parse_id'] != snapshot['source']['parse_id']
                or checkpoint['next_node'] != 'done' or checkpoint['node'] != 'done' or state['result_id'] != row['id']
                or state['decision_id'] != row['decision_id'] or state['candidate'] != {k:row[k] for k in CandidateReference.model_fields}
                or obj.parent_source.model_dump(mode='json') != snapshot['source']
                or dump_edits(obj.edits) != row['edits_json'] or row['edits_json'] != state['edits']
                or obj.summary.model_dump(mode='json') != row['summary_json']):
            raise StorageError('task_source_conflict','OCR 核对数据版本来源与确认记录不一致。',409)
        return row,content,obj

    @staticmethod
    def version_summary(project,row,obj):
        prefix = '/api/v1/projects/{}/files/{}/ocr-review-versions/{}'.format(*[quote(str(v),safe='') for v in (project,row['file_id'],row['id'])])
        parent_source = obj.parent_source.model_dump(mode='json')
        return dict(id=row['id'],file_id=row['file_id'],parent_parse_id=row['parent_parse_id'],
            parent_parse_version=parent_source['parse_version'],version=row['version'],created_at=row['created_at'].isoformat(),
            task_id=row['task_id'],source=parent_source,
            summary=row['summary_json'],download_url=prefix+'/download')

    def get_version(self,project,file,id):
        row,_,obj = self.load_version(project,file,id)
        return dict(self.version_summary(project,row,obj),edits=row['edits_json'])

    def list_versions(self,project,file,parse_id=None,page=1,page_size=5):
        if type(page) is not int or not 1<=page<=1000000 or type(page_size) is not int or page_size != 5:
            raise StorageError('task_input_invalid','OCR 核对数据分页参数无效。',422)
        with self.store.connection() as db:
            self.documents.file(db,project,file)
            condition='file_id=%s AND created_by=%s'
            values=[file,self.store.user_id]
            if parse_id is not None:
                condition+=' AND parent_parse_id=%s';values.append(parse_id)
            total = db.execute('SELECT count(*) AS n FROM ocr_review_versions WHERE '+condition,tuple(values)).fetchone()['n']
            rows = db.execute('SELECT id FROM ocr_review_versions WHERE '+condition+' ORDER BY created_at DESC,version DESC,id DESC LIMIT %s OFFSET %s',(*values,page_size,(page-1)*page_size)).fetchall()
        return dict(items=[self.version_summary(project,*self._version_pair(project,file,row['id'])) for row in rows],total=total,page=page,page_size=page_size)

    def _version_pair(self,project,file,id):
        row,_,obj=self.load_version(project,file,id)
        return row,obj

    def list_tasks(self,project,file,parse_id=None):
        with self.store.connection() as db:
            self.documents.file(db,project,file)
            condition="user_id=%s AND project_id=%s AND task_type='review_ocr' AND input_snapshot->'source'->>'file_id'=%s"
            values=[self.store.user_id,project,file]
            if parse_id is not None:
                condition+=" AND input_snapshot->'source'->>'parse_id'=%s";values.append(parse_id)
            rows=db.execute('SELECT * FROM tasks WHERE '+condition+' ORDER BY created_at DESC,id DESC',tuple(values)).fetchall()
            return dict(items=[self.store.public_task(row) for row in rows])


def retry_ocr_review_in_transaction(store,db,task,expected_revision):
    if (task['task_type'] != 'review_ocr' or task['status'] != 'failed'
            or task.get('error_code') not in ('storage_unavailable','task_worker_interrupted')):
        raise StorageError('task_transition_invalid','当前OCR 核对任务不能安全重试。',409)
    if task['revision'] != expected_revision:
        raise StorageError('task_revision_conflict','任务已更新，请重新读取。',409)
    store.require_project(db,task['project_id'])
    latest_checkpoint(db,task)  # Retry keeps the persisted node and revised edits.
    task.update(status='queued',revision=expected_revision+1,error_code=None,reason_code='retry_requested',
        _retry_reason='manual_retry',retry_count=0,updated_at=max(datetime.now(timezone.utc),task['updated_at']))
    store.update_task(db,task,expected_revision)
    store.append_event(db,task,'requeued')
    store.enqueue(db,task)
    return store.public_task(task)


def retry_ocr_review_task(store,task_id,expected_revision):
    with store.connection(write=True) as db:
        task = store.require_task(db,task_id)
        repeated = db.execute("SELECT seq FROM task_events WHERE task_id=%s AND seq=%s AND event_type='requeued' AND reason_code='retry_requested'",(task_id,expected_revision+1)).fetchone()
        if repeated:
            return store.public_task(task)
        return retry_ocr_review_in_transaction(store,db,task,expected_revision)


def review_source(row,document):
    return OcrReviewSource(file_id=row['file_id'],parse_id=row['id'],parse_version=row['version'],
        source_sha256=row['source_sha256'],document_sha256=row['result_json']['object']['sha256'],
        parser_version=row['parser_version'],selected_pages=document.selected_pages).model_dump(mode='json')
