"""Transactional collection versions and durable local export intents."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.report_store import digest
from app.adapters.task_store import TaskStore
from app.core.exceptions import StorageError
from app.domain.report_collections.contracts import CollectionRequest, RENDERER, freeze_collection, invalid, request_key, json_value


def now(): return datetime.now(timezone.utc)

class CollectionStore:
    def __init__(self,store):
        self.store=store
        self.tasks=TaskStore(store.owner_id,store.db_config)
        self.directory=Path(store.directory)/'collection_reports'

    def project(self,db,project_id,lock=False):
        result=self.tasks.require_project(db,project_id)
        if lock: db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project_id,)).fetchone()
        return result

    def require_collection(self,db,project_id,collection_id,lock=False):
        self.project(db,project_id)
        row=db.execute('SELECT * FROM report_collections WHERE id=%s AND project_id=%s'+(' FOR UPDATE' if lock else ''),(collection_id,project_id)).fetchone()
        if not row: raise StorageError('collection_not_found','报告集合不存在。',404)
        return dict(row)

    def read_bundle(self,project_id,figure_id,explanation_id=None):
        from app.adapters.figure_workbench_store import read_bundle
        self.require_compatible_figure(project_id,figure_id)
        value=read_bundle(self.store,project_id,figure_id,explanation_id)
        return self.enrich_bundle(project_id,value)

    def require_compatible_figure(self,project_id,figure_id):
        with self.store.connection() as db:
            self.project(db,project_id)
            row=db.execute('''SELECT f.figure_config_version_id FROM figures f JOIN analysis_runs a ON a.id=f.analysis_run_id
                JOIN files x ON x.id=a.file_id WHERE f.id=%s AND x.project_id=%s''',(figure_id,project_id)).fetchone()
            if not row: raise StorageError('figure_missing','图表不存在。',404)
            if row['figure_config_version_id'] is None: raise invalid('collection_legacy_numbering')

    def read_config_bundle(self,project_id,config_id):
        from app.adapters.figure_workbench_store import FigureWorkbenchStore
        workbench=FigureWorkbenchStore(self.store)
        with self.store.connection() as db:
            self.project(db,project_id)
            row=db.execute('''SELECT c.analysis_run_id,a.file_id FROM figure_config_versions v
                JOIN figure_configurations c ON c.id=v.configuration_id JOIN analysis_runs a ON a.id=c.analysis_run_id
                WHERE v.id=%s AND c.project_id=%s''',(config_id,project_id)).fetchone()
            if not row: raise invalid()
        version,result,computed,_,expected=workbench.material(project_id,row['file_id'],row['analysis_run_id'],config_id)
        with self.store.connection() as db: projection=workbench._projection(db,version)
        if not projection or projection['result']!=computed: raise StorageError('collection_dependencies_missing','请先确认图表描述性投影，再将该配置加入集合。',409)
        return self.enrich_bundle(project_id,{'result':result,'figure':None,'explanation':None,
            'configuration':workbench.public_version(version),'projection':projection,'planned_caption':expected['caption'],'planned_title':expected['title']})

    def enrich_bundle(self,project_id,value):
        from app.domain.dataset_profile.service import DatasetProfileService
        source=value['result']['source']
        value['profile']=DatasetProfileService(self.store).profile(project_id,source['file_id'],source['dataset_id'])
        with self.store.connection() as db:
            row=db.execute('SELECT recipe_json,summary_json FROM prepared_dataset_versions WHERE id=%s',(source['dataset_id'],)).fetchone()
        if not row: raise invalid()
        value['processing']={'recipe':row['recipe_json'],'receipt':row['summary_json']}
        if source.get('schema_version') in (2,3):
            from app.domain.dataset_processing import load_processing
            value['processing'] = load_processing(self.store,project_id,source)
        if value['configuration'].get('figure_contract') in (2,3):
            value['dependency_engine']='figure_explanation_v4' if value['configuration']['figure_contract']==3 else 'figure_explanation_v2'
        return json_value(value)

    def candidates(self,project_id,file_id=None):
        with self.store.connection() as db:
            self.project(db,project_id)
            rows=db.execute('''SELECT g.id FROM figures g JOIN analysis_runs r ON r.id=g.analysis_run_id
                JOIN files f ON f.id=r.file_id WHERE f.project_id=%s AND g.figure_config_version_id IS NOT NULL
                AND (%s::text IS NULL OR f.id=%s) ORDER BY g.id''',(project_id,file_id,file_id)).fetchall()
            output=[]
            for row in rows:
                explanations=db.execute('SELECT id FROM explanations WHERE figure_id=%s ORDER BY id',(row['id'],)).fetchall()
                for explanation in explanations or [None]:
                    try: output.append(self.read_bundle(project_id,row['id'],explanation['id'] if explanation else None))
                    except StorageError: continue
            configs=db.execute('''SELECT v.id FROM figure_config_versions v JOIN figure_configurations c ON c.id=v.configuration_id
                JOIN analysis_runs a ON a.id=c.analysis_run_id WHERE c.project_id=%s
                AND (%s::text IS NULL OR a.file_id=%s) AND NOT EXISTS (SELECT 1 FROM figures f WHERE f.figure_config_version_id=v.id)''',(project_id,file_id,file_id)).fetchall()
            for row in configs:
                try: output.append(self.read_config_bundle(project_id,row['id']))
                except StorageError: continue
        return {'items':output}

    def requested_snapshot(self,project_id,request):
        bundles=[]
        for requested in request.items:
            item=self.read_bundle(project_id,requested.figure_id,requested.explanation_id) if requested.figure_id else self.read_config_bundle(project_id,requested.figure_config_version_id)
            item['figure_dependency_config_id']=requested.figure_config_version_id
            item['caption']=requested.caption
            item['caption_provenance']={'origin':'user','created_by':self.store.owner_id} if requested.caption is not None else {
                'origin':'figure_configuration',**({'figure_id':requested.figure_id} if requested.figure_id else {'figure_config_version_id':requested.figure_config_version_id})}
            required=item.get('dependency_engine','figure_explanation_v1')
            if not item.get('explanation') and 'explanation_engine' in requested.model_fields_set and requested.explanation_engine!=required:
                raise invalid('collection_explanation_conflict')
            item['dependency_engine']=item['explanation']['engine']['id'] if item.get('explanation') else required
            bundles.append(item)
        return freeze_collection(bundles,language=request.language,title=request.title)

    def create(self,project_id,request,key):
        request=CollectionRequest.model_validate(request.model_dump(exclude_unset=True) if isinstance(request,CollectionRequest) else request)
        request_key(key); hashed=digest(request.model_dump())
        with self.store.connection(write=True) as db:
            self.project(db,project_id,lock=True)
            existing=db.execute('SELECT * FROM report_collections WHERE project_id=%s AND created_by=%s AND creation_key=%s',(project_id,self.store.owner_id,key)).fetchone()
            if existing:
                if existing['creation_digest']!=hashed: raise StorageError('collection_idempotency_conflict','同一请求标识不能用于不同内容。',409)
                collection_id=existing['id']
            else:
                snapshot=self.requested_snapshot(project_id,request)
                collection_id=str(uuid4()); timestamp=now()
                db.execute('''INSERT INTO report_collections (id,project_id,created_by,title,current_version_id,created_at,updated_at,creation_key,creation_digest)
                    VALUES (%s,%s,%s,%s,NULL,%s,%s,%s,%s)''',(collection_id,project_id,self.store.owner_id,request.title,timestamp,timestamp,key,hashed))
                self.insert_version(db,project_id,collection_id,1,request,snapshot,key,hashed)
        return self.get(project_id,collection_id)

    def new_version(self,project_id,collection_id,request,key):
        request=CollectionRequest.model_validate(request.model_dump(exclude_unset=True) if isinstance(request,CollectionRequest) else request)
        request_key(key); hashed=digest(request.model_dump())
        with self.store.connection(write=True) as db:
            collection=self.require_collection(db,project_id,collection_id,lock=True)
            repeated=db.execute('SELECT * FROM report_collection_versions WHERE collection_id=%s AND request_key=%s',(collection_id,key)).fetchone()
            if repeated:
                if repeated['request_digest']!=hashed: raise StorageError('collection_idempotency_conflict','同一请求标识不能用于不同内容。',409)
            else:
                revision=db.execute('SELECT revision FROM report_collection_versions WHERE id=%s',(collection['current_version_id'],)).fetchone()['revision']
                if request.expected_revision!=revision: raise StorageError('collection_revision_conflict','集合已有新版本，请刷新后操作。',409)
                self.insert_version(db,project_id,collection_id,revision+1,request,self.requested_snapshot(project_id,request),key,hashed)
        return self.get(project_id,collection_id)

    def insert_version(self,db,project_id,collection_id,revision,request,snapshot,key,hashed):
        version_id=str(uuid4()); timestamp=now()
        db.execute('''INSERT INTO report_collection_versions
            (id,collection_id,revision,language,automatic,source_json,content_json,sha256,request_key,request_digest,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(version_id,collection_id,revision,request.language,request.automatic,
            Jsonb(snapshot['sources'][0]),Jsonb(snapshot),digest(snapshot),key,hashed,timestamp))
        for item in snapshot['items']:
            db.execute('''INSERT INTO report_collection_items (id,version_id,position,analysis_run_id,figure_id,figure_config_version_id,explanation_id,dependency_engine,figure_number,caption,item_json,sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(str(uuid4()),version_id,item['figure_number'],item['result']['id'],item['figure']['id'] if item['figure'] else None,item.get('figure_dependency_config_id'),
                item['explanation']['id'] if item.get('explanation') else None,item['dependency_engine'],item['figure_number'],item['caption'],Jsonb(item),digest(item)))
        db.execute('UPDATE report_collections SET current_version_id=%s,title=%s,updated_at=%s WHERE id=%s',(version_id,request.title,timestamp,collection_id))
        if request.automatic:
            build=self.insert_request(db,version_id,'automatic:v1')
            self.advance_in_transaction(db,project_id,build['id'])
        return version_id

    def insert_request(self,db,version_id,key):
        row=db.execute('SELECT * FROM report_build_requests WHERE version_id=%s AND request_key=%s',(version_id,key)).fetchone()
        if row: return dict(row)
        version=db.execute('SELECT * FROM report_collection_versions WHERE id=%s FOR UPDATE',(version_id,)).fetchone()
        revision=db.execute('SELECT COALESCE(max(export_revision),0)+1 AS n FROM report_build_requests WHERE version_id=%s',(version_id,)).fetchone()['n']
        request_id=str(uuid4()); timestamp=now()
        db.execute('''INSERT INTO report_build_requests (id,version_id,export_revision,renderer_version,request_key,request_digest,status,dependencies_json,input_json,input_sha256,task_id,created_at,updated_at,error_code)
            VALUES (%s,%s,%s,%s,%s,%s,'waiting',%s,NULL,NULL,NULL,%s,%s,NULL)''',(request_id,version_id,revision,RENDERER,key,digest({'version_id':version_id,'sha256':version['sha256'],'request_key':key}),Jsonb(version['content_json']['missing']),timestamp,timestamp))
        return dict(db.execute('SELECT * FROM report_build_requests WHERE id=%s',(request_id,)).fetchone())

    def export(self,project_id,collection_id,version_id,key):
        request_key(key)
        if key.startswith('automatic:'): raise StorageError('collection_input_invalid','请求标识使用了保留前缀。',422)
        with self.store.connection(write=True) as db:
            self.require_collection(db,project_id,collection_id,lock=True)
            version=db.execute('SELECT id FROM report_collection_versions WHERE id=%s AND collection_id=%s',(version_id,collection_id)).fetchone()
            if not version: raise StorageError('collection_not_found','集合版本不存在。',404)
            request=self.insert_request(db,version_id,key)
            self.advance_in_transaction(db,project_id,request['id'])
            return self.request_view(db,request['id'])

    def resolve_snapshot(self,db,project_id,version_id):
        version=db.execute('SELECT * FROM report_collection_versions WHERE id=%s',(version_id,)).fetchone()
        if not version or digest(version['content_json'])!=version['sha256']: raise invalid()
        original=version['content_json']; items=[]
        rows=db.execute('SELECT * FROM report_collection_items WHERE version_id=%s ORDER BY position',(version_id,)).fetchall()
        if len(rows)!=len(original['items']): raise invalid()
        for row,expected in zip(rows,original['items'],strict=True):
            if row['item_json']!=expected or digest(expected)!=row['sha256']: raise invalid()
            figure_id=row['figure_id']
            if figure_id is None:
                from app.domain.figure_workbench.presentation import renderer_for
                config=db.execute('SELECT source_json FROM figure_config_versions WHERE id=%s',(row['figure_config_version_id'],)).fetchone()
                if not config:raise invalid()
                figure=db.execute('SELECT id FROM figures WHERE figure_config_version_id=%s AND renderer_version=%s',(row['figure_config_version_id'],renderer_for(config['source_json']))).fetchall()
                if len(figure)>1: raise invalid()
                figure_id=figure[0]['id'] if figure else None
            explanation_id=row['explanation_id']
            if explanation_id is None and figure_id is not None:
                dependency=db.execute('SELECT id FROM explanations WHERE figure_id=%s AND engine_version=%s',(figure_id,row['dependency_engine'])).fetchall()
                if len(dependency)>1: raise invalid('collection_explanation_conflict')
                explanation_id=dependency[0]['id'] if dependency else None
            current=json_value(self.read_bundle(project_id,figure_id,explanation_id) if figure_id else self.read_config_bundle(project_id,row['figure_config_version_id']))
            for key in ('result','figure','configuration','projection','profile','processing'):
                if key=='figure' and expected.get('figure') is None: continue
                if current.get(key)!=expected.get(key): raise invalid()
            if expected.get('explanation') is not None and current.get('explanation')!=expected['explanation']: raise invalid('collection_explanation_conflict')
            current.update(user_caption=expected.get('user_caption'),dependency_engine=row['dependency_engine'])
            for key in ('planned_caption','planned_title'):
                if key in expected:
                    if current.get('figure') and current['figure'][key.removeprefix('planned_')]!=expected[key]: raise invalid()
                    current[key]=expected[key]
            current['caption_provenance']=expected.get('caption_provenance')
            current['figure_dependency_config_id']=expected.get('figure_dependency_config_id')
            items.append(current)
        return freeze_collection(items,language=version['language'],title=original['title'])

    def advance_in_transaction(self,db,project_id,request_id):
        row=db.execute('SELECT * FROM report_build_requests WHERE id=%s FOR UPDATE',(request_id,)).fetchone()
        if not row or row['status']!='waiting': return
        version=db.execute('SELECT * FROM report_collection_versions WHERE id=%s',(row['version_id'],)).fetchone()
        collection=self.require_collection(db,project_id,version['collection_id'])
        snapshot=self.resolve_snapshot(db,project_id,row['version_id'])
        if not snapshot['ready']:
            db.execute('UPDATE report_build_requests SET dependencies_json=%s,updated_at=%s WHERE id=%s',(Jsonb(snapshot['missing']),now(),request_id))
            return
        snapshot.update(build_request_id=request_id,collection_id=collection['id'],collection_version_id=row['version_id'],export_revision=row['export_revision'],
            project_id=project_id,output_language=snapshot['language'],workflow_version='collection_word_report_v1')
        timestamp=now()
        task=dict(id=str(uuid4()),project_id=project_id,user_id=self.store.owner_id,task_type='collection_word_report',
            idempotency_key='collection:'+request_id,input_digest=digest(snapshot),input_snapshot=snapshot,workflow_version='collection_word_report_v1',
            status='queued',phase='export',revision=1,current_attempt=0,reason_code=None,created_at=timestamp,updated_at=timestamp)
        self.tasks.insert_task(db,task); self.tasks.append_event(db,task,'created'); self.tasks.enqueue(db,task)
        db.execute("UPDATE report_build_requests SET status='queued',dependencies_json=%s,input_json=%s,input_sha256=%s,task_id=%s,updated_at=%s WHERE id=%s",
            (Jsonb([]),Jsonb(snapshot),digest(snapshot),task['id'],timestamp,request_id))

    def advance(self,project_id,request_id):
        with self.store.connection(write=True) as db:
            self.project(db,project_id)
            self.advance_in_transaction(db,project_id,request_id)

    def request_view(self,db,request_id):
        row=dict(db.execute('SELECT * FROM report_build_requests WHERE id=%s',(request_id,)).fetchone())
        report=db.execute('SELECT report_json FROM collection_reports WHERE build_request_id=%s',(request_id,)).fetchone()
        task=db.execute('SELECT status,error_code FROM tasks WHERE id=%s',(row['task_id'],)).fetchone() if row['task_id'] else None
        return {key:row[key] for key in ('id','version_id','export_revision','task_id','created_at','updated_at')}|{
            'status':'failed' if task and task['status']=='failed' else row['status'],
            'error_code':task['error_code'] if task and task['error_code'] else row['error_code'],
            'missing':row['dependencies_json'],'report':report['report_json'] if report else None}

    def get(self,project_id,collection_id):
        with self.store.connection() as db:
            collection=self.require_collection(db,project_id,collection_id)
            versions=[]
            for row in db.execute('SELECT * FROM report_collection_versions WHERE collection_id=%s ORDER BY revision DESC',(collection_id,)).fetchall():
                requests=db.execute('SELECT id FROM report_build_requests WHERE version_id=%s ORDER BY export_revision DESC',(row['id'],)).fetchall()
                versions.append({key:row[key] for key in ('id','revision','language','automatic','created_at')}|{'title':row['content_json']['title'],
                    'items':row['content_json']['items'],'requests':[self.request_view(db,x['id']) for x in requests]})
            return {key:collection[key] for key in ('id','title','current_version_id','created_at','updated_at')}|{'versions':versions}

    def list(self,project_id):
        with self.store.connection() as db:
            self.project(db,project_id)
            ids=db.execute('SELECT id FROM report_collections WHERE project_id=%s ORDER BY updated_at DESC,id',(project_id,)).fetchall()
        return {'items':[self.get(project_id,row['id']) for row in ids]}

    def preview(self,project_id,collection_id,version_id):
        with self.store.connection() as db:
            self.require_collection(db,project_id,collection_id)
            version=db.execute('SELECT id FROM report_collection_versions WHERE id=%s AND collection_id=%s',(version_id,collection_id)).fetchone()
            if not version: raise StorageError('collection_not_found','集合版本不存在。',404)
            return self.resolve_snapshot(db,project_id,version_id)

    def verify_task_snapshot(self,db,task):
        self.project(db,task['project_id'])
        snapshot=task['input_snapshot']
        if (task['task_type']!='collection_word_report' or task['workflow_version']!='collection_word_report_v1'
            or task['input_digest']!=digest(snapshot) or snapshot['project_id']!=task['project_id']): raise invalid()
        request=db.execute('SELECT * FROM report_build_requests WHERE id=%s',(snapshot['build_request_id'],)).fetchone()
        if not request or request['task_id']!=task['id'] or request['input_json']!=snapshot or request['input_sha256']!=digest(snapshot): raise invalid()
        current=self.resolve_snapshot(db,task['project_id'],snapshot['collection_version_id'])
        if any(snapshot.get(key)!=value for key,value in current.items()): raise invalid()
        return snapshot

    def content(self,metadata):
        try:
            with (self.directory/(metadata['id']+'.docx')).open('rb') as stream: raw=stream.read(metadata['size_bytes']+1)
        except FileNotFoundError as exc: raise StorageError('report_missing','集合报告文件缺失。',410) from exc
        if len(raw)!=metadata['size_bytes'] or hashlib.sha256(raw).hexdigest()!=metadata['sha256']: raise StorageError('report_changed','集合报告文件内容已改变。',409)
        return raw

    def download(self,project_id,collection_id,report_id):
        with self.store.connection() as db:
            self.require_collection(db,project_id,collection_id)
            row=db.execute('''SELECT r.*,q.task_id FROM collection_reports r JOIN report_collection_versions v ON v.id=r.version_id
                JOIN report_build_requests q ON q.id=r.build_request_id WHERE r.id=%s AND v.collection_id=%s''',(report_id,collection_id)).fetchone()
            if not row: raise StorageError('collection_not_found','集合报告不存在。',404)
            task=db.execute('SELECT * FROM tasks WHERE id=%s',(row['task_id'],)).fetchone()
            snapshot=self.verify_task_snapshot(db,dict(task))
            metadata=row['report_json']
            if (metadata['id']!=row['id'] or metadata['collection_id']!=collection_id
                or metadata['collection_version_id']!=row['version_id'] or metadata['build_request_id']!=row['build_request_id']
                or metadata['export_revision']!=row['export_revision'] or metadata['engine']['id']!=row['renderer_version']
                or row['input_json']!=snapshot or metadata['input_sha256']!=digest(snapshot) or row['sha256']!=metadata['sha256']): raise invalid()
        return metadata,self.content(metadata)
