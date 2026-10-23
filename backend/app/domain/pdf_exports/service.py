"""Seal exact successful DOCX objects; never select a newer upstream version."""
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.manuscripts.service import now
from app.domain.literature.service import digest
from .contracts import WORKFLOW,PdfCreateRequest

RETRYABLE=frozenset(('pdf_renderer_unavailable','pdf_conversion_timeout','pdf_renderer_busy','storage_unavailable','task_worker_interrupted','pdf_conversion_failed'))

def renderer_identity():
    from app.adapters.pdf_renderer import renderer_identity as identity
    return identity()

def missing(): return StorageError('pdf_export_not_found','PDF导出不存在。',404)

class PdfExportService:
    def __init__(self,assets):
        self.assets=assets;self.store=TaskStore(assets.owner_id,assets.db_config)
        self.directory=Path(assets.directory)/'pdf_exports'

    def source(self,db,project,kind,identity):
        self.store.require_project(db,project)
        if kind=='review_document_export':
            from app.domain.review_rounds.document_exports import ReviewDocumentExportService
            svc=ReviewDocumentExportService(self.assets)
            row=svc.row(db,project,identity)
            metadata,raw=svc.download(project,identity)
            doc=svc.documents.row(db,project,row['document_id'])
            version=dict(id=doc['id'],revision=doc['version'],kind=doc['kind'],language=doc['language'],document_sha256=doc['snapshot_sha256'])
        elif kind=='layout_export':
            from app.domain.layout_exports.service import LayoutExportService
            svc=LayoutExportService(self.assets)
            row=svc.row(db,project,identity)
            metadata,raw=svc.download(project,identity)
            version=dict(id=row['id'],layout_version=row['layout_version'],input_sha256=row['input_sha256'])
        elif kind=='manuscript_export':
            from app.domain.manuscripts.service import ManuscriptService
            row=db.execute('SELECT e.*,v.manuscript_id,v.project_id,v.revision FROM manuscript_exports e JOIN manuscript_versions v ON v.id=e.version_id WHERE e.id=%s AND v.project_id=%s AND v.user_id=%s',(identity,project,self.store.user_id)).fetchone()
            if not row: raise StorageError('pdf_source_not_found','DOCX来源不存在。',404)
            task=self.store.require_task(db,row['task_id'])
            if task['status']!='succeeded': raise StorageError('pdf_source_not_ready','请等待DOCX成功后生成PDF。',409)
            metadata,raw=ManuscriptService(self.assets).export(project,row['manuscript_id'],identity,True)
            version=dict(id=row['version_id'],revision=row['revision'])
        elif kind=='collection_report':
            from app.adapters.collection_store import CollectionStore
            row=db.execute('SELECT r.*,v.collection_id,v.revision AS source_revision,q.task_id FROM collection_reports r JOIN report_collection_versions v ON v.id=r.version_id JOIN report_collections c ON c.id=v.collection_id JOIN report_build_requests q ON q.id=r.build_request_id WHERE r.id=%s AND c.project_id=%s AND c.created_by=%s',(identity,project,self.store.user_id)).fetchone()
            if not row: raise StorageError('pdf_source_not_found','DOCX来源不存在。',404)
            if self.store.require_task(db,row['task_id'])['status']!='succeeded': raise StorageError('pdf_source_not_ready','请等待DOCX成功后生成PDF。',409)
            metadata,raw=CollectionStore(self.assets).download(project,row['collection_id'],identity)
            version=dict(id=row['version_id'],revision=row['source_revision'],export_revision=row['export_revision'])
        elif kind=='report':
            from app.adapters.report_store import ReportStore
            row=db.execute('SELECT r.*,a.file_id FROM reports r JOIN analysis_runs a ON a.id=r.analysis_run_id JOIN files f ON f.id=a.file_id WHERE r.id=%s AND f.project_id=%s',(identity,project)).fetchone()
            if not row: raise StorageError('pdf_source_not_found','DOCX来源不存在。',404)
            repository=ReportStore(self.assets)
            metadata=repository.by_id(project,row['file_id'],row['analysis_run_id'],identity)
            raw=repository.content(metadata)
            version=dict(id=row['analysis_run_id'],revision=metadata['setup_revision'],renderer_version=row['renderer_version'])
        else: raise StorageError('task_input_invalid','PDF来源类型无效。',422)
        if metadata.get('id',identity)!=identity or sha256(raw).hexdigest()!=metadata['sha256'] or len(raw)!=metadata['size_bytes']: raise source_conflict()
        return dict(source_kind=kind,source_id=identity,version=version,metadata=metadata),raw

    def row(self,db,project,identity):
        self.store.require_project(db,project)
        row=db.execute('SELECT * FROM pdf_exports WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row: raise missing()
        return row

    def verify(self,db,row):
        task=self.store.require_task(db,row['task_id'])
        snap=row['input_json']
        if (row['input_sha256']!=digest(snap) or task['input_digest']!=digest(task['input_snapshot']) or task['input_snapshot']!=dict(export_id=row['id'],**snap)
            or task['task_type']!='pdf_export' or task['workflow_version']!=WORKFLOW or task['project_id']!=row['project_id']
            or task['user_id']!=row['user_id'] or snap.get('project_id')!=row['project_id'] or snap.get('source_kind')!=row['source_kind']
            or snap.get('workflow_version')!=WORKFLOW or snap.get('source_id')!=row['source_id'] or snap.get('source_sha256')!=row['source_sha256'] or snap.get('renderer_identity')!=row['renderer_identity']): raise source_conflict()
        column={'report':'report_id','collection_report':'collection_report_id','manuscript_export':'manuscript_export_id','layout_export':'layout_export_id','review_document_export':'review_document_export_id'}[row['source_kind']]
        if row[column]!=row['source_id']: raise source_conflict()
        request=dict(source_kind=row['source_kind'],source_id=row['source_id'],parent_export_id=row['parent_export_id'])
        if digest(request)!=row['request_digest']: raise source_conflict()
        if row['parent_export_id']:
            parent=self.row(db,row['project_id'],row['parent_export_id'])
            if (parent['source_id'],parent['source_kind'],parent['source_sha256'])!=(row['source_id'],row['source_kind'],row['source_sha256']): raise source_conflict()
        return task

    def verify_source(self,db,row):
        self.verify(db,row)
        source,raw=self.source(db,row['project_id'],row['source_kind'],row['source_id'])
        if source!=row['input_json']['source'] or sha256(raw).hexdigest()!=row['source_sha256']: raise source_conflict()
        return raw

    def view(self,db,row):
        task=self.verify(db,row);meta=row['metadata_json'] or {}
        if bool(meta)!=(task['status']=='succeeded'): raise source_conflict()
        if meta and (meta.get('source_sha256')!=row['source_sha256'] or meta.get('input_sha256')!=row['input_sha256'] or meta.get('renderer_manifest')!=row['renderer_identity']): raise source_conflict()
        return dict(id=row['id'],project_id=row['project_id'],source_kind=row['source_kind'],source_id=row['source_id'],status=task['status'],task_id=row['task_id'],created_at=row['created_at'].isoformat(),
            filename=meta.get('filename'),error_code=task.get('error_code'),source_sha256=row['source_sha256'],parent_export_id=row['parent_export_id'],renderer_manifest=meta.get('renderer_manifest'),sha256=meta.get('sha256'),size_bytes=meta.get('size_bytes'),
            download_url=f"/api/v1/projects/{row['project_id']}/pdf-exports/{row['id']}/download" if meta else None)

    def create(self,project,request,parent=None):
        request=PdfCreateRequest.model_validate(request) if isinstance(request,dict) else request
        body=dict(source_kind=request.source_kind,source_id=request.source_id,parent_export_id=parent);hashed=digest(body)
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project);db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            existing=db.execute('SELECT * FROM pdf_exports WHERE project_id=%s AND user_id=%s AND request_key=%s',(project,self.store.user_id,request.request_key)).fetchone()
            if existing:
                if existing['request_digest']!=hashed: raise StorageError('task_idempotency_conflict','请求标识已用于不同输入。',409)
                return self.view(db,existing),200
            previous=None
            if parent:
                previous=self.row(db,project,parent);task=self.verify(db,previous)
                depth=0;ancestor=previous
                while ancestor['parent_export_id']:
                    depth+=1;ancestor=self.row(db,project,ancestor['parent_export_id'])
                    if depth>=3: break
                if task['status']!='failed' or task.get('error_code') not in RETRYABLE or depth>=3: raise StorageError('pdf_retry_not_allowed','此PDF任务不可重试。',409)
            source,raw=self.source(db,project,request.source_kind,request.source_id)
            identity=renderer_identity()
            if previous and (source!=previous['input_json']['source'] or identity!=previous['renderer_identity']): raise source_conflict()
            export_id=str(uuid4());timestamp=now();source_hash=sha256(raw).hexdigest()
            snapshot=dict(project_id=project,source_kind=request.source_kind,source_id=request.source_id,source_sha256=source_hash,source=source,renderer_identity=identity,workflow_version=WORKFLOW)
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='pdf_export',idempotency_key='pdf:'+export_id,input_snapshot=dict(export_id=export_id,**snapshot),workflow_version=WORKFLOW,status='queued',phase='export',revision=1,current_attempt=0,reason_code=None,created_at=timestamp,updated_at=timestamp)
            task['input_digest']=digest(task['input_snapshot'])
            self.store.insert_task(db,task);self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            column={'report':'report_id','collection_report':'collection_report_id','manuscript_export':'manuscript_export_id','layout_export':'layout_export_id','review_document_export':'review_document_export_id'}[request.source_kind]
            fields=dict(id=export_id,project_id=project,user_id=self.store.user_id,source_kind=request.source_kind,source_id=request.source_id,task_id=task['id'],parent_export_id=parent,request_key=request.request_key,request_digest=hashed,input_json=Jsonb(snapshot),input_sha256=digest(snapshot),source_sha256=source_hash,renderer_identity=Jsonb(identity),created_at=timestamp)
            fields[column]=request.source_id
            db.execute('INSERT INTO pdf_exports('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))
            return self.view(db,self.row(db,project,export_id)),201

    def retry(self,project,identity,key):
        with self.store.connection() as db: row=self.row(db,project,identity)
        return self.create(project,dict(source_kind=row['source_kind'],source_id=row['source_id'],request_key=key),identity)

    def get(self,project,identity):
        with self.store.connection() as db: return self.view(db,self.row(db,project,identity))

    def list(self,project,source_kind=None,source_id=None):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            rows=db.execute('SELECT * FROM pdf_exports WHERE project_id=%s AND user_id=%s AND (%s::text IS NULL OR source_kind=%s) AND (%s::text IS NULL OR source_id=%s) ORDER BY created_at DESC,id',(project,self.store.user_id,source_kind,source_kind,source_id,source_id)).fetchall()
            return dict(items=[self.view(db,row) for row in rows])

    @staticmethod
    def object_name(row,meta):
        from uuid import UUID
        name=meta.get('object_name','')
        prefix=row['id']+'-'
        try:
            token=name.removeprefix(prefix).removesuffix('.pdf')
            if name!=prefix+str(UUID(token))+'.pdf': raise ValueError()
        except (ValueError,TypeError,AttributeError): raise source_conflict()
        return name

    def download(self,project,identity):
        with self.store.connection() as db:
            row=self.row(db,project,identity);view=self.view(db,row)
            if view['status']!='succeeded': raise StorageError('pdf_export_not_ready','PDF尚未成功。',409)
            self.verify_source(db,row);meta=row['metadata_json']
        try: raw=(self.directory/self.object_name(row,meta)).read_bytes()
        except FileNotFoundError as exc: raise StorageError('report_missing','PDF文件缺失。',410) from exc
        if sha256(raw).hexdigest()!=meta['sha256'] or len(raw)!=meta['size_bytes'] or not raw.startswith(b'%PDF-'): raise StorageError('report_changed','PDF内容已变化。',409)
        return meta,raw


def input_version(task):
    from .contracts import PdfInputVersion
    snap=task['input_snapshot']
    return PdfInputVersion(**{k:snap[k] for k in ('export_id','source_kind','source_id','source_sha256')}).model_dump()
