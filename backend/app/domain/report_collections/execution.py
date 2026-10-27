"""Lease-fenced local Word worker; never submits paid model work."""
from app.domain.storage_governance import export_candidates as candidates
import hashlib
import os
from threading import Event, Thread
from uuid import UUID, uuid5
from psycopg.types.json import Jsonb
from app.adapters.collection_store import CollectionStore, now
from app.adapters.collection_docx import build_collection_report
from app.adapters.report_store import digest
from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
from app.adapters.task_store import TaskStore
from app.core.exceptions import StorageError
from app.domain.regression.common import NumericError
from app.domain.report_collections.contracts import RENDERER, invalid
from app.domain.report_collections.service import scoped_store

REPORT_NAMESPACE=UUID('e5eb1353-9472-448b-a2ee-af00c20fcfbd')


def run_collection_word_task(task_id,task_revision,*,config=None,directory=None):
    execution=TaskExecutionStore(config=config,directory=directory)
    lease=execution.claim(task_id,task_revision,task_type='collection_word_report')
    if lease is None: return None
    stop=Event()
    def heartbeat():
        while not stop.wait(10):
            try:
                if not execution.heartbeat(lease): return
            except StorageError: return
    thread=Thread(target=heartbeat,daemon=True); thread.start()
    staged=None
    try:
        from app.domain.fixed_statistics_runtime import numeric_execution_scope
        from app.domain.statistics_execution.verification import verification_scope
        with numeric_execution_scope(timeout_seconds=60), verification_scope():
            with execution.connection(write=True) as db:
                task=execution.require_lease(db,lease); execution.require_owner(db,task)
                repository=CollectionStore(scoped_store(task['user_id'],execution.config,execution.assets.directory))
                snapshot=repository.verify_task_snapshot(db,task)
                restored=candidates.restore(db,execution.assets.directory,task,lease)
            report_id=str(uuid5(REPORT_NAMESPACE,snapshot['build_request_id']))
            if restored:
                metadata,content,target=restored
            else:
                metadata={'created_at':task['created_at'].isoformat(),'id':report_id,'schema_version':1,'collection_id':snapshot['collection_id'],
                    'collection_version_id':snapshot['collection_version_id'],'build_request_id':snapshot['build_request_id'],
                    'export_revision':snapshot['export_revision'],'language':snapshot['language'],'engine':{'id':RENDERER},
                    'input_sha256':digest(snapshot),'filename':f"{'Analysis-report' if snapshot['language']=='en' else '分析报告'}-v{snapshot['export_revision']}-{report_id[:8]}.docx"}
                pngs={x['figure']['id']:repository.store.figure_png(x['figure']) for x in snapshot['items']}
                content=build_collection_report(snapshot,metadata,pngs)
                metadata.update(sha256=hashlib.sha256(content).hexdigest(),size_bytes=len(content))
                repository.directory.mkdir(parents=True,exist_ok=True)
                staged=repository.directory/(report_id+'-'+lease.lease_owner+'.part')
            with execution.connection(write=True) as db:
                task=execution.require_lease(db,lease); execution.require_owner(db,task)
                if repository.verify_task_snapshot(db,task)!=snapshot: raise invalid()
                existing=db.execute('SELECT report_json FROM collection_reports WHERE build_request_id=%s',(snapshot['build_request_id'],)).fetchone()
                if existing:
                    repository.content(existing['report_json'])
                else:
                    target=repository.directory/(report_id+'.docx')
                    if not restored:
                        candidates.capture(db,execution.assets.directory,task,lease,target,staged,content,metadata)
                    candidates.publish(db,execution.assets.directory,task,lease,metadata)
                    db.execute('''INSERT INTO collection_reports (id,build_request_id,version_id,export_revision,renderer_version,report_json,input_json,sha256,created_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(report_id,snapshot['build_request_id'],snapshot['collection_version_id'],snapshot['export_revision'],RENDERER,Jsonb(metadata),Jsonb(snapshot),metadata['sha256'],metadata['created_at']))
                db.execute("UPDATE report_build_requests SET status='succeeded',error_code=NULL,updated_at=clock_timestamp() WHERE id=%s",(snapshot['build_request_id'],))
                execution.require_lease(db,lease)
                execution._finish(db,task,'succeeded',None)
                return TaskStore.public_task(task)
    except LeaseLost: return None
    except Exception as exc:
        code=exc.code if isinstance(exc,(StorageError,NumericError)) else 'storage_unavailable' if isinstance(exc,OSError) else 'report_render_failed'
        try:
            with execution.connection(write=True) as db:
                task=execution.require_lease(db,lease)
                receipt=getattr(exc,'execution_receipt',None)
                if receipt is not None:
                    from app.domain.statistics_execution.verification import validate_statistics_receipt
                    validate_statistics_receipt(receipt)
                    task['execution_receipt']=receipt
                db.execute("UPDATE report_build_requests SET status='failed',error_code=%s,updated_at=clock_timestamp() WHERE task_id=%s",(code,task_id))
                execution._finish(db,task,'failed',code)
                return TaskStore.public_task(task)
        except LeaseLost: return None
    finally:
        stop.set(); thread.join(timeout=1)
        # Complete and partial governed candidates remain charged and retained.


def retry_collection_in_transaction(store,db,task,expected_revision):
    if task['task_type']!='collection_word_report' or task['status']!='failed' or task['revision']!=expected_revision:
        raise StorageError('task_revision_conflict','仅能重试当前版本的失败报告任务。',409)
    repository=CollectionStore(scoped_store(task['user_id'],store.config))
    repository.verify_task_snapshot(db,task)
    candidates.authorize(db,repository.store.directory,task)
    task.update(status='queued',revision=expected_revision+1,reason_code='retry_requested',error_code=None,retry_count=0,updated_at=max(now(),task['updated_at']),_retry_reason='manual_retry')
    store.update_task(db,task,expected_revision); store.append_event(db,task,'requeued'); store.enqueue(db,task)
    db.execute("UPDATE report_build_requests SET status='queued',error_code=NULL,updated_at=clock_timestamp() WHERE task_id=%s",(task['id'],))
    return store.public_task(task)
