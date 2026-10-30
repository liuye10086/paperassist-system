"""Lease-fenced school note suggestions; only this worker can call a provider."""
import json
from copy import deepcopy
from threading import Event,Thread
from psycopg.types.json import Jsonb
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import append_checkpoint
from app.domain.report_collections.service import scoped_store
from app.domain.model_usage.contracts import CallRequest,ModelPolicy
from app.domain.model_usage.gateway import ModelGateway,ModelGatewayError
from app.domain.model_usage.service import ModelUsageService
from app.domain.tasks.errors import classify_read_error
from .suggestion_service import SuggestionService,input_version,artifact_sha
from .suggestion_validation import validate_output

def checkpoint(db,task):
    row=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
    if not row or row['state_json'].get('input_digest')!=task['input_digest']:raise source_conflict()
    return row

def wait(repository,lease,reason,code):
    from app.domain.tasks.waits import persist_wait
    with repository.connection(write=True) as db:
        task=repository.require_lease(db,lease);previous=checkpoint(db,task);revision=task['revision']
        task.update(status='waiting_confirmation',revision=revision+1,reason_code=reason,error_code=code,updated_at=max(repository.now(db),task['updated_at']))
        append_checkpoint(db,task,'await_confirmation','await_confirmation',previous['state_json'],previous)
        TaskStore.finish_attempt(db,task);TaskStore.update_task(db,task,revision);TaskStore.append_event(db,task,'waiting');persist_wait(db,task)
        return TaskStore.public_task(task)

def parse_response(response):
    if not isinstance(response,dict) or response.get('status')!='completed':raise ValueError('Incomplete output')
    messages=[o for o in response['output'] if o['type']=='message']
    if len(messages)!=1 or len(messages[0]['content'])!=1:raise ValueError('One JSON output required')
    item=messages[0]['content'][0]
    if item['type']!='output_text' or len(item['text'].encode())>100000:raise ValueError('Invalid output text')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate output key')
            result[key]=value
        return result
    return json.loads(item['text'],object_pairs_hook=pairs)

def run_school_suggestion_task(task_id,task_revision,*,config=None,directory=None,provider=None):
    repository=TaskExecutionStore(config=config,directory=directory)
    if provider is not None and (repository.config.environment!='test' or getattr(provider,'source_kind',None)!='synthetic_fixture'):
        raise StorageError('task_input_invalid','仅隔离测试允许注入合成建议供应商。',422)
    lease=repository.claim(task_id,task_revision,task_type='school_rule_suggestion')
    if lease is None:return None
    stop=Event()
    def heartbeat():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):return
            except StorageError:return
    thread=Thread(target=heartbeat,daemon=True);thread.start()
    try:return execute(repository,lease,provider)
    except LeaseLost:return None
    except StorageError as exc:
        if exc.code in ('model_budget_missing','model_budget_exceeded'):return wait(repository,lease,'budget_exceeded',exc.code)
        if exc.status>=500:return None
        return repository.fail(lease,exc.code)
    except (ValueError,KeyError,TypeError):return repository.fail(lease,'model_response_invalid')
    finally:stop.set();thread.join(timeout=1)

def execute(repository,lease,provider):
    with repository.connection() as db:
        task=repository.require_lease(db,lease);repository.require_owner(db,task);input_version(task);checkpoint(db,task)
        service=SuggestionService(scoped_store(task['user_id'],repository.config,repository.assets.directory))
        row=service.suggestion_row(db,task['project_id'],task['input_snapshot']['suggestion_id']);snap=row['input_snapshot'];frozen=snap['bundle']
        call=db.execute('SELECT * FROM model_calls WHERE task_id=%s ORDER BY created_at DESC,id DESC LIMIT 1',(task['id'],)).fetchone()
        if not call:service.require_current(db,service.row(db,task['project_id'],row['template_version_id']))
    if call and not call.get('provider_response_id') and call['status'] in ('submitting','submission_unknown'):
        return wait(repository,lease,'submission_unknown','model_submission_unknown')
    owned=False
    if provider is None:
        from .suggestion_policy import real_calls_enabled
        if not frozen['real_calls_enabled'] or not real_calls_enabled():return wait(repository,lease,'confirmation_required','model_policy_not_configured')
        from app.domain.explanation_policy import explanation_api_key
        from app.adapters.models.openai_responses import OpenAIResponsesProvider
        try:provider=OpenAIResponsesProvider(api_key=explanation_api_key());owned=True
        except StorageError:return wait(repository,lease,'confirmation_required','model_policy_not_configured')
    gateway=ModelGateway(ModelUsageService(task['user_id'],repository.config),provider)
    try:
        if call and call.get('provider_response_id'):output=gateway.refresh(call['id'])
        else:
            request=CallRequest(task_id=task['id'],expected_task_revision=task['revision'],call_key='school-rule-suggestion-v1',input_digest=frozen['input_digest'],
                policy=ModelPolicy.model_validate(frozen['policy']),input_token_allowance=frozen['input_token_allowance'])
            output=gateway.submit(request,instructions=frozen['instructions'],payload=frozen['material'],execution_lease=lease)
    except ModelGatewayError as exc:
        with repository.connection() as db:call=db.execute('SELECT * FROM model_calls WHERE task_id=%s ORDER BY created_at DESC,id DESC LIMIT 1',(task['id'],)).fetchone()
        if call and not call.get('provider_response_id') and call['status'] in ('submitting','submission_unknown'):return wait(repository,lease,'submission_unknown','model_submission_unknown')
        if exc.code=='model_receipt_persistence_failed':return None
        return repository.retry_failure(lease,classify_read_error(exc.code,exc.status_code))
    finally:
        if owned:provider.close()
    call,response=output['call'],output.get('response')
    if not call.get('provider_response_id'):return wait(repository,lease,'submission_unknown','model_submission_unknown')
    if isinstance(response,dict) and response.get('status') in ('queued','in_progress'):return repository.defer(lease)
    invalid=False
    try:
        raw=parse_response(response);result=validate_output(raw,frozen['material'])
        for candidate in result['candidates']:
            candidate['source']=deepcopy(next(n['source'] for n in frozen['notes'] if n['alias']==candidate['note_alias']))
    except (ValueError,KeyError,TypeError):
        raw=dict(invalid_response=response);result=dict(candidates=[],validation_status='invalid');invalid=True
    with repository.connection(write=True) as db:
        task=repository.require_lease(db,lease);repository.require_owner(db,task)
        fresh=service.suggestion_row(db,task['project_id'],row['id'])
        if fresh['result_json'] is not None:raise source_conflict()
        db.execute('''UPDATE school_rule_suggestions SET raw_output_json=%s,result_json=%s,artifact_sha256=%s,model_call_id=%s WHERE id=%s AND result_json IS NULL''',
            (Jsonb(raw),Jsonb(result),artifact_sha(row,result,raw,call['id']),call['id'],row['id']))
        if invalid:
            repository._finish(db,task,'failed','model_response_invalid')
            return TaskStore.public_task(task)
        previous=checkpoint(db,task);append_checkpoint(db,task,'done','done',previous['state_json'],previous);repository._finish(db,task,'succeeded',None)
        return TaskStore.public_task(task)

def retry_in_transaction(store,db,task,expected_revision,*,assets=None):
    from .service import now
    input_version(task)
    if task['revision']!=expected_revision or task['status'] not in ('failed','waiting_confirmation'):raise source_conflict()
    service=SuggestionService(assets or scoped_store(task['user_id'],store.config));row=service.suggestion_row(db,task['project_id'],task['input_snapshot']['suggestion_id'])
    if row['result_json'] is not None:raise source_conflict()
    task.update(status='queued',revision=expected_revision+1,reason_code='retry_requested',error_code=None,updated_at=max(now(),task['updated_at']),_retry_reason='manual_retry')
    store.update_task(db,task,expected_revision);store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)
