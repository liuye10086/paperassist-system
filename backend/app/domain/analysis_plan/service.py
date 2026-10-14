"""Owner-scoped, explicit review generations and immutable approved plans."""
from datetime import datetime,timezone
from uuid import UUID,uuid4,uuid5
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_analysis import load_dataset
from app.domain.datasets.service import DatasetService
from app.domain.dataset_preparation.service import request_digest,require_key,append_checkpoint
from app.domain.tasks.waits import get_open_wait,resolve_open_wait
from app.domain.analysis import AnalysisSelection
from app.domain.analysis_plan.contracts import (AnalysisPlanCreateRequest,AnalysisPlanDecisionRequest,
    AnalysisPlanSnapshot,AnalysisPlanState,PlanContent,WORKFLOW_VERSION,RULES_VERSION)
from app.domain.analysis_plan.references import PlanReference
from app.domain.analysis_plan.checks import build_check,validate_resolutions

PLAN_NAMESPACE=UUID('cffbb467-bb6c-466b-9c72-7f09bf3de7c5')


def decision_material(request):
    value=request.model_dump(mode='json')
    if request.operation=='approve': value.pop('selection')
    return value


def plan_id(task_id):
    return str(uuid5(PLAN_NAMESPACE,task_id))


def validate_snapshot(task):
    try:
        raw=task['input_snapshot']
        snapshot=AnalysisPlanSnapshot.model_validate(raw,strict=True).model_dump(mode='json')
        if (task['task_type']!='analysis_plan' or task['workflow_version']!=WORKFLOW_VERSION
                or type(raw['schema_version']) is not int or task['project_id']!=snapshot['project_id']
                or snapshot['selection']['sheet_name']!=snapshot['source']['sheet_name']
                or task['input_digest']!=request_digest(dict(file_id=snapshot['source']['file_id'],
                    dataset_id=snapshot['source']['dataset_id'],expected_setup_revision=snapshot['expected_setup_revision'],
                    selection=snapshot['selection']))):
            raise ValueError('Frozen plan identity differs')
        return snapshot
    except (KeyError,TypeError,ValueError) as exc:
        raise source_conflict() from exc


def plan_input_version(task):
    snapshot=validate_snapshot(task)
    return dict(kind='analysis_plan',source=snapshot['source'],workflow_version=WORKFLOW_VERSION)


def read_decision(db,task,decision_id):
    """Verify a separate decision against its exact reviewed generation."""
    row=db.execute('SELECT * FROM analysis_plan_decisions WHERE id=%s AND task_id=%s',(decision_id,task['id'])).fetchone()
    try:
        request=decision_material(AnalysisPlanDecisionRequest.model_validate(row['request_json'],strict=True))
        reviewed=db.execute('SELECT * FROM task_checkpoints WHERE id=%s AND task_id=%s',(row['checkpoint_id'],task['id'])).fetchone()
        state=AnalysisPlanState.model_validate(reviewed['state_json'],strict=True).model_dump(mode='json')
        wait=db.execute('SELECT * FROM task_waits WHERE id=%s AND task_id=%s',(row['wait_id'],task['id'])).fetchone()
        if (row['operation']!=request['operation'] or row['request_digest']!=request_digest(request)
                or row['user_id']!=task['user_id'] or row['project_id']!=task['project_id']
                or request['checkpoint_id']!=reviewed['id'] or reviewed['next_node']!='await_confirmation'
                or request['input_version']!=plan_input_version(task) or state['input_version']!=request['input_version']
                or state['plan_revision']!=request['plan_revision'] or state['check'] is None
                or request['wait_id']!=wait['id'] or wait['kind']!='analysis_plan_confirmation'
                or wait['user_id']!=task['user_id'] or wait['project_id']!=task['project_id']
                or wait['input_version']!=request['input_version'] or wait['task_revision']!=request['expected_task_revision']
                or wait['resolved_task_revision']!=request['expected_task_revision']+1
                or wait['status']!=('resolved' if request['operation']=='approve' else 'superseded')
                or row['response_json']['id']!=task['id'] or row['response_json']['revision']!=wait['resolved_task_revision']):
            raise ValueError('Decision generation differs')
        return dict(row),request,state
    except (KeyError,TypeError,ValueError) as exc:
        raise source_conflict() from exc


def latest_checkpoint(db,task):
    row=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
    try:
        state=AnalysisPlanState.model_validate(row['state_json'],strict=True).model_dump(mode='json')
        snapshot=validate_snapshot(task)
        if state['input_version']!=plan_input_version(task): raise ValueError('Input changed')
        revised=db.execute('''SELECT d.id FROM analysis_plan_decisions d JOIN task_checkpoints c ON c.id=d.checkpoint_id
            WHERE d.task_id=%s AND d.operation='revise' AND c.seq<%s ORDER BY c.seq DESC LIMIT 1''',(task['id'],row['seq'])).fetchone()
        if revised:
            _,request,_=read_decision(db,task,revised['id'])
            expected_selection=request['selection']; expected_revision=request['plan_revision']+1
        else:
            expected_selection=snapshot['selection'];expected_revision=1
        if state['selection']!=expected_selection or state['plan_revision']!=expected_revision:
            raise ValueError('Selection lacks a revision decision')
        if row['next_node'] in ('await_confirmation','publish','done') and state['check'] is None:
            raise ValueError('Missing candidate check')
        return {**dict(row),'state_json':state}
    except (KeyError,TypeError,ValueError) as exc:
        raise source_conflict() from exc


def require_approval(db,task,state):
    decision,request,reviewed=read_decision(db,task,state['decision_id'])
    if (request['operation']!='approve' or any(reviewed[k]!=state[k] for k in ('input_version','plan_revision','selection','check'))
            or state['resolutions']!=request['resolutions']):
        raise source_conflict()
    try: validate_resolutions(state['check'],state['resolutions'])
    except (ValueError,TypeError,StorageError) as exc: raise source_conflict() from exc
    return decision


def validate_published(db,task,row):
    """Pure database provenance validation, also reused by the read-only audit."""
    snapshot=validate_snapshot(task)
    checkpoint=latest_checkpoint(db,task);state=checkpoint['state_json']
    require_approval(db,task,state)
    try:
        content=PlanContent.model_validate(row['plan_json'],strict=True).model_dump(mode='json')
        if (task['status']!='succeeded' or checkpoint['node']!='done' or checkpoint['next_node']!='done'
                or row['id']!=plan_id(task['id']) or state['result_id']!=row['id']
                or row['task_id']!=task['id'] or row['decision_id']!=state['decision_id']
                or row['created_by']!=task['user_id'] or row['file_id']!=snapshot['source']['file_id']
                or row['sha256']!=request_digest(content) or row['setup_revision']!=snapshot['expected_setup_revision']+1
                or content!=dict(schema_version=1,workflow_version=WORKFLOW_VERSION,rules_version=RULES_VERSION,
                    id=row['id'],task_id=task['id'],decision_id=state['decision_id'],project_id=task['project_id'],
                    file_id=row['file_id'],source=snapshot['source'],selection=state['selection'],check=state['check'],
                    resolutions=state['resolutions'],plan_revision=state['plan_revision'],setup_revision=row['setup_revision'],
                    created_at=row['created_at'].astimezone(timezone.utc).isoformat())):
            raise ValueError('Published plan differs')
        return {**content,'sha256':row['sha256']}
    except (KeyError,TypeError,ValueError) as exc: raise source_conflict() from exc


class AnalysisPlanService:
    def __init__(self,assets):
        self.assets=assets
        self.store=TaskStore(assets.owner_id,assets.db_config)
        self.datasets=DatasetService(assets)

    def require_source(self,source,project_id):
        record,frozen,sheet=load_dataset(self.assets,project_id,source['file_id'],source['dataset_id'],expected_source=source)
        if frozen['kind']!='prepared_dataset_version': raise source_conflict()
        return record,sheet

    def require_check(self,task,state):
        record,sheet=self.require_source(plan_input_version(task)['source'],task['project_id'])
        if record['filename']!=validate_snapshot(task)['filename']:
            raise source_conflict()
        if state['check'] is not None and build_check(sheet,AnalysisSelection.model_validate(state['selection'],strict=True))!=state['check']:
            raise source_conflict()
        return sheet

    def create(self,project,file,request,key):
        require_key(key)
        request=AnalysisPlanCreateRequest.model_validate(request)
        material=request.model_dump(mode='json');digest=request_digest(dict(file_id=file,**material))
        with self.store.connection() as db:
            self.datasets.require_file(db,project,file)
            existing=self.store.find_request(db,project,'analysis_plan',key)
            if existing:
                if existing['input_digest']!=digest: raise StorageError('task_idempotency_conflict','请求标识已用于其他输入。',409)
                return self.store.public_task(existing),200
        record,source,sheet=load_dataset(self.assets,project,file,request.dataset_id)
        if source['kind']!='prepared_dataset_version' or request.selection.sheet_name!=source['sheet_name']:
            raise StorageError('task_input_invalid','请选择已确认整理版本及其工作表。',422)
        with self.store.connection(write=True) as db:
            self.datasets.require_file(db,project,file)
            existing=self.store.find_request(db,project,'analysis_plan',key)
            if existing:
                if existing['input_digest']!=digest: raise StorageError('task_idempotency_conflict','请求标识已用于其他输入。',409)
                return self.store.public_task(existing),200
            self.require_source(source,project)
            row=db.execute('SELECT revision FROM analysis_setups WHERE file_id=%s',(file,)).fetchone()
            if (row['revision'] if row else 0)!=request.expected_setup_revision:
                raise StorageError('setup_conflict','分析配置已更新，请重新读取后生成计划。',409)
            now=datetime.now(timezone.utc)
            snapshot=AnalysisPlanSnapshot(schema_version=1,kind='analysis_plan',workflow_version=WORKFLOW_VERSION,
                rules_version=RULES_VERSION,project_id=project,filename=record['filename'],source=source,
                expected_setup_revision=request.expected_setup_revision,selection=request.selection).model_dump(mode='json')
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='analysis_plan',
                idempotency_key=key,input_digest=digest,input_snapshot=snapshot,workflow_version=WORKFLOW_VERSION,
                status='queued',phase='plan',revision=1,current_attempt=0,reason_code=None,created_at=now,updated_at=now)
            self.store.insert_task(db,task)
            state=AnalysisPlanState(input_version=plan_input_version(task),plan_revision=1,selection=request.selection).model_dump(mode='json')
            append_checkpoint(db,task,'check','check',state)
            self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            return self.store.public_task(task),202

    def get_task(self,task_id):
        with self.store.connection() as db:
            task=self.store.require_task(db,task_id);snapshot=validate_snapshot(task)
            checkpoint=latest_checkpoint(db,task);state=checkpoint['state_json'];wait=get_open_wait(db,task)
            row=db.execute('SELECT * FROM confirmed_analysis_plans WHERE task_id=%s',(task_id,)).fetchone()
            result=validate_published(db,task,row) if row else None
        self.require_check(task,state)
        return dict(task=self.store.public_task(task),source=snapshot['source'],checkpoint_id=checkpoint['id'],
            wait_id=wait['id'] if wait else None,plan_revision=state['plan_revision'],input_version=state['input_version'],
            selection=state['selection'],check=state['check'],resolutions=state['resolutions'],result=result)

    def decide(self,task_id,request,key):
        require_key(key)
        request=AnalysisPlanDecisionRequest.model_validate(request)
        material=decision_material(request);digest=request_digest(material)
        with self.store.connection(write=True) as db:
            task=self.store.require_task(db,task_id);validate_snapshot(task)
            existing=db.execute('SELECT * FROM analysis_plan_decisions WHERE task_id=%s AND user_id=%s AND idempotency_key=%s',
                (task_id,self.store.user_id,key)).fetchone()
            if existing:
                if existing['request_digest']!=digest: raise StorageError('task_idempotency_conflict','确认标识已用于其他输入。',409)
                return existing['response_json'],200
            checkpoint=latest_checkpoint(db,task);state=dict(checkpoint['state_json']);wait=get_open_wait(db,task)
            if (task['revision']!=request.expected_task_revision or task['status']!='waiting_confirmation'
                    or material['input_version']!=plan_input_version(task) or checkpoint['id']!=request.checkpoint_id
                    or checkpoint['next_node']!='await_confirmation' or state['plan_revision']!=request.plan_revision
                    or not wait or wait['id']!=request.wait_id or wait['task_revision']!=task['revision']
                    or wait['kind']!='analysis_plan_confirmation' or wait['input_version']!=material['input_version']):
                raise StorageError('task_revision_conflict','待确认计划已经更新，请重新读取。',409)
            self.require_check(task,state)
            decision_id=str(uuid4())
            if request.operation=='approve':
                validate_resolutions(state['check'],material['resolutions'])
                state.update(decision_id=decision_id,resolutions=material['resolutions']);next_node='publish'
            else:
                if request.selection.sheet_name!=state['input_version']['source']['sheet_name']:
                    raise StorageError('task_input_invalid','修订字段必须属于冻结整理工作表。',422)
                state.update(selection=material['selection'],plan_revision=state['plan_revision']+1,check=None,
                    resolutions={},decision_id=None,result_id=None);next_node='check'
            previous=task['revision']
            task.update(status='queued',phase='plan',revision=previous+1,updated_at=max(datetime.now(timezone.utc),task['updated_at']),
                reason_code='confirmation_received',error_code=None)
            self.store.update_task(db,task,previous)
            resolve_open_wait(db,task,status='resolved' if request.operation=='approve' else 'superseded')
            response=self.store.public_task(task)
            db.execute('''INSERT INTO analysis_plan_decisions
                (id,task_id,user_id,project_id,wait_id,checkpoint_id,idempotency_key,request_digest,operation,request_json,response_json,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (decision_id,task_id,task['user_id'],task['project_id'],request.wait_id,request.checkpoint_id,key,digest,
                    request.operation,Jsonb(material),Jsonb(response),task['updated_at']))
            append_checkpoint(db,task,request.operation,next_node,state,checkpoint)
            self.store.append_event(db,task,'requeued');self.store.enqueue(db,task)
            return response,202

    def get_plan(self,project,file,id):
        with self.store.connection() as db:
            self.datasets.require_file(db,project,file)
            row=db.execute('SELECT * FROM confirmed_analysis_plans WHERE id=%s AND file_id=%s AND created_by=%s',(id,file,self.store.user_id)).fetchone()
            if not row: raise StorageError('result_not_found','已确认分析计划不存在。',404)
            task=self.store.require_task(db,row['task_id'])
            if task['project_id']!=project: raise source_conflict()
            result=validate_published(db,task,row)
            state=latest_checkpoint(db,task)['state_json']
        self.require_check(task,state)
        return result

    def list(self,project,file,page=1,page_size=5):
        if type(page) is not int or not 1<=page<=1000000 or type(page_size) is not int or page_size!=5:
            raise StorageError('task_input_invalid','计划分页参数无效。',422)
        with self.store.connection() as db:
            self.datasets.require_file(db,project,file)
            args=(self.store.user_id,project,file)
            where="user_id=%s AND project_id=%s AND task_type='analysis_plan' AND input_snapshot->'source'->>'file_id'=%s"
            total=db.execute('SELECT count(*) AS n FROM tasks WHERE '+where,args).fetchone()['n']
            rows=db.execute('SELECT id FROM tasks WHERE '+where+' ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s',args+(page_size,(page-1)*page_size)).fetchall()
        return dict(items=[self.get_task(row['id']) for row in rows],total=total,page=page,page_size=page_size)


def validate_plan_reference(assets,project_id,file_id,value):
    """Absence is legacy only if this exact revision has no published plan."""
    revision=value.get('setup_revision',value.get('revision'))
    from app.adapters.storage import _storage_connection
    from app.adapters.task_store import DatasetTaskAssets
    with _storage_connection(config=assets.db_config) as db:
        row=db.execute('SELECT id FROM confirmed_analysis_plans WHERE file_id=%s AND setup_revision=%s',(file_id,revision)).fetchone()
        if assets.owner_id is None and ('analysis_plan' in value or row):
            # Trusted recovery has no session owner. Resolve the exact file's
            # owner and retain every owner-scoped plan/source validation.
            owner=db.execute('''SELECT p.owner_id FROM projects p JOIN files f ON f.project_id=p.id
                WHERE p.id=%s AND f.id=%s''',(project_id,file_id)).fetchone()
            if not owner: raise source_conflict()
            assets=DatasetTaskAssets(owner['owner_id'],assets.db_config,assets.directory)
    if 'analysis_plan' not in value and not row: return None
    service=AnalysisPlanService(assets)
    try:
        reference=PlanReference.model_validate(value['analysis_plan'],strict=True).model_dump(mode='json')
        if not row or row['id']!=reference['plan_id']: raise ValueError('Reference removed or replaced')
        plan=service.get_plan(project_id,file_id,reference['plan_id'])
        if (reference!=dict(plan_id=plan['id'],sha256=plan['sha256'],resolutions=plan['resolutions'])
                or value.get('file_id')!=file_id or value.get('source_sha256')!=plan['source']['source_sha256']
                or revision!=plan['setup_revision'] or value.get('source')!=plan['source']
                or value.get('selection')!=plan['selection'] or value.get('check')!=plan['check']['selection_check']):
            raise ValueError('Plan differs from execution input')
        return plan
    except (KeyError,TypeError,ValueError) as exc: raise source_conflict() from exc


def retry_plan_in_transaction(store,db,task,expected_revision):
    if (task['task_type']!='analysis_plan' or task['status']!='failed'
            or task.get('error_code') not in ('storage_unavailable','task_worker_interrupted')):
        raise StorageError('task_transition_invalid','当前分析计划不能安全重试。',409)
    if task['revision']!=expected_revision: raise StorageError('task_revision_conflict','任务已更新。',409)
    store.require_project(db,task['project_id']);latest_checkpoint(db,task)
    task.update(status='queued',revision=expected_revision+1,error_code=None,reason_code='retry_requested',
        _retry_reason='manual_retry',retry_count=0,updated_at=max(datetime.now(timezone.utc),task['updated_at']))
    store.update_task(db,task,expected_revision);store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)


def retry_plan_task(store,task_id,expected_revision):
    with store.connection(write=True) as db:
        task=store.require_task(db,task_id)
        if db.execute("SELECT seq FROM task_events WHERE task_id=%s AND seq=%s AND event_type='requeued' AND reason_code='retry_requested'",(task_id,expected_revision+1)).fetchone():
            return store.public_task(task)
        return retry_plan_in_transaction(store,db,task,expected_revision)
