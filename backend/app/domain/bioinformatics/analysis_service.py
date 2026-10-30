"""Unified queued spatial runs, explicit QC decisions and atomic publication."""
import json
import re
from datetime import datetime,timezone,timedelta
from uuid import UUID,uuid4,uuid5
from app.adapters.bio_analysis_store import BioAnalysisStore,base_row,identity,insert,lock,now,error,object_by_key,scoped_object
from app.adapters.task_store import TaskStore,DatasetTaskAssets
from app.domain.bioinformatics.analysis_contracts import input_version,validate_snapshot,ENGINE_VERSION
from app.domain.bioinformatics.analysis_settings import BioAnalysisLimits,runtime_identity
from app.domain.bioinformatics.contracts import canonical,digest,conflict
from app.domain.bioinformatics.service import require_key,append_checkpoint
from app.domain.tasks.waits import get_open_wait,resolve_open_wait


def latest_checkpoint(db,task):
    row=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
    if not row or row['state_json'].get('input_version')!=input_version(task):raise conflict('bio_input_integrity_changed')
    return dict(row)


def engine_member(record,path,*,role=None,format=None):
    """Only the scientific file contract crosses the JSON subprocess boundary."""
    value=dict(path=str(path),sha256=record['sha256'],size_bytes=record['size_bytes'],
        role=role if role is not None else record['role'],format=format if format is not None else record['format'])
    if (type(value['size_bytes']) is not int or value['size_bytes']<1
            or type(value['sha256']) is not str or not re.fullmatch(r'[a-f0-9]{64}',value['sha256'])
            or any(type(value[key]) is not str or not value[key] for key in ('role','format'))):
        raise conflict('bio_input_integrity_changed')
    for key in ('source_file_id','source_member_name','compression','verification_state'):
        if record.get(key) is not None:
            if type(record[key]) is not str:raise conflict('bio_input_integrity_changed')
            value[key]=record[key]
    return value


class BioAnalysisService(BioAnalysisStore):
    def require_sources(self,db,task,*,runtime=True):
        snapshot=validate_snapshot(task);project=task['project_id']
        self.store.require_project(db,project)
        if runtime:
            environment=runtime_identity()
            if not environment['available']:raise error('bio_environment_unavailable')
            if any(snapshot[k]!=environment[k] for k in ('engine_version','environment_digest','code_digest')):raise conflict('bio_input_integrity_changed')
        if task['task_type']=='bio_figure':
            figure=self.require(db,'bio_figure_versions',project,snapshot['figure_version_id'])
            row,manifest,members=self.processed_record(db,project,figure['processed_dataset_version_id'])
            if self.processed_source(row,manifest)!=snapshot['processed_source'] or figure['task_id']!=task['id'] or figure['config_json']!=snapshot['config']:raise conflict('bio_input_integrity_changed')
            raw_source=snapshot['processed_source']['raw_source']
        else:
            run=self.require(db,'bio_analysis_runs',project,snapshot['run_id'])
            recipe=self.require(db,'bio_analysis_recipe_versions',project,snapshot['recipe_version_id'])
            if run['task_id']!=task['id'] or run['source_digest']!=task['input_digest'] or recipe['params_json']!=snapshot['params'] or recipe['setup_id']!=snapshot['setup_id'] or recipe['observation_map_version_id']!=snapshot['observation_map_version_id'] or recipe['design_version_id']!=snapshot['design_version_id']:raise conflict('bio_input_integrity_changed')
            execution=scoped_object(db,project,self.store.user_id,run['execution_snapshot_object_id'])
            if execution['sha256']!=run['execution_snapshot_sha256'] or json.loads(self.objects.read(execution))!=snapshot:raise conflict('bio_input_integrity_changed')
            raw_source=snapshot['raw_source']
        raw,manifest,members=self.raw(db,project,raw_source)
        payload=dict(raw=dict(manifest=manifest,members={m['key']:engine_member(m,self.raw_store.objects.path(m['object_key'])) for m in members}),
            config=snapshot['params'] if task['task_type']=='bio_analysis' else snapshot['config'],
            identity=dict(raw_source=raw_source,recipe_version_id=snapshot.get('recipe_version_id') or snapshot['processed_source']['recipe_version_id'],
                environment_digest=snapshot['environment_digest'],code_digest=snapshot['code_digest']))
        if task['task_type']=='bio_analysis' and snapshot['observation_map_version_id']:
            mapping=self.require(db,'bio_observation_map_versions',project,snapshot['observation_map_version_id'])
            if mapping['raw_dataset_version_id']!=raw['id'] or mapping['design_version_id']!=snapshot['design_version_id']:raise conflict('bio_input_integrity_changed')
            item=scoped_object(db,project,self.store.user_id,mapping['mapping_object_id'])
            if item['sha256']!=mapping['mapping_sha256']:raise conflict('bio_input_integrity_changed')
            self.mapping_objects.read(item)
            payload['raw']['members']['observation_map_index']=engine_member(item,self.mapping_objects.path(item['object_key']),role='observation_map',format='json')
        if task['task_type']=='bio_figure':
            row,manifest,members=self.processed_record(db,project,snapshot['processed_source']['processed_dataset_version_id'])
            payload['processed']=dict(manifest=manifest,members={m['key']:engine_member(m,self.objects.path(m['object_key'])) for m in members})
            if snapshot['annotation_version_id']:
                from app.adapters.bio_objects import BioAnnotationObjects
                annotation=self.require(db,'bio_annotation_versions',project,snapshot['annotation_version_id'])
                if annotation['processed_dataset_version_id']!=row['id']:raise conflict('bio_input_integrity_changed')
                objects=BioAnnotationObjects(self.assets.directory);parts={}
                for kind in ('geometry','assignments'):
                    item=scoped_object(db,project,self.store.user_id,annotation[kind+'_object_id'])
                    if item['sha256']!=annotation[kind+'_sha256']:raise conflict('bio_input_integrity_changed')
                    objects.read(item);parts[kind]=engine_member(item,objects.path(item['object_key']),role=kind,format='json')
                payload['annotation']=dict(labels=annotation['labels_json'],members=parts)
        return payload

    def create(self,project,request,key):
        require_key(key);sha=digest(request.model_dump());identifier=identity(project,'run',key);task_id=identity(project,'analysis-task',key)
        with self.store.connection() as db:
            self.store.require_project(db,project)
            replay=db.execute('SELECT * FROM bio_analysis_runs WHERE project_id=%s AND request_key=%s',(project,key)).fetchone()
            if replay:
                if replay['request_digest']!=sha:raise error('task_idempotency_conflict')
                return dict(id=replay['id'],task=self.store.public_task(self.store.require_task(db,replay['task_id'])),recipe_version_id=replay['recipe_version_id'],expected_setup_revision=replay['expected_setup_revision'])
            recipe=self.require(db,'bio_analysis_recipe_versions',project,request.recipe_version_id)
            root=self.require(db,'bio_analysis_setups',project,recipe['setup_id'])
            if root['revision']!=request.expected_setup_revision or recipe['raw_dataset_version_id']!=request.raw_source.dataset_version_id:raise conflict('bio_revision_conflict')
            self.raw(db,project,request.raw_source)
        runtime=runtime_identity()
        if not runtime['available']:raise error('bio_environment_unavailable')
        snapshot=dict(schema_version=1,kind='bio_analysis',workflow_version='bio_analysis_v1',project_id=project,run_id=identifier,
            setup_id=recipe['setup_id'],recipe_version_id=recipe['id'],expected_setup_revision=request.expected_setup_revision,
            raw_source=request.raw_source.model_dump(),params=recipe['params_json'],observation_map_version_id=recipe['observation_map_version_id'],design_version_id=recipe['design_version_id'],
            engine_version=runtime['engine_version'],environment_digest=runtime['environment_digest'],code_digest=runtime['code_digest'],
            output_language=recipe['params_json']['output_language'],limits=BioAnalysisLimits().model_dump())
        records,reservations=self.admit_documents(project,identifier,'bio_analysis',self.objects,{'snapshot':canonical(snapshot)})
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project);lock(db,project,'run:'+key)
            replay=db.execute('SELECT * FROM bio_analysis_runs WHERE project_id=%s AND request_key=%s',(project,key)).fetchone()
            if replay:
                if replay['request_digest']!=sha:raise error('task_idempotency_conflict')
                return dict(id=replay['id'],task=self.store.public_task(self.store.require_task(db,replay['task_id'])),recipe_version_id=replay['recipe_version_id'],expected_setup_revision=replay['expected_setup_revision'])
            db.execute('SELECT id FROM bio_analysis_setups WHERE id=%s FOR UPDATE',(recipe['setup_id'],))
            root=self.require(db,'bio_analysis_setups',project,recipe['setup_id'])
            if root['revision']!=request.expected_setup_revision:raise conflict('bio_revision_conflict')
            self.raw(db,project,request.raw_source)
            objects=self.settle_documents(db,project,records,reservations);moment=now()
            task=dict(id=task_id,project_id=project,user_id=self.store.user_id,task_type='bio_analysis',idempotency_key='bio_analysis:'+task_id,
                input_digest=digest(snapshot),input_snapshot=snapshot,workflow_version='bio_analysis_v1',status='queued',phase='parse',revision=1,current_attempt=0,
                reason_code=None,created_at=moment,updated_at=moment)
            self.store.insert_task(db,task,validated_file_ids=request.raw_source.source_file_ids)
            insert(db,'bio_analysis_runs',{**base_row(identifier,project,self.store.user_id),'raw_dataset_version_id':request.raw_source.dataset_version_id,
                'recipe_version_id':recipe['id'],'task_id':task_id,'source_digest':task['input_digest'],'execution_snapshot_object_id':objects['snapshot']['id'],
                'execution_snapshot_sha256':records['snapshot']['sha256'],'expected_setup_revision':request.expected_setup_revision,
                'processed_dataset_version_id':None,'request_key':key,'request_digest':sha})
            append_checkpoint(db,task,'check','check',dict(input_version=input_version(task),stage='qc',candidate=None,decision_id=None,result_id=None))
            self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            return dict(id=identifier,task=self.store.public_task(task),recipe_version_id=recipe['id'],expected_setup_revision=request.expected_setup_revision)

    def read_candidate(self,task,checkpoint):
        reference=checkpoint['state_json'].get('candidate')
        if not reference:return None
        value=self.objects.read_json(reference)
        if value['input_sha256']!=task['input_digest'] or value['run_id']!=task['input_snapshot']['run_id']:raise conflict('bio_input_integrity_changed')
        for member in value['members']:self.objects.read(member)
        return value

    def get(self,project,run_id):
        with self.store.connection() as db:
            run=self.require(db,'bio_analysis_runs',project,run_id);task=self.store.require_task(db,run['task_id']);cp=latest_checkpoint(db,task)
            candidate=self.read_candidate(task,cp);wait=get_open_wait(db,task);public=None
            if candidate:
                public={k:candidate.get(k) for k in ('summary','checks','effective_params')};public['sha256']=cp['state_json']['candidate']['sha256']
                public['members']=[{**{k:m[k] for k in ('id','key','role','format','sha256','size_bytes')},'filename':m['key']+'.'+m['format'],
                    'download_url':f'/api/v1/projects/{project}/bio-analysis-runs/{run_id}/qc-members/{m["id"]}/download'} for m in candidate['members']]
            result=None
            if run['processed_dataset_version_id']:
                row,manifest,_=self.processed_record(db,project,run['processed_dataset_version_id']);result=self.processed_source(row,manifest)
            return dict(id=run_id,task=self.store.public_task(task),recipe_version_id=run['recipe_version_id'],expected_setup_revision=run['expected_setup_revision'],
                raw_source=task['input_snapshot']['raw_source'],checkpoint_id=cp['id'],wait_id=wait['id'] if wait else None,candidate=public,result_source=result)

    def list_runs(self,project,page=1,page_size=50):
        with self.store.connection() as db:
            self.store.require_project(db,project);total=db.execute('SELECT count(*) AS n FROM bio_analysis_runs WHERE project_id=%s',(project,)).fetchone()['n']
            rows=db.execute('SELECT id FROM bio_analysis_runs WHERE project_id=%s ORDER BY created_at DESC,id LIMIT %s OFFSET %s',(project,page_size,(page-1)*page_size)).fetchall()
        return dict(items=[self.get(project,r['id']) for r in rows],total=total,page=page,page_size=page_size)

    def qc_member(self,project,run_id,member_id):
        with self.store.connection() as db:
            run=self.require(db,'bio_analysis_runs',project,run_id);task=self.store.require_task(db,run['task_id'])
            self.require_sources(db,task,runtime=False);candidate=self.read_candidate(task,latest_checkpoint(db,task))
            member=next((m for m in (candidate or {}).get('members',[]) if m['id']==member_id),None)
            if not member:raise error('bio_member_not_found',404)
            object_by_key(db,project,self.store.user_id,member)
            return {**member,'filename':member['key']+'.'+member['format']},self.objects.read(member)

    def confirm(self,project,run_id,request,key):
        require_key(key)
        # Expiration is a durable terminal transition, independent of the rejected POST.
        with self.store.connection(write=True) as db:
            run=self.require(db,'bio_analysis_runs',project,run_id)
            expire_stale_confirmations(db,task_id=run['task_id'])
        with self.store.connection(write=True) as db:
            run=self.require(db,'bio_analysis_runs',project,run_id);task=self.store.require_task(db,run['task_id']);cp=latest_checkpoint(db,task);state=dict(cp['state_json'])
            decision=state.get('decision')
            if decision and decision['request_key']==key:
                if decision['request_digest']!=digest(request.model_dump()):raise error('task_idempotency_conflict')
                return self.store.public_task(task)
            wait=get_open_wait(db,task);root=self.require(db,'bio_analysis_setups',project,task['input_snapshot']['setup_id'])
            if (task['status']!='waiting_confirmation' or task['revision']!=request.task_revision or cp['id']!=request.checkpoint_id
                or cp['next_node']!='await_confirmation' or not wait or wait['id']!=request.wait_id or wait['input_version']!=input_version(task)
                or wait['task_revision']!=task['revision'] or root['revision']!=request.expected_setup_revision
                or run['expected_setup_revision']!=request.expected_setup_revision or not state.get('candidate')
                or state['candidate']['sha256']!=request.candidate_sha256):raise error('bio_confirmation_stale')
            created=datetime.fromisoformat(wait['created_at'].replace('Z','+00:00')) if isinstance(wait['created_at'],str) else wait['created_at']
            if now()-created>timedelta(hours=24):raise error('bio_confirmation_stale')
            self.require_sources(db,task);self.read_candidate(task,cp)
            previous=task['revision'];task.update(status='queued',phase='compute',revision=previous+1,updated_at=now(),reason_code='confirmation_received',error_code=None)
            decision_id=str(uuid4());state.update(stage='compute',decision_id=decision_id,decision=dict(id=decision_id,user_id=self.store.user_id,
                request_key=key,request_digest=digest(request.model_dump()),request=request.model_dump(),reviewed_checkpoint_id=cp['id']))
            append_checkpoint(db,task,'check','check',state,cp);self.store.update_task(db,task,previous);resolve_open_wait(db,task)
            self.store.append_event(db,task,'requeued');self.store.enqueue(db,task);return self.store.public_task(task)

    def publish(self,db,task,checkpoint,moment,prepared,*,progress=None):
        self.require_sources(db,task);snapshot=validate_snapshot(task)
        if progress is not None:progress()
        if checkpoint['next_node']!='publish' or prepared['input_sha256']!=task['input_digest']:raise conflict('bio_input_integrity_changed')
        if task['task_type']=='bio_figure':
            from app.adapters.bio_figure_store import BioFigureStore
            return BioFigureStore(self.assets).publish(db,task,checkpoint,moment,prepared,progress=progress)
        state=checkpoint['state_json'];decision=state.get('decision')
        if not decision or decision['id']!=state.get('decision_id') or decision['user_id']!=task['user_id']:raise error('bio_confirmation_stale')
        reviewed=db.execute('SELECT * FROM task_checkpoints WHERE id=%s AND task_id=%s',(decision['reviewed_checkpoint_id'],task['id'])).fetchone()
        wait=db.execute('SELECT * FROM task_waits WHERE id=%s AND task_id=%s',(decision['request']['wait_id'],task['id'])).fetchone()
        if not reviewed or reviewed['next_node']!='await_confirmation' or reviewed['state_json']['candidate']!=state['candidate'] or not wait or wait['status']!='resolved' or wait['input_version']!=input_version(task) or digest(decision['request'])!=decision['request_digest']:raise error('bio_confirmation_stale')
        root=self.require(db,'bio_analysis_setups',task['project_id'],snapshot['setup_id'])
        if root['revision']!=snapshot['expected_setup_revision']:raise conflict('bio_revision_conflict')
        version_id=str(uuid5(UUID(snapshot['run_id']),'processed-version'));manifest=prepared['manifest'];manifest_ref=prepared['manifest_ref']
        stored=object_by_key(db,task['project_id'],task['user_id'],manifest_ref)
        insert(db,'bio_processed_dataset_versions',{**base_row(version_id,task['project_id'],task['user_id']),'run_id':snapshot['run_id'],'task_id':task['id'],
            'raw_dataset_version_id':snapshot['raw_source']['dataset_version_id'],'recipe_version_id':snapshot['recipe_version_id'],
            'manifest_object_id':stored['id'],'manifest_sha256':manifest_ref['sha256'],'shape_json':prepared['summary'],
            'steps_json':prepared['steps'],'environment_digest':snapshot['environment_digest'],'code_digest':snapshot['code_digest'],'engine_version':snapshot['engine_version']})
        for member in prepared['members']:
            if progress is not None:progress()
            stored=object_by_key(db,task['project_id'],task['user_id'],member)
            insert(db,'bio_analysis_artifacts',{**base_row(member['id'],task['project_id'],task['user_id']),'processed_dataset_version_id':version_id,
                **{k:member[k] for k in ('key','role','format','sha256','size_bytes')},'storage_object_id':stored['id'],'shape_json':{}})
        from app.adapters.bio_figure_store import BioFigureStore
        BioFigureStore(self.assets).publish_defaults(db,task,version_id,prepared,progress=progress)
        db.execute('UPDATE bio_analysis_runs SET processed_dataset_version_id=%s WHERE id=%s AND processed_dataset_version_id IS NULL',(version_id,snapshot['run_id']))
        if progress is not None:progress()
        return finish(db,task,checkpoint,moment,'result_bio_processed_dataset_version_id',version_id)


def finish(db,task,checkpoint,moment,column,identifier):
    previous=task['revision'];task.update(status='succeeded',phase='verify',revision=previous+1,updated_at=moment,reason_code=None,error_code=None)
    task[column]=identifier
    append_checkpoint(db,task,'done','done',{**checkpoint['state_json'],'result_id':identifier},checkpoint)
    TaskStore.finish_attempt(db,task);TaskStore.update_task(db,task,previous);TaskStore.append_event(db,task,'succeeded')
    return TaskStore.public_task(task)


def service_for(db,task,store=None):
    from app.core.config import get_data_dir
    return BioAnalysisService(DatasetTaskAssets(task['user_id'],store.config if store else db.config,get_data_dir()))

def source_current(db,task):
    try:service_for(db,task).require_sources(db,task,runtime=False);return True
    except Exception:return False

def recovery_actions(db,task):
    try:
        service=service_for(db,task);service.require_sources(db,task,runtime=False);cp=latest_checkpoint(db,task)
        if task['status']=='waiting_confirmation':
            wait=get_open_wait(db,task)
            root=service.require(db,'bio_analysis_setups',task['project_id'],task['input_snapshot']['setup_id'])
            return ['approve'] if wait and not confirmation_expired(wait) and root['revision']==task['input_snapshot']['expected_setup_revision'] and wait['task_revision']==task['revision'] and cp['next_node']=='await_confirmation' and service.read_candidate(task,cp) else []
        if task['status']=='failed' and task.get('error_code') in {'storage_unavailable','task_worker_interrupted','storage_quota_exceeded','storage_disk_insufficient','storage_accounting_unknown','bio_environment_unavailable'}:return ['retry']
    except Exception:pass
    return []


def confirmation_expired(wait,moment=None):
    created=wait['created_at']
    if isinstance(created,str):created=datetime.fromisoformat(created.replace('Z','+00:00'))
    return (moment or now())-created>timedelta(hours=24)


def expire_stale_confirmations(db,now=None,limit=20,*,task_id=None):
    """Close bounded expired QC waits in the caller's transaction; retain all evidence."""
    if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Invalid expiry limit')
    moment=now or datetime.now(timezone.utc)
    params=[moment-timedelta(hours=24)]
    scope=''
    if task_id is not None:scope=' AND t.id=%s';params.append(task_id)
    params.append(limit)
    rows=db.execute("""SELECT t.* FROM tasks t JOIN task_waits w ON w.task_id=t.id
        WHERE t.task_type='bio_analysis' AND t.status='waiting_confirmation' AND w.status='open'
        AND w.kind='bio_analysis_confirmation' AND w.created_at<%s"""+scope+
        ' ORDER BY w.created_at LIMIT %s FOR UPDATE OF t SKIP LOCKED',tuple(params)).fetchall()
    for row in rows:
        task=dict(row);cp=latest_checkpoint(db,task);previous=task['revision']
        task.update(status='failed',revision=previous+1,updated_at=max(moment,task['updated_at']),
            reason_code=None,error_code='bio_confirmation_stale')
        append_checkpoint(db,task,'done','done',{**cp['state_json'],'expired_at':moment.isoformat(),'terminal_reason':'bio_confirmation_stale'},cp)
        TaskStore.update_task(db,task,previous);resolve_open_wait(db,task,status='superseded');TaskStore.append_event(db,task,'failed')
    return len(rows)

def retry_in_transaction(store,db,task,expected_revision):
    if task['status']!='failed' or task['revision']!=expected_revision or 'retry' not in recovery_actions(db,task):raise error('bio_confirmation_stale')
    service_for(db,task,store).require_sources(db,task)
    previous=task['revision'];task.update(status='queued',revision=previous+1,updated_at=now(),reason_code='retry_requested',error_code=None)
    TaskStore.update_task(db,task,previous);task['_retry_reason']='manual_retry';TaskStore.append_event(db,task,'requeued');TaskStore.enqueue(db,task)
    return TaskStore.public_task(task)

def task_artifacts(db,task):
    snapshot=validate_snapshot(task)
    if task['task_type']=='bio_figure':return {'bioinformatics':dict(figure_version_id=snapshot['figure_version_id'],processed_source=snapshot['processed_source'])}
    source=None
    if task.get('result_bio_processed_dataset_version_id'):
        service=service_for(db,task);row,manifest,_=service.processed_record(db,task['project_id'],task['result_bio_processed_dataset_version_id']);source=service.processed_source(row,manifest)
    return {'bioinformatics':dict(run_id=snapshot['run_id'],recipe_version_id=snapshot['recipe_version_id'],raw_source=snapshot['raw_source'],result_source=source)}
