"""Offline B04 outputs use the existing fenced task/ledger transaction."""
import hashlib
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import re
from threading import Event,Thread,BoundedSemaphore
from uuid import UUID,uuid5

from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.task_store import DatasetTaskAssets
from app.adapters.bio_insights_store import invalid,identity
from app.adapters.bio_insights_store import BioInsightsObjects
from app.domain.bioinformatics.contracts import canonical
from app.domain.bioinformatics.service import append_checkpoint
from app.domain.bioinformatics.analysis_execution import _staging,_receipt
from app.domain.storage_governance.bio_manifest import admit_bio_manifest,settle_bio_manifest
from app.domain.storage_governance.deterministic import explicit_retry,authorize_rebuild,STORAGE_RETRY_CODES
from app.core.exceptions import StorageError
from app.domain.tasks.publication_transaction import PublicationFailed
from .task_contracts import input_version,INSIGHT_TASKS

_SERIAL_INSIGHTS_WORKER=BoundedSemaphore(1)
logger=logging.getLogger(__name__)

# Only definite source-domain refusals may commit the read-only validation
# phase. Database/storage availability and unknown exceptions still roll back.
SOURCE_REJECTIONS=frozenset(('research_source_conflict','research_source_not_found',
    'research_source_incomplete','research_source_unsupported','research_locator_invalid',
    'bio_insight_limit_exceeded','research_fact_unresolved','research_figure_limit_exceeded',
    'research_export_limit_exceeded','bio_insights_output_invalid','bio_insight_revision_conflict',
    'research_writing_unavailable','bio_input_integrity_changed','bio_source_conflict',
    'bio_version_not_found','bio_processed_not_found','bio_figure_not_found','bio_member_not_found',
    'bio_output_invalid','bio_result_not_ready','source_conflict','task_source_conflict',
    'report_changed','report_missing','report_source_changed','report_source_conflict',
    'pdf_source_not_found','pdf_source_not_ready','file_missing','external_evidence_not_found',
    'bio_insight_source_conflict','bio_insight_not_found','bio_insight_design_blocked','bio_insight_not_ready',
    'bio_insights_input_invalid','bio_insights_environment_unavailable','bio_insight_parse_required'))


class _SourceRejected(Exception):
    def __init__(self,code):self.code=code


def service_for(task,repository):
    from .service import BioInsightsService
    from .resources import BioResourceService
    service=BioResourceService if task['task_type']=='bio_resource_import' else BioInsightsService
    return service(DatasetTaskAssets(task['user_id'],repository.config,repository.assets.directory))


def checkpoint_for(db,task):
    row=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
    if not row or row['state_json'].get('input_version')!=input_version(task):raise invalid()
    return dict(row)


def result_identifier(task):
    snapshot=task['input_snapshot']
    return snapshot['resource_version_id'] if task['task_type']=='bio_resource_import' else identity(task['project_id'],'result',snapshot['run_id'])


class BioInsightsExecution:
    def __init__(self,repository,staging_root):self.repository=repository;self.staging_root=Path(staging_root).resolve()

    @contextmanager
    def source_transaction(self,lease):
        failed=None
        with self.repository.connection(write=True) as db:
            try:
                yield db
            except _SourceRejected as exc:
                # checked() is first in each writer phase. Its source readers
                # only read business state; their sole writes renew this lease.
                # Keep those renewals and the exact rejection in one commit.
                task=self.repository.require_lease(db,lease)
                self.repository._finish(db,task,'failed',exc.code)
                from app.adapters.task_store import TaskStore
                failed=TaskStore.public_task(task)
        if failed is not None:raise PublicationFailed(failed)

    def checked(self,db,lease,checkpoint=None):
        task=self.repository.require_lease(db,lease);self.repository.require_owner(db,task)
        from app.adapters.task_execution_store import LEASE_SECONDS
        def progress():
            updated=db.execute("""UPDATE task_attempts a SET heartbeat_at=clock_timestamp(),lease_expires_at=clock_timestamp()+(%s*interval '1 second') FROM tasks t
                WHERE t.id=%s AND t.id=a.task_id AND t.current_attempt=%s AND a.attempt_no=t.current_attempt
                AND t.task_type IN ('bio_resource_import','bio_comparison','bio_result_import','bio_enrichment','bio_candidate','bio_insight_figure','bio_feature_extract','bio_integration') AND t.status='running' AND a.status='running'
                AND a.lease_owner=%s AND a.lease_expires_at>clock_timestamp()
                RETURNING a.heartbeat_at,a.lease_expires_at""",(LEASE_SECONDS,lease.task_id,lease.attempt_no,lease.lease_owner))
            if updated.rowcount!=1:raise LeaseLost()
            progress.renewed=dict(updated.fetchone())
        progress()
        cp=checkpoint_for(db,task)
        if checkpoint is not None and checkpoint['id']!=cp['id']:raise invalid()
        service=service_for(task,self.repository)
        try:payload=service.require_sources(db,task,progress=progress)
        except StorageError as exc:
            if exc.code not in SOURCE_REJECTIONS or not 400<=exc.status<500:raise
            raise _SourceRejected(exc.code) from exc
        progress()
        return task,cp,service,payload,progress

    def prepare(self,lease,checkpoint,result,output):
        with self.source_transaction(lease) as db:
            task,cp,_,payload,progress=self.checked(db,lease,checkpoint)
            if cp['next_node']!='check':raise invalid()
        from app.adapters.bio_insights_process import validate_result
        validate_result(result,output,payload)
        identifier=result_identifier(task);objects=BioInsightsObjects(self.repository.assets.directory);members=[];leaves=[];keys=set();total=0
        directory=Path(output).resolve()
        for item in result['outputs']:
            path=Path(item['path']);size=item['size_bytes'];key=item['key']
            if (not re.fullmatch('[A-Za-z0-9_-]{1,100}',key) or key in keys or not path.is_absolute() or path.is_symlink()
                    or path.resolve().parent!=directory or not path.is_file() or type(size) is not int or not 0<size<=268435456
                    or path.stat().st_size!=size or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']):raise invalid('bio_insights_output_invalid',422)
            total+=size
            if total>536870912 or len(members)>=256:raise invalid('bio_insight_limit_exceeded',422)
            record=dict(object_key=f'{objects.prefix}/{identifier}/{item["sha256"]}.bin',sha256=item['sha256'],size_bytes=size);objects.path(record['object_key'])
            properties=item.get('properties',{})
            if not isinstance(properties,dict) or len(canonical(properties))>1024**2:raise invalid('bio_insights_output_invalid',422)
            members.append(dict(id=str(uuid5(UUID(identifier),'member:'+key)),**{k:item[k] for k in ('key','role','format')},**record,properties=properties))
            leaves.append(dict(path=str(path),record=record));keys.add(key)
        if not members or {p.resolve() for p in directory.iterdir()}!={Path(l['path']).resolve() for l in leaves}:raise invalid('bio_insights_output_invalid',422)
        initial=[]
        if task['task_type']=='bio_resource_import':
            with self.source_transaction(lease) as db:
                task,cp,service,_,progress=self.checked(db,lease,checkpoint)
                initial=service.initial_resource_members(db,task)
        manifest={**result['manifest'],'execution_resources':result.get('resources',{}),
                  'members':initial+[{k:v for k,v in m.items() if k!='object_key'} for m in members]}
        if initial:
            manifest['input_snapshot_sha256']=next(m['sha256'] for m in initial if m['key']=='execution_snapshot')
        prepared=dict(input_sha256=task['input_digest'],members=members,manifest=manifest,
                      summary=result['summary'],methods=result['methods'])
        ref=objects.describe(identifier,canonical(manifest),json=True);prepared['manifest_ref']=ref
        unique={l['record']['object_key']:l for l in leaves};prefix=task['task_type']+':'+identifier+':'
        entries=[(task['task_type'],prefix+'leaf:'+l['record']['sha256'],l['record']) for l in unique.values()]
        entries.append((task['task_type'],prefix+'manifest',ref))
        with self.source_transaction(lease) as db:
            task,cp,_,_,progress=self.checked(db,lease,checkpoint)
            db.execute('SAVEPOINT research_admission')
            try:
                rows=admit_bio_manifest(db,self.repository.assets.directory,task,entries,progress=progress)
            except StorageError as exc:
                if exc.code not in ('storage_quota_exceeded','storage_disk_insufficient'):raise
                # Admission writes provisional reservations before checking the
                # aggregate limit. Undo those rows, retaining the last still-live
                # renewal obtained while this transaction held the writer lock.
                # Otherwise rollback erases renewal and recovery misclassifies a
                # deterministic quota denial as a crashed worker.
                renewed=progress.renewed
                db.execute('ROLLBACK TO SAVEPOINT research_admission')
                db.execute('RELEASE SAVEPOINT research_admission')
                restored=db.execute("""UPDATE task_attempts a SET heartbeat_at=%s,lease_expires_at=%s FROM tasks t
                    WHERE a.task_id=%s AND a.attempt_no=%s AND a.lease_owner=%s AND a.status='running'
                    AND t.id=a.task_id AND t.current_attempt=a.attempt_no AND t.status='running'
                    AND %s>clock_timestamp()""",(renewed['heartbeat_at'],renewed['lease_expires_at'],
                    lease.task_id,lease.attempt_no,lease.lease_owner,renewed['lease_expires_at']))
                if restored.rowcount!=1:raise LeaseLost()
                task=self.repository.require_lease(db,lease)
                self.repository._finish(db,task,'failed',exc.code)
                from app.adapters.task_store import TaskStore
                return TaskStore.public_task(task)
            db.execute('RELEASE SAVEPOINT research_admission')
            state={**cp['state_json'],'prepared':prepared,'prepared_leaves':list(unique.values()),
                'prepared_reservations':[{k:r[k] for k in ('id','namespace','project_id','owner_id','task_id','kind','operation_key','object_key','size_bytes','sha256')} for r in rows]}
            cp=append_checkpoint(db,task,'publish','publish',state,cp);progress()
        return self.publish(lease,cp)

    def staging_path(self,task,path):
        candidate=Path(path)
        if not candidate.is_absolute() or not candidate.resolve().is_relative_to(self.staging_root/task['id']):raise invalid('bio_insights_output_invalid',422)
        for part in [candidate,*candidate.parents]:
            if part.is_symlink() or getattr(part,'is_junction',lambda:False)():raise invalid('bio_insights_output_invalid',422)
        return candidate

    def publish(self,lease,checkpoint):
        with self.source_transaction(lease) as db:
            task,cp,_,_,progress=self.checked(db,lease,checkpoint)
            if cp['next_node']!='publish':raise invalid()
            state=cp['state_json'];prepared=state['prepared']
            if prepared['input_sha256']!=task['input_digest']:raise invalid()
            if explicit_retry(db,task):
                identifier=result_identifier(task);kind=task['task_type']
                authorize_rebuild(db,self.repository.assets.directory,task,allowed={kind:('bio-insights',identifier,re.escape(kind+':'+identifier+':')+r'(?:leaf:[0-9a-f]{64}|manifest)')},progress=progress)
        objects=BioInsightsObjects(self.repository.assets.directory)
        for leaf in state['prepared_leaves']:
            if objects.path(leaf['record']['object_key']).exists():objects.read(leaf['record'])
            else:objects.write(leaf['record'],self.staging_path(task,leaf['path']).read_bytes())
        objects.write(prepared['manifest_ref'],canonical(prepared['manifest']))
        with self.source_transaction(lease) as db:
            task,cp,service,_,progress=self.checked(db,lease,checkpoint)
            settle_bio_manifest(db,self.repository.assets.directory,task,state['prepared_reservations'],progress=progress)
            progress();return service.publish(db,task,cp,max(self.repository.now(db),task['updated_at']),prepared,progress=progress)


def run_bio_insight_task(task_id,task_revision,*,task_type,config=None,directory=None,engine=None,staging_directory=None):
    # A process runs one resource-bounded research slice at a time. Production
    # worker deployment additionally has concurrency=1 and a 4 GiB cgroup cap.
    with _SERIAL_INSIGHTS_WORKER:
        return _run_bio_insight_task(task_id,task_revision,task_type=task_type,config=config,directory=directory,engine=engine,staging_directory=staging_directory)


def _run_bio_insight_task(task_id,task_revision,*,task_type,config=None,directory=None,engine=None,staging_directory=None):
    if task_type not in INSIGHT_TASKS:raise ValueError('Unknown research task')
    repository=TaskExecutionStore(config=config,directory=directory);lease=repository.claim(task_id,task_revision,task_type=task_type)
    if lease is None:return None
    stop,lost=Event(),Event();attempt=None
    def heartbeat():
        while not stop.wait(1):
            try:
                if not repository.heartbeat(lease):lost.set();return
            except StorageError:pass
    thread=Thread(target=heartbeat,daemon=True);thread.start()
    try:
        from app.core.config import local_config
        staging=staging_directory or os.environ.get('PAPERASSIST_BIO_INSIGHTS_STAGING_DIR') or local_config().get('PAPERASSIST_BIO_INSIGHTS_STAGING_DIR')
        if not staging:raise invalid('bio_insights_environment_unavailable',409)
        try:attempt,output=_staging(repository,lease,staging)
        except StorageError as exc:
            if exc.code=='bio_environment_unavailable':raise invalid('bio_insights_environment_unavailable',409) from exc
            raise
        root=attempt.parent.parent;execution=BioInsightsExecution(repository,root)
        with repository.connection() as db:
            task=repository.require_lease(db,lease);repository.require_owner(db,task);cp=checkpoint_for(db,task)
            payload=service_for(task,repository).require_sources(db,task)
        if cp['next_node']=='publish':
            _receipt(attempt,lease,'resuming_frozen_publication')
            response=execution.publish(lease,cp)
            _receipt(attempt,lease,response['status'])
            return response
        if cp['next_node']!='check':raise invalid()
        from app.adapters.bio_insights_process import execute_bio_insights,input_records,file_sha
        import copy,shutil
        payload=copy.deepcopy(payload)
        for index,member in enumerate(input_records(payload)):
            original=Path(member['path']);target=attempt/('input_'+str(index)+'.bin')
            shutil.copyfile(original,target)
            if target.stat().st_size!=member['size_bytes'] or file_sha(target)!=member['sha256']:
                raise invalid('bio_insights_input_invalid',422)
            member['path']=str(target.resolve())
        render=engine or execute_bio_insights
        _receipt(attempt,lease,'running_bio_insights');result=render(payload,output) if engine else render(payload,output,cancel_event=lost)
        if lost.is_set():raise LeaseLost()
        response=execution.prepare(lease,cp,result,output)
        try:_receipt(attempt,lease,response['status'])
        except OSError:logger.warning('research receipt unavailable task_id=%s',task_id)
        return response
    except PublicationFailed as exc:
        try:_receipt(attempt,lease,'failed_'+exc.task['error_code'])
        except OSError:pass
        return exc.task
    except LeaseLost:
        try:_receipt(attempt,lease,'lease_lost')
        except OSError:pass
        return None
    except Exception as exc:
        from app.core.errors import PUBLIC_CODES
        code=exc.code if isinstance(exc,StorageError) and exc.code in PUBLIC_CODES else ('storage_unavailable' if isinstance(exc,OSError) else 'task_execution_failed')
        logger.warning('research task failed task_id=%s code=%s',task_id,code)
        try:_receipt(attempt,lease,'failed_'+code)
        except OSError:pass
        try:return repository.fail(lease,code)
        except LeaseLost:return None
    finally:stop.set();thread.join(timeout=1)


def source_current(db,task):
    try:
        from app.core.config import get_data_dir
        class Repository:config=db.config;assets=type('Assets',(),{'directory':get_data_dir()})()
        service_for(task,Repository()).require_sources(db,task);return True
    except Exception:return False


def recovery_actions(db,task):
    return ['retry'] if task['status']=='failed' and task.get('error_code') in STORAGE_RETRY_CODES|{'bio_insights_environment_unavailable','bio_insights_timeout','bio_insights_resource_exceeded','task_worker_interrupted'} and source_current(db,task) else []


def retry_in_transaction(store,db,task,expected_revision):
    from app.adapters.research_results_store import now
    from app.adapters.task_store import TaskStore
    if task['revision']!=expected_revision or 'retry' not in recovery_actions(db,task):raise invalid('bio_insight_revision_conflict')
    previous=task['revision'];task.update(status='queued',revision=previous+1,updated_at=now(),reason_code='retry_requested',error_code=None)
    TaskStore.update_task(db,task,previous);task['_retry_reason']='manual_retry';TaskStore.append_event(db,task,'requeued');TaskStore.enqueue(db,task)
    return TaskStore.public_task(task)
