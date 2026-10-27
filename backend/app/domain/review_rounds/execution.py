"""Lease-fenced local planning only; waits never fake scientific completion."""
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.report_collections.service import scoped_store
from app.domain.journals.service import now
from .service import ReviewRoundService,input_version
from .planning import propose,update_status,invalid,detect_conflicts

def run_review_round_task(task_id,task_revision,*,config=None,directory=None):
    execution=TaskExecutionStore(config=config,directory=directory)
    lease=execution.claim(task_id,task_revision,task_type='review_round_plan')
    if lease is None:return None
    try:
        with execution.connection(write=True) as db:
            task=execution.require_lease(db,lease);execution.require_owner(db,task)
            service=ReviewRoundService(scoped_store(task['user_id'],execution.config,execution.assets.directory))
            row=service.round_row(db,task['project_id'],input_version(task)['round_id'],True);base=service.fixed(db,row)
            state,events=service.state(db,row)
            from app.domain.admin_configuration.rule_consumption import rules,round_version
            version=round_version(db,row['id']);policy=rules(version,'review') if version else None
            if not events:
                state['items']=[propose(source,n,segment,rules=policy) for source in row['snapshot_json']['sources'] for n,segment in enumerate(source['segments'],1)]
                from .grounded import grounded_plans
                for item,grounded in zip(state['items'],grounded_plans(base['snapshot_json'],state['items'],state['materials'],rules=policy)):
                    item['plan']=grounded['plan'];item['locations']=[{k:loc[k] for k in ('kind','id')} for loc in grounded['locations']]
                    item['evidence_ids']=[e['id'] for e in grounded['evidence']]
                detect_conflicts(state['items']);update_status(state['items']);service.append(db,row,1,'initial','worker-initial',{},state)
            needs=any(i['status']=='waiting_material' for i in state['items']);confirmation=any(i['status']=='waiting_confirmation' for i in state['items'])
            from app.domain.manuscripts.execution import checkpoint
            checkpoint(db,task,'check','await_input' if needs else 'await_confirmation' if confirmation else 'done',dict(round_id=row['id'],plan_revision=(events[-1]['revision'] if events else 1),scientific_revision_completed=False))
            if needs or confirmation:
                previous=task['revision'];task.update(status='waiting_input' if needs else 'waiting_confirmation',phase='verify',revision=previous+1,updated_at=max(execution.now(db),task['updated_at']),reason_code='input_required' if needs else 'confirmation_required',error_code=None)
                TaskStore.finish_attempt(db,task);TaskStore.update_task(db,task,previous);TaskStore.append_event(db,task,'waiting')
                from app.domain.tasks.waits import persist_wait
                persist_wait(db,task)
            else:execution._finish(db,task,'succeeded',None)
            return TaskStore.public_task(task)
    except LeaseLost:return None
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("review round planning failed task_id=%s",task_id)
        try:return execution.fail(lease,exc.code if isinstance(exc,StorageError) else 'task_worker_interrupted')
        except LeaseLost:return None

def retry_in_transaction(store,db,task,expected_revision):
    if task['task_type']!='review_round_plan' or task['revision']!=expected_revision or task['status'] not in ('failed','waiting_input','waiting_confirmation'):raise invalid('返修计划任务不能恢复。',409)
    service=ReviewRoundService(scoped_store(task['user_id'],store.config));row=service.round_row(db,task['project_id'],input_version(task)['round_id'],True);base=service.fixed(db,row)
    if task['status']=='failed' and task.get('error_code') not in ('storage_unavailable','task_worker_interrupted'):raise invalid('此错误不支持安全重试。',409)
    task.update(status='queued',revision=expected_revision+1,reason_code='retry_requested',error_code=None,updated_at=max(now(),task['updated_at']),_retry_reason='manual_retry')
    store.update_task(db,task,expected_revision)
    from app.domain.tasks.waits import resolve_open_wait
    resolve_open_wait(db,task)
    store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)
