"""Public lease fence: only one read-only formatting report may publish."""
from psycopg.types.json import Jsonb
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.report_collections.service import scoped_store
from app.domain.literature.service import digest
from .format_service import FormatService,input_version

def run_format_task(task_id,task_revision,*,config=None,directory=None,checker=None):
    execution=TaskExecutionStore(config=config,directory=directory)
    lease=execution.claim(task_id,task_revision,task_type='journal_format_check')
    if lease is None:return None
    try:
        with execution.connection() as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            service=FormatService(scoped_store(task['user_id'],execution.config,execution.assets.directory))
            row=service.check_row(db,task['project_id'],input_version(task)['check_id'])
            result=checker(row['snapshot_json']) if checker else service.compute(db,row)
        with execution.connection(write=True) as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            row=service.check_row(db,task['project_id'],row['id'])
            if row['result_json'] is not None:raise source_conflict()
            changed=db.execute('UPDATE journal_format_checks SET result_json=%s,result_sha256=%s WHERE id=%s AND result_json IS NULL',(Jsonb(result),digest(result),row['id']))
            if changed.rowcount!=1:raise source_conflict()
            execution._finish(db,task,'succeeded',None);return TaskStore.public_task(task)
    except LeaseLost:return None
    except Exception as exc:
        try:return execution.fail(lease,exc.code if isinstance(exc,StorageError) else 'task_worker_interrupted')
        except LeaseLost:return None
