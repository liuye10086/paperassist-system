"""Lease-fenced, checkpointed local publication. No remote/model clients."""
from app.domain.storage_governance import export_candidates as candidates
from hashlib import sha256
import os
from threading import Event,Thread
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.tasks.publication_transaction import publication_transaction,PublicationFailed
from app.domain.report_collections.service import scoped_store
from app.domain.literature.service import digest
from .service import ManuscriptService,now
from .contracts import WORKFLOW,ManuscriptRequest


def checkpoint(db,task,node,next_node,state):
    latest=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
    if latest and latest['node']==node and latest['state_json']==state: return
    db.execute('INSERT INTO task_checkpoints(id,task_id,seq,node,next_node,state_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',
        (str(uuid4()),task['id'],latest['seq']+1 if latest else 1,node,next_node,Jsonb(state),now()))


def images_for(service,project,snapshot):
    images={}
    for group in snapshot['results_groups']:
        for figure in group['figures']:
            source=next(s for s in snapshot['sources'] if s['id']==figure['source_ids'][0])
            if figure.get('language_version_id') or source['kind']=='figure_language_version':
                from .figure_language import FigureLanguageService
                languages=FigureLanguageService(service.assets)
                with service.store.connection() as image_db:
                    image_row=languages.row(image_db,project,figure.get('language_version_id') or source['id'])
                    raw=languages.png(image_row)
            elif source['kind']=='research_figure_version':
                from app.domain.research_results.figures import ResearchFigureService
                _,raw=ResearchFigureService(service.assets).member(project,source['id'],figure['research_member_id'])
            elif source['kind']=='figure':raw=service.assets.figure_png(source['content'])
            elif source['kind']=='document_version':
                from app.domain.documents.service import DocumentService
                documents=DocumentService(service.assets);row=documents.load(project,source['file_id'],source['id'],True)
                raw,_=documents.objects().image(row['result_json'],figure['image_id'])
            else:
                file=service.assets.file(project,source['file_id']);raw=service.assets.original(file)
            if sha256(raw).hexdigest()!=figure['sha256']:raise source_conflict()
            images[figure['id']]=raw
    return images


def presentation_images(service,project,snapshot):
    from app.domain.manuscript_writing.language import figure_materials,figure_language
    with service.store.connection() as db:images,items=figure_materials(service.assets,db,project,snapshot)
    figures=[f for g in snapshot['results_groups'] for f in g['figures']]
    for item in items:
        figure=next(f for f in figures if item['location']=='image:'+f['id'] or item['location'].startswith('image:'+f['id']+':'))
        item['target_language']=figure_language(snapshot,figure['id'])
        item['protected_identity']=False
    return images,items


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
        with publication_transaction(execution,lease) as (db,progress):
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            if task['task_type'] not in ('manuscript_draft','manuscript_docx'): raise source_conflict()
            service=ManuscriptService(scoped_store(task['user_id'],execution.config,execution.assets.directory))
            version=service.verify_task(db,task,current=True,progress=progress);snapshot=version['snapshot_json'];progress()
            state=dict(version_id=version['id'],input_sha256=version['snapshot_sha256'],workflow_version=WORKFLOW)
            checkpoint(db,task,'check','publish',state)
            restored=candidates.restore(db,execution.assets.directory,task,lease,progress=progress) if task['task_type']=='manuscript_docx' else None
        content=metadata=None
        if restored:
            metadata,content,target=restored
        elif task['task_type']=='manuscript_docx':
            from app.adapters.manuscript_docx import build_manuscript_docx,RENDERER_VERSION
            presentation=version.get('_presentation_context')
            selected=presentation['selected'] if presentation is not None else version
            rendered=selected['snapshot_json']
            images=images_for(service,task['project_id'],rendered) if presentation is None else {}
            with service.store.connection() as export_db:
                export_row=export_db.execute('SELECT * FROM manuscript_exports WHERE id=%s',(task['input_snapshot']['export_id'],)).fetchone()
                school_intent=service.verify_school_export(export_db,version,export_row,task)
            school_plan=school_intent['plan'] if school_intent is not None else None
            presentation_metadata=None
            if presentation is not None:
                from .presentation_export import excluded_chapters,actual_checks,confirmed_metadata
                from app.adapters.manuscript_presentation_docx import decorate_docx,blind_docx,language_inventory,actual_image_inventory,language_observations
                config=presentation['preview']['config'];binding=presentation['binding']
                render_plan=task['input_snapshot']['presentation'].get('render_school_plan') or school_plan
                language_review=config.get('language_review')
                if language_review:
                    prior,content=service.export(task['project_id'],version['manuscript_id'],language_review['source_export_id'],True)
                    if sha256(content).hexdigest()!=language_review['source_sha256']:raise source_conflict()
                    presentation_metadata=confirmed_metadata(presentation,prior['presentation'])
                    if school_plan is not None:field_update=prior['school']['field_update']
                else:
                    images,image_items=presentation_images(service,task['project_id'],rendered)
                    source_map=[]
                    content=build_manuscript_docx(rendered,images,school_plan=render_plan,source_map=source_map,
                        excluded_chapter_ids=excluded_chapters(presentation))
                    english=next((v['snapshot_json'] for v in (presentation['base'],presentation['peer']) if v and v['snapshot_json']['output_language']=='en'),None)
                    peer_images,peer_items=presentation_images(service,task['project_id'],english) if binding['language_view']=='zh-CN-en' and config['figure_pairs'] else ({},[])
                    content,presentation_metadata=decorate_docx(content,rendered,english,config,binding['language_view'],'identified',peer_images=peer_images,source_map=source_map,excluded_chapter_ids=excluded_chapters(presentation))
                    if render_plan is not None:
                        from app.adapters.school_docx import complete_school_fields
                        content,field_update=complete_school_fields(content,render_plan)
                        if field_update.get('status')!=('updated' if render_plan['toc']['enabled'] else 'not_requested'):
                            raise StorageError('layout_field_update_failed','学校目录实际更新未完成。',422)
                    if binding['review_mode']=='blind':content,presentation_metadata['blind']=blind_docx(content,config['blind'])
                    inventory=language_inventory(content,rendered['output_language'],source_map)+actual_image_inventory(content,image_items+peer_items,rendered['output_language'])
                    presentation_metadata.update(binding=binding,checks=actual_checks(presentation,inventory),
                        quality=dict(presentation['preview']['quality'],language_review='pending_explicit_review'),language_inventory=language_observations(inventory))
                    if binding['review_mode']=='blind':presentation_metadata['blind_rules']=config['blind']
                    if render_plan is not None:presentation_metadata['school']=dict(plan=render_plan,report=render_plan['report'])
            elif school_plan is not None:
                provenance=snapshot.get('writing_provenance',{})
                if provenance.get('school_content_version')=='school-live-v1' and provenance.get('language_review_id'):
                    from app.domain.manuscript_writing.school_render_cache import read
                    content,receipt=read(service.assets.directory,task['user_id'],task['project_id'],provenance['school_final_render'],candidate=snapshot,images=images,plan=school_plan)
                    if sha256(content).hexdigest()!=provenance['school_docx_sha256']:raise source_conflict()
                    field_update=receipt['field_update']
                else:
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
            if snapshot.get('journal_display_context'):metadata['renderer_version']=RENDERER_VERSION+'+journal_display_v1'
            if school_plan is not None:metadata['school']=dict(plan=school_plan,report=school_plan['report'],field_update=field_update)
            if presentation_metadata is not None:
                metadata['presentation']=presentation_metadata
                metadata['renderer_version']+='+presentation_v1'
                metadata['filename']=f"{'Blind' if presentation['binding']['review_mode']=='blind' else 'Manuscript'}-{presentation['binding']['language_view']}-v{version['revision']}-{export_id[:8]}.docx"
            service.directory.mkdir(parents=True,exist_ok=True)
            staged=service.directory/(export_id+'-'+lease.lease_owner+'.part')
        with publication_transaction(execution,lease) as (db,progress):
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            fresh=service.verify_task(db,task,current=True,progress=progress);progress()
            if fresh['snapshot_json']!=snapshot: raise source_conflict()
            if task['task_type']=='manuscript_docx':
                target=service.directory/(task['input_snapshot']['export_id']+'.docx')
                if not restored:
                    candidates.capture(db,execution.assets.directory,task,lease,target,staged,content,metadata,progress=progress)
                candidates.publish(db,execution.assets.directory,task,lease,metadata,progress=progress)
                db.execute('UPDATE manuscript_exports SET metadata_json=%s WHERE id=%s AND task_id=%s',(Jsonb(metadata),task['input_snapshot']['export_id'],task['id']))
            checkpoint(db,task,'publish','done',state)
            execution.require_lease(db,lease);execution._finish(db,task,'succeeded',None)
            return TaskStore.public_task(task)
    except PublicationFailed as exc:return exc.task
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
        # Candidate ownership survives rollback; cleanup is never inferred from metadata.


def retry_in_transaction(store,db,task,expected_revision,*,assets=None):
    if task['task_type'] not in ('manuscript_draft','manuscript_docx') or task['status']!='failed' or task['revision']!=expected_revision:
        raise StorageError('task_revision_conflict','仅能恢复当前失败事实稿任务。',409)
    assets=assets or scoped_store(task['user_id'],store.config)
    ManuscriptService(assets).verify_task(db,task,current=True)
    if task['task_type']=='manuscript_docx': candidates.authorize(db,assets.directory,task)
    task.update(status='queued',revision=expected_revision+1,reason_code='retry_requested',error_code=None,retry_count=0,
        updated_at=max(now(),task['updated_at']),_retry_reason='manual_retry')
    store.update_task(db,task,expected_revision);store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)
