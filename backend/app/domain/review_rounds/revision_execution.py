"""Public lease fenced adaptation; publication and result commit atomically."""
from psycopg.types.json import Jsonb
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.report_collections.service import scoped_store
from app.domain.literature.service import digest
from app.domain.manuscripts.service import ManuscriptService
from .revisions import RevisionService,input_version

def run_review_revision_task(task_id,task_revision,*,config=None,directory=None,before_publish=None):
    execution=TaskExecutionStore(config=config,directory=directory)
    lease=execution.claim(task_id,task_revision,task_type='review_revision')
    if lease is None:return None
    try:
        with execution.connection() as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            service=RevisionService(scoped_store(task['user_id'],execution.config,execution.assets.directory))
            row=service.revision_row(db,task['project_id'],input_version(task)['revision_id'])
            base,candidate,result=service.compute(db,row)
        from app.domain.manuscripts.execution import checkpoint
        with execution.connection(write=True) as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            checkpoint(db,task,'check','publish',dict(public_issues=result['public_issues'],public_check_version=3,candidate_sha256=digest(candidate),can_publish=not any(i['severity']=='error' for i in result['public_issues'])))
        if any(i['severity']=='error' for i in result['public_issues']):raise StorageError('manuscript_review_blocked','公共数值、来源、图表或引用检查存在硬错误。',409)
        if before_publish:before_publish()
        with execution.connection(write=True) as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            row=service.revision_row(db,task['project_id'],row['id'])
            if row['result_json'] is not None:raise source_conflict()
            result['output']=ManuscriptService(service.assets).publish_review_revision(db,base,candidate,row)
            changed=db.execute('UPDATE review_revision_runs SET result_json=%s,result_sha256=%s,output_version_id=%s WHERE id=%s AND result_json IS NULL',(Jsonb(result),digest(result),result['output']['version_id'],row['id']))
            if changed.rowcount!=1:raise source_conflict()
            execution.require_lease(db,lease)
            execution._finish(db,task,'succeeded',None);return TaskStore.public_task(task)
    except LeaseLost:return None
    except Exception as exc:
        try:return execution.fail(lease,exc.code if isinstance(exc,StorageError) else 'task_worker_interrupted')
        except LeaseLost:return None
