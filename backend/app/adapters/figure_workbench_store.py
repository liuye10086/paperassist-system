"""Owner-scoped immutable figure configurations and independent projection receipts."""
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
from uuid import uuid4
import json
import math
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.external_processing import digest
from app.domain.figure_workbench.contracts import FigureConfig,RENDERER
from app.domain.figure_workbench.sources import load_source,calculate,fields_for
from app.domain.figure_workbench.kernel import TOOL_VERSION
from app.domain.figure_workbench.presentation import contract_version,renderer_for,enrich_material


def semantic(config):return {k:v for k,v in config.items() if k!='style'}
def text_identity(config):return {k:config['style'][k] for k in ('title','caption','aliases','display_order')}


def _same_projection_value(left,right,metric=None):
    """Permit machine roundoff only in derived series metrics, never row/type identities."""
    if type(left) is not type(right):return False
    if isinstance(left,dict):
        return left.keys()==right.keys() and all(_same_projection_value(left[k],right[k],k) for k in left)
    if isinstance(left,list):
        return len(left)==len(right) and all(_same_projection_value(a,b,metric) for a,b in zip(left,right))
    if type(left) is float and metric in {'y','value','sd','bandwidth','grid','density','q1','median','q3'}:
        if not math.isfinite(left) or not math.isfinite(right):return False
        return left==right or (abs(left-right)<=32*max(math.ulp(left),math.ulp(right)) and math.isclose(left,right,rel_tol=8e-15,abs_tol=0.))
    return left==right


class FigureWorkbenchStore:
    def __init__(self,store):
        self.assets=store;self.tasks=TaskStore(store.owner_id,store.db_config)
    def _version(self,db,project_id,file_id,run_id,version_id,*,lock=False):
        self.tasks.require_project(db,project_id)
        row=db.execute('''SELECT v.*,c.project_id,c.analysis_run_id,c.current_revision FROM figure_config_versions v
            JOIN figure_configurations c ON c.id=v.configuration_id JOIN analysis_runs a ON a.id=c.analysis_run_id
            WHERE v.id=%s AND c.project_id=%s AND c.analysis_run_id=%s AND a.file_id=%s'''+(' FOR UPDATE OF v' if lock else ''),(version_id,project_id,run_id,file_id)).fetchone()
        if not row:raise StorageError('figure_missing','图表配置不存在。',404)
        row=dict(row);config=FigureConfig.model_validate(row['config_json']).model_dump()
        if row['sha256']!=digest({'config':config,'source':row['source_json']}):raise source_conflict()
        contract_version(row['source_json'])
        return row
    @staticmethod
    def public_version(row):
        return {**{k:row[k] for k in ('id','configuration_id','revision','parent_version_id','created_by','created_at','sha256')},'config':row['config_json'],'source':row['source_json']['source'],**({'figure_contract':contract_version(row['source_json'])} if contract_version(row['source_json'])>=2 else {})}
    def _projection(self,db,row):
        own=row
        for _ in range(100):
            p=db.execute('SELECT * FROM figure_projection_results WHERE config_version_id=%s AND tool_version=%s',(own['id'],TOOL_VERSION)).fetchone()
            if p:
                if p['sha256']!=digest(p['result_json']):raise source_conflict()
                decision=db.execute('SELECT * FROM figure_projection_decisions WHERE id=%s',(p['decision_id'],)).fetchone()
                if not decision or decision['config_version_id']!=own['id'] or decision['input_sha256']!=p['result_json']['input_sha256']:raise source_conflict()
                receipt=decision['decision_json']
                wait=db.execute('SELECT * FROM task_waits WHERE id=%s AND task_id=%s',(receipt.get('wait_id'),decision['task_id'])).fetchone()
                checkpoint=db.execute('SELECT * FROM task_checkpoints WHERE id=%s AND task_id=%s',(receipt.get('checkpoint_id'),decision['task_id'])).fetchone()
                task=db.execute('SELECT * FROM tasks WHERE id=%s',(decision['task_id'],)).fetchone()
                if (receipt.get('approved') is not True or receipt.get('input_sha256')!=decision['input_sha256'] or not wait or not checkpoint or not task
                    or task['task_type']!='figure_projection' or task['status']!='succeeded' or task['user_id']!=decision['approved_by']
                    or task['input_snapshot']['figure_workbench']['version_id']!=own['id'] or task['input_digest']!=(projection_request_digest(own) if task['workflow_version']=='figure_projection_v2' else decision['input_sha256'])
                    or wait['kind']!='figure_projection_confirmation' or wait['status']!='resolved' or wait['user_id']!=decision['approved_by']
                    or wait['task_revision']!=receipt.get('expected_task_revision') or wait['resolved_task_revision']!=(receipt.get('expected_task_revision',0)+1 if task['workflow_version']=='figure_projection_v2' or receipt.get('async_publication') is True else task['revision'])
                    or checkpoint['next_node']!='await_confirmation' or (checkpoint['state_json'].get('check',{}).get('input_sha256') if task['workflow_version']=='figure_projection_v2' else checkpoint['state_json'].get('input_sha256'))!=decision['input_sha256']):raise source_conflict()
                if task['workflow_version']=='figure_projection_v1' and checkpoint['state_json'].get('check')!={k:v for k,v in p['result_json'].items() if k!='_material'}:raise source_conflict()
                if task['workflow_version']=='figure_projection_v2':
                    state=validate_projection_checkpoint(task,checkpoint)
                    if {k:v for k,v in p['result_json'].items() if k!='_material'}!=state['check']:raise source_conflict()
                    material=p['result_json'].get('_material')
                    if not material or material['sha256']!=digest({'payload':material['payload'],'expected':material['expected']}) or material['payload']!=state['payload'] or material['expected']!=state['expected']:raise source_conflict()
                return {'id':p['id'],'config_version_id':p['config_version_id'],'decision_id':p['decision_id'],'tool_version':p['tool_version'],'sha256':p['sha256'],'result':p['result_json']}
            if not own['parent_version_id']:return None
            parent=db.execute('SELECT * FROM figure_config_versions WHERE id=%s',(own['parent_version_id'],)).fetchone()
            if not parent or parent['configuration_id']!=row['configuration_id'] or semantic(parent['config_json'])!=semantic(row['config_json']) or parent['source_json']!=row['source_json']:return None
            if parent['sha256']!=digest({'config':parent['config_json'],'source':parent['source_json']}):raise source_conflict()
            own=parent
        raise source_conflict()
    def _entry(self,db,row):
        fig=db.execute('SELECT figure_json FROM figures WHERE figure_config_version_id=%s',(row['id'],)).fetchone()
        figure=json.loads(fig['figure_json']) if fig else None
        task=db.execute("SELECT * FROM tasks WHERE project_id=%s AND task_type='figure_workbench' AND input_snapshot->'figure_workbench'->>'version_id'=%s ORDER BY created_at DESC,id DESC LIMIT 1",(row['project_id'],row['id'])).fetchone()
        explanation=explanation_task=None
        if figure:
            from app.domain.figure_workbench.explanations import version_for
            exp=db.execute('SELECT explanation_json FROM explanations WHERE figure_id=%s ORDER BY (engine_version=%s) DESC,id DESC LIMIT 1',(figure['id'],version_for(figure))).fetchone()
            explanation=json.loads(exp['explanation_json']) if exp else None
            # State is a display surface too: validate the same frozen facts as downloads.
            verified=read_bundle(self.assets,row['project_id'],figure['id'],explanation['id'] if explanation else None)
            figure,explanation=verified['figure'],verified['explanation']
            et=db.execute("SELECT * FROM tasks WHERE project_id=%s AND task_type='figure_explanation' AND input_snapshot->'figure'->>'id'=%s ORDER BY created_at DESC,id DESC LIMIT 1",(row['project_id'],figure['id'])).fetchone()
            explanation_task=self.tasks.public_task(dict(et)) if et else None
        pending=self._pending(db,row)
        return {'projection_task':self.tasks.public_task(pending[0]) if pending else None,'projection_check':self._check_view(row,*pending) if pending else None,'id':row['configuration_id'],'revision':row['revision'],'version':self.public_version(row),'projection':self._projection(db,row),'figure':figure,'task':self.tasks.public_task(dict(task)) if task else None,'explanation':explanation,'explanation_task':explanation_task}
    def state(self,project_id,file_id,run_id):
        result,sheet=load_source(self.assets,project_id,file_id,run_id)
        from app.domain.artifact_contracts import figure_kind,artifact_language
        primary=figure_kind(result); primary='boxplot' if primary in ('group_boxplot','paired_connected') else primary
        with self.tasks.connection() as db:
            self.tasks.require_project(db,project_id)
            rows=db.execute('''SELECT v.*,c.project_id,c.analysis_run_id FROM figure_config_versions v JOIN figure_configurations c ON c.id=v.configuration_id
                WHERE c.project_id=%s AND c.analysis_run_id=%s ORDER BY c.created_at,v.revision DESC''',(project_id,run_id)).fetchall()
            entries=[self._entry(db,self._version(db,project_id,file_id,run_id,row['id'])) for row in rows]
        current=[]
        for e in entries:
            if not any(c['id']==e['id'] for c in current): current.append({**e,'versions':[v for v in entries if v['id']==e['id']]})
        return {'configurations':current,'available_kinds':[primary,'line','bar','violin'],'fields':fields_for(sheet),'language':artifact_language(result)}
    def save(self,project_id,file_id,run_id,request):
        result,_=load_source(self.assets,project_id,file_id,run_id);config=request.config.model_dump()
        from app.domain.artifact_contracts import artifact_language,figure_kind
        primary=figure_kind(result)
        if config['language']!=artifact_language(result) or config['figure_kind'] not in (primary,'line','bar','violin') and not (config['figure_kind']=='boxplot' and primary in ('group_boxplot','paired_connected')):raise StorageError('task_input_invalid','图型或语言与已确认结果不匹配。',422)
        provenance={'source':result['source'],'result_sha256':digest(result),'analysis_plan':result['analysis_plan'],'figure_contract':3}
        with self.tasks.connection(write=True) as db:
            self.tasks.require_project(db,project_id);now=datetime.now(timezone.utc);parent=None
            if request.configuration_id:
                c=db.execute('SELECT * FROM figure_configurations WHERE id=%s AND project_id=%s AND analysis_run_id=%s FOR UPDATE',(request.configuration_id,project_id,run_id)).fetchone()
                if not c or c['current_revision']!=request.expected_revision:raise StorageError('task_revision_conflict','图表配置已变化，请重新读取。',409)
                cid=c['id'];revision=c['current_revision']+1
                parent=db.execute('SELECT id FROM figure_config_versions WHERE configuration_id=%s AND revision=%s',(cid,c['current_revision'])).fetchone()['id']
                db.execute('UPDATE figure_configurations SET current_revision=%s WHERE id=%s',(revision,cid))
            else:
                cid=str(uuid4());revision=1
                db.execute('INSERT INTO figure_configurations(id,project_id,analysis_run_id,created_by,current_revision,created_at) VALUES (%s,%s,%s,%s,1,%s)',(cid,project_id,run_id,self.tasks.user_id,now))
            vid=str(uuid4());sha=digest({'config':config,'source':provenance})
            db.execute('''INSERT INTO figure_config_versions(id,configuration_id,revision,parent_version_id,created_by,created_at,sha256,config_json,source_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(vid,cid,revision,parent,self.tasks.user_id,now,sha,Jsonb(config),Jsonb(provenance)))
            return self._entry(db,self._version(db,project_id,file_id,run_id,vid))
    def _pending(self,db,row):
        task=db.execute("SELECT * FROM tasks WHERE project_id=%s AND task_type='figure_projection' AND idempotency_key=%s",(row['project_id'],row['id'])).fetchone()
        if not task:return None
        task=dict(task)
        if task['workflow_version'] not in ('figure_projection_v1','figure_projection_v2'):raise source_conflict()
        if task['workflow_version']=='figure_projection_v1' and task['status']=='succeeded':return None
        snapshot=task['input_snapshot']
        if (task['workflow_version']=='figure_projection_v2' and (task['input_digest']!=projection_request_digest(row) or snapshot['figure_workbench'].get('configuration_sha256')!=row['sha256'])
            or snapshot['source']!=row['source_json']['source'] or digest(snapshot['result'])!=row['source_json']['result_sha256']):raise source_conflict()
        checkpoint=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
        state=validate_projection_checkpoint(task,checkpoint)
        return task,state

    def _check_view(self,row,task,state):
        computed=state.get('check')
        from app.domain.figure_workbench.diagnostics import projection_diagnostics
        return {'version_id':row['id'],'input_sha256':computed['input_sha256'] if computed else None,
            'requires_confirmation':task['status']=='waiting_confirmation','status':task['status'],
            'check':{**computed['audit'],'method':computed['method'],'original_statistical_n':computed['original_statistical_n']} if computed else None,
            'diagnostics':projection_diagnostics(computed,row['config_json']['language']) if computed else [],'task':self.tasks.public_task(task)}

    def material(self,project_id,file_id,run_id,version_id):
        from app.domain.statistics_execution.verification import should_recompute
        result,sheet=load_source(self.assets,project_id,file_id,run_id)
        with self.tasks.connection() as db:
            row=self._version(db,project_id,file_id,run_id,version_id);projection=self._projection(db,row)
            old_figure=db.execute('SELECT figure_json FROM figures WHERE figure_config_version_id=%s',(version_id,)).fetchone()
            if old_figure is None and projection and projection['config_version_id']!=version_id:
                old_figure=db.execute('SELECT figure_json FROM figures WHERE figure_config_version_id=%s',(projection['config_version_id'],)).fetchone()
        if row['source_json']['result_sha256']!=digest(result) or row['source_json']['source']!=result['source']:raise source_conflict()
        if not should_recompute() and projection is None:raise StorageError('task_input_invalid','请先提交本地计算并独立确认。',409)
        frozen=projection['result'] if projection else None
        saved_expected=frozen.get('_material',{}).get('expected') if frozen else None
        if saved_expected is None and old_figure:saved_expected=json.loads(old_figure['figure_json'])
        bare={k:v for k,v in frozen.items() if k not in ('input_sha256','original_statistical_n','_material')} if frozen else None
        computed,payload,expected=calculate(self.assets,project_id,file_id,result,sheet,row['config_json'],
            frozen=bare if frozen and not should_recompute() else None,saved_expected=saved_expected,figure_contract=contract_version(row['source_json']))
        input_sha=digest({'source':row['source_json'],'semantic':semantic(row['config_json']),'computed':computed})
        computed={**computed,'input_sha256':input_sha,'original_statistical_n':result['check']['valid_count']}
        if projection:
            if not _same_projection_value({k:v for k,v in computed.items() if k!='input_sha256'},{k:v for k,v in frozen.items() if k not in ('_material','input_sha256')}):raise source_conflict()
            computed=deepcopy(frozen)
            if row['config_json']['figure_kind'] in ('line','bar','violin'):expected['statistics']['series']=deepcopy(frozen['series'])
        if contract_version(row['source_json'])>=2:
            payload,expected=enrich_material(payload,expected,config=row['config_json'],result=result,projection=computed,fields={f['column']:f for f in fields_for(sheet)},contract=contract_version(row['source_json']))
        return row,result,computed,payload,expected

    def check(self,project_id,file_id,run_id,version_id):
        result,_=load_source(self.assets,project_id,file_id,run_id)
        with self.tasks.connection(write=True) as db:
            row=self._version(db,project_id,file_id,run_id,version_id,lock=True)
            if row['source_json']['result_sha256']!=digest(result):raise source_conflict()
            projection=self._projection(db,row)
            if projection:
                value=projection['result']
                from app.domain.figure_workbench.diagnostics import projection_diagnostics
                return {'version_id':version_id,'input_sha256':value['input_sha256'],'requires_confirmation':False,'status':'succeeded',
                    'check':{**value['audit'],'method':value['method'],'original_statistical_n':value['original_statistical_n']},
                    'diagnostics':projection_diagnostics(value,row['config_json']['language']),'task':None}
            pending=self._pending(db,row)
            if pending:return self._check_view(row,*pending)
            old=db.execute("SELECT * FROM tasks WHERE project_id=%s AND task_type='figure_projection' AND idempotency_key=%s",(project_id,version_id)).fetchone()
            if old:raise StorageError('task_transition_invalid','请在任务中心完成已有投影确认。',409)
            now=datetime.now(timezone.utc)
            task={'id':str(uuid4()),'project_id':project_id,'user_id':self.tasks.user_id,'task_type':'figure_projection','idempotency_key':version_id,
                'input_digest':projection_request_digest(row),'input_snapshot':{'schema_version':2,'projection_execution':2,'result':result,'source':result['source'],
                'output_language':row['config_json']['language'],'figure_workbench':{'version_id':version_id,'configuration_sha256':row['sha256']}},
                'workflow_version':'figure_projection_v2','status':'queued','phase':'compute','revision':1,'current_attempt':0,'reason_code':None,'created_at':now,'updated_at':now}
            self.tasks.insert_task(db,task)
            from app.domain.dataset_preparation.service import append_checkpoint
            state={'version_id':version_id,'request_sha256':task['input_digest'],'check':None,'payload':None,'expected':None,'material_sha256':None}
            append_checkpoint(db,task,'check','check',state);self.tasks.append_event(db,task,'created');self.tasks.enqueue(db,task)
            return self._check_view(row,task,state)

    def confirm(self,project_id,file_id,run_id,version_id,request):
        # Approval only binds the persisted worker candidate; publication independently verifies it.
        result,_=load_source(self.assets,project_id,file_id,run_id)
        with self.tasks.connection(write=True) as db:
            row=self._version(db,project_id,file_id,run_id,version_id,lock=True)
            previous=self._projection(db,row)
            if previous:
                if previous['result']['input_sha256']!=request.input_sha256:raise source_conflict()
                return previous
            pending=self._pending(db,row)
            if not pending:raise source_conflict()
            task,state=pending
            if task['status']=='queued' and state.get('decision_id'):
                if not state.get('check') or state['check']['input_sha256']!=request.input_sha256:raise source_conflict()
                return {'task':self.tasks.public_task(task)}
            if task['status']!='waiting_confirmation' or not state.get('check') or state['check']['input_sha256']!=request.input_sha256 or request.approved is not True:raise source_conflict()
            wait=db.execute("SELECT * FROM task_waits WHERE task_id=%s AND status='open'",(task['id'],)).fetchone()
            checkpoint=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
            if (not wait or wait['kind']!='figure_projection_confirmation' or wait['task_revision']!=task['revision'] or checkpoint['next_node']!='await_confirmation'
                or task['input_snapshot']['result']!=result):raise source_conflict()
            now=datetime.now(timezone.utc);did=str(uuid4())
            decision={'approved':True,'input_sha256':request.input_sha256,'checkpoint_id':checkpoint['id'],'wait_id':wait['id'],'expected_task_revision':task['revision'],**({'async_publication':True} if task['workflow_version']=='figure_projection_v1' else {})}
            db.execute('INSERT INTO figure_projection_decisions(id,config_version_id,task_id,approved_by,approved_at,input_sha256,decision_json) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                (did,version_id,task['id'],self.tasks.user_id,now,request.input_sha256,Jsonb(decision)))
            revision=task['revision'];task.update(status='queued',phase='compute',revision=revision+1,reason_code='confirmation_received',updated_at=now)
            from app.domain.dataset_preparation.service import append_checkpoint
            append_checkpoint(db,task,'approve','publish',{**state,'decision_id':did},dict(checkpoint))
            self.tasks.update_task(db,task,revision)
            from app.domain.tasks.waits import resolve_open_wait
            resolve_open_wait(db,task);self.tasks.append_event(db,task,'requeued');self.tasks.enqueue(db,task)
            return {'task':self.tasks.public_task(task)}
    def external_preview(self,project_id,file_id,run_id,version_id):
        row,result,computed,payload,expected=self.material(project_id,file_id,run_id,version_id)
        with self.tasks.connection() as db:projection=self._projection(db,row)
        if not projection or projection['result']!=computed:raise StorageError('task_input_invalid','请先核对并确认本地图表投影。',409)
        return {'payload_sha256':digest(payload),'payload':payload,'labels':payload['labels'],'requires_confirmation':True,'disclosure':{'provider':'openai','kind':row['config_json']['figure_kind'],'record_count':computed['audit']['valid_n'],'contains_sensitive_labels':True,'local_expected_values_sent':False}}


def read_bundle(store,project_id,figure_id,explanation_id=None):
    workbench=FigureWorkbenchStore(store)
    with workbench.tasks.connection() as db:
        workbench.tasks.require_project(db,project_id)
        row=db.execute('''SELECT f.*,a.file_id FROM figures f JOIN analysis_runs a ON a.id=f.analysis_run_id JOIN files x ON x.id=a.file_id WHERE f.id=%s AND x.project_id=%s''',(figure_id,project_id)).fetchone()
        if not row or not row['figure_config_version_id']:raise StorageError('figure_missing','请选择无内嵌固定旧图号的新版本。',409)
        figure=json.loads(row['figure_json']);version_id=row['figure_config_version_id']
    version,result,computed,payload,expected=workbench.material(project_id,row['file_id'],row['analysis_run_id'],version_id)
    with workbench.tasks.connection() as db:
        projection=workbench._projection(db,version)
        if (not projection or projection['result']!=computed or figure.get('id')!=figure_id or figure.get('figure_config_version_id')!=version_id or figure.get('configuration_sha256')!=version['sha256'] or figure.get('projection_id')!=projection['id'] or figure.get('projection_sha256')!=projection['sha256'] or figure.get('source')!=result['source'] or figure.get('analysis_run_id')!=result['id'] or figure.get('facts_sha256')!=digest(expected) or figure.get('numbering_mode')!='external'):raise source_conflict()
        if (figure.get('file_id')!=result['file_id'] or figure.get('source_sha256')!=result['source_sha256'] or figure.get('setup_revision')!=result['setup_revision'] or figure.get('engine',{}).get('id')!=renderer_for(version['source_json']) or row['renderer_version']!=figure['engine']['id'] or figure.get('verification',{}).get('status')!='matched' or figure.get('figure_number') is not None or figure.get('method')!=projection['result']['method']):raise source_conflict()
        for key,value in expected.items():
            if figure.get(key)!=value:raise source_conflict()
        explanation=None
        if explanation_id:
            e=db.execute('SELECT * FROM explanations WHERE id=%s AND figure_id=%s',(explanation_id,figure_id)).fetchone()
            if not e:raise source_conflict()
            explanation=json.loads(e['explanation_json'])
            if e['engine_version']!=explanation.get('engine',{}).get('id'):raise source_conflict()
            if explanation.get('figure_sha256')!=figure['sha256'] or explanation.get('figure_id')!=figure_id or explanation.get('facts_sha256')!=figure['facts_sha256'] or explanation.get('source')!=result['source'] or explanation.get('language')!=figure['language']:raise source_conflict()
    store.figure_png(figure)
    if explanation is not None:
        from app.domain.figure_workbench.explanations import validate_saved
        validate_saved({'result':result,'figure':figure,'configuration':workbench.public_version(version),'projection':projection},explanation)
    return {'result':result,'figure':figure,'explanation':explanation,'configuration':workbench.public_version(version),'projection':projection}


def projection_request_digest(row):
    return digest({'source':row['source_json'],'semantic':semantic(row['config_json'])})


def validate_projection_checkpoint(task,checkpoint):
    try:
        state=deepcopy(checkpoint['state_json'])
        if task['workflow_version']=='figure_projection_v1':
            if state['version_id']!=task['input_snapshot']['figure_workbench']['version_id'] or state.get('check',{}).get('input_sha256')!=task['input_digest']:raise ValueError()
            state.setdefault('request_sha256',task['input_digest']);state.setdefault('payload',None);state.setdefault('expected',None);state.setdefault('material_sha256',None)
            return state
        if state['version_id']!=task['input_snapshot']['figure_workbench']['version_id'] or state['request_sha256']!=task['input_digest']:raise ValueError()
        if state['check'] is not None:
            if (state['material_sha256']!=digest({'check':state['check'],'payload':state['payload'],'expected':state['expected']})
                or state['check']['original_statistical_n']!=task['input_snapshot']['result']['check']['valid_count']):raise ValueError()
        elif checkpoint['next_node']!='check':raise ValueError()
        return deepcopy(state)
    except (KeyError,TypeError,ValueError):raise source_conflict() from None
