"""Owner-scoped frozen imports and explicit, replay-safe candidate publication."""
from datetime import datetime, timezone
from uuid import UUID, uuid4, uuid5
import re
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore
from app.adapters.bio_objects import BioObjects
from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import (PARSER_VERSION, WORKFLOW_VERSION, BioDatasetSourceV1,
    canonical, digest, conflict, validate_snapshot, input_version, member_filename)
from app.domain.bioinformatics.contracts import BioImportRequestV2, PARSER_VERSION_V2, WORKFLOW_VERSION_V2, validate_v2_representation
from app.domain.bioinformatics.settings import BioLimits
from app.domain.tasks.waits import get_open_wait, resolve_open_wait


def latest_checkpoint(db, task):
    row = db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1', (task['id'],)).fetchone()
    if not row or row['state_json'].get('input_version') != input_version(task):
        raise conflict()
    return dict(row)


def append_checkpoint(db, task, node, next_node, state, previous=None):
    row = dict(id=str(uuid4()), task_id=task['id'], seq=previous['seq']+1 if previous else 1,
               node=node, next_node=next_node, state_json=state, created_at=task['updated_at'])
    db.execute('''INSERT INTO task_checkpoints(id,task_id,seq,node,next_node,state_json,created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''', (row['id'],task['id'],row['seq'],node,next_node,Jsonb(state),row['created_at']))
    return row


def require_key(key):
    if not isinstance(key, str) or not re.fullmatch(r'[\x21-\x7e]{1,128}', key):
        raise StorageError('task_input_invalid', '缺少有效请求标识。', 422)


class BioDatasetService:
    def __init__(self, assets):
        self.assets = assets
        self.store = TaskStore(assets.owner_id, assets.db_config)
        self.objects = BioObjects(assets.directory)

    def require_import(self, db, project_id, import_id):
        self.store.require_project(db, project_id)
        row = db.execute('SELECT * FROM bio_imports WHERE id=%s AND project_id=%s', (import_id,project_id)).fetchone()
        if not row:
            raise StorageError('bio_import_not_found','导入记录不存在。',404)
        return dict(row)

    def require_sources(self, db, task, *, progress=None):
        snapshot = validate_snapshot(task)
        self.store.require_project(db, task['project_id'])
        row = self.require_import(db, task['project_id'], snapshot['import_id'])
        if (row['task_id'] != task['id'] or row['input_sha256'] != task['input_digest']
                or row['parser_version'] != snapshot['parser_version'] or row['dataset_id'] != snapshot['dataset_id']
                or row['expected_dataset_revision'] != snapshot['expected_dataset_revision']
                or row['settings_json'] != snapshot['settings']):
            raise conflict()
        refs = db.execute('SELECT * FROM bio_import_files WHERE import_id=%s ORDER BY file_id', (row['id'],)).fetchall()
        expected = {f['id']:f for f in snapshot['files']}
        if {r['file_id'] for r in refs} != set(expected):
            raise conflict()
        result=[]
        for ref in refs:
            if progress is not None:progress()
            frozen = expected[ref['file_id']]
            file = db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s', (ref['file_id'],task['project_id'])).fetchone()
            if (not file or any(file[k] != frozen[k] for k in ('id','filename','sha256','size_bytes','object_key','storage_backend'))
                    or file['file_type'] not in ('bio_bundle','bio_component') or file['parse_status'] != 'stored'
                    or ref['source_sha256'] != frozen['sha256'] or ref['source_size_bytes'] != frozen['size_bytes']
                    or ref['declared_role'] != frozen['role']):
                raise conflict()
            # The original adapter checks the private path and every byte hash.
            self.assets.original(dict(file))
            if progress is not None:progress()
            result.append({**frozen, 'path':str(self.assets.directory / frozen['object_key'])})
        return sorted(result,key=lambda f: snapshot['files'].index(expected[f['id']]))

    @staticmethod
    def require_v2_source_root(db, task, candidate):
        """Serialize v2 publication identities without changing legacy imports."""
        snapshot=task['input_snapshot']
        if snapshot['workflow_version']!=WORKFLOW_VERSION_V2:return
        gsm=candidate.get('checks',{}).get('source_accessions',{}).get('gsm')
        if not isinstance(gsm,str) or not re.fullmatch(r'GSM[0-9]+',gsm):return
        db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(task['project_id'],))
        duplicate=db.execute("""SELECT id FROM bio_dataset_versions WHERE project_id=%s AND dataset_id<>%s
            AND checks_json #>> '{source_accessions,gsm}'=%s LIMIT 1""",
            (task['project_id'],snapshot['dataset_id'],gsm)).fetchone()
        if duplicate:raise conflict('bio_source_conflict')

    def create(self, project_id, request, key):
        require_key(key)
        material = request.model_dump(mode='json')
        request_sha = digest(material)
        with self.store.connection(write=True) as db:
            project = self.store.require_project(db, project_id)
            existing = db.execute('SELECT * FROM bio_imports WHERE project_id=%s AND request_key=%s', (project_id,key)).fetchone()
            if existing:
                if existing['request_digest'] != request_sha:
                    raise StorageError('task_idempotency_conflict','此请求标识已登记其他导入。',409)
                task = self.store.require_task(db,existing['task_id'])
                return {'id':existing['id'],'dataset_id':existing['dataset_id'],'task':self.store.public_task(task)}
            workflow, parser_version, extras = WORKFLOW_VERSION, PARSER_VERSION, {}
            if isinstance(request, BioImportRequestV2):
                from app.domain.bioinformatics.analysis_settings import runtime_identity, BioAnalysisLimits
                runtime = runtime_identity()
                if not runtime['available']:
                    raise StorageError('bio_environment_unavailable', '生信执行环境尚未通过验证。', 409)
                workflow, parser_version = WORKFLOW_VERSION_V2, PARSER_VERSION_V2
                extras = dict(matrix_representation=request.matrix_representation, compare_alternate=request.compare_alternate,
                    analysis_limits=BioAnalysisLimits().model_dump(), engine_version=runtime['engine_version'],
                    environment_digest=runtime['environment_digest'], code_digest=runtime['code_digest'])
            files=[]
            for file_id in request.file_ids:
                file = db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s', (file_id,project_id)).fetchone()
                if not file or file['file_type'] not in ('bio_bundle','bio_component') or file['parse_status'] != 'stored':
                    raise StorageError('bio_import_invalid','请选择当前项目中已保存的生信原始文件。',422)
                self.assets.original(dict(file))
                files.append({k:file[k] for k in ('id','filename','sha256','size_bytes','storage_backend','object_key')})
                files[-1]['role']=request.roles.get(file_id,'auto')
            now=datetime.now(timezone.utc)
            dataset_id=request.dataset_id or str(uuid4())
            if request.dataset_id:
                dataset=db.execute('SELECT * FROM bio_datasets WHERE id=%s AND project_id=%s FOR UPDATE', (dataset_id,project_id)).fetchone()
                if not dataset:
                    raise StorageError('bio_dataset_not_found','数据集不存在。',404)
                if dataset['revision'] != request.expected_dataset_revision:
                    raise conflict('bio_revision_conflict')
                revision=dataset['revision']
            else:
                revision=1
                db.execute('''INSERT INTO bio_datasets(id,project_id,name,assay,revision,created_by,created_at,updated_at)
                    VALUES (%s,%s,%s,'visium',1,%s,%s,%s)''',(dataset_id,project_id,request.name,self.store.user_id,now,now))
            import_id,task_id=str(uuid4()),str(uuid4())
            snapshot=dict(schema_version=1,kind='bio_import',workflow_version=workflow,project_id=project_id,
                import_id=import_id,dataset_id=dataset_id,name=request.name,assay='visium',parser_version=parser_version,
                expected_dataset_revision=revision,output_language=project['default_output_language'],files=files,settings=BioLimits().model_dump(), **extras)
            task=dict(id=task_id,project_id=project_id,user_id=self.store.user_id,task_type='bio_import',
                idempotency_key=('bio_import_v2:'+task_id if workflow==WORKFLOW_VERSION_V2 else 'bio_import:'+key),
                input_digest=digest(snapshot),input_snapshot=snapshot,workflow_version=workflow,
                status='queued',phase='parse',revision=1,current_attempt=0,reason_code=None,created_at=now,updated_at=now)
            self.store.insert_task(db,task,validated_file_ids=request.file_ids)
            db.execute('''INSERT INTO bio_imports(id,project_id,dataset_id,task_id,request_key,request_digest,parser_version,
                input_sha256,expected_dataset_revision,settings_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (import_id,project_id,dataset_id,task_id,key,request_sha,parser_version,task['input_digest'],revision,Jsonb(snapshot['settings']),now))
            for file in files:
                db.execute('''INSERT INTO bio_import_files(import_id,file_id,project_id,declared_role,source_sha256,source_size_bytes)
                    VALUES (%s,%s,%s,%s,%s,%s)''',(import_id,file['id'],project_id,file['role'],file['sha256'],file['size_bytes']))
            append_checkpoint(db,task,'check','check',dict(input_version=input_version(task),candidate=None,decision_id=None,result_id=None))
            self.store.append_event(db,task,'created')
            self.store.enqueue(db,task)
            return {'id':import_id,'dataset_id':dataset_id,'task':self.store.public_task(task)}

    def read_candidate(self, task, checkpoint, *, progress=None):
        reference=checkpoint['state_json'].get('candidate')
        if not reference:
            return None
        obj=self.objects.read_json(reference)
        snapshot=validate_snapshot(task)
        if (obj.get('schema_version') != 1 or obj.get('import_id') != snapshot['import_id']
                or obj.get('input_sha256') != task['input_digest'] or obj.get('parser_version') != snapshot['parser_version']):
            raise conflict()
        for member in obj['members']:
            if progress is not None:progress()
            self.objects.read(member)
            if progress is not None:progress()
            if member['source_file_id'] not in {f['id'] for f in snapshot['files']}:
                raise conflict()
        validate_v2_representation(task,obj)
        return obj

    def get(self, project_id, import_id):
        with self.store.connection() as db:
            row=self.require_import(db,project_id,import_id)
            task=self.store.require_task(db,row['task_id'])
            cp=latest_checkpoint(db,task)
            candidate=self.read_candidate(task,cp)
            wait=get_open_wait(db,task)
            result=db.execute('SELECT * FROM bio_dataset_versions WHERE import_id=%s',(import_id,)).fetchone()
            public=None
            if candidate:
                public={k:candidate[k] for k in ('summary','checks')}
                public['sha256']=cp['state_json']['candidate']['sha256']
                public['checks']=public_checks(candidate['checks'])
                public['members']=[{**{k:v for k,v in m.items() if k != 'object_key'},'filename':member_filename(m)} for m in candidate['members']]
                public['images']=candidate.get('manifest',{}).get('spatial',{}).get('images',[])
            return dict(id=import_id,dataset_id=row['dataset_id'],task=self.store.public_task(task),candidate=public,
                checkpoint_id=cp['id'],wait_id=wait['id'] if wait else None,
                expected_dataset_revision=row['expected_dataset_revision'],result_source=self.source(result,[f['id'] for f in validate_snapshot(task)['files']]) if result else None)

    def confirm(self, project_id, import_id, request, key):
        require_key(key)
        with self.store.connection(write=True) as db:
            row=self.require_import(db,project_id,import_id)
            task=self.store.require_task(db,row['task_id'])
            cp=latest_checkpoint(db,task)
            state=dict(cp['state_json'])
            decision=state.get('decision')
            if decision and decision['request_key']==key:
                if decision['request_digest'] != digest(request.model_dump()):
                    raise conflict('bio_candidate_conflict')
                return self.store.public_task(task)
            wait=get_open_wait(db,task)
            if task['input_snapshot']['workflow_version']==WORKFLOW_VERSION_V2:
                self.require_v2_source_root(db,task,self.read_candidate(task,cp))
            dataset=db.execute('SELECT * FROM bio_datasets WHERE id=%s FOR UPDATE',(row['dataset_id'],)).fetchone()
            if (task['status']!='waiting_confirmation' or task['revision']!=request.task_revision
                    or cp['id']!=request.checkpoint_id or cp['next_node']!='await_confirmation' or not wait
                    or wait['id']!=request.wait_id or wait['task_revision']!=task['revision']
                    or wait['input_version']!=input_version(task) or state['candidate']['sha256']!=request.candidate_sha256
                    or dataset['revision']!=request.expected_dataset_revision or row['expected_dataset_revision']!=dataset['revision']):
                raise conflict('bio_candidate_conflict')
            self.require_sources(db,task)
            self.read_candidate(task,cp)
            previous=task['revision']
            task.update(status='queued',phase='verify',revision=previous+1,updated_at=datetime.now(timezone.utc),
                        reason_code='confirmation_received',error_code=None)
            state['decision_id']=str(uuid4())
            state['decision']=dict(id=state['decision_id'],user_id=self.store.user_id,request_key=key,
                request_digest=digest(request.model_dump()),request=request.model_dump(),reviewed_checkpoint_id=cp['id'])
            append_checkpoint(db,task,'publish','publish',state,cp)
            self.store.update_task(db,task,previous)
            resolve_open_wait(db,task)
            self.store.append_event(db,task,'requeued')
            self.store.enqueue(db,task)
            return self.store.public_task(task)

    def publish(self, db, task, checkpoint, now, *, progress=None):
        snapshot=validate_snapshot(task)
        if checkpoint['next_node']!='publish':
            raise conflict()
        self.require_sources(db,task,progress=progress)
        candidate=self.read_candidate(task,checkpoint,progress=progress)
        self.require_v2_source_root(db,task,candidate)
        state=checkpoint['state_json']
        decision=state.get('decision')
        if not decision or decision['id']!=state['decision_id'] or decision['user_id']!=task['user_id']:
            raise conflict()
        request=decision['request']
        reviewed=db.execute('SELECT * FROM task_checkpoints WHERE id=%s AND task_id=%s',(decision['reviewed_checkpoint_id'],task['id'])).fetchone()
        wait=db.execute('SELECT * FROM task_waits WHERE id=%s AND task_id=%s',(request['wait_id'],task['id'])).fetchone()
        if (digest(request)!=decision['request_digest'] or not reviewed or reviewed['next_node']!='await_confirmation'
                or reviewed['id']!=request['checkpoint_id'] or reviewed['state_json']['candidate']!=state['candidate']
                or state['candidate']['sha256']!=request['candidate_sha256'] or not wait or wait['status']!='resolved'
                or wait['task_revision']!=request['task_revision'] or wait['resolved_task_revision']!=request['task_revision']+1
                or wait['input_version']!=input_version(task)):
            raise conflict()
        dataset=db.execute('SELECT * FROM bio_datasets WHERE id=%s AND project_id=%s FOR UPDATE',(snapshot['dataset_id'],task['project_id'])).fetchone()
        if not dataset or dataset['revision']!=snapshot['expected_dataset_revision'] or dataset['revision']!=request['expected_dataset_revision']:
            raise conflict('bio_revision_conflict')
        manifest=canonical(candidate['manifest'])
        record=self.objects.describe(snapshot['import_id'],manifest,json=True)
        # Candidate writer includes this manifest in its single admitted object set.
        self.objects.read(record)
        stored=scoped_object(db,task,record['object_key'])
        if not stored or stored['sha256']!=record['sha256'] or stored['size_bytes']!=record['size_bytes']:
            raise conflict()
        version_id=str(uuid5(UUID(snapshot['import_id']),'dataset-version'))
        number=db.execute('SELECT COALESCE(max(version),0)+1 AS n FROM bio_dataset_versions WHERE dataset_id=%s',(dataset['id'],)).fetchone()['n']
        summary=candidate['summary']
        db.execute('''INSERT INTO bio_dataset_versions(id,dataset_id,project_id,version,parent_id,import_id,task_id,
            manifest_object_id,manifest_sha256,parser_version,shape_json,checks_json,created_by,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (version_id,dataset['id'],task['project_id'],number,dataset['current_version_id'],snapshot['import_id'],task['id'],
             stored['id'],record['sha256'],snapshot['parser_version'],Jsonb(summary),Jsonb(candidate['checks']),task['user_id'],now))
        for member in candidate['members']:
            if progress is not None:progress()
            obj=scoped_object(db,task,member['object_key'])
            if not obj or obj['sha256']!=member['sha256'] or obj['size_bytes']!=member['size_bytes']:
                raise conflict()
            db.execute('''INSERT INTO bio_dataset_members(id,project_id,dataset_version_id,source_file_id,source_member_name,
                role,format,compression,verification_state,sha256,object_id,size_bytes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (member['id'],task['project_id'],version_id,member['source_file_id'],member['source_member_name'],member['role'],
                 member['format'],member['compression'],member['verification_state'],member['sha256'],obj['id'],member['size_bytes']))
        db.execute('UPDATE bio_datasets SET current_version_id=%s,revision=revision+1,updated_at=%s WHERE id=%s',(version_id,now,dataset['id']))
        if progress is not None:progress()
        previous=task['revision']
        task.update(status='succeeded',phase='verify',revision=previous+1,updated_at=now,reason_code=None,error_code=None,
                    result_bio_dataset_version_id=version_id)
        append_checkpoint(db,task,'done','done',{**state,'result_id':version_id},checkpoint)
        TaskStore.finish_attempt(db,task)
        TaskStore.update_task(db,task,previous)
        TaskStore.append_event(db,task,'succeeded')
        return TaskStore.public_task(task)


    @staticmethod
    def source(version,source_file_ids):
        return BioDatasetSourceV1(project_id=version['project_id'],dataset_id=version['dataset_id'],
            dataset_version_id=version['id'],version=version['version'],source_file_ids=source_file_ids,
            manifest_sha256=version['manifest_sha256'],parser_version=version['parser_version']).model_dump()

    def retry_in_transaction(self, db, task, request):
        if task['status']!='failed' or task['revision']!=request.expected_task_revision or request.input_version.model_dump()!=input_version(task):
            raise conflict('bio_candidate_conflict')
        self.require_sources(db,task)
        cp=latest_checkpoint(db,task)
        if cp['next_node']=='publish':
            self.read_candidate(task,cp)
        allowed={'storage_unavailable','task_worker_interrupted','storage_quota_exceeded','storage_disk_insufficient',
                 'storage_accounting_unknown','bio_environment_unavailable','bio_parse_timeout'}
        if task.get('error_code') not in allowed:
            raise StorageError('task_transition_invalid','此错误需检查原始数据后新建导入。',409)
        previous=task['revision']
        task.update(status='queued',revision=previous+1,updated_at=datetime.now(timezone.utc),reason_code='retry_requested',error_code=None)
        TaskStore.update_task(db,task,previous)
        task['_retry_reason']='manual_retry'
        TaskStore.append_event(db,task,'requeued')
        TaskStore.enqueue(db,task)
        return TaskStore.public_task(task)


def scoped_object(db, task, key):
    return db.execute('''SELECT o.* FROM storage_objects o JOIN storage_references r ON r.object_id=o.id
        WHERE o.object_key=%s AND o.namespace='local:assets-v1' AND o.state='present' AND r.project_id=%s
        AND r.owner_id=%s AND r.kind='bio_dataset' ''',(key,task['project_id'],task['user_id'])).fetchone()


def public_checks(checks):
    if isinstance(checks,list):
        return checks
    def status(key,value):
        if isinstance(value,dict) and 'status' in value:
            if value['status'] in ('mismatch','failed'):return 'failed'
            if value['status'] in ('identical','order_reindexed_equal','verified','checked','completed'):return 'passed'
            return 'not_checked'
        if value=='internal_not_checked':return 'not_checked'
        if key=='warnings':return 'warning' if value else 'passed'
        if value is False:return 'warning'
        if value in ('pending','not_checked'):return 'not_checked'
        return 'passed'
    rows=[dict(code=key,status=status(key,value),message=str(value) if not isinstance(value,(dict,list)) else '',value=value)
          for key,value in checks.items()]
    for row in rows:
        if row['status']=='failed':row['blocking']=True
    return rows


def recovery_actions(db,task):
    if task['status']=='waiting_confirmation':
        wait=get_open_wait(db,task)
        cp=latest_checkpoint(db,task)
        return ['approve'] if wait and cp['next_node']=='await_confirmation' and wait['task_revision']==task['revision'] else []
    if task['status']=='failed' and task.get('error_code') in {'storage_unavailable','task_worker_interrupted',
            'storage_quota_exceeded','storage_disk_insufficient','storage_accounting_unknown','bio_environment_unavailable','bio_parse_timeout'}:
        return ['retry']
    return []


def task_artifacts(db,task):
    snapshot=validate_snapshot(task)
    version=db.execute('SELECT * FROM bio_dataset_versions WHERE import_id=%s',(snapshot['import_id'],)).fetchone()
    return {'bioinformatics':dict(import_id=snapshot['import_id'],dataset_id=snapshot['dataset_id'],
        result_source=BioDatasetService.source(version,[f['id'] for f in snapshot['files']]) if version else None)}


def retry_in_transaction(store,db,task,expected_revision):
    from types import SimpleNamespace
    from app.adapters.task_store import DatasetTaskAssets
    from app.core.config import get_data_dir
    from app.domain.bioinformatics.contracts import BioImportInputVersion,BioImportInputVersionV2
    assets=DatasetTaskAssets(store.user_id,store.config,get_data_dir())
    frozen=input_version(task)
    model=BioImportInputVersionV2 if frozen['workflow_version']=='bio_import_v2' else BioImportInputVersion
    request=SimpleNamespace(expected_task_revision=expected_revision,
        input_version=model.model_validate(frozen))
    return BioDatasetService(assets).retry_in_transaction(db,task,request)
