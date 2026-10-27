"""Immutable filter/quality v3 tasks with mixed-version parent chain verification."""
import json
from datetime import datetime, timezone
from functools import partial
from urllib.parse import quote
from uuid import uuid4
from app.core.exceptions import StorageError
from app.adapters.task_store import source_conflict
from app.adapters.prepared_dataset_objects import PreparedDatasetObjects, changed
from app.domain.analysis_sources import prepared_dataset_source
from app.domain.dataset_preparation.service import (DatasetPreparationService,require_key,request_digest,
    validate_snapshot,preparation_input_version,candidate_id,latest_checkpoint,append_checkpoint,require_approval,CandidateReference)
from app.domain.dataset_preparation.quality_service import QualityPreparationService, sheet_metadata
from app.domain.dataset_preparation.quality_contracts import QualityRecipe, MAX_MANIFEST_BYTES
from app.domain.dataset_preparation.filter_contracts import FilterRecipe
from app.domain.dataset_preparation.derivation_contracts import DerivationManifest,PreparedDatasetObjectV3,WORKFLOW_VERSION
from app.domain.dataset_preparation.derivation_workflow import DerivationSnapshot,DerivationState,FilterCreateRequest
from app.domain.dataset_preparation.quality_workflow import QualityCreateRequest
from app.domain.dataset_preparation.filter_transform import prepare_filter,validate_filter_recipe
from app.domain.dataset_preparation.quality_transform import prepare_quality,validate_quality_recipe
from app.domain.tasks.waits import get_open_wait

class DerivationManifestObjects(PreparedDatasetObjects):
    prefix='derivation-manifests-v3'
    max_bytes=MAX_MANIFEST_BYTES

    def _validate_content(self,content):
        if type(content) is not bytes or not 0<len(content)<=self.max_bytes:raise changed('完整筛选/质量回执超过16MiB限制。')
        try:return DerivationManifest.model_validate(json.loads(content))
        except (ValueError,TypeError,RecursionError) as exc:raise changed('完整筛选/质量回执无效。') from exc

    def read(self,record):
        content,obj=super().read(record)
        if 'entry_count' in record and record['entry_count']!=len(obj.entries):raise changed('完整回执条目数量不一致。')
        return content,obj

def _audit_node(db,task,row):
    snapshot=validate_snapshot(task);checkpoint=latest_checkpoint(db,task);state=checkpoint['state_json']
    require_approval(db,task,state)
    relation=db.execute('SELECT * FROM prepared_dataset_derivations_v3 WHERE prepared_dataset_id=%s',(row['id'],)).fetchone()
    base=db.execute('SELECT p.*,t.project_id FROM prepared_dataset_versions p JOIN tasks t ON t.id=p.task_id WHERE p.id=%s',(snapshot['source']['dataset_id'],)).fetchone()
    operation=snapshot['operation'];rules='population_filter_rules_v1' if operation=='population_filter' else 'quality_rules_v1'
    if (not relation or not base or task['workflow_version']!=WORKFLOW_VERSION or task['status']!='succeeded'
        or row['id']!=candidate_id(task['id']) or row['task_id']!=task['id'] or row['created_by']!=task['user_id']
        or base['created_by']!=task['user_id'] or base['project_id']!=task['project_id'] or base['file_id']!=row['file_id']
        or row['file_id']!=snapshot['source']['file_id'] or row['parent_dataset_id']!=snapshot['root_source']['dataset_id']
        or base['parent_dataset_id']!=row['parent_dataset_id'] or base['version']>=row['version'] or base['id']==row['id']
        or prepared_dataset_source(base,snapshot['root_source'],schema_version=snapshot['source']['schema_version'])!=snapshot['source']
        or relation['base_prepared_dataset_id']!=base['id'] or relation['object_schema_version']!=3
        or relation['operation']!=operation or relation['rules_version']!=rules
        or relation['workflow_version']!=WORKFLOW_VERSION or relation['transform_version']!='excel_prepare_v3'
        or relation['manifest_entry_count']!=row['summary_json']['impact_count'] or row['summary_json']['retained_record_count']==0
        or relation['manifest_object_key']!=f"derivation-manifests-v3/{row['id']}/{relation['manifest_sha256']}.json"
        or checkpoint['node']!='done' or checkpoint['next_node']!='done' or state['result_id']!=row['id']
        or state['decision_id']!=row['decision_id'] or state['candidate']!={k:row[k] for k in CandidateReference.model_fields}
        or state['recipe']!=row['recipe_json']):raise source_conflict()
    return prepared_dataset_source(row,snapshot['root_source'],schema_version=3),dict(base),dict(relation)

def _walk(db,task,row):
    from app.domain.dataset_preparation.quality_service import _audit_published_node, audit_published as audit_old
    chain=[];seen=set();owner=task['user_id'];project=task['project_id'];file=row['file_id'];root=row['parent_dataset_id']
    while task['workflow_version'] in ('dataset_preparation_v2',WORKFLOW_VERSION):
        if row['id'] in seen or task['user_id']!=owner or task['project_id']!=project or row['file_id']!=file or row['parent_dataset_id']!=root:raise source_conflict()
        seen.add(row['id'])
        if task['workflow_version']==WORKFLOW_VERSION:source,parent,relation=_audit_node(db,task,row)
        else:
            source,parent=_audit_published_node(db,task,row)
            relation=dict(db.execute('SELECT * FROM prepared_dataset_derivations WHERE prepared_dataset_id=%s',(row['id'],)).fetchone())
        chain.append((dict(row),dict(task),latest_checkpoint(db,task),relation,source))
        row=parent;task=db.execute('SELECT * FROM tasks WHERE id=%s',(row['task_id'],)).fetchone()
        if not task:raise source_conflict()
    if task['user_id']!=owner or task['project_id']!=project or row['created_by']!=owner or row['file_id']!=file or row['parent_dataset_id']!=root:raise source_conflict()
    audit_old(db,task,row)
    return chain,dict(row)

def audit_published(db,task,row):
    try:
        chain,_=_walk(db,task,row)
        if not chain:raise source_conflict()
        return chain[0][4]
    except (KeyError,TypeError,ValueError) as exc:raise source_conflict() from exc

class DerivationPreparationService(QualityPreparationService):
    def __init__(self,assets):
        super().__init__(assets)
        self.manifests=DerivationManifestObjects(assets.directory)

    def defaults(self,project,file,id):
        row,_,obj=DatasetPreparationService(self.assets).load_version(project,file,id)
        return dict(source=prepared_dataset_source(row,obj.parent_source.model_dump(),schema_version=obj.schema_version),
            sheet=sheet_metadata(obj.sheet),base_record_count=obj.sheet.row_count,
            recipe=dict(conditions=[],reason='',unit_acknowledged=False))

    def create(self,project,file,request,key,*,operation='population_filter'):
        require_key(key)
        cls=FilterCreateRequest if operation=='population_filter' else QualityCreateRequest
        request=cls.model_validate(request.model_dump() if hasattr(request,'model_dump') else request)
        digest=request_digest(dict(file_id=file,**request.model_dump(mode='json')))
        with self.store.connection() as db:
            self.datasets.require_file(db,project,file)
            existing=self.store.find_request(db,project,'prepare_dataset',key)
            if existing:
                if existing['input_digest']!=digest or existing['input_snapshot'].get('operation')!=operation:raise StorageError('task_idempotency_conflict','同一请求标识已用于不同输入。',409)
                return self.store.public_task(existing),200
        row,obj=self.base_object(project,self.defaults(project,file,request.base_dataset_id)['source'])
        source=prepared_dataset_source(row,obj.parent_source.model_dump(),schema_version=obj.schema_version)
        (validate_filter_recipe if operation=='population_filter' else validate_quality_recipe)(obj.sheet,request.recipe)
        with self.store.connection(write=True) as db:
            file_row=self.datasets.require_file(db,project,file)
            db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            existing=self.store.find_request(db,project,'prepare_dataset',key)
            if existing:
                if existing['input_digest']!=digest or existing['input_snapshot'].get('operation')!=operation:raise StorageError('task_idempotency_conflict','同一请求标识已用于不同输入。',409)
                return self.store.public_task(existing),200
            now=datetime.now(timezone.utc)
            snapshot=DerivationSnapshot(schema_version=3,kind='dataset_preparation',project_id=project,filename=file_row['filename'],source=source,
                root_source=obj.parent_source,operation=operation,recipe=request.recipe,workflow_version=WORKFLOW_VERSION).model_dump(mode='json')
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='prepare_dataset',idempotency_key=key,input_digest=digest,
                input_snapshot=snapshot,workflow_version=WORKFLOW_VERSION,status='queued',phase='plan',revision=1,current_attempt=0,reason_code=None,created_at=now,updated_at=now)
            self.store.insert_task(db,task)
            state=DerivationState(input_version=preparation_input_version(task),recipe=request.recipe,recipe_revision=1).model_dump(mode='json')
            append_checkpoint(db,task,'prepare_preview','prepare_preview',state)
            self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            return self.store.public_task(task),202

    def transform(self,base,source,recipe,operation):
        if operation=='population_filter':return prepare_filter(base,source,recipe)
        return prepare_quality(base,source,recipe,manifest_factory=partial(DerivationManifest,operation='quality'))

    def build_candidate(self,task,state):
        snapshot=validate_snapshot(task);_,base=self.base_object(task['project_id'],snapshot['source'])
        sheet,summary,manifest=self.transform(base,snapshot['source'],state['recipe'],snapshot['operation'])
        content=manifest.model_dump_json().encode('utf-8')
        ref=dict(**self.manifests.describe(candidate_id(task['id']),content),entry_count=len(manifest.entries))
        return PreparedDatasetObjectV3(parent_source=base.parent_source,base_source=snapshot['source'],operation=snapshot['operation'],recipe=state['recipe'],sheet=sheet,summary=summary,manifest=ref),content

    def read_candidate(self,task,checkpoint,*,verified_base=None):
        snapshot=validate_snapshot(task);state=checkpoint['state_json']
        if state['candidate'] is None:return None,None
        content,obj=self.objects.read(state['candidate'])
        if (obj.schema_version!=3 or obj.operation!=snapshot['operation'] or obj.base_source.model_dump(mode='json')!=snapshot['source']
            or obj.parent_source.model_dump(mode='json')!=snapshot['root_source'] or obj.recipe.model_dump(mode='json')!=state['recipe']):raise source_conflict()
        base_row,base=verified_base or self.base_object(task['project_id'],snapshot['source'])
        if prepared_dataset_source(base_row,base.parent_source.model_dump(),schema_version=base.schema_version)!=snapshot['source']:raise source_conflict()
        _,manifest=self.manifests.read({**obj.manifest.model_dump(),'id':candidate_id(task['id'])})
        sheet,summary,expected=self.transform(base,snapshot['source'],obj.recipe,obj.operation)
        if sheet!=obj.sheet or summary!=obj.summary or manifest!=expected:raise changed('筛选/质量数据、完整回执与直接父版本不一致。')
        return content,obj

    def verify_publication(self,task,checkpoint):self.read_candidate(task,checkpoint)

    def get_task(self,task_id):
        with self.store.connection() as db:
            task=self.store.require_task(db,task_id);snapshot=validate_snapshot(task);checkpoint=latest_checkpoint(db,task);wait=get_open_wait(db,task)
            row=db.execute('SELECT id FROM prepared_dataset_versions WHERE task_id=%s',(task_id,)).fetchone()
        self.require_raw(snapshot['source'],task['project_id']);_,obj=self.read_candidate(task,checkpoint)
        manifest=self.manifests.read(obj.manifest.model_dump())[1] if obj else None
        prefix=f'/api/v1/tasks/{quote(task_id,safe="")}/dataset-preparation';query='?checkpoint_id='+quote(checkpoint['id'],safe='')
        return dict(task=self.store.public_task(task),source=snapshot['source'],root_source=snapshot['root_source'],operation=snapshot['operation'],wait=wait,
            checkpoint_id=checkpoint['id'],recipe_revision=checkpoint['state_json']['recipe_revision'],recipe=checkpoint['state_json']['recipe'],
            preview=obj.summary.model_dump(mode='json') if obj else None,changes=[e.model_dump(mode='json') for e in manifest.entries[:20]] if manifest else [],
            preview_download_url=prefix+'/preview/download' if obj else None,impact_url=prefix+'/impacts'+query if obj else None,
            impact_download_url=prefix+'/impacts/download'+query if obj else None,result=self.get_version(task['project_id'],snapshot['source']['file_id'],row['id']) if row else None)

    def load_derivation_version(self,project,file,id):
        with self.store.connection() as db:
            self.datasets.require_file(db,project,file)
            row=db.execute('SELECT * FROM prepared_dataset_versions WHERE id=%s AND file_id=%s AND created_by=%s',(id,file,self.store.user_id)).fetchone()
            if not row:raise StorageError('dataset_missing','整理版本不存在。',404)
            task=self.store.require_task(db,row['task_id'])
            try:chain,root=_walk(db,task,row)
            except (KeyError,TypeError,ValueError) as exc:raise source_conflict() from exc
        base_row,_,base=DatasetPreparationService(self.assets).load_version(project,file,root['id'])
        for row,task,checkpoint,relation,_ in reversed(chain):
            service=self if task['workflow_version']==WORKFLOW_VERSION else QualityPreparationService(self.assets)
            content,obj=service.read_candidate(task,checkpoint,verified_base=(base_row,base))
            if (obj.summary.model_dump(mode='json')!=row['summary_json']
                or {k:relation['manifest_'+k] for k in ('object_key','sha256','size_bytes','entry_count')}!=obj.manifest.model_dump()):raise source_conflict()
            base_row,base=row,obj
        return row,content,obj

    @staticmethod
    def version_summary(project,row,obj):
        prefix='/api/v1/projects/{}/files/{}/prepared-dataset-versions/{}'.format(*[quote(str(v),safe='') for v in (project,row['file_id'],row['id'])])
        return dict(id=row['id'],file_id=row['file_id'],parent_dataset_id=row['parent_dataset_id'],parent_dataset_version=obj.parent_source.dataset_version,
            version=row['version'],created_at=row['created_at'].isoformat(),task_id=row['task_id'],operation=obj.operation,
            source=prepared_dataset_source(row,obj.parent_source.model_dump(),schema_version=3),base_source=obj.base_source.model_dump(mode='json'),
            recipe=row['recipe_json'],summary=row['summary_json'],sheet=sheet_metadata(obj.sheet),download_url=prefix+'/download',impact_url=prefix+'/impacts',impact_download_url=prefix+'/impacts/download')

    def manifest_for_version(self,project,file,id):
        _,_,obj=DatasetPreparationService(self.assets).load_version(project,file,id)
        if obj.schema_version!=3:return QualityPreparationService(self.assets).manifest_for_version(project,file,id)
        return self.manifests.read({**obj.manifest.model_dump(),'id':id})

    def manifest_for_task(self,task_id,checkpoint_id=None):
        with self.store.connection() as db:
            task=self.store.require_task(db,task_id);validate_snapshot(task);checkpoint=latest_checkpoint(db,task)
        if task['workflow_version']!=WORKFLOW_VERSION:return QualityPreparationService(self.assets).manifest_for_task(task_id,checkpoint_id)
        if checkpoint_id is not None and checkpoint_id!=checkpoint['id']:raise StorageError('task_revision_conflict','影响预览已更新，请重新读取。',409)
        _,obj=self.read_candidate(task,checkpoint)
        if obj is None:raise StorageError('dataset_missing','当前筛选预览尚未生成。',404)
        return self.manifests.read({**obj.manifest.model_dump(),'id':candidate_id(task_id)})

    @staticmethod
    def impact_page(manifest,page=1,page_size=20,operation=None,reason=None):
        if getattr(manifest,'operation',None)!='population_filter':return QualityPreparationService.impact_page(manifest,page,page_size,operation,reason)
        if type(page) is not int or not 1<=page<=1000000 or type(page_size) is not int or page_size!=20 or operation not in (None,'retained','mismatch','unknown') or reason is not None:
            raise StorageError('task_input_invalid','筛选影响分页参数无效。',422)
        entries=[e for e in manifest.entries if operation is None or e.classification==operation]
        return dict(items=[e.model_dump(mode='json') for e in entries[(page-1)*20:page*20]],total=len(entries),page=page,page_size=20)
