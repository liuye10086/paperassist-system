"""Idempotent registration and per-item atomic asynchronous upload."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID, uuid4
from typing import Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.adapters.task_store import TaskStore
from app.adapters.file_objects import original_digest
from app.core.config import get_excel_settings
from app.core.exceptions import StorageError
from app.core.errors import error_detail
from app.domain.file_parsing import PARSER_VERSION, PROCESS_SETTINGS, ParseFileSnapshot
from app.domain.tasks.contracts import TaskView


class BatchItemInput(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    client_id: str
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0, le=2**63-1)

    @field_validator('client_id')
    @classmethod
    def uuid_identifier(cls, value):
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError('A canonical UUID is required')
        return value

    @field_validator('filename')
    @classmethod
    def safe_filename(cls, value):
        if any(c in value for c in ('/', '\\', '\x00')) or not value.strip():
            raise ValueError('A base filename is required')
        return value


class BatchInput(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    items: list[BatchItemInput] = Field(min_length=1, max_length=10)

    @model_validator(mode='after')
    def unique_items(self):
        if len({item.client_id for item in self.items}) != len(self.items):
            raise ValueError('Duplicate item IDs')
        return self


class BatchItem(BaseModel):
    id: str
    ordinal: int
    filename: str
    size_bytes: int
    status: Literal['pending', 'rejected', 'queued', 'parsing', 'parsed', 'failed']
    file_id: str | None
    task: TaskView | None
    error: dict | None


class BatchView(BaseModel):
    id: str
    project_id: str
    created_at: str
    revision: int
    items: list[BatchItem]


class BatchPage(BaseModel):
    items: list[BatchView]
    total: int
    page: int
    page_size: int


class FileBatchService:
    def __init__(self, project_store):
        self.assets = project_store
        self.store = TaskStore(project_store.owner_id, project_store.db_config)

    def require_batch(self, db, project_id, batch_id):
        self.store.require_project(db, project_id)
        row = db.execute('SELECT * FROM file_upload_batches WHERE id=%s AND project_id=%s AND user_id=%s',
                         (batch_id, project_id, self.store.user_id)).fetchone()
        if row is None:
            raise StorageError('file_batch_not_found', '上传批次不存在，请重新载入。', 404)
        return row

    def project(self, db, batch):
        items = []
        revision = 1
        for row in db.execute('SELECT * FROM file_upload_items WHERE batch_id=%s ORDER BY ordinal', (batch['id'],)):
            file = db.execute('SELECT * FROM files WHERE id=%s', (row['file_id'],)).fetchone() if row['file_id'] else None
            task = db.execute('SELECT t.* FROM tasks t JOIN file_parse_results r ON r.task_id=t.id WHERE r.file_id=%s AND r.version=1',
                              (row['file_id'],)).fetchone() if file else None
            revision += file['parse_revision'] if file else 0
            items.append({'id': row['id'], 'ordinal': row['ordinal'], 'filename': row['filename'],
                'size_bytes': row['size_bytes'], 'file_id': row['file_id'],
                'status': {'queued':'queued','running':'parsing','succeeded':'parsed','failed':'failed'}.get(task['status'], file['parse_status']) if task else file['parse_status'] if file else ('rejected' if row['error_json'] else 'pending'),
                'task': self.store.public_task(dict(task)) if task else None,
                'error': error_detail(task['error_code'], '文件解析失败，请检查文件或重试。') if task and task['error_code'] else row['error_json']})
        return {'id': batch['id'], 'project_id': batch['project_id'],
                'created_at': batch['created_at'].astimezone(timezone.utc).isoformat(), 'revision': revision, 'items': items}

    def register(self, project_id, request, key):
        digest = hashlib.sha256(json.dumps(request.model_dump(), sort_keys=True, ensure_ascii=False,
                                          separators=(',', ':')).encode()).hexdigest()
        with self.store.connection(write=True) as db:
            self.store.require_project(db, project_id)
            existing = db.execute('SELECT * FROM file_upload_batches WHERE project_id=%s AND user_id=%s AND idempotency_key=%s',
                                  (project_id, self.store.user_id, key)).fetchone()
            if existing:
                if existing['request_digest'] != digest:
                    raise StorageError('file_batch_idempotency_conflict', '同一批次标识已用于不同文件列表。', 409)
                return self.project(db, existing), 200
            ids = [item.client_id for item in request.items]
            if db.execute('SELECT id FROM file_upload_items WHERE id=ANY(%s)', (ids,)).fetchone():
                raise StorageError('file_batch_item_conflict', '文件项标识已使用，请重新登记批次。', 409)
            batch = {'id': str(uuid4()), 'project_id': project_id, 'created_at': datetime.now(timezone.utc)}
            db.execute('''INSERT INTO file_upload_batches(id,project_id,user_id,idempotency_key,request_digest,created_at)
                VALUES (%s,%s,%s,%s,%s,%s)''', (batch['id'], project_id, self.store.user_id, key, digest, batch['created_at']))
            maximum = min(get_excel_settings().max_upload_bytes, 10485760)
            for ordinal, item in enumerate(request.items):
                code = ('unsupported_file_type' if not item.filename.lower().endswith(('.xlsx', '.docx', '.pdf', '.png', '.jpg', '.jpeg')) else
                        'empty_file' if item.size_bytes == 0 else 'file_too_large' if item.size_bytes > maximum else None)
                error = error_detail(code, {'unsupported_file_type': '仅支持 .xlsx、.docx、.pdf、.png 或 .jpg/.jpeg 文件。',
                    'empty_file': '文件为空，请选择有效文件。', 'file_too_large': '文件超过上传大小限制。'}[code],
                    {'max_bytes': maximum}) if code else None
                db.execute('''INSERT INTO file_upload_items(id,batch_id,ordinal,filename,size_bytes,file_id,error_json)
                    VALUES (%s,%s,%s,%s,%s,NULL,%s)''',
                    (item.client_id, batch['id'], ordinal, item.filename, item.size_bytes, Jsonb(error) if error else None))
            return self.project(db, batch), 201

    def get(self, project_id, batch_id):
        with self.store.connection() as db:
            return self.project(db, self.require_batch(db, project_id, batch_id))

    def list(self, project_id, page, page_size):
        with self.store.connection() as db:
            self.store.require_project(db, project_id)
            args = (project_id, self.store.user_id)
            total = db.execute('SELECT count(*) AS n FROM file_upload_batches WHERE project_id=%s AND user_id=%s', args).fetchone()['n']
            rows = db.execute('''SELECT * FROM file_upload_batches WHERE project_id=%s AND user_id=%s
                ORDER BY created_at DESC,id LIMIT %s OFFSET %s''', (*args, page_size, (page-1)*page_size)).fetchall()
            return {'items': [self.project(db, row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}

    def upload(self, project_id, batch_id, item_id, filename, content):
        # The writer transaction serializes item confirmation. Preserve an object on
        # rollback or unknown commit; deterministic item paths allow safe retransmission.
        with self.store.connection(write=True) as db:
            batch = self.require_batch(db, project_id, batch_id)
            item = db.execute('SELECT * FROM file_upload_items WHERE id=%s AND batch_id=%s', (item_id, batch_id)).fetchone()
            if not item:
                raise StorageError('file_batch_item_not_found', '上传文件项不存在。', 404)
            if item['error_json']:
                raise StorageError('file_batch_item_rejected', '此文件已在登记时拒绝，请重新选择。', 409)
            if filename != item['filename'] or len(content) != item['size_bytes']:
                raise StorageError('file_upload_mismatch', '文件名称或大小与登记不一致，请重新选择原文件。', 409)
            sha = original_digest(content)
            if item['file_id']:
                file = db.execute('SELECT * FROM files WHERE id=%s', (item['file_id'],)).fetchone()
                if file['sha256'] != sha:
                    raise StorageError('file_batch_item_conflict', '此文件项已保存不同内容。', 409)
                self.assets.original(dict(file))
                return next(row for row in self.project(db, batch)['items'] if row['id'] == item_id)
            task_id, parse_id = str(uuid4()), str(uuid4())
            file_type = filename.rsplit('.', 1)[-1].lower()
            if file_type == 'jpg':
                file_type = 'jpeg'
            descriptor = self.assets.objects.put_original(
                project_id, batch['id'], file_type, content, item_id=item['id'])
            file_id = descriptor.id
            now = datetime.now(timezone.utc)
            file = {'filename': filename, **asdict(descriptor)}
            settings = {'excel': get_excel_settings().model_dump(), 'process': PROCESS_SETTINGS.copy()}
            snapshot = ParseFileSnapshot.model_validate({'schema_version': 1, 'kind': 'parse_file',
                'project': {'id': project_id}, 'file': file, 'parse_id': parse_id,
                'parser_version': PARSER_VERSION, 'settings': settings}).model_dump() if file_type == 'xlsx' else None
            parser_version, workflow_version = PARSER_VERSION, 'parse_file_v1'
            if file_type in ('docx', 'pdf', 'png', 'jpeg'):
                from app.domain.documents.service import document_snapshot
                snapshot = document_snapshot(project_id, file, parse_id, 1)
                settings = snapshot['settings']
                parser_version, workflow_version = snapshot['parser_version'], snapshot['kind'] + '_v1'
            db.execute('''INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,
                parse_status,error_json,preview_json,uploader_id,storage_backend,object_key,metadata_revision,upload_item_id,parse_revision)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'queued',NULL,NULL,%s,%s,%s,1,%s,1)''',
                (file_id, project_id, filename, descriptor.file_type, descriptor.size_bytes, descriptor.sha256,
                 now.isoformat(), self.store.user_id, descriptor.storage_backend, descriptor.object_key, item_id))
            task = {'id': task_id, 'project_id': project_id, 'user_id': self.store.user_id,
                'task_type': 'parse_file', 'idempotency_key': item_id, 'input_digest': sha,
                'input_snapshot': snapshot, 'workflow_version': workflow_version, 'status': 'queued',
                'phase': 'parse', 'revision': 1, 'current_attempt': 0, 'reason_code': None,
                'created_at': now, 'updated_at': now}
            self.store.insert_task(db, task)
            db.execute('''INSERT INTO file_parse_results(id,file_id,task_id,version,source_sha256,parser_version,
                settings_json,created_at,completed_at,result_json) VALUES (%s,%s,%s,1,%s,%s,%s,%s,NULL,NULL)''',
                (parse_id, file_id, task_id, sha, parser_version, Jsonb(settings), now))
            self.store.append_event(db, task, 'created')
            self.store.enqueue(db, task)
            db.execute('UPDATE file_upload_items SET file_id=%s WHERE id=%s', (file_id, item_id))
            db.execute('UPDATE projects SET updated_at=GREATEST(updated_at,%s) WHERE id=%s', (now.isoformat(), project_id))
            return next(row for row in self.project(db, batch)['items'] if row['id'] == item_id)
