"""Immutable, local figure language artifacts with exact source/asset binding."""
from datetime import datetime,timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from uuid import uuid4

from PIL import Image
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore,source_conflict
from app.adapters.figure_language_renderer import render_boxplot,text_item
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from .figure_language_contracts import FigureLanguageRequest


class FigureLanguageService:
    def __init__(self,assets):
        self.assets=assets;self.store=TaskStore(assets.owner_id,assets.db_config)
        self.directory=Path(assets.directory)/'manuscript_figure_language_versions'

    def require_project(self,db,project):
        row=self.store.require_project(db,project)
        if row['project_type'] not in ('sci','thesis'): raise StorageError('task_input_invalid','此项目不支持图件语言版本。',422)

    def original(self,db,project,source):
        self.require_project(db,project)
        file=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(source['file_id'],project)).fetchone()
        if not file: raise source_conflict()
        raw=self.assets.original(dict(file));content={}
        if source['kind']=='original':
            if source['id']!=file['id'] or file['file_type'] not in ('png','jpeg'): raise source_conflict()
        elif source['kind']=='figure':
            row=db.execute('SELECT f.* FROM figures f JOIN analysis_runs a ON a.id=f.analysis_run_id WHERE f.id=%s AND a.file_id=%s',(source['id'],file['id'])).fetchone()
            if not row: raise source_conflict()
            if row['figure_config_version_id']:
                from app.adapters.figure_workbench_store import read_bundle
                content=read_bundle(self.assets,project,source['id'])['figure']
            else: content=json.loads(row['figure_json'])
            if content.get('id')!=row['id'] or content.get('analysis_run_id')!=row['analysis_run_id']: raise source_conflict()
            raw=self.assets.figure_png(content)
        elif source['kind']=='document_version':
            from app.domain.documents.service import DocumentService
            documents=DocumentService(self.assets)
            row=documents.load(project,file['id'],source['id'],True)
            raw,_=documents.objects().image(row['result_json'],source['image_id'])
        else: raise source_conflict()
        return raw,content

    @staticmethod
    def verify_image(raw):
        try:
            with Image.open(BytesIO(raw)) as image:
                if image.format not in ('PNG','JPEG') or image.width*image.height>20_000_000: raise ValueError('bounds')
                image.verify()
        except (OSError,ValueError,Image.DecompressionBombError) as exc:
            raise StorageError('figure_language_invalid_image','图片损坏或超出支持范围。',422) from exc

    def png(self,row):
        snapshot=row['snapshot_json']
        try: raw=(self.directory/(row['id']+'.png')).read_bytes()
        except FileNotFoundError as exc: raise StorageError('figure_missing','图件语言版本图片缺失。',410) from exc
        if sha256(raw).hexdigest()!=snapshot['sha256'] or len(raw)!=snapshot['size_bytes']: raise source_conflict()
        return raw

    def row(self,db,project,identity):
        self.require_project(db,project)
        row=db.execute('SELECT * FROM manuscript_figure_language_versions WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row: raise StorageError('figure_language_not_found','图件语言版本不存在。',404)
        row=dict(row);snap=row['snapshot_json'];body=row['request_json']
        if digest(snap)!=row['snapshot_sha256'] or digest(body)!=row['request_digest']: raise source_conflict()
        request=FigureLanguageRequest.model_validate(body)
        original,source=self.original(db,project,body['source'])
        if sha256(original).hexdigest()!=body['original_sha256'] or snap['original']!=body['source']|{'sha256':body['original_sha256']}:
            raise source_conflict()
        if snap['id']!=row['id'] or snap['output_language']!=request.output_language or snap['mode']!=request.mode or row['file_id']!=request.source.file_id:
            raise source_conflict()
        if row['figure_id']!=(request.source.id if request.source.kind=='figure' else None) or row['document_version_id']!=(request.source.id if request.source.kind=='document_version' else None) or row['replacement_file_id']!=request.replacement_file_id:
            raise source_conflict()
        if snap['mode']=='local_boxplot':
            # Validate the frozen geometry and every label independently of PNG metadata.
            expected=render_boxplot(source,request.texts.model_dump(),request.output_language,renderer_version=snap['renderer_version'])
            expected_png=expected.pop('png')
            if any(snap.get(k)!=v for k,v in expected.items()) or sha256(expected_png).hexdigest()!=snap['sha256']: raise source_conflict()
        else:
            expected=[text_item(t.location,t.text) for t in request.text_items]
            if snap['text_manifest']!=expected: raise source_conflict()
            if request.replacement_file_id:
                file=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(request.replacement_file_id,project)).fetchone()
                if not file: raise source_conflict()
                replacement=self.assets.original(dict(file))
                if sha256(replacement).hexdigest()!=snap['sha256']: raise source_conflict()
            elif snap['sha256']!=sha256(original).hexdigest(): raise source_conflict()
        self.png(row)
        return row

    def view(self,row):
        return dict(row['snapshot_json'],snapshot_sha256=row['snapshot_sha256'],created_at=row['created_at'].astimezone(timezone.utc).isoformat(),
            download_url=f"/api/v1/projects/{row['project_id']}/manuscript-figure-language-versions/{row['id']}/download")

    def get(self,project,identity):
        with self.store.connection() as db: return self.view(self.row(db,project,identity))

    def list(self,project):
        with self.store.connection() as db:
            self.require_project(db,project)
            rows=db.execute('SELECT id FROM manuscript_figure_language_versions WHERE project_id=%s AND user_id=%s ORDER BY created_at,id',(project,self.store.user_id)).fetchall()
            return dict(items=[self.view(self.row(db,project,r['id'])) for r in rows])

    def create(self,project,request,key):
        require_key(key)
        request=FigureLanguageRequest.model_validate(request) if isinstance(request,dict) else request
        body=request.model_dump(mode='json');hashed=digest(body);target=None
        try:
            with self.store.connection(write=True) as db:
                self.require_project(db,project)
                db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
                replay=db.execute('SELECT * FROM manuscript_figure_language_versions WHERE project_id=%s AND user_id=%s AND idempotency_key=%s',(project,self.store.user_id,key)).fetchone()
                if replay:
                    if replay['request_digest']!=hashed: raise StorageError('task_idempotency_conflict','请求标识已用于不同输入。',409)
                    return self.view(self.row(db,project,replay['id'])),200
                original,source=self.original(db,project,body['source'])
                if sha256(original).hexdigest()!=request.original_sha256: raise source_conflict()
                self.verify_image(original)
                identity=str(uuid4())
                snapshot=dict(schema_version=1,id=identity,output_language=request.output_language,mode=request.mode,
                    original=body['source']|dict(sha256=request.original_sha256),reason=request.reason)
                if request.mode=='local_boxplot':
                    rendered=render_boxplot(source,request.texts.model_dump(),request.output_language)
                    raw=rendered.pop('png');snapshot.update(rendered,title=request.texts.title,caption=request.texts.caption)
                else:
                    raw=original
                    if request.replacement_file_id:
                        file=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(request.replacement_file_id,project)).fetchone()
                        if not file or file['file_type'] not in ('png','jpeg'): raise source_conflict()
                        raw=self.assets.original(dict(file));self.verify_image(raw)
                    snapshot.update(title=request.title,caption=request.caption,text_manifest=[text_item(t.location,t.text) for t in request.text_items],
                        data_fingerprint=None,geometry_fingerprint=None,renderer_version=None,font_hashes={},
                        support_scope='User supplied image inventory or explicit no-text inspection; numerical/geometry equivalence is not claimed.')
                snapshot.update(sha256=sha256(raw).hexdigest(),size_bytes=len(raw))
                self.directory.mkdir(parents=True,exist_ok=True);target=self.directory/(identity+'.png')
                with target.open('xb') as stream: stream.write(raw);stream.flush();os.fsync(stream.fileno())
                fields=dict(id=identity,project_id=project,user_id=self.store.user_id,file_id=request.source.file_id,
                    figure_id=request.source.id if request.source.kind=='figure' else None,
                    document_version_id=request.source.id if request.source.kind=='document_version' else None,
                    replacement_file_id=request.replacement_file_id,idempotency_key=key,request_digest=hashed,request_json=Jsonb(body),
                    snapshot_json=Jsonb(snapshot),snapshot_sha256=digest(snapshot),created_at=datetime.now(timezone.utc))
                db.execute('INSERT INTO manuscript_figure_language_versions('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))
                result=self.view(dict(fields,snapshot_json=snapshot))
            return result,201
        except Exception:
            if target is not None: target.unlink(missing_ok=True)
            raise
