"""Immutable final school DOCX bytes, retained with the existing asset ledger."""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from app.domain.literature.service import digest
from app.adapters.school_docx import build_school_docx,complete_school_fields,final_school_source_map

PREFIX='manuscript_school_language'
MAPPER_VERSION='school-final-map-v2'


def _paths(root,owner,project,key):
    if any(not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',v) for v in (owner,project)) or not re.fullmatch('[0-9a-f]{64}',key):raise ValueError('Invalid school cache identity')
    from app.domain.storage_governance.service import _key
    base=Path(root)/PREFIX/owner/project/key
    paths=(base.with_suffix('.docx'),base.with_suffix('.json'))
    for path in paths:_key(root,path)
    return paths


def basis(candidate,images,plan,renderer,*,mapper_version=MAPPER_VERSION,docx_renderer=None):
    from app.adapters.manuscript_docx import RENDERER_VERSION
    projection=deepcopy(candidate)
    # Audit IDs/proofs are not rendered; all actual content and paragraph IDs
    # (which determine bookmarks) remain bound, including manual material.
    projection.pop('writing_provenance',None)
    return digest(dict(candidate=projection,plan={k:v for k,v in plan.items() if k!='snapshot_sha256'},images={k:sha256(v).hexdigest() for k,v in images.items()},mapper=mapper_version,docx_renderer=docx_renderer or RENDERER_VERSION,renderer_identity=renderer))


def descriptors(proof,owner,project):
    # Relative object keys are derived by this producer, never supplied paths.
    _paths(Path('.').absolute(),owner,project,proof['key'])
    prefix='/'.join((PREFIX,owner,project,proof['key']))
    return [dict(object_key=prefix+'.docx',sha256=proof['docx_sha256'],size_bytes=proof['docx_size_bytes']),dict(object_key=prefix+'.json',sha256=proof['receipt_sha256'],size_bytes=proof['receipt_size_bytes'])]


def read(root,owner,project,proof,*,candidate=None,images=None,plan=None):
    docx,path=_paths(root,owner,project,proof['key'])
    if proof.get('mapper_version') not in ('school-final-map-v1','school-final-map-v2') or not isinstance(proof.get('docx_renderer_version'),str):raise ValueError('School mapper version differs')
    if plan is not None and (proof['mapper_version']=='school-final-map-v2')!=(plan.get('pagination_version')==2):raise ValueError('School cache pagination differs')
    if candidate is not None and basis(candidate,images,plan,proof['renderer_identity'],mapper_version=proof['mapper_version'],docx_renderer=proof['docx_renderer_version'])!=proof['key']:raise ValueError('School rendered material differs from the reviewed basis')
    with path.open('rb') as stream:raw=stream.read(8*1024*1024+1)
    if len(raw)>8*1024*1024 or len(raw)!=proof['receipt_size_bytes'] or sha256(raw).hexdigest()!=proof['receipt_sha256']:raise ValueError('School final receipt differs')
    record=json.loads(raw)
    if any(record.get(k)!=v for k,v in dict(schema_version=1,key=proof['key'],owner_id=owner,project_id=project,mapper_version=proof['mapper_version'],docx_renderer_version=proof['docx_renderer_version'],renderer_identity=proof['renderer_identity'],docx_sha256=proof['docx_sha256'],docx_size_bytes=proof['docx_size_bytes']).items()):raise ValueError('School final receipt scope differs')
    with docx.open('rb') as stream:content=stream.read(80*1024*1024+1)
    if len(content)>80*1024*1024 or len(content)!=proof['docx_size_bytes'] or sha256(content).hexdigest()!=proof['docx_sha256']:raise ValueError('School final DOCX differs')
    expected='updated' if record['toc_enabled'] else 'not_requested'
    if record['field_update'].get('status')!=expected or (record['toc_enabled'] and record['field_update'].get('renderer_identity')!=record['renderer_identity']):raise ValueError('School final fields were not completed')
    return content,record


def _write_once(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid4().hex+'.part')
    try:
        with temporary.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        try:os.link(temporary,path)
        except FileExistsError:
            if path.read_bytes()!=raw:raise ValueError('Concurrent school cache publication differs')
    finally:
        temporary.unlink(missing_ok=True)


def materialize(root,owner,project,candidate,images,plan,*,db=None,frozen=None):
    if frozen is not None:
        content,record=read(root,owner,project,frozen,candidate=candidate,images=images,plan=plan)
        return content,record,deepcopy(frozen)
    from app.adapters.pdf_renderer import renderer_identity
    from app.adapters.manuscript_docx import RENDERER_VERSION
    mapper_version='school-final-map-v2' if plan.get('pagination_version')==2 else 'school-final-map-v1'
    renderer=renderer_identity();key=basis(candidate,images,plan,renderer,mapper_version=mapper_version)
    docx,path=_paths(root,owner,project,key)
    if path.exists():
        with path.open('rb') as stream:raw=stream.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:raise ValueError('School receipt exceeds limit')
        record=json.loads(raw)
        proof=dict(key=key,mapper_version=mapper_version,docx_renderer_version=RENDERER_VERSION,renderer_identity=renderer,docx_sha256=record['docx_sha256'],docx_size_bytes=record['docx_size_bytes'],receipt_sha256=sha256(raw).hexdigest(),receipt_size_bytes=len(raw))
        content,record=read(root,owner,project,proof,candidate=candidate,images=images,plan=plan)
        return content,record,proof
    mapped=[];pending=build_school_docx(candidate,images,plan,source_map=mapped)
    content,update=complete_school_fields(pending,plan)
    if update.get('status')!=('updated' if plan['toc']['enabled'] else 'not_requested'):raise ValueError('School final fields were not completed')
    mapped=final_school_source_map(pending,content,mapped,candidate['output_language'])
    record=dict(schema_version=1,key=key,owner_id=owner,project_id=project,mapper_version=mapper_version,docx_renderer_version=RENDERER_VERSION,renderer_identity=renderer,docx_sha256=sha256(content).hexdigest(),docx_size_bytes=len(content),source_map=mapped,field_update=update,toc_enabled=plan['toc']['enabled'])
    raw=json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    if len(raw)>8*1024*1024:raise ValueError('School receipt exceeds limit')
    proof=dict(key=key,mapper_version=mapper_version,docx_renderer_version=RENDERER_VERSION,renderer_identity=renderer,docx_sha256=record['docx_sha256'],docx_size_bytes=len(content),receipt_sha256=sha256(raw).hexdigest(),receipt_size_bytes=len(raw))
    for target,data in ((docx,content),(path,raw)):
        if db is None:_write_once(target,data)
        else:
            from app.domain.storage_governance.service import publication
            suffix='docx' if target==docx else 'receipt'
            with publication(db,root,project,'school-language:'+key+':'+suffix,target,data,kind='school_language_artifact',recover=True):_write_once(target,data)
    content,record=read(root,owner,project,proof,candidate=candidate,images=images,plan=plan)
    return content,record,proof
