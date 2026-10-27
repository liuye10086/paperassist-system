"""Lease-fenced hosted drawing and explanation consumers with original receipt recovery."""
from datetime import datetime,timezone
from app.domain.statistics_execution.verification import local_numeric_node
from hashlib import sha256
from uuid import uuid5,NAMESPACE_URL
from threading import Event,Thread
import json
import logging
from psycopg.types.json import Jsonb
from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
from app.adapters.models.openai_responses import ModelProviderError
from app.adapters.task_store import TaskStore,source_conflict
from app.adapters.figure_workbench_store import FigureWorkbenchStore,read_bundle
from app.domain.figure_workbench.tasks import assets_for,require_task_sources,validate_policy,PLOT_KEY,EXPLANATION_KEY
from app.domain.figure_workbench.contracts import RENDERER
from app.domain.figure_workbench.presentation import renderer_for
from app.domain.external_processing import digest
from app.domain.model_usage.gateway import ModelGateway,ModelGatewayError,input_digest
from app.domain.model_usage.service import ModelUsageService
from app.domain.model_usage.contracts import CallRequest,ModelPolicy
from app.domain.tasks.boxplot_execution import unknown_submission
from app.core.exceptions import StorageError,PlotError
from app.domain.regression.common import NumericError
from app.domain.tasks.numeric_failure import fail_numeric_task
logger=logging.getLogger(__name__)


def _call(repository,lease):
    with repository.connection() as db:
        task=repository.require_lease(db,lease)
        row=db.execute('SELECT * FROM model_calls WHERE task_id=%s ORDER BY created_at DESC,id DESC LIMIT 1',(task['id'],)).fetchone()
        return dict(row) if row else None


@local_numeric_node
def _context(repository,lease):
    with repository.connection() as db:
        task=repository.require_lease(db,lease);snapshot=require_task_sources(repository,db,task)
    assets=assets_for(repository,task['user_id']);store=FigureWorkbenchStore(assets);r=snapshot['result']
    row,result,computed,payload,expected=store.material(task['project_id'],r['file_id'],r['id'],snapshot['figure_workbench']['version_id'])
    with repository.connection() as db:projection=store._projection(db,row)
    return task,store,row,result,projection,payload,expected


@local_numeric_node
def _publish_figure(repository,lease,store,figure):
    # Existing immutable bytes and all source/config/facts are rechecked before publication.
    with repository.connection(write=True) as db:
        task=repository.require_lease(db,lease);require_task_sources(repository,db,task)
        call=db.execute('SELECT * FROM model_calls WHERE task_id=%s AND call_key=%s',(task['id'],PLOT_KEY)).fetchone()
        provenance=figure.get('provenance') or {}
        if (not call or call['provider_status']!='completed' or provenance.get('model_call_id')!=call['id']
                or provenance.get('model_input_digest')!=call['input_digest'] or provenance.get('response_id')!=call['provider_response_id']
                or provenance.get('container_id')!=(call['provider_state'] or {}).get('container_id')
                or provenance.get('model')!=call['model']):raise source_conflict()
        current=db.execute('SELECT figure_json FROM figures WHERE figure_config_version_id=%s',(figure['figure_config_version_id'],)).fetchone()
        if current:
            saved=json.loads(current['figure_json'])
            if saved['sha256']!=figure['sha256'] or saved['facts_sha256']!=figure['facts_sha256']:raise source_conflict()
            figure=saved
        else:
            from app.domain.storage_governance.candidates import task_hold,task_recovery_authorized
            from app.domain.storage_governance.service import publish_candidate,invalid
            hold=task_hold(db,task)
            if not hold:raise invalid()
            publish_candidate(db,store.assets.directory,hold['id'],explicit_recovery=task_recovery_authorized(hold,task,lease))
            db.execute('INSERT INTO figures(id,analysis_run_id,renderer_version,figure_config_version_id,figure_json) VALUES (%s,%s,%s,%s,%s)',(figure['id'],figure['analysis_run_id'],figure['engine']['id'],figure['figure_config_version_id'],json.dumps(figure,ensure_ascii=False,allow_nan=False)))
        store.assets.figure_png(figure)
        task['result_figure_id']=figure['id'];db.execute('UPDATE tasks SET figure_candidate=NULL WHERE id=%s',(task['id'],))
        repository.require_lease(db,lease)
        repository._finish(db,task,'succeeded',None)
        return TaskStore.public_task(task)


@local_numeric_node
def _publish_explanation(repository,lease,bundle,value):
    from app.domain.figure_workbench.explanations import validate_saved,task_version
    validate_saved(bundle,value)
    version=value['engine']['id']
    with repository.connection(write=True) as db:
        task=repository.require_lease(db,lease);require_task_sources(repository,db,task)
        if version!=task_version(task['input_snapshot']):raise source_conflict()
        existing=db.execute('SELECT explanation_json FROM explanations WHERE figure_id=%s AND engine_version=%s',(value['figure_id'],version)).fetchone()
        if existing:
            value=json.loads(existing['explanation_json']);validate_saved(bundle,value)
        else:db.execute('INSERT INTO explanations(id,analysis_run_id,figure_id,engine_version,explanation_json) VALUES (%s,%s,%s,%s,%s)',(value['id'],value['analysis_run_id'],value['figure_id'],version,json.dumps(value,ensure_ascii=False,allow_nan=False)))
        task['result_explanation_id']=value['id']
        repository.require_lease(db,lease)
        repository._finish(db,task,'succeeded',None)
        return TaskStore.public_task(task)


def _execute(repository,lease,provider_factory,providers,explanation):
    with repository.connection() as db:
        task=repository.require_lease(db,lease);repository.require_owner(db,task)
    from app.domain.figure_workbench.prompts import instructions_for
    from app.domain.figure_workbench.explanations import build_payload,instructions_for as explanation_instructions,render,task_version
    bundle=None
    call=_call(repository,lease)
    if unknown_submission(call):return repository.wait_explanation(lease,'submission_unknown','model_submission_unknown')
    if call and call['status']=='released':return repository.fail(lease,'task_source_conflict')
    if not explanation and task.get('figure_candidate'):
        task,store,row,result,projection,payload,expected=_context(repository,lease)
        candidate=task['figure_candidate']
        if (candidate.get('facts_sha256')!=digest(expected) or any(candidate.get(k)!=v for k,v in expected.items()) or candidate.get('figure_config_version_id')!=row['id'] or candidate.get('configuration_sha256')!=row['sha256'] or candidate.get('projection_id')!=projection['id'] or candidate.get('projection_sha256')!=projection['sha256'] or candidate.get('source')!=result['source'] or candidate.get('analysis_run_id')!=result['id']):raise source_conflict()
        return _publish_figure(repository,lease,store,candidate)
    if not call or not call.get('provider_response_id'):
        task,store,row,result,projection,payload,expected=_context(repository,lease)
        if explanation:
            bundle=read_bundle(store.assets,task['project_id'],task['input_snapshot']['figure']['id']);payload=build_payload(bundle,version=task_version(task['input_snapshot']));instructions=explanation_instructions(payload)
        else:instructions=instructions_for(payload)
        from app.domain.admin_configuration.model_consumption import task_instructions
        with repository.connection() as db:instructions=task_instructions(db,task,instructions,'explanation' if explanation else 'plot')
        frozen=validate_policy(task['input_snapshot']['explanation_policy' if explanation else 'boxplot_policy'],payload,explanation=explanation,instructions=instructions)
    if not explanation:repository.admit_figure_storage(lease)
    provider=provider_factory();providers.append(provider);gateway=ModelGateway(ModelUsageService(task['user_id'],repository.config),provider)
    try:
        if call and call.get('provider_response_id'):output=gateway.refresh(call['id'])
        else:
            request=CallRequest(task_id=task['id'],expected_task_revision=task['revision'],call_key=EXPLANATION_KEY if explanation else PLOT_KEY,input_digest=input_digest(instructions=instructions,payload=payload),policy=ModelPolicy.model_validate(frozen['policy']),input_token_allowance=frozen['input_token_allowance'],tool_reserve_micro_usd=0 if explanation else frozen['tool_reserve_micro_usd'],tool_reserve_version=None if explanation else frozen['tool_reserve_version'])
            output=gateway.submit(request,instructions=instructions,payload=payload,execution_lease=lease) if explanation else gateway.submit_plot(request,instructions=instructions,payload=payload,execution_lease=lease)
    except ModelGatewayError as exc:
        if exc.code=='model_receipt_persistence_failed':raise
        call=_call(repository,lease)
        if unknown_submission(call):return repository.wait_explanation(lease,'submission_unknown','model_submission_unknown')
        from app.domain.tasks.errors import classify_read_error
        return repository.retry_failure(lease,classify_read_error(exc.code,exc.status_code))
    call=output['call'];response=output.get('response')
    if unknown_submission(call):return repository.wait_explanation(lease,'submission_unknown','model_submission_unknown')
    if response is None:
        return repository.fail(lease,'model_response_invalid') if call.get('provider_response_id') else repository.defer(lease)
    if isinstance(response,dict) and response.get('status') in ('queued','in_progress'):return repository.defer(lease)
    # A saved response can still incur cost after local source/configuration damage.
    # Record its terminal receipt before rejecting publication against those sources.
    task,store,row,result,projection,payload,expected=_context(repository,lease)
    if explanation:
        bundle=read_bundle(store.assets,task['project_id'],task['input_snapshot']['figure']['id']);payload=build_payload(bundle,version=task_version(task['input_snapshot']))
    validate_policy(task['input_snapshot']['explanation_policy' if explanation else 'boxplot_policy'],payload,explanation=explanation)
    if explanation:
        from app.domain.explanation_response import parse_explanation_response
        parsed=parse_explanation_response(response)
        value=render(bundle,parsed['draft'],{**parsed['provenance'],'model_call_id':call['id'],'model_input_digest':call['input_digest']},version=task_version(task['input_snapshot']))
        return _publish_explanation(repository,lease,bundle,value)
    from app.domain.plot_response import parse_plot_response,PlotVerificationError,bounded_manifest
    from app.domain.figure_workbench.material import verify_manifest
    from app.adapters.openai_plot import validate_output
    parsed=parse_plot_response(response,(call.get('provider_state') or {}).get('container_id'),expected={'schema_version':4})
    policy=ModelPolicy.model_validate({k:call['policy_snapshot'][k] for k in ModelPolicy.model_fields if k in call['policy_snapshot']})
    raw=provider.download(parsed['files']['result.json'],parsed['provenance']['container_id'],8*1024*1024,policy=policy)
    if type(raw) is not bytes or len(raw)>8*1024*1024:raise PlotError('plot_output_limit','结果文件超过上限。')
    def reject(value):raise ValueError()
    def finite_float(value):
        import math
        number=float(value)
        if not math.isfinite(number):raise ValueError()
        return number
    try:manifest=json.loads(raw.decode('utf8'),parse_constant=reject,parse_float=finite_float)
    except (ValueError,UnicodeError,RecursionError):raise PlotError('plot_invalid_result','结果JSON无效。') from None
    try:verify_manifest(manifest,expected)
    except PlotVerificationError as exc:
        with repository.connection(write=True) as db:
            task=repository.require_lease(db,lease)
            evidence={'status':'mismatched','differences':exc.differences,'manifest':bounded_manifest(manifest),'model_call_id':call['id'],'response_id':call['provider_response_id']}
            db.execute('UPDATE tasks SET verification_failure=%s WHERE id=%s',(Jsonb(evidence),task['id']));repository._finish(db,task,'failed','plot_result_mismatch')
            return TaskStore.public_task(task)
    png=provider.download(parsed['files']['figure.png'],parsed['provenance']['container_id'],12*1024*1024,policy=policy)
    if type(png) is not bytes or len(png)>12*1024*1024:raise PlotError('plot_output_limit','PNG超过上限。')
    validate_output({'png':png,'manifest':{}},{})
    from PIL import Image
    from io import BytesIO
    with Image.open(BytesIO(png)) as im:
        style=row['config_json']['style']
        if (im.width,im.height)!=(style['width'],style['height']):raise PlotError('plot_invalid_image','图片尺寸不符合冻结配置。')
    figure={**expected,'id':str(uuid5(NAMESPACE_URL,'paperassist:figure:'+task['id'])),'analysis_run_id':result['id'],'file_id':result['file_id'],'source':result['source'],'source_sha256':result['source_sha256'],'setup_revision':result['setup_revision'],'sha256':sha256(png).hexdigest(),'size_bytes':len(png),'figure_config_version_id':row['id'],'configuration_sha256':row['sha256'],'projection_id':projection['id'],'projection_sha256':projection['sha256'],'facts_sha256':digest(expected),'figure_number':None,'numbering_mode':'external','method':projection['result']['method'],'created_at':datetime.now(timezone.utc).isoformat(),'engine':{'id':renderer_for(row['source_json']),'provider':'openai_code_interpreter','model':call['model']},'verification':{'status':'matched','note':'Structured values verified; image pixels require human review.' if row['config_json']['language']=='en' else '结构化数值已核验；图像视觉仍需人工审阅。'},'provenance':{**parsed['provenance'],'prompt_version':renderer_for(row['source_json']),'model_call_id':call['id'],'model_input_digest':call['input_digest'],'input_sha256':digest(payload)},'text_authorship':{'title':'user' if style['title'] else 'program','additional_caption':'user','created_by':row['created_by']},'external_processing':task['input_snapshot']['external_processing']}
    with repository.connection(write=True) as db:
        task=repository.require_lease(db,lease);require_task_sources(repository,db,task)
        from app.domain.storage_governance.candidates import task_hold,FIGURE_DESCRIPTOR_FORMAT
        from app.domain.storage_governance.service import capture_candidate,invalid
        hold=task_hold(db,task)
        if not hold:raise invalid()
        figure['created_at']=task['created_at'].isoformat()
        document={k:task[k] for k in ('id','project_id','user_id','input_digest','task_type')}
        document['candidate']=figure
        capture_candidate(db,store.assets.directory,hold['id'],png,
            [store.assets.figures_dir/(figure['id']+'.png'),store.assets.directory/'task-staging'/(figure['id']+'.candidate')],source_identity=task['input_digest'],
            descriptor=json.dumps(document,ensure_ascii=False,allow_nan=False,sort_keys=True).encode(),
            descriptor_path=store.assets.directory/'task-staging'/(figure['id']+'.json'),
            write_path=store.assets.directory/'task-staging'/(figure['id']+'.candidate'),descriptor_format=FIGURE_DESCRIPTOR_FORMAT)
        db.execute('UPDATE tasks SET figure_candidate=%s WHERE id=%s',(Jsonb(figure),task['id']))
    store.assets.figures_dir.mkdir(parents=True,exist_ok=True)
    write_candidate(repository,lease,store,figure,png)
    return _publish_figure(repository,lease,store,figure)


def _run(task_id,task_revision,*,config=None,directory=None,provider_factory=None,explanation=False):
    repository=TaskExecutionStore(config=config,directory=directory);lease=repository.claim(task_id,task_revision,task_type='figure_explanation' if explanation else 'figure_workbench')
    if lease is None:return None
    if provider_factory is None:
        if explanation:from app.domain.tasks.explanation_execution import create_provider as provider_factory
        else:from app.domain.tasks.boxplot_execution import create_provider as provider_factory
    stop=Event();providers=[]
    def heartbeat():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease):return
            except Exception:logger.warning('figure heartbeat unavailable task=%s',task_id)
    thread=Thread(target=heartbeat,daemon=True);thread.start()
    try:return _execute(repository,lease,provider_factory,providers,explanation)
    except LeaseLost:return None
    except NumericError as exc:
        return fail_numeric_task(repository,lease,exc)
    except ModelProviderError as exc:
        # POST errors are handled by the gateway; only safe output downloads reach here.
        from app.domain.tasks.errors import classify_read_error
        code='plot_invalid_result' if exc.code in ('plot_receipt_invalid','model_input_invalid') else classify_read_error(exc.code,exc.status_code)
        return repository.retry_failure(lease,code)
    except (StorageError,PlotError) as exc:
        if exc.code in ('model_budget_missing','model_budget_exceeded','plot_not_configured','explanation_not_configured','openai_not_configured'):return repository.wait_explanation(lease,'budget_exceeded',exc.code)
        if isinstance(exc,PlotError) or exc.status<500 or exc.code.startswith('storage_'):
            call=_call(repository,lease)
            if call and call['status']=='reserved' and not call.get('provider_state') and not call.get('provider_response_id'):
                ModelUsageService(call['user_id'],repository.config).release_unsubmitted(call['id'],event_key='figure:unsubmitted_failure:v1',reason_code=exc.code)
            return repository.fail(lease,exc.code)
        logger.warning('figure persistence unavailable task=%s code=%s',task_id,exc.code);return None
    except Exception as exc:
        logger.warning('figure execution interrupted task=%s type=%s',task_id,type(exc).__name__);return None
    finally:
        stop.set();thread.join(timeout=1)
        for provider in providers:
            try:provider.close()
            except Exception:pass


def run_figure_workbench_task(task_id,task_revision,**kwargs):return _run(task_id,task_revision,**kwargs)
def run_figure_explanation_task(task_id,task_revision,**kwargs):return _run(task_id,task_revision,explanation=True,**kwargs)


def write_candidate(repository,lease,store,figure,png):
    """Consume the committed bounded hold; preserve the sole complete staging file."""
    import os
    from app.domain.storage_governance.candidates import task_hold
    from app.domain.storage_governance.service import require_publication_allowed,invalid
    if sha256(png).hexdigest()!=figure['sha256'] or len(png)!=figure['size_bytes']:raise source_conflict()
    with repository.connection(write=True) as db:
        task=repository.require_lease(db,lease);require_task_sources(repository,db,task)
        hold=task_hold(db,task)
        if not hold or hold['sha256']!=figure['sha256'] or hold['size_bytes']!=len(png):raise invalid()
        temporary=store.assets.directory/'task-staging'/(figure['id']+'.candidate')
        if temporary.relative_to(store.assets.directory).as_posix() not in hold['candidate_json']['locations']:raise invalid()
        for key in hold['candidate_json']['locations']:require_publication_allowed(db,task['project_id'],key)
        temporary.parent.mkdir(parents=True,exist_ok=True)
        from app.domain.storage_governance.candidates import _write_immutable
        _write_immutable(temporary,png)
