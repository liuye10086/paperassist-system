"""Versioned, owner-scoped local declarations; no statistics or model calls."""
from datetime import datetime, timezone
import json
from urllib.parse import quote
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import request_digest, require_key
from app.domain.external_evidence.contracts import EvidenceRequest
from app.domain.files import require_file

MAX_SNAPSHOT_BYTES=256*1024
DECLARATIONS=('title','source_description','intended_use','original_data','user_note','limitations')


def not_found():
    return StorageError('external_evidence_not_found','外部材料版本不存在。',404)


def validate_evidence_row(db,row):
    """Read-only metadata and immutable declaration check, shared by audit."""
    try:
        request=EvidenceRequest.model_validate(row['request_json'],strict=True).model_dump(mode='json')
        snapshot=row['snapshot_json']
        if request_digest(request)!=row['request_digest'] or request_digest(snapshot)!=row['sha256']:
            raise ValueError('Evidence digest differs')
        for key in ('id','evidence_id','version','previous_version_id','project_id','file_id'):
            if snapshot[key]!=row[key]:raise ValueError('Evidence identity differs')
        if snapshot['created_at']!=row['created_at'].astimezone(timezone.utc).isoformat():
            raise ValueError('Evidence timestamp differs')
        if snapshot['verification_status']!='external_not_recomputed' or snapshot['computed_by_system'] is not False or snapshot['included_in_reports'] is not False:
            raise ValueError('External material cannot become verified results')
        if any(snapshot[k]!=request[k] for k in DECLARATIONS):raise ValueError('Declaration differs')
        if any(row[k]!=request[k] for k in ('file_id','source_kind','document_version_id','ocr_review_version_id','previous_version_id')):
            raise ValueError('Evidence request identity differs')
        file=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(row['file_id'],row['project_id'])).fetchone()
        project=db.execute('SELECT owner_id FROM projects WHERE id=%s',(row['project_id'],)).fetchone()
        if not file or not project or project['owner_id']!=row['user_id']:raise ValueError('Evidence owner differs')
        source=snapshot['source']
        if any(source[k]!=file[f] for k,f in (('file_id','id'),('filename','filename'),('file_type','file_type'),('source_sha256','sha256'),('size_bytes','size_bytes'))):
            raise ValueError('Evidence file differs')
        if source['kind']!=row['source_kind'] or [i['id'] for i in snapshot['items']]!=request['item_ids']:
            raise ValueError('Selected evidence differs')
        if row['source_kind']=='original':
            if (source['version_id'] is not None or source['version'] is not None
                    or source['sha256']!=file['sha256'] or source['review_status']!='not_reviewed'):
                raise ValueError('Original source differs')
        else:
            table='file_parse_results' if row['source_kind']=='document_version' else 'ocr_review_versions'
            version_id=row['document_version_id'] or row['ocr_review_version_id']
            version=db.execute('SELECT * FROM '+table+' WHERE id=%s',(version_id,)).fetchone()
            producer=db.execute('SELECT * FROM tasks WHERE id=%s',(version['task_id'],)).fetchone() if version else None
            if (not version or not producer or version['file_id']!=row['file_id'] or producer['status']!='succeeded'
                    or producer['user_id']!=row['user_id'] or producer['project_id']!=row['project_id']
                    or source['version_id']!=version_id or source['version']!=version['version']):
                raise ValueError('Version source differs')
            if row['source_kind']=='document_version':
                from app.domain.file_parsing import require_parse_source
                from app.maintenance.document_source_audit import validate_manifest
                require_parse_source(db,producer);validate_manifest(version['result_json'],version['id'])
                expected_hash=version['result_json']['object']['sha256'];expected_review='not_reviewed'
            else:
                from app.maintenance.ocr_review_audit import validate_parent
                validate_parent(db,producer)
                if version['created_by']!=row['user_id']:
                    raise ValueError('Review owner differs')
                expected_hash=version['sha256'];expected_review='human_reviewed'
            if source['sha256']!=expected_hash or source['review_status']!=expected_review:
                raise ValueError('Version hash or review status differs')
        current=row;seen=set()
        while current['previous_version_id'] is not None:
            if current['id'] in seen:raise ValueError('Evidence lineage cycle')
            seen.add(current['id'])
            parent=db.execute('SELECT * FROM external_evidence_versions WHERE id=%s',(current['previous_version_id'],)).fetchone()
            if (not parent or parent['version']+1!=current['version'] or any(parent[k]!=row[k] for k in ('evidence_id','project_id','user_id','file_id'))
                    or request_digest(parent['snapshot_json'])!=parent['sha256']):raise ValueError('Evidence predecessor differs')
            current=parent
        if current['version']!=1 or current['id']!=row['evidence_id']:raise ValueError('Evidence root differs')
        return dict(snapshot,sha256=row['sha256'])
    except (KeyError,TypeError,ValueError) as exc:
        raise source_conflict() from exc


class ExternalEvidenceService:
    def __init__(self,assets):
        self.assets=assets
        self.store=TaskStore(assets.owner_id,assets.db_config)

    def source(self,project,file_id,kind,version_id=None):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            file=dict(require_file(db,project,file_id))
        self.assets.original(file)
        prefix='/api/v1/projects/{}/files/{}'.format(quote(project,safe=''),quote(file_id,safe=''))
        source=dict(kind=kind,file_id=file_id,filename=file['filename'],file_type=file['file_type'],
                    source_sha256=file['sha256'],size_bytes=file['size_bytes'],original_download_url=prefix+'/download',
                    version_id=None,version=None,sha256=file['sha256'],object_download_url=None,review_status='not_reviewed')
        items=[]
        if kind=='original':
            if version_id is not None:raise StorageError('task_input_invalid','原件不接受解析版本。',422)
        elif kind=='document_version' and version_id:
            from app.domain.documents.service import DocumentService
            from app.domain.parsed_evidence.documents import docx_items,page_items
            service=DocumentService(self.assets);row=service.load(project,file_id,version_id,True)
            _,document=service.read(row)
            base=prefix+'/document-versions/'+quote(version_id,safe='')
            items=docx_items(document,base+'/images') if document.kind=='docx_document' else page_items(document)
            for item in items:
                if document.kind=='ocr_document' and item.kind=='image':item.preview_url=base+'/images/'+item.image_id
            items=[i.model_dump(mode='json') for i in items]
            source.update(version_id=version_id,version=row['version'],sha256=row['result_json']['object']['sha256'],object_download_url=base+'/download')
        elif kind=='ocr_review_version' and version_id:
            from app.domain.ocr_review.service import OcrReviewService
            row,_,document=OcrReviewService(self.assets).load_version(project,file_id,version_id)
            items=[dict(id=b.original.id,kind='text',location=b.original.source.model_dump(mode='json'),text=b.effective_text,
                        uncertainties=['unreadable'] if b.action=='unreadable' else [],review_action=b.action) for b in document.blocks]
            source.update(version_id=version_id,version=row['version'],sha256=row['sha256'],
                          object_download_url=prefix+'/ocr-review-versions/'+quote(version_id,safe='')+'/download',review_status='human_reviewed')
        else:raise StorageError('task_input_invalid','请选择明确的原件、文档版本或OCR核对版本。',422)
        return source,items

    def preview(self,project,file,kind,version_id=None,page=1):
        if type(page) is not int or not 1<=page<=1000000:raise StorageError('task_input_invalid','页码无效。',422)
        source,items=self.source(project,file,kind,version_id)
        return dict(source=source,items=items[(page-1)*20:page*20],total=len(items),page=page,page_size=20)

    def _read(self,db,project,id):
        self.store.require_project(db,project)
        row=db.execute('SELECT * FROM external_evidence_versions WHERE id=%s AND project_id=%s AND user_id=%s',
                       (id,project,self.store.user_id)).fetchone()
        if not row:raise not_found()
        return dict(row)

    def get(self,project,id):
        with self.store.connection() as db:
            row=self._read(db,project,id);view=validate_evidence_row(db,row)
        source,items=self.source(project,row['file_id'],row['source_kind'],row['document_version_id'] or row['ocr_review_version_id'])
        lookup={i['id']:i for i in items}
        try:selected=[lookup[i] for i in row['request_json']['item_ids']]
        except KeyError as exc:raise source_conflict() from exc
        if source!=view['source'] or selected!=view['items']:raise source_conflict()
        return view

    def require_versions(self,project,ids):
        if not isinstance(ids,list) or len(ids)>10 or len(set(ids))!=len(ids) or any(not isinstance(i,str) or not i for i in ids):
            raise StorageError('task_input_invalid','请选择最多10个不同的材料版本。',422)
        with self.store.connection() as db:self.store.require_project(db,project)
        return [self.get(project,id) for id in ids]

    def list(self,project,page=1,file_id=None):
        if type(page) is not int or not 1<=page<=1000000:raise StorageError('task_input_invalid','页码无效。',422)
        with self.store.connection() as db:
            self.store.require_project(db,project)
            if file_id is not None:require_file(db,project,file_id)
            where='project_id=%s AND user_id=%s';params=[project,self.store.user_id]
            if file_id is not None:where+=' AND file_id=%s';params.append(file_id)
            count=db.execute('SELECT count(*) AS n FROM external_evidence_versions WHERE '+where,tuple(params)).fetchone()['n']
            ids=[r['id'] for r in db.execute('SELECT id FROM external_evidence_versions WHERE '+where+' ORDER BY created_at DESC,id DESC LIMIT 10 OFFSET %s',(*params,(page-1)*10))]
        return dict(items=[self.get(project,id) for id in ids],total=count,page=page,page_size=10)

    def create(self,project,request,key):
        require_key(key)
        request=EvidenceRequest.model_validate(request,strict=True) if isinstance(request,dict) else request
        material=request.model_dump(mode='json');digest=request_digest(material)
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project)
            # Serializes request-key replay and predecessor selection without changing rows.
            db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            previous=db.execute('SELECT * FROM external_evidence_versions WHERE user_id=%s AND project_id=%s AND idempotency_key=%s',
                                (self.store.user_id,project,key)).fetchone()
            if previous:
                if previous['request_digest']!=digest:raise StorageError('task_idempotency_conflict','请求标识已用于其他材料。',409)
                result=validate_evidence_row(db,previous);status=200
            else:
                source,items=self.source(project,request.file_id,request.source_kind,request.document_version_id or request.ocr_review_version_id)
                lookup={i['id']:i for i in items}
                try:selected=[lookup[i] for i in request.item_ids]
                except KeyError as exc:raise StorageError('task_input_invalid','选定证据不属于此版本。',422) from exc
                id=str(uuid4());version=1;evidence_id=id
                if request.previous_version_id:
                    prior=self._read(db,project,request.previous_version_id);validate_evidence_row(db,prior)
                    if prior['file_id']!=request.file_id or db.execute('SELECT 1 FROM external_evidence_versions WHERE previous_version_id=%s',(prior['id'],)).fetchone():
                        raise StorageError('external_evidence_revision_conflict','材料已更新或来源文件不同，请读取最新版本。',409)
                    version=prior['version']+1;evidence_id=prior['evidence_id']
                now=datetime.now(timezone.utc)
                snapshot=dict(id=id,evidence_id=evidence_id,version=version,previous_version_id=request.previous_version_id,
                              project_id=project,file_id=request.file_id,created_at=now.isoformat(),source=source,items=selected,
                              **{k:material[k] for k in DECLARATIONS},verification_status='external_not_recomputed',
                              computed_by_system=False,included_in_reports=False)
                if len(json.dumps(snapshot,ensure_ascii=False).encode('utf-8'))>MAX_SNAPSHOT_BYTES:
                    raise StorageError('task_input_invalid','材料摘录过大，请减少选定片段；原件仍保留。',422)
                sha=request_digest(snapshot)
                db.execute('''INSERT INTO external_evidence_versions
                    (id,evidence_id,version,previous_version_id,project_id,user_id,file_id,source_kind,document_version_id,
                     ocr_review_version_id,idempotency_key,request_digest,request_json,snapshot_json,sha256,created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (id,evidence_id,version,request.previous_version_id,project,self.store.user_id,request.file_id,request.source_kind,
                     request.document_version_id,request.ocr_review_version_id,key,digest,Jsonb(material),Jsonb(snapshot),sha,now))
                result=dict(snapshot,sha256=sha);status=201
        # Replays receive the same full source/asset verification as fresh reads.
        return self.get(project,result['id']),status
