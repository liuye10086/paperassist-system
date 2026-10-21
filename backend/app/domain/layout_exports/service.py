"""Seal exact successful DOCX objects; never select a newer upstream version."""
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.manuscripts.service import now
from app.domain.literature.service import digest
from .contracts import WORKFLOW,LAYOUT_VERSION,LayoutCreateRequest

RETRYABLE=frozenset(('pdf_renderer_unavailable','pdf_conversion_timeout','pdf_renderer_busy','storage_unavailable','task_worker_interrupted','pdf_conversion_failed','layout_field_update_failed'))

def renderer_identity():
    from app.adapters.pdf_renderer import renderer_identity as identity
    return identity()

def missing(): return StorageError('layout_docx_not_found','排版DOCX导出不存在。',404)

class LayoutExportService:
    def __init__(self,assets):
        self.assets=assets;self.store=TaskStore(assets.owner_id,assets.db_config)
        self.directory=Path(assets.directory)/'layout_exports'

    def source(self,db,project,kind,identity):
        from app.domain.pdf_exports.service import PdfExportService
        if kind not in ('report','collection_report','manuscript_export'):
            raise StorageError('task_input_invalid','排版来源类型无效。',422)
        return PdfExportService(self.assets).source(db,project,kind,identity)

    def language(self,db,source):
        kind=source['source_kind']
        if kind=='manuscript_export':
            row=db.execute('SELECT snapshot_json FROM manuscript_versions WHERE id=%s',(source['version']['id'],)).fetchone()
            return row['snapshot_json']['output_language']
        if kind=='collection_report':
            return db.execute('SELECT language FROM report_collection_versions WHERE id=%s',(source['version']['id'],)).fetchone()['language']
        return source['metadata']['language']

    def retry_chain(self,db,row):
        """One root plus at most three children; every parent has one successor."""
        ancestor=row;seen={row['id']}
        while ancestor['parent_export_id']:
            ancestor=self.row(db,row['project_id'],ancestor['parent_export_id'])
            if ancestor['id'] in seen or len(seen)>=4: raise source_conflict()
            seen.add(ancestor['id'])
        chain=[ancestor['id']]
        while True:
            children=db.execute('''SELECT id FROM layout_exports
                WHERE parent_export_id=%s AND project_id=%s AND user_id=%s LIMIT 2''',
                (chain[-1],row['project_id'],self.store.user_id)).fetchall()
            if not children: return chain
            if len(children)!=1 or len(chain)>=4 or children[0]['id'] in chain:
                raise source_conflict()
            chain.append(children[0]['id'])

    def can_retry(self,db,row,task):
        chain=self.retry_chain(db,row)
        return (task['status']=='failed' and task.get('error_code') in RETRYABLE
            and len(chain)<4 and chain[-1]==row['id'])

    def config(self,project):
        with self.store.connection() as db: self.store.require_project(db,project)
        return dict(workflow_version=WORKFLOW,layout_version=LAYOUT_VERSION,real_model_calls=False,
            source_kinds=['report','collection_report','manuscript_export'],max_retries=3)

    def catalog(self,project,kind,identity):
        from app.adapters.document_layout import catalog_docx
        with self.store.connection() as db:
            source,raw=self.source(db,project,kind,identity)
            return dict(**catalog_docx(raw),source_kind=kind,source_id=identity,filename=source['metadata']['filename'],
                version=source['version'],output_language=self.language(db,source))

    def sources(self,project):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            queries={
                'report': 'SELECT r.id FROM reports r JOIN analysis_runs a ON a.id=r.analysis_run_id JOIN files f ON f.id=a.file_id WHERE f.project_id=%s',
                'collection_report': "SELECT r.id FROM collection_reports r JOIN report_collection_versions v ON v.id=r.version_id JOIN report_collections c ON c.id=v.collection_id JOIN report_build_requests q ON q.id=r.build_request_id JOIN tasks t ON t.id=q.task_id WHERE c.project_id=%s AND t.status='succeeded'",
                'manuscript_export': "SELECT e.id FROM manuscript_exports e JOIN manuscript_versions v ON v.id=e.version_id JOIN tasks t ON t.id=e.task_id WHERE v.project_id=%s AND t.status='succeeded'"}
            items=[]
            for kind,sql in queries.items():
                for row in db.execute(sql,(project,)).fetchall():
                    source,raw=self.source(db,project,kind,row['id'])
                    items.append(dict(source_kind=kind,source_id=row['id'],filename=source['metadata']['filename'],
                        source_sha256=sha256(raw).hexdigest(),source_size=len(raw),version=source['version'],output_language=self.language(db,source)))
            return dict(items=items)

    def row(self,db,project,identity):
        self.store.require_project(db,project)
        row=db.execute('SELECT * FROM layout_exports WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row: raise missing()
        return row

    def verify(self,db,row):
        task=self.store.require_task(db,row['task_id'])
        snap=row['input_json']
        from .contracts import RequiredLayoutOptions
        from pydantic import ValidationError
        try:
            layout=RequiredLayoutOptions.model_validate(snap['layout'])
        except (ValidationError,KeyError,TypeError):
            raise source_conflict() from None
        if layout.model_dump(mode='json')!=snap['layout'] or layout.source_sha256!=row['source_sha256']:
            raise source_conflict()
        if (row['input_sha256']!=digest(snap) or task['input_digest']!=digest(task['input_snapshot']) or task['input_snapshot']!=dict(export_id=row['id'],**snap)
            or task['task_type']!='layout_docx' or task['workflow_version']!=WORKFLOW or task['project_id']!=row['project_id']
            or task['user_id']!=row['user_id'] or snap.get('project_id')!=row['project_id'] or snap.get('source_kind')!=row['source_kind']
            or snap.get('workflow_version')!=WORKFLOW or snap.get('source_id')!=row['source_id'] or snap.get('source_sha256')!=row['source_sha256'] or snap.get('renderer_identity')!=row['renderer_identity'] or snap.get('layout_version')!=row['layout_version'] or row['layout_version']!=LAYOUT_VERSION): raise source_conflict()
        column={'report':'report_id','collection_report':'collection_report_id','manuscript_export':'manuscript_export_id'}[row['source_kind']]
        if row[column]!=row['source_id']: raise source_conflict()
        request=dict(source_kind=row['source_kind'],source_id=row['source_id'],parent_export_id=row['parent_export_id'],layout=snap['layout'])
        if digest(request)!=row['request_digest']: raise source_conflict()
        if row['parent_export_id']:
            parent=self.row(db,row['project_id'],row['parent_export_id'])
            parent_task=self.store.require_task(db,parent['task_id'])
            if (parent['id']==row['id'] or parent['created_at']>row['created_at']
                or parent['input_json']!=snap or parent_task['status']!='failed'
                or parent_task.get('error_code') not in RETRYABLE):
                raise source_conflict()
        self.retry_chain(db,row)
        return task

    def verify_source(self,db,row):
        self.verify(db,row)
        source,raw=self.source(db,row['project_id'],row['source_kind'],row['source_id'])
        if (source!=row['input_json']['source'] or sha256(raw).hexdigest()!=row['source_sha256']
            or self.language(db,source)!=row['input_json']['output_language']): raise source_conflict()
        return raw

    def view(self,db,row):
        task=self.verify(db,row);meta=row['metadata_json'] or {}
        if bool(meta)!=(task['status']=='succeeded'): raise source_conflict()
        if meta and (meta.get('source_sha256')!=row['source_sha256'] or meta.get('input_sha256')!=row['input_sha256'] or meta.get('renderer_manifest')!=row['renderer_identity']): raise source_conflict()
        return dict(id=row['id'],project_id=row['project_id'],source_kind=row['source_kind'],source_id=row['source_id'],status=task['status'],task_id=row['task_id'],created_at=row['created_at'].isoformat(),
            layout=row['input_json']['layout'],output_language=row['input_json']['output_language'],layout_version=row['layout_version'],request_key=row['request_key'],can_retry=self.can_retry(db,row,task),filename=meta.get('filename'),error_code=task.get('error_code'),source_sha256=row['source_sha256'],parent_export_id=row['parent_export_id'],renderer_manifest=meta.get('renderer_manifest'),sha256=meta.get('sha256'),size_bytes=meta.get('size_bytes'),
            download_url=f"/api/v1/projects/{row['project_id']}/layout-exports/{row['id']}/download" if meta else None)

    def create(self,project,request,parent=None):
        request=LayoutCreateRequest.model_validate(request) if isinstance(request,dict) else request
        body=dict(source_kind=request.source_kind,source_id=request.source_id,parent_export_id=parent,layout=request.layout.model_dump(mode='json'));hashed=digest(body)
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project);db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            existing=db.execute('SELECT * FROM layout_exports WHERE project_id=%s AND user_id=%s AND request_key=%s',(project,self.store.user_id,request.request_key)).fetchone()
            if existing:
                if existing['request_digest']!=hashed: raise StorageError('task_idempotency_conflict','请求标识已用于不同输入。',409)
                return self.view(db,existing),200
            previous=None
            if parent:
                previous=self.row(db,project,parent);task=self.verify(db,previous)
                if not self.can_retry(db,previous,task):
                    raise StorageError('layout_retry_not_allowed','此排版DOCX任务不可重试。',409)
            source,raw=self.source(db,project,request.source_kind,request.source_id)
            from app.adapters.document_layout import apply_layout
            language=self.language(db,source)
            apply_layout(raw,request.layout,language=language)
            identity=renderer_identity()
            if previous and (source!=previous['input_json']['source'] or identity!=previous['renderer_identity']): raise source_conflict()
            export_id=str(uuid4());timestamp=now();source_hash=sha256(raw).hexdigest()
            snapshot=dict(project_id=project,source_kind=request.source_kind,source_id=request.source_id,source_sha256=source_hash,source=source,renderer_identity=identity,workflow_version=WORKFLOW,layout=body['layout'],layout_version=LAYOUT_VERSION,output_language=language)
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='layout_docx',idempotency_key='layout:'+export_id,input_snapshot=dict(export_id=export_id,**snapshot),workflow_version=WORKFLOW,status='queued',phase='export',revision=1,current_attempt=0,reason_code=None,created_at=timestamp,updated_at=timestamp)
            task['input_digest']=digest(task['input_snapshot'])
            self.store.insert_task(db,task);self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            column={'report':'report_id','collection_report':'collection_report_id','manuscript_export':'manuscript_export_id'}[request.source_kind]
            fields=dict(id=export_id,project_id=project,user_id=self.store.user_id,source_kind=request.source_kind,source_id=request.source_id,task_id=task['id'],parent_export_id=parent,request_key=request.request_key,request_digest=hashed,input_json=Jsonb(snapshot),input_sha256=digest(snapshot),source_sha256=source_hash,renderer_identity=Jsonb(identity),layout_version=LAYOUT_VERSION,created_at=timestamp)
            fields[column]=request.source_id
            db.execute('INSERT INTO layout_exports('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))
            return self.view(db,self.row(db,project,export_id)),201

    def retry(self,project,identity,key):
        with self.store.connection() as db: row=self.row(db,project,identity)
        return self.create(project,dict(source_kind=row['source_kind'],source_id=row['source_id'],request_key=key,layout=row['input_json']['layout']),identity)

    def get(self,project,identity):
        with self.store.connection() as db: return self.view(db,self.row(db,project,identity))

    def list(self,project,source_kind=None,source_id=None):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            rows=db.execute('SELECT * FROM layout_exports WHERE project_id=%s AND user_id=%s AND (%s::text IS NULL OR source_kind=%s) AND (%s::text IS NULL OR source_id=%s) ORDER BY created_at DESC,id',(project,self.store.user_id,source_kind,source_kind,source_id,source_id)).fetchall()
            return dict(items=[self.view(db,row) for row in rows])

    @staticmethod
    def object_name(row,meta):
        from uuid import UUID
        name=meta.get('object_name','')
        prefix=row['id']+'-'
        try:
            token=name.removeprefix(prefix).removesuffix('.docx')
            if name!=prefix+str(UUID(token))+'.docx': raise ValueError()
        except (ValueError,TypeError,AttributeError): raise source_conflict()
        return name

    def download(self,project,identity):
        with self.store.connection() as db:
            row=self.row(db,project,identity);view=self.view(db,row)
            if view['status']!='succeeded': raise StorageError('layout_docx_not_ready','排版DOCX尚未成功。',409)
            self.verify_source(db,row);meta=row['metadata_json']
        try: raw=(self.directory/self.object_name(row,meta)).read_bytes()
        except FileNotFoundError as exc: raise StorageError('report_missing','排版DOCX文件缺失。',410) from exc
        if sha256(raw).hexdigest()!=meta['sha256'] or len(raw)!=meta['size_bytes'] or not raw.startswith(b'PK'): raise StorageError('report_changed','排版DOCX内容已变化。',409)
        return meta,raw


def input_version(task):
    from .contracts import LayoutInputVersion
    snap=task['input_snapshot']
    return LayoutInputVersion(**{k:snap[k] for k in ('export_id','source_kind','source_id','source_sha256')}).model_dump()
