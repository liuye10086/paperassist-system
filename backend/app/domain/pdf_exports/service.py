"""Read frozen historical PDF exports with exact owner/source/output checks."""
from app.domain.storage_governance import export_candidates as candidates
from hashlib import sha256
from pathlib import Path
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.literature.service import digest
from .contracts import WORKFLOW
from app.domain.docx_sources import DocxSourceReader

def missing(): return StorageError('pdf_export_not_found','PDF导出不存在。',404)

class PdfExportService(DocxSourceReader):
    def __init__(self,assets):
        self.assets=assets;self.store=TaskStore(assets.owner_id,assets.db_config)
        self.directory=Path(assets.directory)/'pdf_exports'

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
        column={'report':'report_id','collection_report':'collection_report_id','manuscript_export':'manuscript_export_id','layout_export':'layout_export_id','review_document_export':'review_document_export_id','research_report':'research_report_member_id'}[row['source_kind']]
        if row[column]!=row['source_id']: raise source_conflict()
        request=dict(source_kind=row['source_kind'],source_id=row['source_id'],parent_export_id=row['parent_export_id'])
        if digest(request)!=row['request_digest']: raise source_conflict()
        if row['parent_export_id']:
            parent=self.row(db,row['project_id'],row['parent_export_id'])
            if (parent['source_id'],parent['source_kind'],parent['source_sha256'])!=(row['source_id'],row['source_kind'],row['source_sha256']): raise source_conflict()
        return task

    def verify_source(self,db,row,*,progress=None):
        self.verify(db,row)
        source,raw=self.source(db,row['project_id'],row['source_kind'],row['source_id'],progress=progress)
        if source!=row['input_json']['source'] or sha256(raw).hexdigest()!=row['source_sha256']: raise source_conflict()
        return raw

    def view(self,db,row):
        task=self.verify(db,row);meta=row['metadata_json'] or {}
        if bool(meta)!=(task['status']=='succeeded'): raise source_conflict()
        if meta and (meta.get('source_sha256')!=row['source_sha256'] or meta.get('input_sha256')!=row['input_sha256'] or meta.get('renderer_manifest')!=row['renderer_identity']): raise source_conflict()
        mode=candidates.recovery_mode(db,self.assets.directory,task)
        return dict(recovery_mode=mode,id=row['id'],project_id=row['project_id'],source_kind=row['source_kind'],source_id=row['source_id'],status=task['status'],task_id=row['task_id'],created_at=row['created_at'].isoformat(),
            filename=meta.get('filename'),error_code=task.get('error_code'),source_sha256=row['source_sha256'],parent_export_id=row['parent_export_id'],renderer_manifest=meta.get('renderer_manifest'),sha256=meta.get('sha256'),size_bytes=meta.get('size_bytes'),
            download_url=f"/api/v1/projects/{row['project_id']}/pdf-exports/{row['id']}/download" if meta else None,
            **({'presentation':meta['presentation']} if meta.get('presentation') else {}))

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

    def download(self,project,identity,*,progress=None):
        with self.store.connection() as db:
            row=self.row(db,project,identity);view=self.view(db,row)
            if view['status']!='succeeded': raise StorageError('pdf_export_not_ready','PDF尚未成功。',409)
            self.verify_source(db,row,progress=progress);meta=row['metadata_json']
        try: raw=(self.directory/self.object_name(row,meta)).read_bytes()
        except FileNotFoundError as exc: raise StorageError('report_missing','PDF文件缺失。',410) from exc
        if sha256(raw).hexdigest()!=meta['sha256'] or len(raw)!=meta['size_bytes'] or not raw.startswith(b'%PDF-'): raise StorageError('report_changed','PDF内容已变化。',409)
        if progress is not None:progress()
        return meta,raw


def input_version(task):
    from .contracts import PdfInputVersion
    snap=task['input_snapshot']
    return PdfInputVersion(**{k:snap[k] for k in ('export_id','source_kind','source_id','source_sha256')}).model_dump()
