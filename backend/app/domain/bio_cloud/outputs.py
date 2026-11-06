"""Bounded streaming retrieval into existing governed original-file storage."""
import hashlib
import json
import os
from pathlib import PurePosixPath
from uuid import uuid4
from psycopg.types.json import Jsonb

from app.domain.bioinformatics.settings import BioLimits
from app.domain.storage_governance import service as storage
from .execution import output_prefix
from .service import error, now


def _save(repository, lease, service, row, role, source_key, size, stream_factory):
    root = repository.assets.directory
    with repository.connection(write=True) as db:
        task = repository.require_lease(db,lease)
        repository.require_owner(db,task)
        existing = db.execute('SELECT o.*,f.object_key,f.storage_backend,f.file_type,f.filename FROM bio_cloud_outputs o JOIN files f ON f.id=o.file_id AND f.project_id=o.project_id WHERE o.run_id=%s AND o.role=%s',(row['id'],role)).fetchone()
        if existing:
            if existing['source_key']!=source_key or existing['size_bytes']!=size:
                raise error('output_invalid','已保存结果与当前远端输出不一致。')
            # Use the established immutable-original verifier on recovery.
            repository.assets.original({**dict(existing),'id':existing['file_id']})
            return
        file_id = str(uuid4())
        object_key = f'files/cloud-{row["id"]}-{file_id}.bio_component'
        target = root / object_key
        reservation = storage.reserve(db,root,task['project_id'],'cloud-output:'+file_id,target,size,kind='original',task_id=task['id'])
    # An interrupted partial remains charged/reserved, not silently deleted or
    # overwritten. Previously published roles are reused on the next attempt.
    storage._key(root,target)
    target.parent.mkdir(parents=True,exist_ok=True)
    storage._key(root,target)
    digest = hashlib.sha256()
    length = 0
    stream = stream_factory()
    try:
        with target.open('xb') as destination:
            while True:
                block = stream.read(min(1024*1024,size-length+1))
                if not block:
                    break
                length += len(block)
                if length>size:
                    raise error('output_invalid','云结果实际大小超过已登记长度。')
                destination.write(block)
                digest.update(block)
            destination.flush()
            os.fsync(destination.fileno())
    finally:
        stream.close()
    if length!=size:
        raise error('output_invalid','云结果下载不完整，请重试获取已有结果。')
    filename = PurePosixPath(source_key).name if source_key else 'cloud-provenance.json'
    with repository.connection(write=True) as db:
        task = repository.require_lease(db,lease)
        progress = repository.transaction_progress(db,lease)
        storage.settle(db,root,reservation['id'])
        progress(force=True)
        db.execute('''INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status,error_json,preview_json,uploader_id,storage_backend,object_key,metadata_revision,parse_revision)
            VALUES(%s,%s,%s,'bio_component',%s,%s,%s,'stored',NULL,NULL,%s,'local',%s,1,0)''',
            (file_id,row['project_id'],filename,length,digest.hexdigest(),now().isoformat(),task['user_id'],object_key))
        db.execute('INSERT INTO bio_cloud_outputs(run_id,role,project_id,file_id,source_key,sha256,size_bytes) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                   (row['id'],role,row['project_id'],file_id,source_key,digest.hexdigest(),length))


def collect_outputs(repository, lease, service, provider, row, uri):
    snapshot = row['snapshot_json']
    prefix = output_prefix(snapshot,uri)
    listing = provider.list_outputs(uri)
    by_key = {}
    for item in listing:
        key = item.get('key')
        if not isinstance(key,str) or not key.startswith(prefix) or key in by_key:
            raise error('output_invalid','云结果目录或对象清单不一致。')
        by_key[key] = item
    selected = []
    limits = BioLimits()
    for role,relative in snapshot['profile']['outputs'].items():
        item = by_key.get(prefix+relative)
        if item is None or type(item.get('size_bytes')) is not int or item['size_bytes']<=0 or not item.get('etag'):
            raise error('output_invalid','云流程缺少必需结果，请核对工作流输出合同及运行日志。')
        if item['size_bytes']>limits.max_upload_bytes:
            raise error('input_limit','云计算已完成，但单个结果超过当前矩阵导入上限；需先配置下游资源档位。',413)
        selected.append((role,item))
    if sum(item['size_bytes'] for _,item in selected)>512*1024*1024:
        raise error('input_limit','结果总量超过当前下游导入容量。',413)
    manifest = {role:{k:item[k] for k in ('key','size_bytes','etag')} for role,item in selected}
    with repository.connection(write=True) as db:
        repository.require_lease(db,lease)
        current = db.execute('SELECT output_manifest_json FROM bio_cloud_runs WHERE id=%s FOR UPDATE',(row['id'],)).fetchone()
        if current['output_manifest_json'] is not None and current['output_manifest_json']!=manifest:
            raise error('output_invalid','远端结果版本已改变，未混合不同版本的矩阵及标识文件。')
        if current['output_manifest_json'] is None:
            db.execute('UPDATE bio_cloud_runs SET output_manifest_json=%s WHERE id=%s',(Jsonb(manifest),row['id']))
    for role,item in selected:
        _save(repository,lease,service,row,role,item['key'],item['size_bytes'],
              lambda item=item:provider.stream_output(item['key'],expected_etag=item.get('etag')))
    import io
    metadata = dict(schema_version=1,provider='aws_healthomics',provider_run_id=row['provider_run_id'],
        workflow={k:snapshot['profile'][k] for k in ('workflow_id','workflow_type','workflow_version','engine','reference_id')},
        sample=snapshot['request'],input_objects=snapshot['inputs'],output_objects=manifest,
        verification={'transport':'size_and_sha256_checked','matrix_structure':'requires_existing_import_review','biological_validation':'not_claimed'})
    content = json.dumps(metadata,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8')
    _save(repository,lease,service,row,'provenance','',len(content),lambda:io.BytesIO(content))
