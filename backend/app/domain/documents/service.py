"""Owner-scoped immutable document version access and serialized reparse."""
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import quote
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.files import require_file
from app.domain.documents.snapshots import DocxFileSnapshot
from app.domain.file_lifecycle.contracts import AssessmentRevision
from app.domain.file_lifecycle.service import FileLifecycleService

class ReparseRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    expected_latest_version: int = Field(ge=1)
    expected_assessment_revision: AssessmentRevision | None = None

class OcrRequest(ReparseRequest):
    page_numbers: list[int] = Field(min_length=1,max_length=10)

    @field_validator('page_numbers')
    @classmethod
    def selected_pages(cls,value):
        if len(set(value))!=len(value) or any(not 1<=p<=100 for p in value):
            raise ValueError('Unique physical pages from 1 to 100 required')
        return sorted(value)

def word_snapshot(project_id, file, parse_id, version):
    from app.adapters.docx_parser import DOCX_SETTINGS, PARSER_VERSION
    return DocxFileSnapshot.model_validate(dict(schema_version=1, kind='docx_document',
        project={'id':project_id}, file=file, parse_id=parse_id, parse_version=version,
        parser_version=PARSER_VERSION, settings=DOCX_SETTINGS)).model_dump()

def document_snapshot(project_id, file, parse_id, version):
    if file['file_type'] in ('png','jpeg'):
        from app.domain.documents.ocr_snapshots import ocr_snapshot
        return ocr_snapshot(project_id,file,parse_id,version,[1])
    if file['file_type'] == 'docx':
        return word_snapshot(project_id, file, parse_id, version)
    from app.domain.documents.pdf_contracts import PDF_SETTINGS, PARSER_VERSION
    from app.domain.documents.snapshots import PdfFileSnapshot
    return PdfFileSnapshot.model_validate(dict(schema_version=1, kind='pdf_document',
        project={'id':project_id}, file=file, parse_id=parse_id, parse_version=version,
        parser_version=PARSER_VERSION, settings=PDF_SETTINGS)).model_dump()

class DocumentService:
    def __init__(self, assets):
        self.assets = assets
        self.store = TaskStore(assets.owner_id, assets.db_config)

    def file(self, db, project_id, file_id, lock=False):
        self.store.require_project(db, project_id)
        file = require_file(db, project_id, file_id, lock=lock)
        if file['file_type'] not in ('docx', 'pdf', 'png', 'jpeg'):
            raise StorageError('unsupported_file_type', '此接口仅支持 Word、PDF 或图片。', 422)
        return file

    def row(self, db, file_id, parse_id):
        row = db.execute('SELECT r.*,t.status,t.error_code,t.input_snapshot,t.workflow_version,t.project_id,t.user_id,t.task_type FROM file_parse_results r JOIN tasks t ON t.id=r.task_id WHERE r.file_id=%s AND r.id=%s', (file_id, parse_id)).fetchone()
        if not row:
            raise StorageError('document_version_not_found', '文档解析版本不存在。', 404)
        return row

    def validate(self, db, row):
        from app.domain.file_parsing import require_parse_source
        task = dict(row, id=row['task_id'])
        if row['user_id'] != self.store.user_id or row['workflow_version'] not in ('docx_document_v1','pdf_document_v1','ocr_document_v1'):
            raise source_conflict()
        require_parse_source(db, task)
        if row['result_json'] is not None:
            from app.maintenance.document_source_audit import validate_manifest
            validate_manifest(row['result_json'],row['id'])
            if row['result_json']['kind'] != row['input_snapshot']['kind']:
                raise source_conflict()
            if row['status'] != 'succeeded':
                raise source_conflict()

    def projection(self, row, project_id):
        prefix = '/api/v1/projects/{}/files/{}/document-versions/{}'.format(*[quote(v,safe='') for v in (project_id,row['file_id'],row['id'])])
        saved = row['result_json']
        if saved is not None and (saved.get('kind') not in ('docx_document','pdf_document','ocr_document') or not isinstance(saved.get('summary'),dict)):
            raise source_conflict()
        result = dict(id=row['id'],file_id=row['file_id'],version=row['version'],task_id=row['task_id'],status=row['status'],
            created_at=row['created_at'].astimezone(timezone.utc).isoformat(),
            completed_at=row['completed_at'].astimezone(timezone.utc).isoformat() if row['completed_at'] else None,
            parser_version=row['parser_version'],summary=saved['summary'] if saved else None,
            error={'code':row['error_code'],'message':'文件解析失败，请检查文件或重试。'} if row['error_code'] else None,
            download_url=prefix+'/download' if saved else None,blocks_url=prefix+'/blocks' if saved else None)
        result['kind']=row['input_snapshot']['kind']
        if row['workflow_version'] in ('pdf_document_v1','ocr_document_v1'):
            result.pop('blocks_url')
            result.update(pages_url=prefix+'/pages' if saved else None)
        if row['workflow_version']=='ocr_document_v1':
            result['selected_pages']=row['input_snapshot']['page_numbers']
        return result

    def list(self, project_id, file_id, page):
        with self.store.connection() as db:
            self.file(db,project_id,file_id)
            total = db.execute('SELECT count(*) AS n FROM file_parse_results WHERE file_id=%s',(file_id,)).fetchone()['n']
            ids = db.execute('SELECT id FROM file_parse_results WHERE file_id=%s ORDER BY version DESC LIMIT 5 OFFSET %s',(file_id,(page-1)*5)).fetchall()
            rows = [self.row(db,file_id,item['id']) for item in ids]
            for row in rows:
                self.validate(db,row)
            return dict(items=[self.projection(row,project_id) for row in rows],total=total,page=page,page_size=5,latest_version=total)

    def load(self, project_id, file_id, parse_id, require_success=False):
        with self.store.connection() as db:
            self.file(db,project_id,file_id)
            row = self.row(db,file_id,parse_id)
            self.validate(db,row)
            if row['workflow_version']=='ocr_document_v1':
                self.assets.original(row['input_snapshot']['file'])
        if require_success and row['result_json'] is None:
            raise StorageError('file_parse_pending','此版本尚无可用解析结果。',409)
        return row

    def objects(self):
        from app.adapters.document_objects import DocumentObjects
        return DocumentObjects(self.assets.directory)

    def read(self, row):
        raw, document = self.objects().read(row['result_json'])
        if document.filename != row['input_snapshot']['file']['filename'] or document.parser_version != row['parser_version']:
            raise source_conflict()
        if document.counts.model_dump() != row['result_json']['summary']['counts'] or [w.model_dump() for w in document.warnings] != row['result_json']['summary']['warnings']:
            raise source_conflict()
        if document.kind=='ocr_document':
            from app.adapters.ocr_result_validation import validate_ocr_document
            validate_ocr_document(document,row['input_snapshot'])
        return raw, document

    def detail(self, project_id, file_id, parse_id):
        row = self.load(project_id,file_id,parse_id)
        result = self.projection(row,project_id)
        if row['workflow_version'] == 'pdf_document_v1':
            if row['result_json']:
                self.read(row)
            return result
        if row['workflow_version']=='ocr_document_v1':
            result.update(images=[],source_type=row['input_snapshot']['file']['file_type'],source_pages=None)
            if row['result_json']:
                _,document=self.read(row)
                result.update(source_pages=document.source_pages,
                    images=[dict(image.model_dump(),download_url=result['download_url'].removesuffix('/download')+'/images/'+quote(image.id,safe='')) for image in document.images])
            return result
        result.update(styles=[],sections=[],images=[])
        if row['result_json']:
            _, document = self.read(row)
            result.update(styles=[s.model_dump() for s in document.styles],sections=[s.model_dump() for s in document.sections],
                images=[dict(image.model_dump(),download_url=result['download_url'].removesuffix('/download')+'/images/'+quote(image.id,safe='')) for image in document.images])
        return result

    def blocks(self, project_id, file_id, parse_id, page):
        row = self.load(project_id,file_id,parse_id,True)
        self.require_format(row, 'docx_document_v1')
        _, document = self.read(row)
        return dict(items=[b.model_dump() for b in document.blocks[(page-1)*20:page*20]],total=len(document.blocks),page=page,page_size=20)

    def require_format(self, row, workflow):
        if row['workflow_version'] not in ((workflow,) if isinstance(workflow,str) else workflow):
            raise StorageError('unsupported_file_type', '此内容接口不适用于该文档格式。', 422)

    def pages(self, project_id, file_id, parse_id, page):
        row = self.load(project_id,file_id,parse_id,True)
        self.require_format(row, ('pdf_document_v1','ocr_document_v1'))
        _, document = self.read(row)
        return dict(items=[p.model_dump() for p in document.pages[page-1:page]],total=len(document.pages),page=page,page_size=1)

    def create(self, project_id, file_id, request, key, *, ocr=False):
        body=dict(file_id=file_id,expected_latest_version=request.expected_latest_version)
        if request.expected_assessment_revision is not None:
            body['expected_assessment_revision'] = request.expected_assessment_revision
        if ocr: body.update(kind='ocr_document',page_numbers=request.page_numbers)
        digest = hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
        scoped_key = ('ocr:' if ocr else 'document:') + file_id + ':' + key
        with self.store.connection(write=True) as db:
            file = self.file(db,project_id,file_id,True)
            if ocr and (file['file_type']=='docx' or file['file_type'] in ('png','jpeg') and request.page_numbers!=[1]):
                raise StorageError('invalid_document','此文件不支持所选识别页。',422)
            existing = db.execute('SELECT r.id,t.input_digest FROM tasks t JOIN file_parse_results r ON r.task_id=t.id WHERE t.project_id=%s AND t.user_id=%s AND t.task_type=\'parse_file\' AND t.idempotency_key=%s',(project_id,self.store.user_id,scoped_key)).fetchone()
            if existing:
                if existing['input_digest'] != digest:
                    raise StorageError('document_idempotency_conflict','同一操作标识已用于不同解析请求。',409)
                row = self.row(db,file_id,existing['id']); self.validate(db,row)
                return self.projection(row,project_id),200
            lifecycle = FileLifecycleService(self.assets)
            assessment = lifecycle.guard_reparse(db,project_id,file_id,request.expected_assessment_revision)
            latest = db.execute('SELECT max(version) AS n FROM file_parse_results WHERE file_id=%s',(file_id,)).fetchone()['n']
            if latest != request.expected_latest_version:
                raise StorageError('document_version_conflict','解析版本已更新，请重新载入。',409)
            if db.execute("SELECT t.id FROM tasks t JOIN file_parse_results r ON r.task_id=t.id WHERE r.file_id=%s AND t.status IN ('queued','running','waiting_input','waiting_confirmation')",(file_id,)).fetchone():
                raise StorageError('document_parse_active','文件已有在途解析，请等待完成。',409)
            self.assets.original(dict(file))
            parse_id,task_id = str(uuid4()),str(uuid4()); now=datetime.now(timezone.utc)
            frozen_file={k:file[k] for k in ('id','filename','sha256','size_bytes','file_type','storage_backend','object_key')}
            if ocr:
                from app.domain.documents.ocr_snapshots import ocr_snapshot
                snapshot=ocr_snapshot(project_id,frozen_file,parse_id,latest+1,request.page_numbers)
            else:
                snapshot=document_snapshot(project_id,frozen_file,parse_id,latest+1)
            task=dict(id=task_id,project_id=project_id,user_id=self.store.user_id,task_type='parse_file',idempotency_key=scoped_key,input_digest=digest,input_snapshot=snapshot,workflow_version=snapshot['kind']+'_v1',status='queued',phase='parse',revision=1,current_attempt=0,reason_code=None,created_at=now,updated_at=now)
            self.store.insert_task(db,task)
            db.execute('INSERT INTO file_parse_results(id,file_id,task_id,version,source_sha256,parser_version,settings_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',(parse_id,file_id,task_id,latest+1,file['sha256'],snapshot['parser_version'],Jsonb(snapshot['settings']),now))
            self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            lifecycle.record_reparse(db,project_id,file_id,task_id,assessment,request.expected_assessment_revision is not None)
            db.execute("UPDATE files SET parse_status='queued',error_json=NULL,parse_revision=parse_revision+1 WHERE id=%s",(file_id,))
            return self.projection(self.row(db,file_id,parse_id),project_id),202
