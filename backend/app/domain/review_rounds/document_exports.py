"""Ordinary authenticated DOCX exports, bound to one immutable document."""
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from app.domain.manuscripts.service import now
from .document_contracts import WORKFLOW, ReviewDocumentInputVersion
from .documents import ReviewDocumentService
from .planning import invalid

RETRYABLE=frozenset(('storage_unavailable','task_worker_interrupted','report_render_failed'))

def input_version(task):
    snap=task['input_snapshot']
    if (task['task_type']!='review_document_export' or task['workflow_version']!=WORKFLOW or digest(snap)!=task['input_digest']
        or snap.get('project_id')!=task['project_id'] or snap.get('kind')!='review_document_export' or snap.get('workflow_version')!=WORKFLOW
        or snap.get('real_model_calls') is not False or snap.get('real_network_calls') is not False):
        raise source_conflict()
    return ReviewDocumentInputVersion(**{k:snap[k] for k in ('export_id','document_id','document_sha256','revision_id','round_id')}).model_dump()

class ReviewDocumentExportService:
    def __init__(self,assets):
        self.assets=assets;self.store=TaskStore(assets.owner_id,assets.db_config);self.documents=ReviewDocumentService(assets)
        self.directory=Path(assets.directory)/'review_document_exports'

    def row(self,db,project,identity):
        self.store.require_project(db,project)
        row=db.execute('SELECT * FROM review_document_exports WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row:raise StorageError('review_document_export_not_found','独立文档导出不存在。',404)
        self.verify(db,row)
        return row

    def verify(self,db,row):
        task=self.store.require_task(db,row['task_id']);version=input_version(task);snap=row['snapshot_json']
        document=self.documents.row(db,row['project_id'],row['document_id'])
        if (digest(row['request_json'])!=row['request_digest'] or digest(snap)!=row['snapshot_sha256'] or task['input_snapshot']!=dict(export_id=row['id'],**snap)
            or task['project_id']!=row['project_id'] or task['user_id']!=row['user_id'] or version['document_id']!=document['id']
            or version['document_sha256']!=document['snapshot_sha256'] or snap['document']!=document['snapshot_json']
            or version['revision_id']!=document['revision_id'] or version['round_id']!=document['round_id']):raise source_conflict()
        result=row['result_json'];artifact=row['artifact_json']
        if bool(result)!=(task['status']=='succeeded') or bool(result)!=bool(artifact):raise source_conflict()
        if result and (digest(result)!=row['result_sha256'] or result.get('artifact')!=artifact or artifact.get('document_sha256')!=version['document_sha256']
            or artifact.get('renderer_version','review_docx_v1')!=snap.get('renderer_version','review_docx_v1')):raise source_conflict()
        return task

    def view(self,db,row):
        task=self.verify(db,row);meta=row['artifact_json'] or {}
        return dict(id=row['id'],project_id=row['project_id'],document_id=row['document_id'],task_id=task['id'],status=task['status'],task=TaskStore.public_task(task),
            filename=meta.get('filename'),sha256=meta.get('sha256'),size_bytes=meta.get('size_bytes'),error_code=task.get('error_code'),created_at=row['created_at'].isoformat(),
            download_url=f"/api/v1/projects/{row['project_id']}/reviews/document-exports/{row['id']}/download" if meta else None)

    def create(self,project,document_id,key):
        require_key(key);body=dict(document_id=document_id)
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project);db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            old=db.execute('SELECT * FROM review_document_exports WHERE project_id=%s AND user_id=%s AND idempotency_key=%s',(project,self.store.user_id,key)).fetchone()
            if old:
                if old['request_digest']!=digest(body):raise StorageError('task_idempotency_conflict','请求标识已用于不同输入。',409)
                return self.view(db,self.row(db,project,old['id'])),200
            doc=self.documents.row(db,project,document_id)
            identity=str(uuid4());timestamp=now()
            from app.adapters.review_docx import RENDERER_VERSION
            snap=dict(kind='review_document_export',renderer_version=RENDERER_VERSION,project_id=project,document_id=document_id,document_version=doc['version'],confirmed_at=doc['confirmed_at'].isoformat() if doc['confirmed_at'] else None,document_sha256=doc['snapshot_sha256'],round_id=doc['round_id'],revision_id=doc['revision_id'],document=doc['snapshot_json'],workflow_version=WORKFLOW,real_model_calls=False,real_network_calls=False)
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='review_document_export',idempotency_key='review-document:'+identity,input_snapshot=dict(export_id=identity,**snap),workflow_version=WORKFLOW,status='queued',phase='export',revision=1,current_attempt=0,reason_code=None,created_at=timestamp,updated_at=timestamp)
            task['input_digest']=digest(task['input_snapshot'])
            self.store.insert_task(db,task);self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            db.execute('INSERT INTO review_document_exports(id,project_id,user_id,document_id,task_id,idempotency_key,request_json,request_digest,snapshot_json,snapshot_sha256,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (identity,project,self.store.user_id,document_id,task['id'],key,Jsonb(body),digest(body),Jsonb(snap),digest(snap),timestamp))
            return self.view(db,self.row(db,project,identity)),202

    def get(self,project,identity):
        with self.store.connection() as db:return self.view(db,self.row(db,project,identity))

    def listing(self,project,document_id):
        with self.store.connection() as db:
            self.documents.row(db,project,document_id)
            rows=db.execute('SELECT id FROM review_document_exports WHERE document_id=%s AND project_id=%s AND user_id=%s ORDER BY created_at DESC',(document_id,project,self.store.user_id)).fetchall()
            return dict(items=[self.view(db,self.row(db,project,r['id'])) for r in rows])

    @staticmethod
    def object_name(row,meta):
        name=meta.get('object_name','');prefix=row['id']+'-'
        try:
            token=name.removeprefix(prefix).removesuffix('.docx')
            if name!=prefix+str(UUID(token))+'.docx':raise ValueError()
        except (ValueError,TypeError,AttributeError):raise source_conflict()
        return name

    def download(self,project,identity):
        with self.store.connection() as db:
            row=self.row(db,project,identity);task=self.verify(db,row)
            if task['status']!='succeeded':raise StorageError('review_document_export_not_ready','请等待独立文档导出成功。',409)
            metadata=row['artifact_json']
        try:raw=(self.directory/self.object_name(row,metadata)).read_bytes()
        except FileNotFoundError as exc:raise StorageError('report_missing','独立文档导出文件缺失。',410) from exc
        if len(raw)!=metadata['size_bytes'] or sha256(raw).hexdigest()!=metadata['sha256'] or not raw.startswith(b'PK'):raise StorageError('report_changed','独立文档文件已变化。',409)
        return metadata,raw

def retry_in_transaction(store,db,task,expected_revision):
    if task['revision']!=expected_revision or task['status']!='failed' or task.get('error_code') not in RETRYABLE:raise invalid('此独立文档任务不能恢复。',409)
    from app.domain.report_collections.service import scoped_store
    service=ReviewDocumentExportService(scoped_store(task['user_id'],store.config))
    service.row(db,task['project_id'],input_version(task)['export_id'])
    task.update(status='queued',revision=expected_revision+1,reason_code='retry_requested',error_code=None,updated_at=max(now(),task['updated_at']),_retry_reason='manual_retry')
    store.update_task(db,task,expected_revision);store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)

def workspace(db,task):
    version=input_version(task);snap=task['input_snapshot'];document=snap['document']
    return dict(source=dict(file_id=None,filename=document['title'],analysis_run_id=None,is_current=True),
        results=dict(review_document_export_id=version['export_id'],review_document_id=version['document_id'],review_revision_id=version['revision_id'],review_round_id=version['round_id'],output=document['output'],
            review_document={key:version[key] for key in ('round_id','revision_id','document_id','export_id')}))
