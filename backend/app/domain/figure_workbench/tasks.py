"""Durable task intents, immutable source guards and receipt-aware recovery."""
from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime,timezone
from uuid import uuid4
from pathlib import Path
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore,source_conflict
from app.adapters.storage import ProjectStore
from app.adapters.figure_workbench_store import FigureWorkbenchStore,read_bundle
from app.domain.external_processing import digest
from app.domain.figure_workbench.contracts import RENDERER
from app.core.exceptions import StorageError

PLOT_KEY='figure_workbench:v1'
EXPLANATION_KEY='figure_explanation:v1'
from app.domain.plot_tasks import OUTPUT_FAILURES as PLOT_OUTPUT_FAILURES
OUTPUT_FAILURES=PLOT_OUTPUT_FAILURES | frozenset({'explanation_invalid','explanation_invalid_json',
    'explanation_refused','explanation_output_limit','explanation_incomplete'})


def assets_for(repository,user_id):
    store=object.__new__(ProjectStore);store.owner_id=user_id;store.db_config=repository.config
    directory=repository.assets.directory if hasattr(repository,'assets') else None
    if directory is None:
        from app.core.config import get_data_dir
        directory=get_data_dir()
    store.directory=Path(directory);store.files_dir=store.directory/'files';store.figures_dir=store.directory/'figures'
    from app.adapters.file_objects import LocalFileObjects
    store.objects=LocalFileObjects(store.directory)
    return store


def policy_for(payload,explanation=False):
    if explanation:
        from app.domain.explanation_policy import get_execution_policy
        value=get_execution_policy(payload)
        value['policy']['prompt_version']=prompt_version(payload,explanation=True)
    else:
        from app.domain.plot_policy import get_execution_policy
        value=get_execution_policy();value['policy']['prompt_version']=prompt_version(payload)
    validate_policy(value,payload,explanation=explanation)
    return value


def prompt_version(payload,*,explanation=False):
    if explanation:
        from app.domain.figure_workbench.explanations import VERSION,V2_VERSION,V3_VERSION,V4_VERSION,LATEST_VERSION
        version=payload.get('figure_explanation_contract',1)
        if type(version) is not int or version not in (1,2,3,4,5):raise source_conflict()
        return {1:VERSION,2:V2_VERSION,3:V3_VERSION,4:V4_VERSION,5:LATEST_VERSION}[version]
    from app.domain.figure_workbench.presentation import LATEST_RENDERER,V2_RENDERER,V3_RENDERER
    if 'presentation' not in payload:return RENDERER
    version=payload['presentation'].get('schema_version')
    if type(version) is not int or version not in (1,2,3):raise source_conflict()
    return {1:V2_RENDERER,2:V3_RENDERER,3:LATEST_RENDERER}[version]


def validate_policy(value,payload,*,explanation=False,instructions=None):
    from app.domain.model_usage.contracts import ModelPolicy
    from app.domain.figure_workbench.prompts import instructions_for
    from app.domain.figure_workbench.explanations import instructions_for as explanation_instructions
    policy=ModelPolicy.model_validate(value['policy'])
    if policy.tools!=([] if explanation else ['code_interpreter']) or policy.prompt_version!=prompt_version(payload,explanation=explanation):raise source_conflict()
    from app.adapters.models.openai_responses import canonical_payload
    minimum=len((instructions if instructions is not None else explanation_instructions(payload) if explanation else instructions_for(payload)).encode())+len(canonical_payload(payload).encode())+4096
    if minimum>value['input_token_allowance']:raise StorageError('explanation_input_limit' if explanation else 'plot_input_limit','材料超过已配置输入预算范围。',422)
    return value


def require_task_sources(repository,db,task):
    repository.require_owner(db,task) if hasattr(repository,'require_owner') else TaskStore(task['user_id'],repository.config).require_project(db,task['project_id'])
    snapshot=task['input_snapshot'];assets=assets_for(repository,task['user_id']);workbench=FigureWorkbenchStore(assets)
    try:
        result=snapshot['result'];v=snapshot['figure_workbench']['version_id']
        row,current,computed,payload,expected=workbench.material(task['project_id'],result['file_id'],result['id'],v)
        projection=workbench._projection(db,row)
        if current!=result or snapshot['source']!=current['source'] or not projection or projection['result']!=computed or snapshot['figure_workbench']['projection_id']!=projection['id'] or snapshot['figure_workbench']['configuration_sha256']!=row['sha256']:raise ValueError()
        if task['task_type']=='figure_explanation':
            from app.domain.figure_workbench.explanations import build_payload,task_version
            bundle=read_bundle(assets,task['project_id'],snapshot['figure']['id'])
            if bundle['figure']!=snapshot['figure']:raise ValueError()
            payload=build_payload(bundle,version=task_version(snapshot))
        external=snapshot['external_processing']
        if external['confirmed'] is not True or external['confirmed_by']!=task['user_id'] or external['payload_sha256']!=digest(payload) or external['version_id']!=v:raise ValueError()
    except (KeyError,TypeError,ValueError):raise source_conflict() from None
    return snapshot


def submit(workbench,project_id,file_id,run_id,version_id,request,*,figure_id=None,db=None):
    """Use one transaction for the public queue and any caller-owned intent."""
    row,result,computed,payload,expected=workbench.material(project_id,file_id,run_id,version_id)
    explanation=figure_id is not None;bundle=None
    if explanation:
        from app.domain.figure_workbench.explanations import build_payload
        bundle=read_bundle(workbench.assets,project_id,figure_id);payload=build_payload(bundle)
        if bundle['figure']['figure_config_version_id']!=version_id:raise source_conflict()
    external=request.external_processing
    if set(external)!={'confirmed','payload_sha256'} or external.get('confirmed') is not True or external.get('payload_sha256')!=digest(payload):raise source_conflict()
    kind='figure_explanation' if explanation else 'figure_workbench'
    with (nullcontext(db) if db is not None else workbench.tasks.connection(write=True)) as db:
        row=workbench._version(db,project_id,file_id,run_id,version_id,lock=True);projection=workbench._projection(db,row)
        if not projection or projection['result']!=computed:raise source_conflict()
        input_hash=digest({'version_id':version_id,'figure_id':figure_id,'external':external})
        old=workbench.tasks.find_request(db,project_id,kind,request.idempotency_key)
        if old:
            if old['input_digest']!=input_hash:raise StorageError('task_idempotency_conflict','请求标识已用于不同输入。',409)
            return {'task':workbench.tasks.public_task(old),'explanation':None}
        from app.domain.admin_configuration.bindings import resolve,bind
        from app.domain.admin_configuration.model_consumption import execution
        configuration=resolve(db)
        frozen=execution(configuration,'explanation' if explanation else 'plot',payload,figure=True) if configuration else policy_for(payload,explanation=explanation)
        if frozen is None:raise StorageError('explanation_not_configured' if explanation else 'plot_not_configured','模型策略尚未配置。',503)
        active=db.execute('''SELECT * FROM tasks WHERE project_id=%s AND task_type=%s AND input_snapshot->'figure_workbench'->>'version_id'=%s ORDER BY created_at DESC,id DESC LIMIT 1''',(project_id,kind,version_id)).fetchone()
        same_contract=not explanation or not active or active['input_snapshot']['explanation_policy']['policy']['prompt_version']==frozen['policy']['prompt_version']
        if active and not same_contract and active['status'] not in ('succeeded','failed','cancelled'):
            raise StorageError('task_transition_invalid','旧版本解释任务尚未结束，请先核对原调用。',409)
        if active and same_contract and active['status']!='failed':return {'task':workbench.tasks.public_task(dict(active)),'explanation':None}
        if active and active['status']=='failed':
            call=_call(db,active)
            from app.domain.plot_tasks import _unknown_submission
            if _unknown_submission(call):raise StorageError('task_transition_invalid','已有提交结果未知，请先核对调用回执。',409)
            if call and call['status']!='released' and (active.get('error_code') not in OUTPUT_FAILURES or call['status'] not in ('completed','failed')):
                raise StorageError('task_transition_invalid','此任务仍可恢复，请恢复已有任务。',409)
        now=datetime.now(timezone.utc)
        snapshot={'schema_version':2,'result':result,'source':result['source'],'output_language':row['config_json']['language'],
            'figure_workbench':{'version_id':version_id,'projection_id':projection['id'],'configuration_sha256':row['sha256']},
            'external_processing':{**external,'version':7,'version_id':version_id,'confirmed_by':workbench.tasks.user_id,'confirmed_at':now.isoformat()},
            'explanation_policy' if explanation else 'boxplot_policy':frozen}
        if bundle:snapshot['figure']=bundle['figure']
        task={'id':str(uuid4()),'project_id':project_id,'user_id':workbench.tasks.user_id,'task_type':kind,'idempotency_key':request.idempotency_key,'input_digest':input_hash,'input_snapshot':snapshot,'workflow_version':kind+'_v1','status':'queued','phase':'interpret' if explanation else 'compute','revision':1,'current_attempt':0,'reason_code':None,'created_at':now,'updated_at':now}
        workbench.tasks.insert_task(db,task)
        bind(db,kind='task',object_id=task['id'],version=configuration)
        db.execute('''INSERT INTO model_budgets(id,user_id,scope_type,scope_key,project_id,task_id,limit_micro_usd,revision,created_at,updated_at) VALUES (%s,%s,'task',%s,%s,%s,%s,1,%s,%s)''',(str(uuid4()),task['user_id'],task['id'],project_id,task['id'],frozen['task_limit_micro_usd'],now,now))
        workbench.tasks.append_event(db,task,'created');workbench.tasks.enqueue(db,task)
        return {'task':workbench.tasks.public_task(task),'explanation':None}


def _call(db,task):
    return db.execute('SELECT * FROM model_calls WHERE task_id=%s ORDER BY created_at DESC,id DESC LIMIT 1',(task['id'],)).fetchone()


def allowed_recovery_actions(db,task):
    if task['task_type']=='figure_projection':return []
    if task['status'] not in ('failed','waiting_confirmation'):return []
    if task['status']=='waiting_confirmation' and task['reason_code']!='budget_exceeded':return []
    from app.domain.plot_tasks import _can_resume,_unknown_submission
    call=_call(db,task)
    if _unknown_submission(call):return []
    if task.get('error_code') in OUTPUT_FAILURES:
        # A v5 validator rejection can be rechecked against the same completed
        # receipt after a local guard repair. No other output failure or version
        # is recoverable here, and an unknown/incomplete submission stays blocked.
        if (task['task_type']=='figure_explanation' and task['status']=='failed'
            and task.get('error_code')=='explanation_invalid' and call
            and call['status']=='completed' and call.get('provider_status')=='completed'
            and call.get('provider_response_id')):
            from app.domain.figure_workbench.explanations import task_version
            try:version=task_version(task['input_snapshot'])
            except (KeyError,TypeError,StorageError):return []
            if version=='figure_explanation_v5':return ['retry']
        return []
    return ['resume' if task['status']=='waiting_confirmation' else 'retry'] if task['status']=='waiting_confirmation' or _can_resume(task,call) else []


def retry_in_transaction(store,db,task,expected_revision):
    if task['revision']!=expected_revision or not allowed_recovery_actions(db,task):raise StorageError('task_transition_invalid','此任务不能安全恢复。',409)
    from app.adapters.task_execution_store import TaskExecutionStore
    require_task_sources(TaskExecutionStore(config=store.config),db,task)
    if task['task_type']=='figure_workbench':
        from app.domain.storage_governance.candidates import authorize_task_recovery
        authorize_task_recovery(db,assets_for(store,task['user_id']).directory,task)
    waiting=task['status']=='waiting_confirmation';task.update(status='queued',revision=expected_revision+1,error_code=None,reason_code='confirmation_received' if waiting else 'retry_requested',retry_count=0,_retry_reason='manual_retry',updated_at=datetime.now(timezone.utc))
    store.update_task(db,task,expected_revision);store.append_event(db,task,'requeued');store.enqueue(db,task)
    from app.domain.tasks.waits import resolve_open_wait
    resolve_open_wait(db,task)
    return store.public_task(task)

def task_source(store,db,task):
    """Read-only workspace guard also supports an unapproved projection task."""
    store.require_project(db,task['project_id']);assets=assets_for(store,task['user_id']);workbench=FigureWorkbenchStore(assets)
    snapshot=task['input_snapshot'];result=snapshot['result']
    if task['task_type']=='figure_projection':
        from app.domain.figure_workbench.sources import load_source
        from app.adapters.figure_workbench_store import projection_request_digest
        current,_=load_source(assets,task['project_id'],result['file_id'],result['id'])
        row=workbench._version(db,task['project_id'],result['file_id'],result['id'],snapshot['figure_workbench']['version_id'])
        if current!=result or snapshot['source']!=result['source'] or snapshot['schema_version']!=2:raise source_conflict()
        if task['workflow_version']=='figure_projection_v2':
            pending=workbench._pending(db,row)
            if not pending or pending[0]['id']!=task['id'] or task['input_digest']!=projection_request_digest(row):raise source_conflict()
        return {'file_id':result['file_id'],'filename':result['filename'],'analysis_run_id':result['id'],'is_current':True,'dataset_source':result['source']}
    row,current,computed,_,_=workbench.material(task['project_id'],result['file_id'],result['id'],snapshot['figure_workbench']['version_id'])
    if current!=result or snapshot['source']!=result['source'] or snapshot['schema_version']!=2:raise source_conflict()
    if task['task_type']!='figure_projection':
        from app.adapters.task_execution_store import TaskExecutionStore
        require_task_sources(TaskExecutionStore(config=store.config),db,task)
    return {'file_id':result['file_id'],'filename':result['filename'],'analysis_run_id':result['id'],'is_current':True,'dataset_source':result['source']}


def task_artifacts(store,db,task):
    output={'figure':None,'explanation':None,'report':None}
    if task['task_type']=='figure_projection':return output
    figure_id=task.get('result_figure_id') or task['input_snapshot'].get('figure',{}).get('id')
    if not figure_id:return output
    bundle=read_bundle(assets_for(store,task['user_id']),task['project_id'],figure_id,task.get('result_explanation_id'))
    r=bundle['result'];f=bundle['figure']
    prefix=f"/api/v1/projects/{task['project_id']}/files/{r['file_id']}/analysis-runs/{r['id']}/figure-workbench/figures/{figure_id}"
    output['figure']={'title':f['title'],'caption':f['caption'],'download_url':prefix+'/package'}
    if bundle['explanation']:output['explanation']={k:bundle['explanation'][k] for k in ('sections','limitations')}
    return output
