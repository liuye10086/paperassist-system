"""Owner-scoped metadata preview, frozen recommendation tasks and provenance."""
from datetime import datetime, timezone
from uuid import uuid4
import unicodedata
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore, DatasetTaskAssets, source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_analysis import load_dataset, scan_dataset
from app.domain.dataset_preparation.service import request_digest, require_key, append_checkpoint
from app.domain.analysis_recommendation.contracts import parse_request, request_version, draft_model, validate_draft, call_key, COMPARISON_METHODS, MODELING_METHODS,alias_in_summary


def input_version(task):
    snapshot=validate_snapshot(task)
    return dict(kind='analysis_recommendation',source=snapshot['source'],workflow_version=request_version(snapshot['request']))


def validate_snapshot(task):
    try:
        value=task['input_snapshot']; request=parse_request(value['request'],create=True).model_dump(mode='json')
        if (task['task_type']!='analysis_recommendation' or task['workflow_version']!=request_version(request)
                or task['input_digest']!=request_digest(dict(file_id=value['source']['file_id'],**request))
                or type(value['schema_version']) is not int or value['schema_version']!=request.get('schema_version',1) or value['project_id']!=task['project_id']
                or value['source']['dataset_id']!=request['dataset_id'] or value['source']['sheet_name']!=request['sheet_name']
                or value['external_processing']['confirmed_by']!=task['user_id']):
            raise ValueError('Recommendation identity mismatch')
        return value
    except (KeyError,TypeError,ValueError) as exc: raise source_conflict() from exc


def last_call(db, task_id):
    return db.execute('SELECT * FROM model_calls WHERE task_id=%s ORDER BY created_at DESC,id DESC LIMIT 1',(task_id,)).fetchone()


class RecommendationService:
    def __init__(self, assets):
        self.assets=assets; self.store=TaskStore(assets.owner_id,assets.db_config)

    def preview(self,project,file,request):
        request=parse_request(request)
        record,source,sheet=load_dataset(self.assets,project,file,request.dataset_id)
        if source['kind']!='prepared_dataset_version' or source['sheet_name']!=request.sheet_name:
            raise StorageError('task_input_invalid','请选择冻结整理版本及其工作表。',422)
        profile,_=scan_dataset(sheet)
        lookup={c.id:c for c in profile.columns}
        if any(c not in lookup for c in request.candidate_columns):
            raise StorageError('invalid_column','候选字段不存在。',422)
        fields=[dict(column=c,name=lookup[c].name,type=lookup[c].type,unit=lookup[c].unit.model_dump(),
            missing_count=lookup[c].missing_count,non_missing_count=lookup[c].non_missing_count) for c in request.candidate_columns]
        digest=request_digest(dict(user_id=self.store.user_id,source=source,request=request.model_dump(),fields=fields))
        version=request.model_dump().get('schema_version',1)
        modern=version in (2,3,4,5)
        result=dict(version=version,provider='openai',source=source,source_digest=digest,fields=fields,
            labels=[dict(key='field:'+f['column'],value=f['name']) for f in fields]+[dict(key='research_summary',value=request.research_summary)],
            allowed_methods=['descriptive','pearson','spearman']+(COMPARISON_METHODS if modern else [])+(MODELING_METHODS if version in (3,4,5) else []),
            **(dict(allowed_modes=['pair','matrix','independent','paired','multiple']+(['regression','roc','survival'] if version in (3,4,5) else [])) if modern else {}),
            output_language=request.output_language,research_summary=request.research_summary)
        if version==5:
            result['source_mapping']=local_source_mapping(record['filename'],source)
            result['source_digest']=request_digest(dict(user_id=self.store.user_id,source=source,request=request.model_dump(),fields=fields,source_mapping=result['source_mapping']))
        return result

    def material(self,project,file,request):
        request=parse_request(request,create=True)
        raw=request.model_dump(mode='json');preview=self.preview(project,file,{k:v for k,v in raw.items() if k!='external_processing'})
        confirm=request.external_processing
        if (set(confirm)!={'version','confirmed','source_digest','labels'} or type(confirm['version']) is not int
                or confirm['version']!=1 or confirm['confirmed'] is not True or not isinstance(confirm['labels'],dict)):
            raise StorageError('task_input_invalid','请单独确认规划外发材料。',422)
        if confirm['source_digest']!=preview['source_digest']: raise source_conflict()
        expected={i['key'] for i in preview['labels']}
        if set(confirm['labels'])!=expected: raise StorageError('task_input_invalid','确认字段与预览不一致。',422)
        labels={}
        for key,value in confirm['labels'].items():
            summary=key=='research_summary'
            if (not isinstance(value,str) or len(value)>(4000 if summary else 160)
                    or not summary and not value.strip()
                    or any(unicodedata.category(c) in ('Cc','Cf','Cs') and not(summary and c in '\n\t') for c in value)):
                raise StorageError('task_input_invalid','外发摘要或字段名称无效。',422)
            labels[key]=value if summary else value.strip()
        payload=dict(schema_version=raw.get('schema_version',1),output_language=request.output_language,research_summary=labels['research_summary'],
            allowed_methods=preview['allowed_methods'],**(dict(allowed_modes=preview['allowed_modes']) if 'allowed_modes' in preview else {}),
            fields=[{**f,'name':labels['field:'+f['column']]} for f in preview['fields']])
        if raw.get('schema_version')==5:
            payload['source_aliases']=[dict(code=x['code'],level=x['level']) for x in preview['source_mapping'] if alias_in_summary(x['code'],labels['research_summary'])]
        external=dict(version=1,provider='openai',task_type='analysis_recommendation',source_digest=preview['source_digest'],
            labels=labels,confirmed_by=self.store.user_id,confirmed_at=datetime.now(timezone.utc).isoformat(),confirmation_digest=request_digest(confirm))
        return preview,payload,external

    def create(self,project,file,request,key):
        require_key(key);request=parse_request(request,create=True);raw=request.model_dump(mode='json')
        digest=request_digest(dict(file_id=file,**raw))
        with self.store.connection() as db:
            self.store.require_project(db,project);existing=self.store.find_request(db,project,'analysis_recommendation',key)
            if existing:
                if existing['input_digest']!=digest: raise StorageError('task_idempotency_conflict','请求标识已用于其他资料。',409)
                return self.store.public_task(existing),200
        preview,payload,external=self.material(project,file,request)
        from app.domain.analysis_recommendation.policy import get_execution_policy
        try: policy=get_execution_policy(payload)
        except StorageError as exc:
            if exc.code not in ('recommendation_not_configured','explanation_not_configured'): raise
            policy=None
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project);existing=self.store.find_request(db,project,'analysis_recommendation',key)
            if existing:
                if existing['input_digest']!=digest: raise StorageError('task_idempotency_conflict','请求标识已用于其他资料。',409)
                return self.store.public_task(existing),200
            record,_,_=load_dataset(self.assets,project,file,request.dataset_id,expected_source=preview['source'])
            now=datetime.now(timezone.utc)
            snapshot=dict(schema_version=raw.get('schema_version',1),project_id=project,filename=record['filename'],source=preview['source'],
                request=raw,payload=payload,external_processing=external,recommendation_policy=policy,require_explanation=True)
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='analysis_recommendation',
                idempotency_key=key,input_digest=digest,input_snapshot=snapshot,workflow_version=request_version(raw),status='queued',
                phase='plan',revision=1,current_attempt=0,reason_code=None,created_at=now,updated_at=now)
            self.store.insert_task(db,task)
            db.execute("""INSERT INTO model_budgets (id,user_id,scope_type,scope_key,project_id,task_id,
                limit_micro_usd,revision,created_at,updated_at) VALUES (%s,%s,'task',%s,%s,%s,500000,1,%s,%s)""",
                (str(uuid4()),task['user_id'],task['id'],project,task['id'],now,now))
            append_checkpoint(db,task,'check','check',dict(input_version=input_version(task),recommendation=None))
            self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            return self.store.public_task(task),202

    def require_material(self,task):
        snapshot=validate_snapshot(task)
        preview,payload,external=self.material(task['project_id'],snapshot['source']['file_id'],snapshot['request'])
        frozen=snapshot['external_processing']
        if (snapshot['source']!=preview['source'] or payload!=snapshot['payload']
                or any(frozen[k]!=external[k] for k in external if k!='confirmed_at')):
            raise source_conflict()
        return snapshot

    def get(self,task_id):
        with self.store.connection() as db:
            task=self.store.require_task(db,task_id);snapshot=self.require_material(task)
            row=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task_id,)).fetchone()
            result=row['state_json'].get('recommendation') if row else None
            if result:
                from app.domain.analysis_recommendation.policy import instructions_for
                from app.domain.model_usage.gateway import input_digest
                try:
                    fields=set(draft_model(snapshot['request']).model_fields)
                    if type(result) is not dict or set(result)!=fields|{'sha256','task_id','model_call_id'}:
                        raise ValueError('Saved recommendation fields differ from its contract.')
                    draft={k:result[k] for k in fields}
                    validate_draft(draft,{**snapshot['request'],'research_summary':snapshot['payload']['research_summary']},require_explanation=snapshot.get('require_explanation',False))
                except (KeyError,TypeError,ValueError) as exc:
                    raise source_conflict() from exc
                material={k:v for k,v in result.items() if k!='sha256'}
                call=last_call(db,task_id)
                if (task['status']!='succeeded' or row['node']!='done' or result['sha256']!=request_digest(material)
                        or not call or call['provider_status']!='completed'
                        or call['call_key']!=call_key(snapshot['request'])
                        or call['input_digest']!=input_digest(instructions=instructions_for(snapshot['payload']),payload=snapshot['payload'])
                        or result['task_id']!=task_id or result['model_call_id']!=call['id'] or not call['provider_response_id']):
                    raise source_conflict()
        return dict(task=self.store.public_task(task),source=snapshot['source'],input_version=input_version(task),
            recommendation=result,request={k:v for k,v in snapshot['request'].items() if k!='external_processing'},
            external_processing=snapshot['external_processing'])


def validate_reference(assets,project,source,request):
    ref=request.recommendation_ref
    view=RecommendationService(assets).get(ref.task_id)
    result=view['recommendation']
    if request.selection.task_type in ('regression','roc','survival'):
        from importlib import import_module
        columns=import_module('app.domain.'+request.selection.task_type+'.contracts').selected_columns(request.selection)
    elif request.selection.task_type=='group_comparison':
        from app.domain.comparison.contracts import selected_columns
        columns=selected_columns(request.selection)
    else:columns=request.selection.columns if request.selection.task_type=='correlation' else [request.selection.numeric_column]+([request.selection.group_column] if request.selection.group_column else [])
    if (not result or result['sha256']!=ref.sha256 or view['source']!=source or view['task']['project_id']!=project
            or not set(columns).issubset(view['request']['candidate_columns'])):
        raise source_conflict()


def retry_in_transaction(store,db,task,expected_revision):
    from app.domain.tasks.waits import allowed_recovery_actions,resolve_open_wait
    if task['revision']!=expected_revision: raise StorageError('task_revision_conflict','任务已更新。',409)
    if not allowed_recovery_actions(db,task): raise StorageError('task_transition_invalid','规划任务不能安全恢复。',409)
    service=RecommendationService(DatasetTaskAssets(store.user_id,store.config));snapshot=service.require_material(task)
    if snapshot.get('recommendation_policy') is None:
        from app.domain.analysis_recommendation.policy import get_execution_policy
        snapshot={**snapshot,'recommendation_policy':get_execution_policy(snapshot['payload'])}
        db.execute('UPDATE tasks SET input_snapshot=%s WHERE id=%s',(Jsonb(snapshot),task['id']))
        task['input_snapshot']=snapshot
    task.update(status='queued',revision=expected_revision+1,reason_code='confirmation_received' if task['status']=='waiting_confirmation' else 'retry_requested',
        updated_at=max(datetime.now(timezone.utc),task['updated_at']),error_code=None,retry_count=0)
    store.update_task(db,task,expected_revision);resolve_open_wait(db,task);store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)


def local_source_mapping(filename,source):
    if source is None:return []
    return [dict(code='F1',level='file',name=filename),dict(code='S1',level='sheet',name=source['sheet_name']),
            dict(code='D1',level='dataset',name='v'+str(source['dataset_version']))]
