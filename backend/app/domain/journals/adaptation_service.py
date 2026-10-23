"""One frozen plan, public task and publication through ManuscriptService."""
from copy import deepcopy
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from app.domain.manuscripts.service import ManuscriptService
from .format_service import FormatService
from .service import now
from .adaptation_contracts import WORKFLOW,AdaptationInputVersion
from .display import plan,apply,DISPLAY_VERSION,synthetic_input

def invalid(message,code='journal_adaptation_invalid',status=409):return StorageError(code,message,status)

def input_version(task):
    snap=task['input_snapshot']
    if task['task_type']!='journal_adaptation' or task['workflow_version']!=WORKFLOW or digest(snap)!=task['input_digest'] or snap.get('kind')!='journal_adaptation' or snap.get('project_id')!=task['project_id'] or snap.get('real_model_calls') is not False or snap.get('real_network_calls') is not False:raise source_conflict()
    return AdaptationInputVersion(adaptation_id=snap['id'],target_id=snap['target_id'],check_id=snap['check_id'],manuscript_version_id=snap['manuscript']['version_id'],requirements_version=snap['requirements_version']).model_dump()

class AdaptationService(FormatService):
    def fixed(self,db,project,request):
        check=self.check_row(db,project,request.check_id)
        if check['target_id']!=request.target_id or self.store.require_task(db,check['task_id'])['status']!='succeeded' or check['result_json'] is None:raise invalid('需要相同目标的已完成固定检查。')
        base=self.manuscript(db,project,request.manuscript.id,request.manuscript.revision)
        if base['id']!=request.manuscript.version_id or check['manuscript_version_id']!=base['id']:raise invalid('检查输入与选定稿件不同，请为该组合新建检查。')
        target=self.target_row(db,project,request.target_id)['snapshot_json']
        return check,base,target

    def preview_in(self,db,project,request):
        check,base,target=self.fixed(db,project,request)
        result=plan(base['snapshot_json'],target,check['snapshot_json']['warnings'])
        current=ManuscriptService(self.assets).root(db,project,request.manuscript.id)['current_revision']
        result.update(target_id=request.target_id,check_id=request.check_id,manuscript=request.manuscript.model_dump(),expected_current_revision=current,synthetic=bool(target['synthetic'] or synthetic_input(base['snapshot_json'])),can_adopt=bool(result['actions']),display_version=DISPLAY_VERSION)
        result['preview_sha256']=digest(result)
        return result
    def preview(self,project,request):
        with self.store.connection() as db:return self.preview_in(db,project,request)

    def adaptation_row(self,db,project,identity):
        row=self.row(db,project,identity,'journal_adaptations');task=self.store.require_task(db,row['task_id']);input_version(task)
        if task['input_snapshot']!=row['snapshot_json']:raise source_conflict()
        return row
    def view_adaptation(self,db,row):
        self.validate(row)
        check=db.execute("SELECT state_json FROM task_checkpoints WHERE task_id=%s AND node='check' ORDER BY seq DESC LIMIT 1",(row['task_id'],)).fetchone()
        return dict(id=row['id'],input_snapshot=row['snapshot_json'],created_at=row['created_at'],task=self.store.public_task(self.store.require_task(db,row['task_id'])),result=row['result_json'],validation=check['state_json'] if check else None)
    def get_adaptation(self,project,identity):
        with self.store.connection() as db:return self.view_adaptation(db,self.adaptation_row(db,project,identity))
    def adaptations(self,project):
        with self.store.connection() as db:
            self.project(db,project)
            return dict(items=[self.view_adaptation(db,self.adaptation_row(db,project,r['id'])) for r in db.execute('SELECT id FROM journal_adaptations WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id',(project,self.store.user_id)).fetchall()])
    def create_adaptation(self,project,request,key):
        require_key(key);body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.project(db,project,True);old=self.replay(db,'journal_adaptations',project,key,body)
            if old:return self.view_adaptation(db,self.adaptation_row(db,project,old['id'])),200
            preview=self.preview_in(db,project,request)
            if request.expected_current_revision!=preview['expected_current_revision']:raise invalid('稿件已有新版本，请刷新。','manuscript_revision_conflict')
            if preview['preview_sha256']!=request.preview_sha256:raise invalid('请重新查看固定输入的差异预览。','journal_adaptation_preview_conflict')
            actions=[a for a in preview['actions'] if a['id'] in request.selected_action_ids]
            if len(actions)!=len(request.selected_action_ids):raise invalid('所选动作不属于当前可执行预览。')
            if not actions:raise invalid('没有可执行差异，不生成空新版本。','journal_adaptation_no_changes')
            check,base,target=self.fixed(db,project,request)
            identity=str(uuid4());timestamp=now()
            snap=dict(id=identity,kind='journal_adaptation',project_id=project,workflow_version=WORKFLOW,target_id=request.target_id,check_id=request.check_id,manuscript=request.manuscript.model_dump(),base_sha256=base['snapshot_sha256'],requirements_version=target['guide']['requirements_version'],expected_current_revision=request.expected_current_revision,preview_sha256=request.preview_sha256,preview=preview,selected_action_ids=request.selected_action_ids,synthetic=preview['synthetic'],real_model_calls=False,real_network_calls=False)
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='journal_adaptation',idempotency_key='journal-adapt:'+identity,input_digest=digest(snap),input_snapshot=snap,workflow_version=WORKFLOW,status='queued',phase='verify',revision=1,current_attempt=0,reason_code=None,created_at=timestamp,updated_at=timestamp)
            self.store.insert_task(db,task);self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            self.insert(db,'journal_adaptations',project,key,body,snap,target_id=request.target_id,check_id=request.check_id,task_id=task['id'],manuscript_id=base['manuscript_id'],manuscript_version_id=base['id'])
            return self.view_adaptation(db,self.adaptation_row(db,project,identity)),202

    def compute(self,db,row):
        from .adaptation_contracts import AdaptationRequest
        request=AdaptationRequest.model_validate(row['request_json']);check,base,target=self.fixed(db,row['project_id'],request)
        frozen=row['snapshot_json']
        if base['snapshot_sha256']!=frozen['base_sha256']:raise source_conflict()
        replanned=plan(base['snapshot_json'],target,check['snapshot_json']['warnings'])
        if replanned['actions']!=frozen['preview']['actions']:raise source_conflict()
        actions=[a for a in replanned['actions'] if a['id'] in frozen['selected_action_ids']]
        candidate=apply(base['snapshot_json'],actions)
        if candidate.get('journal_display_context')==base['snapshot_json'].get('journal_display_context'):raise invalid('没有实际变化。','journal_adaptation_no_changes')
        from app.domain.manuscript_review.checks import check_snapshot
        from app.domain.manuscript_review.writing_context import load_writing_context
        ms=ManuscriptService(self.assets)
        ms.verify_task(db,self.store.require_task(db,base['task_id']),current=True)
        for guide in [target['guide'],*target.get('additional_guides',[])]:
            if guide.get('material'):
                selected={k:guide['material'][k] for k in ('kind','id','file_id')}
                if self.material(row['project_id'],selected)!=guide['material']:raise source_conflict()
        context=load_writing_context(ms,db,row['project_id'],base['manuscript_id'],base['snapshot_json'],check_version=2)
        issues=check_snapshot(candidate,writing_context=context)
        candidate['journal_adaptation_provenance']=dict(adaptation_id=row['id'],base_version_id=base['id'],input_sha256=row['snapshot_sha256'],display_version=DISPLAY_VERSION,synthetic=frozen['synthetic'])
        unexecuted=replanned['unexecuted']+[dict(key=a['key'],evidence=a['evidence'],reason='用户未采用此项。') for a in replanned['actions'] if a['id'] not in frozen['selected_action_ids']]
        return base,candidate,dict(actual_changes=actions,unexecuted=unexecuted,public_issues=issues,public_check_version=3,synthetic=frozen['synthetic'],display_version=DISPLAY_VERSION)

    def retry_adaptation(self,project,identity):
        with self.store.connection(write=True) as db:
            self.project(db,project,True);row=self.adaptation_row(db,project,identity);task=self.store.require_task(db,row['task_id'])
            retry_in_transaction(self.store,db,task,task['revision']);return self.view_adaptation(db,row)

def retry_in_transaction(store,db,task,expected_revision):
    if task['task_type']!='journal_adaptation' or task['status']!='failed' or task['revision']!=expected_revision:raise invalid('仅可重试当前失败的期刊适配任务。')
    from app.domain.report_collections.service import scoped_store
    service=AdaptationService(scoped_store(task['user_id'],store.config));row=service.adaptation_row(db,task['project_id'],input_version(task)['adaptation_id'])
    if row['result_json'] is not None:raise source_conflict()
    task.update(status='queued',revision=expected_revision+1,reason_code='retry_requested',error_code=None,updated_at=max(now(),task['updated_at']),_retry_reason='manual_retry')
    store.update_task(db,task,expected_revision);store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)

def validate_adapted_version(manuscripts,db,version):
    from app.domain.report_collections.service import scoped_store
    service=AdaptationService(scoped_store(version['user_id'],manuscripts.store.config,manuscripts.assets.directory))
    provenance=version['snapshot_json']['journal_adaptation_provenance']
    row=service.adaptation_row(db,version['project_id'],provenance.get('adaptation_id'))
    if row['output_version_id']!=version['id'] or not row['result_json'] or row['result_json']['output']['parent_version_id']!=version['parent_version_id'] or row['snapshot_sha256']!=provenance.get('input_sha256'):raise source_conflict()
    base=manuscripts.version(db,version['project_id'],version['manuscript_id'],row['snapshot_json']['manuscript']['revision'])
    selected=[a for a in row['snapshot_json']['preview']['actions'] if a['id'] in row['snapshot_json']['selected_action_ids']]
    result=row['result_json']
    if result['actual_changes']!=selected or any(i['severity']=='error' for i in result['public_issues']) or result['output']!=dict(manuscript_id=version['manuscript_id'],version_id=version['id'],revision=version['revision'],parent_version_id=version['parent_version_id'],task_id=version['task_id']):raise source_conflict()
    expected=apply(base['snapshot_json'],selected)
    expected['journal_adaptation_provenance']=dict(adaptation_id=row['id'],base_version_id=base['id'],input_sha256=row['snapshot_sha256'],display_version=DISPLAY_VERSION,synthetic=row['snapshot_json']['synthetic'])
    if expected!=version['snapshot_json'] or base['id']!=version['parent_version_id']:raise source_conflict()
