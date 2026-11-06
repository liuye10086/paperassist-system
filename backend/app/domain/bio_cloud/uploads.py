"""Durable multipart identities; FASTQ bytes go directly from browser to S3."""
import base64
import hashlib
import math
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.domain.bioinformatics.contracts import digest
from .provider import ProviderError
from .requests import PART_SIZE
from .service import error, now, require_key


def composite_checksum(parts):
    value = b''.join(base64.b64decode(p['checksum_sha256'], validate=True) for p in parts)
    return base64.b64encode(hashlib.sha256(value).digest()).decode() + '-' + str(len(parts))


class CloudUploads:
    def __init__(self, service):
        self.service = service
        self.store = service.store

    def list(self, project):
        with self.store.connection() as db:
            self.store.require_project(db, project)
            rows = db.execute('SELECT * FROM bio_cloud_uploads WHERE project_id=%s ORDER BY created_at DESC LIMIT 100', (project,)).fetchall()
            return {'items':[self.service.public_upload(row) for row in rows]}

    def get(self, project, identifier):
        with self.store.connection() as db:
            return self.service.public_upload(self.service.require_upload(db,project,identifier))

    def settings_for(self, row):
        settings = self.service.ready_settings()
        if (row['region'],row['bucket']) != (settings.region,settings.input_bucket):
            raise error('configuration_changed', '上传时使用的地域或存储配置已改变，请先核对。')
        return settings

    def begin(self, project, request, key):
        require_key(key)
        settings = self.service.ready_settings()
        request_hash = digest(request.model_dump())
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project)
            from app.domain.storage_governance.guards import require_scope_open
            require_scope_open(db,project)
            row = db.execute('SELECT * FROM bio_cloud_uploads WHERE project_id=%s AND request_key=%s',(project,key)).fetchone()
            if row:
                if row['request_digest'] != request_hash:
                    raise error('idempotency_conflict', '此上传请求已用于不同文件。')
                return self.service.public_upload(row), 200
            if not any(p.account_verified for p in settings.profiles):
                raise error('profile_unverified', '请先核验目标账号中的工作流，之后再上传 FASTQ。')
            identifier = str(uuid4())
            object_key = f'paperassist/{project}/bio-cloud/uploads/{identifier}/{request.filename}'
            timestamp = now()
            db.execute('''INSERT INTO bio_cloud_uploads(id,project_id,owner_id,request_key,request_digest,filename,region,bucket,object_key,status,size_bytes,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'initializing',%s,%s,%s)''',
                (identifier,project,self.store.user_id,key,request_hash,request.filename,settings.region,settings.input_bucket,object_key,request.size_bytes,timestamp,timestamp))
        # The durable identity is committed before starting a remote multipart session.
        try:
            with self.service.provider(settings) as provider:
                upload_id = provider.begin_upload(object_key)
        except Exception:
            with self.store.connection(write=True) as db:
                db.execute("UPDATE bio_cloud_uploads SET status='initialization_unknown',error_code='bio_cloud_upload_unknown',updated_at=%s WHERE id=%s",(now(),identifier))
            raise error('upload_unknown', '上传会话建立结果待核实。尚未传输文件，请保留记录并联系管理员核对。', 503) from None
        with self.store.connection(write=True) as db:
            self.service.require_upload(db,project,identifier)
            db.execute("UPDATE bio_cloud_uploads SET provider_upload_id=%s,status='uploading',updated_at=%s WHERE id=%s AND status='initializing'",(upload_id,now(),identifier))
            return self.service.public_upload(self.service.require_upload(db,project,identifier)), 201

    def sign(self, project, identifier, number, checksum):
        with self.store.connection(write=True) as db:
            row = self.service.require_upload(db,project,identifier)
            settings = self.settings_for(row)
            if row['status'] != 'uploading' or not row['provider_upload_id']:
                raise error('upload_not_ready', '此上传会话当前不能写入分片。')
            if not 1 <= number <= math.ceil(row['size_bytes']/PART_SIZE):
                raise error('part_invalid', '分片编号超出该文件范围。', 422)
            existing = db.execute('SELECT checksum_sha256 FROM bio_cloud_parts WHERE upload_id=%s AND part_number=%s',(identifier,number)).fetchone()
            if existing and existing['checksum_sha256'] != checksum:
                raise error('part_changed', '本地文件分片与已登记内容不同，请选择原文件；不能混合上传。')
            db.execute('INSERT INTO bio_cloud_parts(upload_id,part_number,checksum_sha256) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(identifier,number,checksum))
        with self.service.provider(settings) as provider:
            return provider.sign_part(row['object_key'],row['provider_upload_id'],number,checksum)

    def parts(self, project, identifier):
        with self.store.connection() as db:
            row = self.service.require_upload(db,project,identifier)
            settings = self.settings_for(row)
        if row['status'] not in ('uploading','completing') or not row['provider_upload_id']:
            return {'items':[]}
        with self.service.provider(settings) as provider:
            return {'items':provider.list_parts(row['object_key'],row['provider_upload_id'])}

    def complete(self, project, identifier):
        with self.store.connection(write=True) as db:
            row = self.service.require_upload(db,project,identifier)
            if row['status']=='completed':
                return self.service.public_upload(row)
            settings = self.settings_for(row)
            if row['status'] not in ('uploading','completing') or not row['provider_upload_id']:
                raise error('upload_not_ready', '上传会话当前不能完成。')
            signed = {r['part_number']:r['checksum_sha256'] for r in db.execute('SELECT * FROM bio_cloud_parts WHERE upload_id=%s',(identifier,))}
        with self.service.provider(settings) as provider:
            if row['status']=='completing':
                # A lost completion response must not start a new upload.
                pending = row['receipt_json'] or {}
                parts = pending.get('completion_parts', [])
                try:
                    receipt = provider.head_input(row['object_key'])
                except ProviderError:
                    # The original Complete request may never have arrived. It
                    # is safe to finish this same upload and exact frozen parts;
                    # no new session or paid compute request is created.
                    actual = sorted(provider.list_parts(row['object_key'],row['provider_upload_id']),key=lambda p:p['part_number'])
                    if not parts or actual != parts:
                        raise error('part_changed','恢复完成上传时，远端分片已改变；请管理员核对。')
                    receipt = provider.complete_upload(row['object_key'],row['provider_upload_id'],parts)
            else:
                parts = sorted(provider.list_parts(row['object_key'],row['provider_upload_id']),key=lambda p:p['part_number'])
                count = math.ceil(row['size_bytes']/PART_SIZE)
                if [p['part_number'] for p in parts] != list(range(1,count+1)):
                    raise error('parts_incomplete', '部分分片尚未上传完成，请恢复上传。')
                for part in parts:
                    expected_size = min(PART_SIZE,row['size_bytes']-(part['part_number']-1)*PART_SIZE)
                    if part['size_bytes'] != expected_size or part.get('checksum_sha256') != signed.get(part['part_number']) or not part.get('etag'):
                        raise error('part_changed', '远端分片与已登记的大小或校验不一致，请核对原文件。')
                with self.store.connection(write=True) as db:
                    fresh = self.service.require_upload(db,project,identifier)
                    if fresh['status'] != 'uploading':
                        raise error('upload_not_ready', '上传状态已改变，请刷新后核对。')
                    db.execute("UPDATE bio_cloud_uploads SET status='completing',receipt_json=%s,updated_at=%s WHERE id=%s",(Jsonb({'completion_parts':parts}),now(),identifier))
                receipt = provider.complete_upload(row['object_key'],row['provider_upload_id'],parts)
            if (not parts or receipt.get('size_bytes') != row['size_bytes']
                    or receipt.get('checksum_sha256') != composite_checksum(parts)
                    or receipt.get('checksum_type') not in (None,'COMPOSITE')):
                raise error('upload_integrity', '完整对象的大小或组合校验值不一致；未允许提交计算。')
        with self.store.connection(write=True) as db:
            fresh = self.service.require_upload(db,project,identifier)
            if fresh['status'] != 'completing':
                raise error('upload_not_ready', '上传状态已改变，请刷新后核对。')
            db.execute("UPDATE bio_cloud_uploads SET status='completed',receipt_json=%s,error_code=NULL,updated_at=%s WHERE id=%s",(Jsonb(receipt),now(),identifier))
            return self.service.public_upload(self.service.require_upload(db,project,identifier))

    def cancel(self, project, identifier):
        with self.store.connection(write=True) as db:
            row = self.service.require_upload(db,project,identifier)
            if row['status']=='cancelled':
                return self.service.public_upload(row)
            if row['status'] not in ('uploading','cancelling'):
                raise error('upload_not_ready', '已完成或待核实的对象不能从此操作删除。')
            settings = self.settings_for(row)
            db.execute("UPDATE bio_cloud_uploads SET status='cancelling',updated_at=%s WHERE id=%s",(now(),identifier))
        with self.service.provider(settings) as provider:
            provider.abort_upload(row['object_key'],row['provider_upload_id'])
        with self.store.connection(write=True) as db:
            db.execute("UPDATE bio_cloud_uploads SET status='cancelled',updated_at=%s WHERE id=%s",(now(),identifier))
            return self.service.public_upload(self.service.require_upload(db,project,identifier))
