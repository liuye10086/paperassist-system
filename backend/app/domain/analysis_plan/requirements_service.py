"""Durable v4 requirement intake and atomic fixed-source continuation."""
from datetime import datetime,timezone
from uuid import uuid4,uuid5,UUID
from psycopg.types.json import Jsonb
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_analysis import load_dataset
from app.domain.dataset_preparation.service import request_digest,require_key,append_checkpoint
from app.domain.tasks.waits import get_open_wait,resolve_open_wait
from app.domain.analysis_plan.requirements import (RequirementCreateRequest,RequirementSnapshot,RequirementState,
    ContinuationRequest,requirement_check,SourceRequirementCreateRequest,SourceRequirementSnapshot,SourceRequirementState)

CONTINUATION_NAMESPACE=UUID('97f3c1ed-74db-4b51-8ad1-d02262ca0742')


def validate_requirement_snapshot(task):
    raw=task['input_snapshot']
    modern=raw.get('schema_version')==5
    snapshot=(SourceRequirementSnapshot if modern else RequirementSnapshot).model_validate(raw,strict=True).model_dump(mode='json')
    request=(SourceRequirementCreateRequest if modern else RequirementCreateRequest).model_validate(snapshot['request_material'],strict=True).model_dump(mode='json')
    source=snapshot['source']
    if (task['task_type']!='analysis_plan' or task['workflow_version']!=snapshot['workflow_version']
            or task['project_id']!=snapshot['project_id'] or task['input_digest']!=request_digest(request)
            or snapshot['input_kind']!=request['input_kind'] or snapshot['expected_setup_revision']!=request['expected_setup_revision']
            or snapshot['selection']!=request['selection'] or snapshot['research_request']!=request['research_request']
            or snapshot['recommendation_ref']!=request['recommendation_ref'] or snapshot['origin_recommendation_ref']!=request['origin_recommendation_ref']
            or (source is None)!=(request['input_kind']=='materials')
            or source is not None and (source['kind']!='prepared_dataset_version' or source['dataset_id']!=request['dataset_id']
                or source['file_id']!=request['file_id'] or snapshot['selection'] is not None and snapshot['selection']['sheet_name']!=source['sheet_name'])
            or [v['id'] for v in snapshot['evidence_versions']]!=request['evidence_version_ids']):
        raise source_conflict()
    return snapshot


def evidence_versions(service,project,ids):
    if not ids:return []
    from app.domain.external_evidence.service import ExternalEvidenceService
    return ExternalEvidenceService(service.assets).require_versions(project,ids)


def require_requirement_check(service,task,state,*,recompute=True):
    snapshot=validate_requirement_snapshot(task)
    if evidence_versions(service,task['project_id'],[x['id'] for x in snapshot['evidence_versions']])!=snapshot['evidence_versions']:
        raise source_conflict()
    source=snapshot['source'];sheet=None
    if source is not None:
        record,sheet=service.require_source(source,task['project_id'])
        if record['filename']!=snapshot['filename']:raise source_conflict()
    if state['recommendation_ref'] is not None:
        from types import SimpleNamespace
        from app.domain.correlation.contracts import RecommendationReference,parse_selection
        from app.domain.analysis_recommendation.service import validate_reference,RecommendationService
        if state['selection'] is None:
            ref=state['recommendation_ref'];view=RecommendationService(service.assets).get(ref['task_id']);result=view['recommendation']
            if (not result or state['plan_revision']==1 and result['method'] is not None or result['sha256']!=ref['sha256'] or view['source']!=source or view['task']['project_id']!=task['project_id']):
                raise source_conflict()
        else:
            validate_reference(service.assets,task['project_id'],source,SimpleNamespace(
                recommendation_ref=RecommendationReference.model_validate(state['recommendation_ref']),selection=parse_selection(state['selection'])))
    if state['origin_recommendation_ref'] is not None:
        validate_origin_reference(service,task['project_id'],source,state['origin_recommendation_ref'])
    if snapshot['schema_version']==5:
        expected=source_reference(service,task['project_id'],source,state['recommendation_ref'])
        if expected!=snapshot['source_reference']:raise source_conflict()
    if recompute and state['check'] is not None and requirement_check(source,state['selection'],state['research_request'],sheet,schema_version=snapshot['schema_version'],source_resolution=state.get('source_resolution'))!=state['check']:
        raise source_conflict()
    return sheet


def validate_origin_reference(service,project,source,reference):
    from app.domain.analysis_recommendation.service import RecommendationService
    view=RecommendationService(service.assets).get(reference['task_id'])
    if (not source or not view['recommendation'] or view['task']['project_id']!=project
            or view['recommendation']['sha256']!=reference['sha256'] or view['source']==source):
        raise source_conflict()
    # Each edge is loaded through the published-version provenance validator.
    from app.domain.dataset_preparation.service import DatasetPreparationService
    current=source;seen=set()
    while current!=view['source']:
        if current['dataset_id'] in seen or current['file_id']!=view['source']['file_id'] or current['kind']!='prepared_dataset_version':raise source_conflict()
        seen.add(current['dataset_id'])
        loaded=DatasetPreparationService(service.assets).load_version(project,current['file_id'],current['dataset_id'])
        obj=loaded[2]
        if hasattr(obj,'model_dump'):obj=obj.model_dump(mode='json')
        parent=obj.get('base_source')
        if not parent:raise source_conflict()
        current=parent


def create_requirement(service,project,request,key,*,db=None,parent=None):
    require_key(key)
    request=(SourceRequirementCreateRequest if (request.schema_version if hasattr(request,'schema_version') else request.get('schema_version'))==5 else RequirementCreateRequest).model_validate(request)
    raw=request.model_dump(mode='json');digest=request_digest(raw)
    if db is None:
        with service.store.connection(write=True) as transaction:
            return create_requirement(service,project,request,key,db=transaction,parent=parent)
    service.store.require_project(db,project)
    existing=service.store.find_request(db,project,'analysis_plan',key)
    if existing:
        if existing['input_digest']!=digest:raise StorageError('task_idempotency_conflict','请求标识已用于其他输入。',409)
        return service.store.public_task(existing),200
    versions=evidence_versions(service,project,request.evidence_version_ids)
    source=None;filename=None
    if request.input_kind=='data':
        record,source,sheet=load_dataset(service.assets,project,request.file_id,request.dataset_id)
        if source['kind']!='prepared_dataset_version' or request.selection is not None and request.selection.sheet_name!=source['sheet_name']:
            raise StorageError('task_input_invalid','请选择已确认整理版本及其工作表。',422)
        filename=record['filename']
        setup=db.execute('SELECT revision FROM analysis_setups WHERE file_id=%s',(request.file_id,)).fetchone()
        if (setup['revision'] if setup else 0)!=request.expected_setup_revision:
            raise StorageError('setup_conflict','分析配置已更新，请重新读取。',409)
    now=datetime.now(timezone.utc)
    version=request.schema_version
    snapshot=(SourceRequirementSnapshot if version==5 else RequirementSnapshot)(schema_version=version,kind='analysis_plan',workflow_version=f'analysis_plan_v{version}',rules_version=f'analysis_plan_rules_v{version}',
        project_id=project,filename=filename,source=source,expected_setup_revision=request.expected_setup_revision,input_kind=request.input_kind,
        selection=request.selection,research_request=request.research_request,evidence_versions=versions,recommendation_ref=request.recommendation_ref,
        origin_recommendation_ref=request.origin_recommendation_ref,parent_requirement_task_id=parent,request_material=raw,**(dict(source_reference=source_reference(service,project,source,raw['recommendation_ref'])) if version==5 else {})).model_dump(mode='json')
    task=dict(id=str(uuid4()),project_id=project,user_id=service.store.user_id,task_type='analysis_plan',idempotency_key=key,input_digest=digest,
        input_snapshot=snapshot,workflow_version=f'analysis_plan_v{version}',status='queued',phase='plan',revision=1,current_attempt=0,reason_code=None,created_at=now,updated_at=now)
    from app.domain.analysis_plan.service import plan_input_version
    state=(SourceRequirementState if version==5 else RequirementState)(input_version=plan_input_version(task),plan_revision=1,selection=request.selection,research_request=request.research_request,
        recommendation_ref=request.recommendation_ref,origin_recommendation_ref=request.origin_recommendation_ref).model_dump(mode='json')
    require_requirement_check(service,task,state)
    service.store.insert_task(db,task);append_checkpoint(db,task,'check','check',state)
    service.store.append_event(db,task,'created');service.store.enqueue(db,task)
    return service.store.public_task(task),202


def get_requirement_task(service,task_id):
    from app.domain.analysis_plan.service import latest_checkpoint,validate_published
    with service.store.connection() as db:
        task=service.store.require_task(db,task_id);snapshot=validate_requirement_snapshot(task)
        checkpoint=latest_checkpoint(db,task);state=checkpoint['state_json'];wait=get_open_wait(db,task)
        row=db.execute('SELECT * FROM confirmed_analysis_plans WHERE task_id=%s',(task_id,)).fetchone()
        result=validate_published(db,task,row) if row else None
    require_requirement_check(service,task,state,recompute=False)
    from app.domain.analysis_recommendation.service import local_source_mapping
    return dict(task=service.store.public_task(task),source=snapshot['source'],checkpoint_id=checkpoint['id'],wait_id=wait['id'] if wait else None,
        plan_revision=state['plan_revision'],input_version=state['input_version'],selection=state['selection'],check=state['check'],resolutions=state['resolutions'],
        result=result,research_request=state['research_request'],recommendation_ref=state['recommendation_ref'],origin_recommendation_ref=state['origin_recommendation_ref'],
        input_kind=snapshot['input_kind'],evidence_versions=snapshot['evidence_versions'],continuation=state['continuation'],**(dict(source_reference=snapshot['source_reference'],source_resolution=state['source_resolution'],source_mapping=local_source_mapping(snapshot['filename'],snapshot['source'])) if snapshot['schema_version']==5 else {}))


def continue_requirement(service,task_id,request,key):
    from app.domain.analysis_plan.service import latest_checkpoint,plan_input_version
    require_key(key);request=ContinuationRequest.model_validate(request);raw=request.model_dump(mode='json');digest=request_digest(raw)
    with service.store.connection(write=True) as db:
        db.execute('SELECT id FROM tasks WHERE id=%s AND user_id=%s FOR UPDATE',(task_id,service.store.user_id)).fetchone()
        task=service.store.require_task(db,task_id);snapshot=validate_requirement_snapshot(task)
        existing=db.execute('SELECT * FROM analysis_plan_decisions WHERE task_id=%s AND user_id=%s AND idempotency_key=%s',(task_id,service.store.user_id,key)).fetchone()
        if existing:
            if existing['request_digest']!=digest:raise StorageError('task_idempotency_conflict','补交标识已用于其他输入。',409)
            return existing['response_json'],200
        checkpoint=latest_checkpoint(db,task);state=dict(checkpoint['state_json']);wait=get_open_wait(db,task)
        if (task['status'] not in ('waiting_input','waiting_confirmation') or task['revision']!=request.expected_task_revision
                or raw['input_version']!=plan_input_version(task) or request.checkpoint_id!=checkpoint['id'] or request.plan_revision!=state['plan_revision']
                or not wait or request.wait_id!=wait['id'] or wait['task_revision']!=task['revision'] or state['continuation'] is not None):
            raise StorageError('task_revision_conflict','待补充需求已经更新，请重新读取。',409)
        require_requirement_check(service,task,state,recompute=False)
        child_request=SourceRequirementCreateRequest(schema_version=5,input_kind='data',file_id=request.file_id,dataset_id=request.dataset_id,
            expected_setup_revision=request.expected_setup_revision,selection=request.selection,research_request=request.research_request,
            evidence_version_ids=[v['id'] for v in snapshot['evidence_versions']],recommendation_ref=None,origin_recommendation_ref=request.origin_recommendation_ref)
        child,status=create_requirement(service,task['project_id'],child_request,'continuation:'+str(uuid5(CONTINUATION_NAMESPACE,task_id)),db=db,parent=task_id)
        response=dict(completion_type='continued_as_plan',parent_task_id=task_id,task=child)
        previous=task['revision'];now=max(datetime.now(timezone.utc),task['updated_at'])
        decision_id=str(uuid4())
        task.update(status='succeeded',revision=previous+1,updated_at=now,reason_code='input_provided',error_code=None)
        service.store.update_task(db,task,previous);resolve_open_wait(db,task,status='superseded')
        db.execute('''INSERT INTO analysis_plan_decisions (id,task_id,user_id,project_id,wait_id,checkpoint_id,idempotency_key,request_digest,operation,request_json,response_json,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'revise',%s,%s,%s)''',(decision_id,task_id,task['user_id'],task['project_id'],request.wait_id,request.checkpoint_id,key,digest,Jsonb(raw),Jsonb(response),now))
        state.update(continuation=response,decision_id=decision_id)
        append_checkpoint(db,task,'done','done',state,checkpoint)
        service.store.append_event(db,task,'succeeded')
        return response,202


def validate_continuation_checkpoint(db,task,row):
    state=(SourceRequirementState if task['workflow_version']=='analysis_plan_v5' else RequirementState).model_validate(row['state_json'],strict=True).model_dump(mode='json')
    decision=db.execute('SELECT * FROM analysis_plan_decisions WHERE id=%s AND task_id=%s',(state['decision_id'],task['id'])).fetchone()
    request=ContinuationRequest.model_validate(decision['request_json'],strict=True).model_dump(mode='json')
    previous=db.execute('SELECT * FROM task_checkpoints WHERE id=%s AND task_id=%s',(decision['checkpoint_id'],task['id'])).fetchone()
    wait=db.execute('SELECT * FROM task_waits WHERE id=%s AND task_id=%s',(decision['wait_id'],task['id'])).fetchone()
    from app.domain.analysis_plan.service import validate_checkpoint,plan_input_version
    reviewed=validate_checkpoint(db,task,previous)['state_json']
    child=db.execute('SELECT * FROM tasks WHERE id=%s',(state['continuation']['task']['id'],)).fetchone()
    frozen=validate_requirement_snapshot(child)
    if (task['status']!='succeeded' or row['node']!='done' or row['next_node']!='done'
            or decision['request_digest']!=request_digest(request) or decision['response_json']!=state['continuation']
            or decision['operation']!='revise' or decision['user_id']!=task['user_id'] or decision['project_id']!=task['project_id']
            or request['checkpoint_id']!=previous['id'] or previous['next_node'] not in ('await_input','await_confirmation')
            or request['wait_id']!=wait['id'] or wait['status']!='superseded' or wait['input_version']!=request['input_version']
            or wait['task_revision']!=request['expected_task_revision'] or wait['resolved_task_revision']!=task['revision']
            or task['revision']!=request['expected_task_revision']+1 or wait['user_id']!=task['user_id'] or wait['project_id']!=task['project_id']
            or state['continuation']['completion_type']!='continued_as_plan' or state['continuation']['parent_task_id']!=task['id']
            or frozen['parent_requirement_task_id']!=task['id'] or child['project_id']!=task['project_id'] or child['user_id']!=task['user_id']
            or request['input_version']!=plan_input_version(task) or request['plan_revision']!=reviewed['plan_revision']
            or any(state[k]!=reviewed[k] for k in state if k not in ('continuation','decision_id'))
            or frozen['source']['file_id']!=request['file_id'] or frozen['source']['dataset_id']!=request['dataset_id']
            or frozen['selection']!=request['selection'] or frozen['research_request']!=request['research_request']
            or frozen['evidence_versions']!=task['input_snapshot']['evidence_versions'] or frozen['recommendation_ref'] is not None
            or frozen['origin_recommendation_ref']!=request['origin_recommendation_ref']
            or frozen['expected_setup_revision']!=request['expected_setup_revision']):
        raise source_conflict()
    return {**dict(row),'state_json':state}


def source_reference(service,project,source,reference):
    if reference is None:return None
    from app.domain.analysis_recommendation.service import RecommendationService
    view=RecommendationService(service.assets).get(reference['task_id'])
    result=view['recommendation']
    if not result or result['schema_version']!=5 or result['sha256']!=reference['sha256'] or view['source']!=source or view['task']['project_id']!=project:raise source_conflict()
    return result['source_reference']
