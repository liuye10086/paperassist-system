"""Frozen inputs and one-publication journal check tasks, without review writes."""
from uuid import uuid4
from app.adapters.task_store import source_conflict
from app.domain.literature.service import digest
from app.domain.dataset_preparation.service import require_key
from .service import invalid,now
from .guides import GuideService
from .format_contracts import FORMAT_WORKFLOW,FormatInputVersion

def input_version(task):
    snap=task['input_snapshot']
    if task['task_type']!='journal_format_check' or task['workflow_version']!=FORMAT_WORKFLOW or digest(snap)!=task['input_digest'] or snap.get('kind')!='journal_format_check' or snap.get('workflow_version')!=FORMAT_WORKFLOW or snap.get('project_id')!=task['project_id'] or snap.get('real_model_calls') is not False or snap.get('real_network_calls') is not False or type(snap.get('check_version')) is not int or snap['check_version']!=1:raise source_conflict()
    return FormatInputVersion(check_id=snap['id'],target_id=snap['target']['id'],guide_id=snap['target']['guide']['id'],requirements_version=snap['target']['guide']['requirements_version'],manuscript_version_id=snap['manuscript']['version_id']).model_dump()

class FormatService(GuideService):
    def manuscript(self,db,project,identity,revision):
        from app.domain.manuscripts.service import ManuscriptService
        manuscripts=ManuscriptService(self.assets);row=manuscripts.version(db,project,identity,revision)
        producer=self.store.require_task(db,row['task_id'])
        if producer['status']!='succeeded':raise invalid('指定公共稿件版本尚未发布，请等待该版本完成。')
        manuscripts.verify_task(db,producer)
        return row

    def check_row(self,db,project,identity):
        row=self.row(db,project,identity,'journal_format_checks');snapshot=row['snapshot_json']
        target=self.target_row(db,project,row['target_id'])['snapshot_json']
        manuscript=self.manuscript(db,project,row['manuscript_id'],row['manuscript_revision'])
        if (snapshot['target']!=target or row['guide_id']!=target['guide']['id'] or manuscript['id']!=row['manuscript_version_id'] or snapshot['manuscript']['snapshot']!=manuscript['snapshot_json'] or snapshot['manuscript']['sha256']!=manuscript['snapshot_sha256']):raise source_conflict()
        task=self.store.require_task(db,row['task_id']);input_version(task)
        if task['input_snapshot']!=snapshot:raise source_conflict()
        return row

    def check_view(self,db,row):
        self.validate(row);task=self.store.require_task(db,row['task_id']);input_version(task)
        if row['snapshot_json']!=task['input_snapshot']:raise source_conflict()
        return dict(id=row['id'],input_snapshot=row['snapshot_json'],created_at=row['created_at'],task=self.store.public_task(task),result=row['result_json'])

    def create_check(self,project,request,key):
        require_key(key);body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.project(db,project,True);old=self.replay(db,'journal_format_checks',project,key,body)
            if old:return self.check_view(db,self.check_row(db,project,old['id'])),200
            target=self.target_row(db,project,request.target_id)['snapshot_json']
            m=request.manuscript;row=self.manuscript(db,project,m.id,m.revision)
            identity=str(uuid4());timestamp=now();warnings=list(target['warnings'])
            # Re-read only the explicitly frozen local guide material, never a URL
            # or newer source. A missing original remains an item-level warning.
            for guide in [target['guide'],*target.get('additional_guides',[])]:
                if guide.get('material'):
                    try:
                        selection={k:guide['material'][k] for k in ('kind','id','file_id')}
                        if self.material(project,selection)!=guide['material']:raise source_conflict()
                    except Exception as exc:
                        from app.core.exceptions import StorageError
                        if isinstance(exc,StorageError) and exc.code in ('storage_unavailable','database_configuration'):raise
                        warnings.append(dict(key='source_status',source_id=guide['id'],message='指定指南公共材料版本当前不可读或内容不匹配，相关规则待核实。',blocks_rules=True))
            snapshot=dict(id=identity,kind='journal_format_check',project_id=project,workflow_version=FORMAT_WORKFLOW,target=target,manuscript=dict(id=m.id,revision=m.revision,version_id=row['id'],snapshot=row['snapshot_json'],sha256=row['snapshot_sha256']),check_version=request.check_version,public_check_version=2,warnings=warnings,real_model_calls=False,real_network_calls=False)
            from .display import synthetic_input
            snapshot['synthetic']=bool(target['synthetic'] or synthetic_input(row['snapshot_json']))
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='journal_format_check',idempotency_key='journal-format:'+identity,input_digest=digest(snapshot),input_snapshot=snapshot,workflow_version=FORMAT_WORKFLOW,status='queued',phase='verify',revision=1,current_attempt=0,reason_code=None,created_at=timestamp,updated_at=timestamp)
            self.store.insert_task(db,task);self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            self.insert(db,'journal_format_checks',project,key,body,snapshot,target_id=target['id'],guide_id=target['guide']['id'],task_id=task['id'],manuscript_id=m.id,manuscript_revision=m.revision,manuscript_version_id=row['id'])
            return self.check_view(db,self.check_row(db,project,identity)),202

    def get_check(self,project,identity):
        with self.store.connection() as db:return self.check_view(db,self.check_row(db,project,identity))
    def checks(self,project):
        with self.store.connection() as db:
            self.project(db,project);rows=db.execute('SELECT * FROM journal_format_checks WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id',(project,self.store.user_id)).fetchall()
            return dict(items=[self.check_view(db,self.check_row(db,project,r['id'])) for r in rows])
    def retry_check(self,project,identity):
        with self.store.connection(write=True) as db:
            self.project(db,project,True);row=self.check_row(db,project,identity);task=self.store.require_task(db,row['task_id'])
            retry_in_transaction(self.store,db,task,task['revision']);return self.check_view(db,row)

    def compute(self,db,row):
        from app.domain.manuscripts.service import ManuscriptService
        from app.domain.manuscript_review.checks import check_snapshot
        from app.domain.manuscript_review.writing_context import load_writing_context
        from .format_rules import check_format
        frozen=row['snapshot_json'];manuscript=frozen['manuscript'];target=frozen['target']
        manuscripts=ManuscriptService(self.assets)
        context=load_writing_context(manuscripts,db,row['project_id'],manuscript['id'],manuscript['snapshot'],check_version=frozen['public_check_version'])
        public=check_snapshot(manuscript['snapshot'],writing_context=context)
        result=check_format(manuscript['snapshot'],target['selected_requirements'],target['conflicts'],public_issues=public,warnings=frozen['warnings'])
        result.update(synthetic=frozen.get('synthetic',target['synthetic']),target_id=target['id'],guide_id=target['guide']['id'],requirements_version=target['guide']['requirements_version'],manuscript_version_id=manuscript['version_id'],public_check_version=frozen['public_check_version'])
        return result

def retry_in_transaction(store,db,task,expected_revision):
    if task['task_type']!='journal_format_check' or task['status']!='failed' or task['revision']!=expected_revision:raise invalid('仅可重试当前失败的期刊格式检查任务。')
    from app.domain.report_collections.service import scoped_store
    service=FormatService(scoped_store(task['user_id'],store.config));row=service.check_row(db,task['project_id'],input_version(task)['check_id'])
    if row['result_json'] is not None:raise source_conflict()
    task.update(status='queued',revision=expected_revision+1,reason_code='retry_requested',error_code=None,updated_at=max(now(),task['updated_at']),_retry_reason='manual_retry')
    store.update_task(db,task,expected_revision);store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)
