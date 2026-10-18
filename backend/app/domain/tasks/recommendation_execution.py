"""One no-tool model recommendation slice, with durable receipt recovery."""
import json
import logging
from threading import Event, Thread
from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
from app.adapters.task_store import TaskStore, DatasetTaskAssets, source_conflict
from app.core.exceptions import StorageError
from app.domain.analysis_recommendation.service import RecommendationService, last_call, validate_snapshot
from app.domain.analysis_recommendation.contracts import validate_draft, call_key as recommendation_call_key
from app.domain.analysis_recommendation.policy import instructions_for, validate_execution_policy
from app.domain.model_usage.contracts import CallRequest, ModelPolicy
from app.domain.model_usage.service import ModelUsageService
from app.domain.model_usage.gateway import ModelGateway, ModelGatewayError, input_digest
from app.domain.dataset_preparation.service import append_checkpoint, request_digest
from app.domain.tasks.errors import classify_read_error

logger=logging.getLogger(__name__)


def create_provider():
    from app.adapters.models.openai_responses import OpenAIResponsesProvider
    from app.domain.explanation_policy import explanation_api_key
    return OpenAIResponsesProvider(api_key=explanation_api_key())


def run_recommendation_task(task_id,task_revision,*,config=None,directory=None,provider_factory=None):
    repository=TaskExecutionStore(config=config,directory=directory)
    lease=repository.claim(task_id,task_revision,task_type='analysis_recommendation')
    if lease is None:return None
    stop=Event();providers=[]
    def heartbeat():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):return
            except Exception:return
    thread=Thread(target=heartbeat,daemon=True);thread.start()
    try:return execute(repository,lease,provider_factory or create_provider,providers)
    except LeaseLost:return None
    except StorageError as exc:
        if exc.code in ('model_budget_missing','model_budget_exceeded','recommendation_not_configured','explanation_not_configured'):
            return repository.wait_explanation(lease,'budget_exceeded',exc.code)
        if exc.status<500:return repository.fail(lease,exc.code)
        return None
    except Exception as exc:
        logger.warning('recommendation interrupted task_id=%s error_type=%s',task_id,type(exc).__name__)
        return None
    finally:
        stop.set();thread.join(timeout=1)
        for provider in providers:
            try:provider.close()
            except Exception:pass


def execute(repository,lease,provider_factory,providers):
    with repository.connection() as db:
        task=repository.require_lease(db,lease);repository.require_owner(db,task)
        call=last_call(db,task['id'])
    service=RecommendationService(DatasetTaskAssets(task['user_id'],repository.config,repository.assets.directory))
    if call and not call['provider_response_id'] and call['status'] in ('submitting','submission_unknown'):
        return repository.wait_explanation(lease,'submission_unknown','model_submission_unknown')
    snapshot=validate_snapshot(task) if call and call.get('provider_response_id') else service.require_material(task)
    instructions=instructions_for(snapshot['payload'])
    call_key=recommendation_call_key(snapshot['request'])
    if not call or not call['provider_response_id']:
        frozen=validate_execution_policy(snapshot['recommendation_policy'],snapshot['payload'])
    provider=provider_factory();providers.append(provider)
    gateway=ModelGateway(ModelUsageService(task['user_id'],repository.config),provider)
    try:
        if call and call['provider_response_id']: output=gateway.refresh(call['id'])
        else:
            request=CallRequest(task_id=task['id'],expected_task_revision=task['revision'],call_key=call_key,
                input_digest=input_digest(instructions=instructions,payload=snapshot['payload']),
                policy=ModelPolicy.model_validate(frozen['policy']),input_token_allowance=frozen['input_token_allowance'])
            output=gateway.submit(request,instructions=instructions,payload=snapshot['payload'],execution_lease=lease)
    except ModelGatewayError as exc:
        if exc.code=='model_receipt_persistence_failed':raise
        with repository.connection() as db: call=last_call(db,task['id'])
        if call and not call['provider_response_id'] and call['status'] in ('submitting','submission_unknown'):
            return repository.wait_explanation(lease,'submission_unknown','model_submission_unknown')
        return repository.retry_failure(lease,classify_read_error(exc.code,exc.status_code))
    response=output.get('response');call=output['call']
    if not call.get('provider_response_id'):
        return repository.wait_explanation(lease,'submission_unknown','model_submission_unknown')
    if isinstance(response,dict) and response.get('status') in ('queued','in_progress'):return repository.defer(lease)
    try:
        if not isinstance(response,dict) or response.get('status')!='completed':raise ValueError('Incomplete recommendation')
        outputs=response['output']
        if len(outputs)!=1 or outputs[0]['type']!='message' or len(outputs[0]['content'])!=1:raise ValueError('Unexpected tool/output')
        item=outputs[0]['content'][0]
        if item['type']!='output_text' or len(item['text'].encode())>30000:raise ValueError('Invalid output')
        def unique_pairs(items):
            value={}
            for key,item in items:
                if key in value: raise ValueError('Duplicate JSON key')
                value[key]=item
            return value
        parsed=json.loads(item['text'],object_pairs_hook=unique_pairs)
        draft=validate_draft(parsed,{**snapshot['request'],'research_summary':snapshot['payload']['research_summary']},require_explanation=snapshot.get('require_explanation',False))
    except (ValueError,TypeError,KeyError):return repository.fail(lease,'recommendation_invalid')
    with repository.connection(write=True) as db:
        task=repository.require_lease(db,lease);repository.require_owner(db,task);service.require_material(task)
        checkpoint=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
        if checkpoint['next_node']!='check':raise source_conflict()
        value={**draft,'task_id':task['id'],'model_call_id':call['id']}
        value['sha256']=request_digest(value)
        state={**checkpoint['state_json'],'recommendation':value}
        append_checkpoint(db,task,'done','done',state,checkpoint)
        repository._finish(db,task,'succeeded',None)
        return TaskStore.public_task(task)
