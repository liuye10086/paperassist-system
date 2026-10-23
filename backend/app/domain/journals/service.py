"""Versioned journal intake and frozen, task-backed recommendation requests."""
from datetime import datetime,timezone
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from .contracts import WORKFLOW,FIELDS,SOURCE_TYPES


def now():return datetime.now(timezone.utc)
def invalid(message,status=409):return StorageError('task_input_invalid',message,status)

def input_version(task):
    snap=task['input_snapshot']
    if task['task_type']!='journal_recommendation' or task['workflow_version']!=WORKFLOW or digest(snap)!=task['input_digest'] or snap.get('project_id')!=task['project_id'] or snap.get('workflow_version')!=WORKFLOW or snap.get('real_model_calls') is not False or snap.get('real_network_calls') is not False:raise source_conflict()
    return dict(kind='journal_recommendation',recommendation_id=snap['recommendation_id'],workflow_version=WORKFLOW)

class JournalService:
    def __init__(self,assets):self.assets=assets;self.store=TaskStore(assets.owner_id,assets.db_config)
    def project(self,db,project,lock=False):
        row=self.store.require_project(db,project)
        if row['project_type']!='sci':raise invalid('本批期刊建议仅用于SCI项目。',422)
        if lock:db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
        return row
    def config(self,project):
        from .configuration import configuration
        with self.store.connection() as db:
            self.project(db,project);policy=configuration(db,project,self.store.user_id)
        from .format_contracts import FORMAT_WORKFLOW,CHECK_VERSION,RULE_KEYS,COUNT_METHODS,STATUSES
        return dict(format_check=dict(workflow_version=FORMAT_WORKFLOW,check_version=CHECK_VERSION,rule_keys=list(RULE_KEYS),count_methods=list(COUNT_METHODS),statuses=list(STATUSES),extraction='finite_explicit_lines_v1'),workflow_version=WORKFLOW,real_model_calls=False,real_network_calls=False,fields=list(FIELDS),source_types=list(SOURCE_TYPES),default_limit=3,max_limit=5,metrics_enabled=False,material_kinds=['original','document_version','ocr_review_version','external_evidence_version'],**policy)
    def row(self,db,project,identity,table='journal_recommendations'):
        assert table in ('journal_profiles','journal_recommendations')
        self.project(db,project)
        row=db.execute('SELECT * FROM '+table+' WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row:raise StorageError('not_found','期刊资料或建议批次不存在。',404)
        self.validate(row);return row
    def validate(self,row):
        if digest(row['request_json'])!=row['request_digest'] or digest(row['snapshot_json'])!=row['snapshot_sha256'] or row['snapshot_json']['id']!=row['id']:raise source_conflict()
        if row.get('result_json') is not None and digest(row['result_json'])!=row['result_sha256']:raise source_conflict()
    def replay(self,db,table,project,key,body):
        row=db.execute('SELECT * FROM '+table+' WHERE project_id=%s AND user_id=%s AND idempotency_key=%s',(project,self.store.user_id,key)).fetchone()
        if row and row['request_digest']!=digest(body):raise StorageError('task_idempotency_conflict','请求标识已用于不同输入。',409)
        if row:self.validate(row)
        return row
    def material(self,project,selection):
        from app.domain.manuscripts.sources import read_source
        return read_source(self,project,selection)
    def references(self,db,project,parent,materials,profile=False):
        for material in materials:
            kind=material['kind'];columns={k:None for k in ('document_version_id','ocr_review_version_id','external_evidence_version_id')}
            if kind!='original':columns[kind+'_id']=material['id']
            db.execute('''INSERT INTO journal_material_refs(id,project_id,user_id,profile_id,recommendation_id,file_id,document_version_id,ocr_review_version_id,external_evidence_version_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(str(uuid4()),project,self.store.user_id,parent if profile else None,None if profile else parent,material['file_id'],*columns.values()))
    def create_profile(self,project,request,key):
        require_key(key);body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.project(db,project,True);old=self.replay(db,'journal_profiles',project,key,body)
            if old:return old['snapshot_json'],200
            parent=self.row(db,project,request.previous_version_id,'journal_profiles') if request.previous_version_id else None
            if parent and parent['snapshot_json']['synthetic'] and request.source_type!='synthetic':raise invalid('合成来源链不能升级为真实期刊材料。',422)
            if parent and db.execute('SELECT id FROM journal_profiles WHERE previous_version_id=%s',(parent['id'],)).fetchone():raise invalid('来源已有后续版本，请在后续版本上继续更新。')
            material=self.material(project,request.material) if request.material else None
            for evidence in request.fields.values():
                if evidence.status!='verified':continue
                if evidence.quote in request.source_text:continue
                items=(material or {}).get('content',{}).get('items',[])
                if not any(evidence.quote in item.get('text','') and (evidence.location==item.get('id') or evidence.location==str(item.get('location'))) for item in items):
                    raise invalid('字段引文未在所登记原文或材料的对应位置找到。',422)
            identity=str(uuid4());timestamp=now()
            snap=body|dict(id=identity,project_id=project,synthetic=request.source_type=='synthetic',verification_level='synthetic_material_only' if request.source_type=='synthetic' else 'user_material_only',material=material,created_at=timestamp.isoformat())
            for evidence in snap['fields'].values():
                if evidence['verified_on'] is None:evidence['verified_on']=body['verified_on']
            db.execute('''INSERT INTO journal_profiles(id,project_id,user_id,idempotency_key,request_json,request_digest,snapshot_json,snapshot_sha256,created_at,previous_version_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(identity,project,self.store.user_id,key,Jsonb(body),digest(body),Jsonb(snap),digest(snap),timestamp,request.previous_version_id))
            if material:self.references(db,project,identity,[material],True)
            return snap,201
    def profiles(self,project):
        with self.store.connection() as db:
            self.project(db,project);rows=db.execute('SELECT * FROM journal_profiles WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id',(project,self.store.user_id)).fetchall()
            for row in rows:self.validate(row)
            return dict(items=[r['snapshot_json'] for r in rows])
    def profile(self,project,identity):
        with self.store.connection() as db:return self.row(db,project,identity,'journal_profiles')['snapshot_json']
    def create(self,project,request,key):
        require_key(key);body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.project(db,project,True);old=self.replay(db,'journal_recommendations',project,key,body)
            if old:return self.view(db,old),200
            if request.profile_ids is None:
                rows=db.execute('''SELECT p.* FROM journal_profiles p WHERE p.project_id=%s AND p.user_id=%s AND NOT EXISTS(SELECT 1 FROM journal_profiles n WHERE n.previous_version_id=p.id) ORDER BY p.id''',(project,self.store.user_id)).fetchall()
            else:
                if len(set(request.profile_ids))!=len(request.profile_ids):raise invalid('资料版本不能重复。',422)
                rows=[self.row(db,project,i,'journal_profiles') for i in request.profile_ids]
            for row in rows:self.validate(row)
            materials=[self.material(project,m) for m in request.materials];manuscript=None
            if request.manuscript:
                m=request.manuscript
                from app.domain.manuscripts.service import ManuscriptService
                manuscripts=ManuscriptService(self.assets)
                row=manuscripts.version(db,project,m.id,m.revision)
                producer=self.store.require_task(db,row['task_id'])
                if producer['status']!='succeeded':raise invalid('指定稿件版本尚未发布。')
                manuscripts.verify_task(db,producer,current=True)
                manuscript=dict(id=m.id,revision=m.revision,version_id=row['id'],snapshot=row['snapshot_json'],sha256=row['snapshot_sha256'])
            identity=str(uuid4());timestamp=now()
            snap=dict(id=identity,kind='journal_recommendation',recommendation_id=identity,project_id=project,workflow_version=WORKFLOW,research=body,materials=materials,manuscript=manuscript,profiles=[r['snapshot_json'] for r in rows],real_model_calls=False,real_network_calls=False)
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='journal_recommendation',idempotency_key='journal:'+identity,input_digest=digest(snap),input_snapshot=snap,workflow_version=WORKFLOW,status='queued',phase='plan',revision=1,current_attempt=0,reason_code=None,created_at=timestamp,updated_at=timestamp)
            self.store.insert_task(db,task);self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            db.execute('''INSERT INTO journal_recommendations(id,project_id,user_id,idempotency_key,request_json,request_digest,snapshot_json,snapshot_sha256,created_at,task_id,manuscript_id,manuscript_revision) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(identity,project,self.store.user_id,key,Jsonb(body),digest(body),Jsonb(snap),digest(snap),timestamp,task['id'],request.manuscript.id if request.manuscript else None,request.manuscript.revision if request.manuscript else None))
            self.references(db,project,identity,materials)
            return self.view(db,self.row(db,project,identity)),202
    def view(self,db,row):
        self.validate(row);task=self.store.require_task(db,row['task_id']);input_version(task)
        if task['input_snapshot']!=row['snapshot_json']:raise source_conflict()
        return dict(id=row['id'],input_snapshot=row['snapshot_json'],created_at=row['created_at'],task=self.store.public_task(task),result=row['result_json'])
    def get(self,project,identity):
        with self.store.connection() as db:return self.view(db,self.row(db,project,identity))
    def list(self,project):
        with self.store.connection() as db:
            self.project(db,project);rows=db.execute('SELECT * FROM journal_recommendations WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id',(project,self.store.user_id)).fetchall()
            return dict(items=[self.view(db,r) for r in rows])
    def retry(self,project,identity):
        with self.store.connection(write=True) as db:
            self.project(db,project,True);row=self.row(db,project,identity);task=self.store.require_task(db,row['task_id'])
            retry_in_transaction(self.store,db,task,task['revision']);return self.view(db,row)


def retry_in_transaction(store,db,task,expected_revision):
    if task['task_type']!='journal_recommendation' or task['status']!='failed' or task['revision']!=expected_revision:raise invalid('仅可重试当前失败的期刊建议任务。')
    from app.domain.report_collections.service import scoped_store
    service=JournalService(scoped_store(task['user_id'],store.config));row=service.row(db,task['project_id'],input_version(task)['recommendation_id']);service.view(db,row)
    if row['result_json'] is not None:raise source_conflict()
    task.update(status='queued',revision=expected_revision+1,reason_code='retry_requested',error_code=None,updated_at=max(now(),task['updated_at']),_retry_reason='manual_retry')
    store.update_task(db,task,expected_revision);store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)
