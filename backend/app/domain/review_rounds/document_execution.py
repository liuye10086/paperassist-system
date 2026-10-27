"""Fenced local conversion; each attempt owns its own unpublished output path."""
import os
from app.domain.storage_governance import export_candidates as candidates
from hashlib import sha256
from threading import Event,Thread
from psycopg.types.json import Jsonb
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.report_collections.service import scoped_store
from .document_exports import ReviewDocumentExportService
from app.domain.literature.service import digest
from app.adapters.review_docx import render_review_document,RENDERER_VERSION

SAFE=frozenset(('task_owner_unavailable','task_source_conflict','source_conflict','report_changed','report_missing','storage_unavailable','review_revision_not_ready','report_render_failed'))


def run_review_document_export_task(task_id,task_revision,*,config=None,directory=None):
    execution=TaskExecutionStore(config=config,directory=directory)
    lease=execution.claim(task_id,task_revision,task_type='review_document_export')
    if lease is None: return None
    stop=Event();staged=None;target=None
    def heartbeat():
        while not stop.wait(10):
            try:
                if not execution.heartbeat(lease): return
            except StorageError: return
    thread=Thread(target=heartbeat,daemon=True);thread.start()
    try:
        with execution.connection(write=True) as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            service=ReviewDocumentExportService(scoped_store(task['user_id'],execution.config,execution.assets.directory))
            row=service.row(db,task['project_id'],task['input_snapshot']['export_id'])
            if row['task_id']!=task_id: raise source_conflict()
            service.verify(db,row)
            if row['snapshot_json'].get('renderer_version','review_docx_v1')!=RENDERER_VERSION:
                raise StorageError('task_source_conflict','独立文档展示模板已变化，请新建导出，旧成功文件仍保留。',409)
            raw=row['snapshot_json']['document']
            restored=candidates.restore(db,execution.assets.directory,task,lease)
        if restored:
            metadata,content,target=restored
        else:
            content=render_review_document(dict(raw,document_version=row['snapshot_json']['document_version'],confirmed_at=row['snapshot_json']['confirmed_at']))
            if not isinstance(content,bytes) or not content.startswith(b'PK') or len(content)>100*1024*1024: raise StorageError('report_render_failed','独立文档输出无效。',422)
            service.directory.mkdir(parents=True,exist_ok=True)
            object_name=row['id']+'-'+lease.lease_owner+'.docx'
            staged=service.directory/(object_name+'.part');target=service.directory/object_name
            metadata=dict(filename=('review-response' if raw['kind']=='reply' else 'review-comparison')+'-'+raw['language']+'.docx',sha256=sha256(content).hexdigest(),size_bytes=len(content),document_sha256=row['snapshot_json']['document_sha256'],object_name=object_name,renderer_version=RENDERER_VERSION)
        with execution.connection(write=True) as db:
            db.execute('SELECT id FROM tasks WHERE id=%s FOR UPDATE',(task_id,)).fetchone()
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            fresh=service.row(db,task['project_id'],row['id']);service.verify(db,fresh)
            if fresh['snapshot_json']!=row['snapshot_json']: raise source_conflict()
            execution.require_lease(db,lease)
            if not restored:
                candidates.capture(db,execution.assets.directory,task,lease,target,staged,content,metadata)
            candidates.publish(db,execution.assets.directory,task,lease,metadata)
            result=dict(artifact=metadata)
            db.execute('UPDATE review_document_exports SET result_json=%s,result_sha256=%s,artifact_json=%s WHERE id=%s AND task_id=%s AND result_json IS NULL',(Jsonb(result),digest(result),Jsonb(metadata),row['id'],task_id))
            execution.require_lease(db,lease);execution._finish(db,task,'succeeded',None)
        return TaskStore.public_task(task)
    except Exception as exc:
        code=exc.code if isinstance(exc,StorageError) and exc.code in SAFE | candidates.STORAGE_ERRORS else 'storage_unavailable' if isinstance(exc,OSError) else 'report_render_failed'
        try:
            with execution.connection(write=True) as db:
                # COMMIT can succeed even when its acknowledgement is lost. Only
                # durable metadata under the publication lock can prove whether
                # this candidate is published; an in-memory flag cannot.
                persisted=db.execute('SELECT * FROM tasks WHERE id=%s FOR UPDATE',(task_id,)).fetchone()
                export=db.execute('SELECT artifact_json FROM review_document_exports WHERE task_id=%s',(task_id,)).fetchone()
                metadata=export['artifact_json'] if export else None
                if target is not None and isinstance(metadata,dict) and metadata.get('object_name')==target.name:
                    return TaskStore.public_task(dict(persisted)) if persisted and persisted['status']=='succeeded' else None
                # A completed renderer followed by a publication error is local
                # recovery, never permission for a replacement child conversion.
                governed=candidates.protected(db,execution.assets.directory,dict(persisted)) if persisted else False
                if governed and code in ('pdf_conversion_failed','report_render_failed'):
                    code='storage_accounting_unknown'
                if target is not None and export is not None and not governed:
                    try: target.unlink(missing_ok=True)
                    except OSError: pass
                try:
                    task=execution.require_lease(db,lease);execution._finish(db,task,'failed',code)
                    return TaskStore.public_task(task)
                except LeaseLost: return None
        except Exception:
            # Reconnection/read/commit may itself be uncertain. Preserve the
            # candidate for protected expiry recovery rather than deleting data.
            return None
    finally:
        stop.set();thread.join(timeout=1)
        # The candidate ledger owns all staged bytes, including unknown commits.


def clean_expired_attempt(execution,db,task):
    """Only remove a known expired attempt's own unpublished files."""
    from uuid import UUID
    if candidates.protected(db,execution.assets.directory,task): return
    row=db.execute('SELECT id,artifact_json FROM review_document_exports WHERE task_id=%s',(task['id'],)).fetchone()
    attempt=db.execute("SELECT lease_owner,lease_expires_at FROM task_attempts WHERE task_id=%s AND attempt_no=%s AND status='running' AND lease_expires_at<=clock_timestamp()",(task['id'],task['current_attempt'])).fetchone()
    if not row or row['artifact_json'] is not None or not attempt: return
    try:
        export_id=str(UUID(row['id']));token=str(UUID(attempt['lease_owner']))
    except (ValueError,TypeError,AttributeError): return
    directory=execution.assets.directory/'review_document_exports'
    for suffix in ('.docx','.docx.part'):
        try: (directory/(export_id+'-'+token+suffix)).unlink(missing_ok=True)
        except OSError: pass
