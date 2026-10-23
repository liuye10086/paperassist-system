"""Lease-fenced, checkpointed local publication. No remote/model clients."""
from hashlib import sha256
import os
from threading import Event,Thread
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.report_collections.service import scoped_store
from app.domain.literature.service import digest
from .service import ManuscriptService,now
from .contracts import WORKFLOW,ManuscriptRequest


def checkpoint(db,task,node,next_node,state):
    latest=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
    if latest and latest['node']==node and latest['state_json']==state: return
    db.execute('INSERT INTO task_checkpoints(id,task_id,seq,node,next_node,state_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',
        (str(uuid4()),task['id'],latest['seq']+1 if latest else 1,node,next_node,Jsonb(state),now()))


def run_manuscript_task(task_id,task_revision,*,config=None,directory=None):
    execution=TaskExecutionStore(config=config,directory=directory)
    lease=execution.claim(task_id,task_revision)
    if lease is None: return None
    stop=Event();staged=None
    def heartbeat():
        while not stop.wait(10):
            try:
                if not execution.heartbeat(lease): return
            except StorageError: return
    thread=Thread(target=heartbeat,daemon=True);thread.start()
    try:
        with execution.connection(write=True) as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            if task['task_type'] not in ('manuscript_draft','manuscript_docx'): raise source_conflict()
            service=ManuscriptService(scoped_store(task['user_id'],execution.config,execution.assets.directory))
            version=service.verify_task(db,task,current=True);snapshot=version['snapshot_json']
            state=dict(version_id=version['id'],input_sha256=version['snapshot_sha256'],workflow_version=WORKFLOW)
            checkpoint(db,task,'check','publish',state)
        content=metadata=None
        if task['task_type']=='manuscript_docx':
            from app.adapters.manuscript_docx import build_manuscript_docx,RENDERER_VERSION
            images={}
            for group in snapshot['results_groups']:
                for figure in group['figures']:
                    source=next(s for s in snapshot['sources'] if s['id']==figure['source_ids'][0])
                    if figure.get('language_version_id') or source['kind']=='figure_language_version':
                        from .figure_language import FigureLanguageService
                        languages=FigureLanguageService(service.assets)
                        with service.store.connection() as image_db:
                            image_row=languages.row(image_db,task['project_id'],figure.get('language_version_id') or source['id'])
                            raw=languages.png(image_row)
                    elif source['kind']=='figure': raw=service.assets.figure_png(source['content'])
                    elif source['kind']=='document_version':
                        from app.domain.documents.service import DocumentService
                        documents=DocumentService(service.assets);row=documents.load(task['project_id'],source['file_id'],source['id'],True)
                        raw,_=documents.objects().image(row['result_json'],figure['image_id'])
                    else:
                        file=service.assets.file(task['project_id'],source['file_id']);raw=service.assets.original(file)
                    if sha256(raw).hexdigest()!=figure['sha256']: raise source_conflict()
                    images[figure['id']]=raw
            with service.store.connection() as export_db:
                export_row=export_db.execute('SELECT * FROM manuscript_exports WHERE id=%s',(task['input_snapshot']['export_id'],)).fetchone()
                school_intent=service.verify_school_export(export_db,version,export_row,task)
            school_plan=school_intent['plan'] if school_intent is not None else None
            if school_plan is not None:
                content=build_manuscript_docx(snapshot,images,school_plan=school_plan)
                from app.adapters.school_docx import complete_school_fields
                content,field_update=complete_school_fields(content,school_plan)
                expected='updated' if school_plan['toc']['enabled'] else 'not_requested'
                if field_update.get('status')!=expected:
                    raise StorageError('layout_field_update_failed','学校目录实际更新未完成。',422)
            else:content=build_manuscript_docx(snapshot,images)
            export_id=task['input_snapshot']['export_id']
            metadata=dict(filename=f"{'Fact-draft' if snapshot['output_language']=='en' else '事实稿'}-v{version['revision']}-{export_id[:8]}.docx",
                sha256=sha256(content).hexdigest(),size_bytes=len(content),input_sha256=version['snapshot_sha256'],renderer_version=RENDERER_VERSION)
            if school_plan is not None:metadata['school']=dict(plan=school_plan,report=school_plan['report'],field_update=field_update)
            service.directory.mkdir(parents=True,exist_ok=True)
            staged=service.directory/(export_id+'-'+lease.lease_owner+'.part')
            with staged.open('xb') as stream: stream.write(content);stream.flush();os.fsync(stream.fileno())
        with execution.connection(write=True) as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            fresh=service.verify_task(db,task,current=True)
            if fresh['snapshot_json']!=snapshot: raise source_conflict()
            if task['task_type']=='manuscript_docx':
                target=service.directory/(task['input_snapshot']['export_id']+'.docx')
                if target.exists():
                    if target.read_bytes()!=content: raise StorageError('report_changed','导出候选文件不一致。',409)
                else: staged.rename(target)
                db.execute('UPDATE manuscript_exports SET metadata_json=%s WHERE id=%s AND task_id=%s',(Jsonb(metadata),task['input_snapshot']['export_id'],task['id']))
            checkpoint(db,task,'publish','done',state)
            execution.require_lease(db,lease);execution._finish(db,task,'succeeded',None)
            return TaskStore.public_task(task)
    except LeaseLost: return None
    except Exception as exc:
        code=exc.code if isinstance(exc,StorageError) else 'storage_unavailable' if isinstance(exc,OSError) else 'report_render_failed'
        with execution.connection(write=True) as db:
            try:
                task=execution.require_lease(db,lease);execution._finish(db,task,'failed',code)
                return TaskStore.public_task(task)
            except LeaseLost: return None
    finally:
        stop.set();thread.join(timeout=1)
        if staged is not None:
            try: staged.unlink(missing_ok=True)
            except OSError: pass


def retry_in_transaction(store,db,task,expected_revision,*,assets=None):
    if task['task_type'] not in ('manuscript_draft','manuscript_docx') or task['status']!='failed' or task['revision']!=expected_revision:
        raise StorageError('task_revision_conflict','仅能恢复当前失败事实稿任务。',409)
    assets=assets or scoped_store(task['user_id'],store.config)
    ManuscriptService(assets).verify_task(db,task,current=True)
    task.update(status='queued',revision=expected_revision+1,reason_code='retry_requested',error_code=None,retry_count=0,
        updated_at=max(now(),task['updated_at']),_retry_reason='manual_retry')
    store.update_task(db,task,expected_revision);store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)
