"""Cancellation is a terminal owner-scoped lease revocation, never a retry."""
from app.adapters.task_execution_store import TaskExecutionStore
from app.core.exceptions import StorageError
from app.domain.bio_insights.task_contracts import INSIGHT_TASKS

LOCAL_CANCEL_TASKS=frozenset({'bio_analysis','bio_figure','bio_annotation',*INSIGHT_TASKS})


def can_cancel(task):
    return task['task_type'] in LOCAL_CANCEL_TASKS and task['status'] in ('queued','running')


def cancel_task(store, task_id, expected_revision):
    store.require_mutable(task_id)
    with store.connection(write=True) as db:
        task=store.require_task(db,task_id)
        if task['task_type'] not in LOCAL_CANCEL_TASKS:
            raise StorageError('task_transition_invalid','此任务不支持本地取消。',409)
        # A replay of the winning revision (or a fresh read of cancelled) is a no-op.
        if task['status']=='cancelled' and expected_revision in (task['revision']-1,task['revision']):
            return store.public_task(task)
        if task['revision']!=expected_revision or not can_cancel(task):
            raise StorageError('task_transition_invalid','任务状态已更新，请刷新后重试。',409)
        repository=TaskExecutionStore(config=store.config)
        if task['status']=='running':
            repository._finish(db,task,'cancelled',None)
        else:
            # Queued/requeued tasks have no running attempt to finish.
            previous=task['revision']
            task.update(status='cancelled',revision=previous+1,updated_at=max(repository.now(db),task['updated_at']),reason_code=None,error_code=None)
            store.update_task(db,task,previous)
            store.append_event(db,task,'cancelled')
        return store.public_task(task)
