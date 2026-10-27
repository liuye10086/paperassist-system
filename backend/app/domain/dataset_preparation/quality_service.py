"""Authenticated incremental quality tasks using existing persisted decisions."""
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import uuid4
from app.core.exceptions import StorageError
from app.adapters.task_store import source_conflict
from app.adapters.quality_manifest_objects import QualityManifestObjects
from app.domain.analysis_sources import prepared_dataset_source
from app.domain.dataset_preparation.service import (DatasetPreparationService, require_key, request_digest,
    validate_snapshot, preparation_input_version, candidate_id, latest_checkpoint, append_checkpoint, require_approval, CandidateReference)
from app.domain.dataset_preparation.quality_contracts import QualityRecipe, QualitySummary, WORKFLOW_VERSION, RULES_VERSION
from app.domain.dataset_preparation.quality_workflow import QualityCreateRequest, QualitySnapshot, QualityState
from app.domain.dataset_preparation.quality_transform import validate_quality_recipe, overview, prepare_quality
from app.domain.tasks.waits import get_open_wait

def _audit_published_node(db,task,row):
    snapshot=validate_snapshot(task); checkpoint=latest_checkpoint(db,task); state=checkpoint['state_json']
    require_approval(db,task,state)
    relation=db.execute('SELECT * FROM prepared_dataset_derivations WHERE prepared_dataset_id=%s',(row['id'],)).fetchone()
    base=db.execute('''SELECT p.*,t.project_id FROM prepared_dataset_versions p JOIN tasks t ON t.id=p.task_id WHERE p.id=%s''',
        (snapshot['source']['dataset_id'],)).fetchone()
    summary=QualitySummary.model_validate(row['summary_json'])
    if (not relation or not base or task['status']!='succeeded' or row['id']!=candidate_id(task['id']) or row['task_id']!=task['id']
            or row['created_by']!=task['user_id'] or base['created_by']!=task['user_id'] or base['project_id']!=task['project_id']
            or row['file_id']!=snapshot['source']['file_id'] or base['file_id']!=row['file_id']
            or row['parent_dataset_id']!=snapshot['root_source']['dataset_id'] or base['parent_dataset_id']!=row['parent_dataset_id']
            or base['version']>=row['version'] or base['id']==row['id']
            or prepared_dataset_source(base,snapshot['root_source'],schema_version=snapshot['source']['schema_version'])!=snapshot['source']
            or relation['base_prepared_dataset_id']!=base['id'] or relation['object_schema_version']!=2
            or relation['transform_version']!='excel_prepare_v2' or relation['workflow_version']!=WORKFLOW_VERSION or relation['rules_version']!=RULES_VERSION
            or relation['manifest_entry_count']!=summary.impact_count or summary.retained_record_count==0
            or relation['manifest_object_key']!=f"quality-manifests/{row['id']}/{relation['manifest_sha256']}.json"
            or checkpoint['node']!='done' or checkpoint['next_node']!='done' or state['result_id']!=row['id']
            or state['decision_id']!=row['decision_id'] or state['candidate']!={k:row[k] for k in CandidateReference.model_fields}
            or state['recipe']!=row['recipe_json']):
        raise source_conflict()
    return prepared_dataset_source(row,snapshot['root_source'],schema_version=2),dict(base)

def _audit_published_chain(db,task,row):
    """Walk the whole parent chain with no asset IO or recursive call stack."""
    first=None; seen=set()
    while task['workflow_version']==WORKFLOW_VERSION:
        if row['id'] in seen: raise source_conflict()
        seen.add(row['id'])
        source,base=_audit_published_node(db,task,row)
        if first is None: first=source
        row=base
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(row['task_id'],)).fetchone()
        if not task: raise source_conflict()
    snapshot=validate_snapshot(task); checkpoint=latest_checkpoint(db,task); state=checkpoint['state_json']
    require_approval(db,task,state)
    if (task['workflow_version']!='dataset_preparation_v1' or task['status']!='succeeded'
            or row['id']!=candidate_id(task['id']) or row['parent_dataset_id']!=snapshot['source']['dataset_id']
            or row['file_id']!=snapshot['source']['file_id'] or row['created_by']!=task['user_id']
            or checkpoint['node']!='done' or checkpoint['next_node']!='done' or state['result_id']!=row['id']
            or state['decision_id']!=row['decision_id'] or state['candidate']!={k:row[k] for k in CandidateReference.model_fields}
            or state['recipe']!=row['recipe_json']):
        raise source_conflict()
    return first

def audit_published(db,task,row):
    try:
        return _audit_published_chain(db,task,row)
    except (KeyError,TypeError,ValueError) as exc:
        raise source_conflict() from exc

def quality_version_summary(project,row,obj):
    prefix='/api/v1/projects/{}/files/{}/prepared-dataset-versions/{}'.format(*[quote(str(v),safe='') for v in (project,row['file_id'],row['id'])])
    return dict(id=row['id'],file_id=row['file_id'],parent_dataset_id=row['parent_dataset_id'],
        parent_dataset_version=obj.parent_source.dataset_version,version=row['version'],created_at=row['created_at'].isoformat(),task_id=row['task_id'],
        source=prepared_dataset_source(row,obj.parent_source.model_dump(),schema_version=2),base_source=obj.base_source.model_dump(mode='json'),
        recipe=row['recipe_json'],summary=row['summary_json'],sheet=sheet_metadata(obj.sheet),download_url=prefix+'/download',
        impact_url=prefix+'/impacts',impact_download_url=prefix+'/impacts/download')

def sheet_metadata(sheet):
    return dict(index=sheet.index,name=sheet.name,data_range=sheet.data_range,fields=[f.model_dump(mode='json') for f in sheet.fields])

class QualityPreparationService(DatasetPreparationService):
    def __init__(self,project_store):
        super().__init__(project_store)
        self.manifests=QualityManifestObjects(project_store.directory)

    def build_candidate(self,task,state):
        """Build both local objects in memory; wait() owns durable admission."""
        import json
        from app.domain.dataset_preparation.quality_transform import build_quality_object
        _,base=self.base_object(task['project_id'],state['input_version']['source'])
        sheet,summary,manifest=prepare_quality(base,state['input_version']['source'],state['recipe'])
        content=json.dumps(manifest.model_dump(mode='json'),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
        reference=dict(**self.manifests.describe(candidate_id(task['id']),content),entry_count=len(manifest.entries))
        return build_quality_object(base,state['input_version']['source'],state['recipe'],sheet,summary,reference),content

    def require_raw(self,source,project_id):
        if source['kind']=='dataset_version': return super().require_raw(source,project_id)
        row,_,obj=DatasetPreparationService(self.assets).load_version(project_id,source['file_id'],source['dataset_id'])
        if prepared_dataset_source(row,obj.parent_source.model_dump(),schema_version=obj.schema_version)!=source:
            raise source_conflict()
        return row,obj.sheet

    def base_object(self,project,source):
        row,_,obj=DatasetPreparationService(self.assets).load_version(project,source['file_id'],source['dataset_id'])
        if prepared_dataset_source(row,obj.parent_source.model_dump(),schema_version=obj.schema_version)!=source:
            raise source_conflict()
        return row,obj

    def defaults(self,project,file,id):
        row,_,obj=DatasetPreparationService(self.assets).load_version(project,file,id)
        return dict(source=prepared_dataset_source(row,obj.parent_source.model_dump(),schema_version=obj.schema_version),
            recipe=QualityRecipe(fields=[dict(column=f.column) for f in obj.sheet.fields]).model_dump(mode='json'),
            summary=overview(obj.sheet).model_dump(mode='json'),sheet=sheet_metadata(obj.sheet))

    def create(self,project,file,request,key):
        require_key(key)
        request=QualityCreateRequest.model_validate(request.model_dump() if isinstance(request,QualityCreateRequest) else request)
        digest=request_digest(dict(file_id=file,**request.model_dump(mode='json')))
        with self.store.connection() as db:
            self.datasets.require_file(db,project,file)
            existing=self.store.find_request(db,project,'prepare_dataset',key)
            if existing:
                if existing['input_digest']!=digest: raise StorageError('task_idempotency_conflict','同一请求标识已用于不同输入。',409)
                return self.store.public_task(existing),200
        row,_,obj=DatasetPreparationService(self.assets).load_version(project,file,request.base_dataset_id)
        source=prepared_dataset_source(row,obj.parent_source.model_dump(),schema_version=obj.schema_version)
        if obj.schema_version==3:
            from app.domain.dataset_preparation.derivation_service import DerivationPreparationService
            return DerivationPreparationService(self.assets).create(project,file,request,key,operation='quality')
        validate_quality_recipe(obj.sheet,request.recipe)
        with self.store.connection(write=True) as db:
            file_row=self.datasets.require_file(db,project,file)
            # Serialize request creation for one owner/project to make replay race safe.
            db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            existing=self.store.find_request(db,project,'prepare_dataset',key)
            if existing:
                if existing['input_digest']!=digest: raise StorageError('task_idempotency_conflict','同一请求标识已用于不同输入。',409)
                return self.store.public_task(existing),200
            now=datetime.now(timezone.utc)
            snapshot=QualitySnapshot(schema_version=2,kind='dataset_preparation',project_id=project,filename=file_row['filename'],
                source=source,root_source=obj.parent_source,recipe=request.recipe,workflow_version=WORKFLOW_VERSION).model_dump(mode='json')
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='prepare_dataset',idempotency_key=key,
                input_digest=digest,input_snapshot=snapshot,workflow_version=WORKFLOW_VERSION,status='queued',phase='plan',revision=1,
                current_attempt=0,reason_code=None,created_at=now,updated_at=now)
            self.store.insert_task(db,task)
            state=QualityState(input_version=preparation_input_version(task),recipe=request.recipe,recipe_revision=1).model_dump(mode='json')
            append_checkpoint(db,task,'prepare_preview','prepare_preview',state)
            self.store.append_event(db,task,'created'); self.store.enqueue(db,task)
            return self.store.public_task(task),202

    def read_candidate(self,task,checkpoint,*,verified_base=None):
        state=checkpoint['state_json']; snapshot=validate_snapshot(task)
        if state['candidate'] is None: return None,None
        content,obj=self.objects.read(state['candidate'])
        if (obj.schema_version!=2 or obj.base_source.model_dump(mode='json')!=snapshot['source']
                or obj.parent_source.model_dump(mode='json')!=snapshot['root_source'] or obj.recipe.model_dump(mode='json')!=state['recipe']):
            raise source_conflict()
        if verified_base is None:
            _,base=self.base_object(task['project_id'],snapshot['source'])
        else:
            base_row,base=verified_base
            if prepared_dataset_source(base_row,base.parent_source.model_dump(),schema_version=base.schema_version)!=snapshot['source']:
                raise source_conflict()
        _,manifest=self.manifests.read({**obj.manifest.model_dump(),'id':state['candidate']['id']})
        from app.domain.dataset_preparation.quality_receipts import verify_frozen_receipt
        verify_frozen_receipt(base,obj,manifest)
        return content,obj

    def verify_publication(self,task,checkpoint):
        """Publication additionally verifies transform output before its atomic commit."""
        _,obj=self.read_candidate(task,checkpoint)
        snapshot=validate_snapshot(task)
        _,base=self.base_object(task['project_id'],snapshot['source'])
        _,manifest=self.manifests.read(obj.manifest.model_dump())
        sheet,summary,expected=prepare_quality(base,snapshot['source'],obj.recipe)
        if sheet!=obj.sheet or summary!=obj.summary or manifest!=expected:
            raise StorageError('dataset_changed','整理数据与完整影响、父版本或批准规则不一致。',409)

    def get_task(self,task_id):
        with self.store.connection() as db:
            task=self.store.require_task(db,task_id); snapshot=validate_snapshot(task)
            checkpoint=latest_checkpoint(db,task); wait=get_open_wait(db,task)
            row=db.execute('SELECT id FROM prepared_dataset_versions WHERE task_id=%s',(task_id,)).fetchone()
        self.require_raw(snapshot['source'],task['project_id'])
        _,obj=self.read_candidate(task,checkpoint)
        manifest=self.manifests.read(obj.manifest.model_dump())[1] if obj else None
        prefix=f'/api/v1/tasks/{quote(task_id,safe="")}/dataset-preparation'
        query='?checkpoint_id='+quote(checkpoint['id'],safe='')
        return dict(task=self.store.public_task(task),source=snapshot['source'],root_source=snapshot['root_source'],wait=wait,checkpoint_id=checkpoint['id'],
            recipe_revision=checkpoint['state_json']['recipe_revision'],recipe=checkpoint['state_json']['recipe'],
            preview=obj.summary.model_dump(mode='json') if obj else None,changes=[e.model_dump(mode='json') for e in manifest.entries[:20]] if manifest else [],
            preview_download_url=prefix+'/preview/download' if obj else None,impact_url=prefix+'/impacts' if obj else None,
            impact_download_url=prefix+'/impacts/download'+query if obj else None,
            result=self.get_version(task['project_id'],snapshot['source']['file_id'],row['id']) if row else None)

    def load_quality_version(self,project,file,id):
        # Audit metadata once from child to root, then verify immutable assets
        # from root to child. Do not recursively reload every ancestor for each
        # edge: legal long histories must not depend on Python's stack limit.
        chain=[];seen=set()
        with self.store.connection() as db:
            self.datasets.require_file(db,project,file)
            row=db.execute('SELECT * FROM prepared_dataset_versions WHERE id=%s AND file_id=%s AND created_by=%s',(id,file,self.store.user_id)).fetchone()
            if not row: raise StorageError('dataset_missing','整理数据版本不存在。',404)
            row=dict(row);task=self.store.require_task(db,row['task_id'])
            while task['workflow_version']==WORKFLOW_VERSION:
                if row['id'] in seen:raise source_conflict()
                seen.add(row['id'])
                try:
                    _,parent=_audit_published_node(db,task,row)
                    checkpoint=latest_checkpoint(db,task)
                    relation=db.execute('SELECT * FROM prepared_dataset_derivations WHERE prepared_dataset_id=%s',(row['id'],)).fetchone()
                    chain.append((row,task,checkpoint,dict(relation)))
                except (KeyError,TypeError,ValueError) as exc:
                    raise source_conflict() from exc
                row=parent;task=self.store.require_task(db,row['task_id'])
            if task['workflow_version']!='dataset_preparation_v1' or not chain:
                raise source_conflict()
        base_row,_,base=DatasetPreparationService(self.assets).load_version(project,file,row['id'])
        for row,task,checkpoint,relation in reversed(chain):
            content,obj=self.read_candidate(task,checkpoint,verified_base=(base_row,base))
            if (obj.summary.model_dump(mode='json')!=row['summary_json']
                    or {key:relation['manifest_'+key] for key in ('object_key','sha256','size_bytes','entry_count')}!=obj.manifest.model_dump()):
                raise source_conflict()
            base_row,base=row,obj
        return row,content,obj

    def manifest_for_version(self,project,file,id):
        _,_,obj=DatasetPreparationService(self.assets).load_version(project,file,id)
        if obj.schema_version!=2: raise StorageError('dataset_missing','旧版本未记录完整影响明细。',404)
        return self.manifests.read({**obj.manifest.model_dump(),'id':id})

    def manifest_for_task(self,task_id,checkpoint_id=None):
        with self.store.connection() as db:
            task=self.store.require_task(db,task_id); validate_snapshot(task); checkpoint=latest_checkpoint(db,task)
        if task['workflow_version']!=WORKFLOW_VERSION:
            raise StorageError('dataset_missing','旧版本未记录完整影响明细。',404)
        if checkpoint_id is not None and checkpoint['id']!=checkpoint_id:
            raise StorageError('task_revision_conflict','影响预览已更新，请重新读取。',409)
        _,obj=self.read_candidate(task,checkpoint)
        if obj is None: raise StorageError('dataset_missing','当前质量预览尚未生成。',404)
        return self.manifests.read({**obj.manifest.model_dump(),'id':candidate_id(task_id)})

    @staticmethod
    def impact_page(manifest,page=1,page_size=20,operation=None,reason=None):
        if type(page) is not int or not 1<=page<=1000000 or page_size!=20 or operation not in (None,'manual_exclusion','cell_change','duplicate_exclusion'):
            raise StorageError('task_input_invalid','影响分页参数无效。',422)
        entries=[e for e in manifest.entries if (operation is None or e.operation==operation) and (reason is None or e.reason==reason)]
        return dict(items=[e.model_dump(mode='json') for e in entries[(page-1)*20:page*20]],total=len(entries),page=page,page_size=20)
