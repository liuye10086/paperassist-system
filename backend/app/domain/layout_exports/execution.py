"""Fenced local conversion; each attempt owns its own unpublished output path."""
import os
from hashlib import sha256
from threading import Event,Thread
from psycopg.types.json import Jsonb
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.report_collections.service import scoped_store
from .service import LayoutExportService,renderer_identity

SAFE=frozenset(('pdf_renderer_unavailable','pdf_conversion_failed','pdf_conversion_timeout','pdf_renderer_busy','pdf_input_invalid','pdf_renderer_mismatch','task_owner_unavailable','task_source_conflict','source_conflict','report_changed','report_missing','report_source_changed','report_source_conflict','storage_unavailable','pdf_source_not_found','pdf_source_not_ready','layout_field_update_failed','layout_source_invalid','layout_source_mismatch','layout_target_invalid','layout_formula_invalid','layout_formula_too_wide'))

def prepare_layout_docx(content,options,*,language):
    from app.adapters.document_layout import prepare_layout_docx as prepare
    return prepare(content,options,language=language)

def run_layout_task(task_id,task_revision,*,config=None,directory=None):
    execution=TaskExecutionStore(config=config,directory=directory)
    lease=execution.claim(task_id,task_revision,task_type='layout_docx')
    if lease is None: return None
    stop=Event();staged=None;target=None
    def heartbeat():
        while not stop.wait(10):
            try:
                if not execution.heartbeat(lease): return
            except StorageError: return
    thread=Thread(target=heartbeat,daemon=True);thread.start()
    try:
        with execution.connection() as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            service=LayoutExportService(scoped_store(task['user_id'],execution.config,execution.assets.directory))
            row=service.row(db,task['project_id'],task['input_snapshot']['export_id'])
            if row['task_id']!=task_id: raise source_conflict()
            raw=service.verify_source(db,row)
            if renderer_identity()!=row['renderer_identity']: raise StorageError('pdf_renderer_mismatch','PDF转换环境与冻结身份不符。',409)
        from app.domain.document_layout import LayoutOptions
        content=prepare_layout_docx(raw,LayoutOptions.model_validate(row['input_json']['layout']),language=row['input_json']['output_language'])
        if not isinstance(content,bytes) or not content.startswith(b'PK') or len(content)>100*1024*1024: raise StorageError('pdf_conversion_failed','PDF转换输出无效。',422)
        service.directory.mkdir(parents=True,exist_ok=True)
        object_name=row['id']+'-'+lease.lease_owner+'.docx'
        staged=service.directory/(object_name+'.part');target=service.directory/object_name
        with staged.open('xb') as stream: stream.write(content);stream.flush();os.fsync(stream.fileno())
        metadata=dict(filename=pdf_filename(row['input_json']['source']['metadata']['filename']),sha256=sha256(content).hexdigest(),size_bytes=len(content),
            source_sha256=row['source_sha256'],input_sha256=row['input_sha256'],renderer_manifest=row['renderer_identity'],object_name=object_name)
        with execution.connection(write=True) as db:
            db.execute('SELECT id FROM tasks WHERE id=%s FOR UPDATE',(task_id,)).fetchone()
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            fresh=service.row(db,task['project_id'],row['id']);fresh_raw=service.verify_source(db,fresh)
            if fresh_raw!=raw or fresh['input_json']!=row['input_json'] or renderer_identity()!=row['renderer_identity']: raise source_conflict()
            execution.require_lease(db,lease)
            staged.rename(target)
            db.execute('UPDATE layout_exports SET metadata_json=%s WHERE id=%s AND task_id=%s AND metadata_json IS NULL',(Jsonb(metadata),row['id'],task_id))
            execution.require_lease(db,lease);execution._finish(db,task,'succeeded',None)
        return TaskStore.public_task(task)
    except Exception as exc:
        code=exc.code if isinstance(exc,StorageError) and exc.code in SAFE else 'storage_unavailable' if isinstance(exc,OSError) else 'pdf_conversion_failed'
        try:
            with execution.connection(write=True) as db:
                # COMMIT can succeed even when its acknowledgement is lost. Only
                # durable metadata under the publication lock can prove whether
                # this candidate is published; an in-memory flag cannot.
                persisted=db.execute('SELECT * FROM tasks WHERE id=%s FOR UPDATE',(task_id,)).fetchone()
                export=db.execute('SELECT metadata_json FROM layout_exports WHERE task_id=%s',(task_id,)).fetchone()
                metadata=export['metadata_json'] if export else None
                if target is not None and isinstance(metadata,dict) and metadata.get('object_name')==target.name:
                    return TaskStore.public_task(dict(persisted)) if persisted and persisted['status']=='succeeded' else None
                # No other attempt uses this UUID path. Delete only after the
                # locked durable record proves it does not reference our file.
                if target is not None and export is not None:
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
        for path in (staged,):
            if path is not None:
                try: path.unlink(missing_ok=True)
                except OSError: pass

def pdf_filename(filename):
    # Only presentation metadata. Storage names are server-created UUIDs.
    from pathlib import PurePath
    return PurePath(filename).stem+'-layout.docx'


def clean_expired_attempt(execution,db,task):
    """Only remove a known expired attempt's own unpublished files."""
    from uuid import UUID
    row=db.execute('SELECT id,metadata_json FROM layout_exports WHERE task_id=%s',(task['id'],)).fetchone()
    attempt=db.execute("SELECT lease_owner,lease_expires_at FROM task_attempts WHERE task_id=%s AND attempt_no=%s AND status='running' AND lease_expires_at<=clock_timestamp()",(task['id'],task['current_attempt'])).fetchone()
    if not row or row['metadata_json'] is not None or not attempt: return
    try:
        export_id=str(UUID(row['id']));token=str(UUID(attempt['lease_owner']))
    except (ValueError,TypeError,AttributeError): return
    directory=execution.assets.directory/'layout_exports'
    for suffix in ('.docx','.docx.part'):
        try: (directory/(export_id+'-'+token+suffix)).unlink(missing_ok=True)
        except OSError: pass
