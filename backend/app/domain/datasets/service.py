"""Explicit version registration and owner scoped read-only raw datasets."""
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import uuid4
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field
from app.adapters.task_store import TaskStore
from app.adapters.dataset_objects import DatasetObjects
from app.core.config import get_excel_settings
from app.core.exceptions import StorageError
from app.domain.file_parsing import PROCESS_SETTINGS
from app.domain.datasets.snapshots import StructureSnapshot
from app.domain.datasets.contracts import STRUCTURE_PARSER_VERSION
from app.domain.file_lifecycle.contracts import AssessmentRevision
from app.domain.file_lifecycle.service import FileLifecycleService


class StructureCreateRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    expected_latest_version: int = Field(ge=0, le=2147483646)
    expected_assessment_revision: AssessmentRevision | None = None


class DatasetService:
    def __init__(self, project_store):
        self.assets = project_store
        self.store = TaskStore(project_store.owner_id, project_store.db_config)
        self.objects = DatasetObjects(project_store.directory)

    def require_file(self, db, project_id, file_id):
        self.store.require_project(db, project_id)
        row = db.execute('SELECT * FROM files WHERE project_id=%s AND id=%s', (project_id, file_id)).fetchone()
        if not row:
            raise StorageError('file_not_found', '当前项目中没有此文件。', 404)
        return dict(row)

    @staticmethod
    def summary(row):
        fields = ('id','file_id','structure_id','version','parent_id','sheet_index','sheet_name')
        return {**{key: row[key] for key in fields}, 'created_at': row['created_at'].isoformat(), **row['summary_json']}

    def view(self, db, row):
        task = self.store.require_task(db, row['task_id'])
        from app.domain.datasets.snapshots import validate_snapshot
        snapshot = validate_snapshot(task)
        parent = db.execute('''SELECT id FROM file_structure_versions WHERE file_id=%s AND version<%s
            AND manifest_json IS NOT NULL ORDER BY version DESC LIMIT 1''',(row['file_id'],row['version'])).fetchone()
        if (snapshot['structure_id'] != row['id'] or snapshot['file']['id'] != row['file_id']
                or row['source_sha256'] != snapshot['file']['sha256']
                or row['parser_version'] != snapshot['parser_version']
                or row['settings_json'] != snapshot['settings']
                or row['created_by'] != task['user_id'] or row['request_digest'] != task['input_digest']
                or row['parent_id'] != (parent['id'] if parent else None)):
            raise StorageError('dataset_changed', '结构任务来源身份不一致。', 409)
        datasets = db.execute('SELECT * FROM dataset_versions WHERE structure_id=%s ORDER BY sheet_index', (row['id'],)).fetchall()
        if row['manifest_json'] is None and datasets:
            raise StorageError('dataset_changed', '数据版本完整性不一致。', 409)
        if row['manifest_json'] is not None:
            manifest = row['manifest_json']
            if (task['status'] != 'succeeded' or manifest.get('schema_version') != 1
                    or manifest.get('epoch') not in ('1900','1904')
                    or manifest.get('filename') != snapshot['file']['filename']
                    or manifest.get('dataset_ids') != [item['id'] for item in datasets]
                    or [item['sheet_index'] for item in datasets] != list(range(len(datasets)))
                    or not datasets or any(item['file_id'] != row['file_id'] or item['version'] != row['version']
                        or item['summary_json'].get('epoch') != manifest['epoch'] for item in datasets)):
                raise StorageError('dataset_changed', '结构版本完整性不一致。', 409)
        return {**{key: row[key] for key in ('id','file_id','version','parent_id')},
                'created_at': row['created_at'].isoformat(),
                'completed_at': row['completed_at'].isoformat() if row['completed_at'] else None,
                'task': self.store.public_task(task), 'datasets': [self.summary(item) for item in datasets]}

    def create(self, project_id, file_id, request, key):
        if not isinstance(key, str) or not re.fullmatch(r'[\x21-\x7e]{1,128}', key):
            raise StorageError('task_input_invalid', '请求标识无效。', 422)
        digest = hashlib.sha256(json.dumps(request.model_dump(exclude_none=True), sort_keys=True, separators=(',',':')).encode()).hexdigest()
        with self.store.connection(write=True) as db:
            file = self.require_file(db, project_id, file_id)
            existing = db.execute('SELECT * FROM file_structure_versions WHERE file_id=%s AND created_by=%s AND idempotency_key=%s',
                (file_id, self.store.user_id, key)).fetchone()
            if existing:
                if existing['request_digest'] != digest:
                    raise StorageError('task_idempotency_conflict', '同一请求标识已用于不同输入。', 409)
                return self.view(db, existing), 200
            lifecycle = FileLifecycleService(self.assets)
            assessment = lifecycle.guard_reparse(db,project_id,file_id,request.expected_assessment_revision)
            latest = db.execute('SELECT COALESCE(max(version),0) AS n FROM file_structure_versions WHERE file_id=%s', (file_id,)).fetchone()['n']
            if latest != request.expected_latest_version:
                raise StorageError('structure_version_conflict', '结构版本已更新，请重新读取。', 409)
            if db.execute('''SELECT t.id FROM tasks t JOIN file_structure_versions s ON s.task_id=t.id
                WHERE s.file_id=%s AND t.status IN ('queued','running')''', (file_id,)).fetchone():
                raise StorageError('structure_task_pending', '已有结构任务正在处理，请读取该任务。', 409)
            if file['file_type'] != 'xlsx' or file['parse_status'] != 'parsed':
                raise StorageError('file_not_parsed', '请先完成原始文件预览解析。', 409)
            self.assets.original(file)
            parent = db.execute('SELECT id FROM file_structure_versions WHERE file_id=%s AND manifest_json IS NOT NULL ORDER BY version DESC LIMIT 1', (file_id,)).fetchone()
            structure_id, task_id = str(uuid4()), str(uuid4())
            frozen_file = {name: file[name] for name in ('id','filename','sha256','size_bytes','file_type','storage_backend','object_key')}
            if frozen_file['object_key'] is None:
                frozen_file['object_key'] = f'files/{file_id}.xlsx'
            settings = dict(excel=get_excel_settings().model_dump(), process=PROCESS_SETTINGS.copy())
            snapshot = StructureSnapshot.model_validate(dict(schema_version=1,kind='excel_structure',project={'id':project_id},
                file=frozen_file,structure_id=structure_id,parser_version=STRUCTURE_PARSER_VERSION,settings=settings)).model_dump()
            now = datetime.now(timezone.utc)
            task = dict(id=task_id,project_id=project_id,user_id=self.store.user_id,task_type='extract_dataset',
                idempotency_key=structure_id,input_digest=digest,input_snapshot=snapshot,workflow_version='excel_structure_v1',
                status='queued',phase='parse',revision=1,current_attempt=0,reason_code=None,created_at=now,updated_at=now)
            self.store.insert_task(db, task)
            db.execute('''INSERT INTO file_structure_versions(id,file_id,task_id,version,parent_id,created_by,idempotency_key,
                request_digest,source_sha256,parser_version,settings_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (structure_id,file_id,task_id,latest+1,parent['id'] if parent else None,self.store.user_id,key,digest,
                 file['sha256'],STRUCTURE_PARSER_VERSION,Jsonb(settings),now))
            self.store.append_event(db,task,'created')
            self.store.enqueue(db,task)
            lifecycle.record_reparse(db,project_id,file_id,task_id,assessment,request.expected_assessment_revision is not None)
            row = db.execute('SELECT * FROM file_structure_versions WHERE id=%s', (structure_id,)).fetchone()
            return self.view(db,row), 202

    def list(self, project_id, file_id, page=1, page_size=5):
        with self.store.connection() as db:
            self.require_file(db,project_id,file_id)
            total = db.execute('SELECT count(*) AS n FROM file_structure_versions WHERE file_id=%s',(file_id,)).fetchone()['n']
            rows = db.execute('SELECT * FROM file_structure_versions WHERE file_id=%s ORDER BY version DESC LIMIT %s OFFSET %s',
                              (file_id,page_size,(page-1)*page_size)).fetchall()
            latest = db.execute('SELECT COALESCE(max(version),0) AS n FROM file_structure_versions WHERE file_id=%s',(file_id,)).fetchone()['n']
            return dict(items=[self.view(db,row) for row in rows],total=total,page=page,page_size=page_size,latest_version=latest)

    def get(self, project_id, file_id, structure_id):
        with self.store.connection() as db:
            self.require_file(db,project_id,file_id)
            row = db.execute('SELECT * FROM file_structure_versions WHERE id=%s AND file_id=%s',(structure_id,file_id)).fetchone()
            if not row:
                raise StorageError('dataset_missing','结构版本不存在。',404)
            return self.view(db,row)

    def dataset(self, project_id, file_id, dataset_id):
        with self.store.connection() as db:
            self.require_file(db,project_id,file_id)
            row = db.execute('''SELECT d.*,s.manifest_json,s.source_sha256,s.parser_version FROM dataset_versions d JOIN file_structure_versions s ON s.id=d.structure_id
                JOIN tasks t ON t.id=s.task_id WHERE d.id=%s AND d.file_id=%s AND s.file_id=d.file_id
                AND s.version=d.version AND s.manifest_json IS NOT NULL AND t.status='succeeded' AND t.user_id=%s''',
                (dataset_id,file_id,self.store.user_id)).fetchone()
            if not row:
                raise StorageError('dataset_missing','原始数据版本不存在。',404)
            row = dict(row)
            structure = db.execute('SELECT * FROM file_structure_versions WHERE id=%s', (row['structure_id'],)).fetchone()
            self.view(db, structure)
            from app.domain.datasets.snapshots import require_structure_source
            task = self.store.require_task(db, structure['task_id'])
            if task['project_id'] != project_id:
                raise StorageError('dataset_changed', '数据版本任务与项目归属不一致。', 409)
            require_structure_source(db, task)
            parent = db.execute('''SELECT id FROM dataset_versions WHERE file_id=%s AND sheet_index=%s
                AND version<%s ORDER BY version DESC LIMIT 1''',(file_id,row['sheet_index'],row['version'])).fetchone()
            if row['parent_id'] != (parent['id'] if parent else None):
                raise StorageError('dataset_changed','数据版本父关系不一致。',409)
        content, obj = self.objects.read(row)
        sheet = obj.sheet
        if (sheet.index != row['sheet_index'] or sheet.name != row['sheet_name']
                or {**sheet.model_dump(exclude={'index','name','cells'}), 'epoch': obj.epoch} != row['summary_json']
                or obj.epoch != row['manifest_json']['epoch']
                or dataset_id not in row['manifest_json']['dataset_ids']):
            raise StorageError('dataset_changed','原始数据版本身份不一致。',409)
        return row, content, sheet

    def rows(self, project_id, file_id, dataset_id, start_row=1, limit=20):
        row, _, sheet = self.dataset(project_id,file_id,dataset_id)
        end = min(sheet.row_count,start_row+limit-1)
        cells = {}
        for cell in sheet.cells:
            if start_row <= cell.row <= end:
                cells.setdefault(cell.row,[]).append(cell.model_dump())
        return dict(dataset=self.summary(row),start_row=start_row,limit=limit,total_rows=sheet.row_count,
            has_more=end<sheet.row_count,rows=[dict(row=r,cells=cells.get(r,[])) for r in range(start_row,end+1)])
