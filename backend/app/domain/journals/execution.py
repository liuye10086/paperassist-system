"""Lease-fenced deterministic journal execution through the public task engine."""
from psycopg.types.json import Jsonb
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.task_store import TaskStore
from app.core.exceptions import StorageError
from app.domain.report_collections.service import scoped_store
from app.domain.literature.service import digest
from .service import JournalService,input_version
from .recommendation import recommend


def run_journal_task(task_id,task_revision,*,config=None,directory=None,recommender=None):
    execution=TaskExecutionStore(config=config,directory=directory)
    lease=execution.claim(task_id,task_revision,task_type='journal_recommendation')
    if lease is None:return None
    try:
        with execution.connection() as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            service=JournalService(scoped_store(task['user_id'],execution.config,execution.assets.directory))
            row=service.row(db,task['project_id'],input_version(task)['recommendation_id']);service.view(db,row)
            snapshot=row['snapshot_json']
            from app.domain.admin_configuration.rule_consumption import rules,task_version
            policy=rules(task_version(db,task),'journals')
        result=recommender(snapshot) if recommender else recommend(snapshot,rules=policy)
        with execution.connection(write=True) as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            row=service.row(db,task['project_id'],row['id']);service.view(db,row)
            db.execute('UPDATE journal_recommendations SET result_json=%s,result_sha256=%s WHERE id=%s AND result_json IS NULL',(Jsonb(result),digest(result),row['id']))
            execution._finish(db,task,'succeeded',None);return TaskStore.public_task(task)
    except LeaseLost:return None
    except Exception as exc:
        try:return execution.fail(lease,exc.code if isinstance(exc,StorageError) else 'task_worker_interrupted')
        except LeaseLost:return None
