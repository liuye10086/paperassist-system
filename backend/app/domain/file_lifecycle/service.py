"""Serialized assessments and immutable terminal retention receipts."""
from datetime import datetime, timezone
import re
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.adapters.task_store import TaskStore
from app.core.exceptions import StorageError
from app.domain.files import require_file
from app.domain.file_lifecycle.contracts import ACTIVE, POLICY_VERSION, digest
from app.domain.file_lifecycle.references import read_references
from app.domain.file_lifecycle.lineage import task_views


def conflict():
    return StorageError('file_assessment_conflict', '文件影响范围已变化，请重新评估。', 409)


class FileLifecycleService:
    def __init__(self, assets):
        self.assets = assets
        self.store = TaskStore(assets.owner_id, assets.db_config)

    def file(self, db, project_id, file_id):
        self.store.require_project(db, project_id)
        return require_file(db, project_id, file_id)

    def assess_in_transaction(self, db, project_id, file_id, action):
        file = self.file(db, project_id, file_id)
        refs = read_references(db, file, self.store.user_id)
        integrity = 'valid'
        try:
            self.assets.original(dict(file))
        except StorageError as exc:
            integrity = {'file_missing':'missing', 'file_changed':'changed'}.get(exc.code, 'unavailable')
        except OSError:
            integrity = 'unavailable'
        reasons = list(refs['reasons'])
        if integrity != 'valid':
            reasons.append('original_' + integrity)
        active_parse = any(t['task_type'] in ('parse_file', 'extract_dataset') and t['status'] in ACTIVE for t in refs['tasks'])
        reparse_reason = ('original_'+integrity if integrity != 'valid' else
                          'integrity_unknown' if 'integrity_unknown' in reasons else
                          'active_parse' if active_parse else
                          'unsupported_file_type' if file['file_type'] not in ('xlsx','docx','pdf','png','jpeg') else
                          'file_not_parsed' if file['file_type']=='xlsx' and file['parse_status']!='parsed' else None)
        public_groups = refs['public_groups']
        latest = {kind: max((row.get('version', row.get('setup_revision', 0)) for row in public_groups[kind]), default=0)
                  for kind in ('parse_versions','structure_versions','confirmed_plans')}
        # Per-lineage latest records avoid treating different Excel sheets,
        # prepared parents or OCR page selections as interchangeable.
        latest['dataset_versions'] = [dict(id=r['id'],version=r['version'],sheet_index=r['sheet_index'])
            for r in sorted(public_groups['dataset_versions'],key=lambda r:(r['sheet_index'],-r['version']))
            if r['version']==max(x['version'] for x in public_groups['dataset_versions'] if x['sheet_index']==r['sheet_index'])]
        for kind,parent in (('prepared_dataset_versions','parent_dataset_id'),('ocr_review_versions','parent_parse_id')):
            by_parent = {}
            for row in public_groups[kind]:
                if row[parent] not in by_parent or row['version'] > by_parent[row[parent]]['version']:
                    by_parent[row[parent]] = {key:row[key] for key in ('id','version',parent)}
            latest[kind] = [by_parent[key] for key in sorted(by_parent)]
        value = dict(policy_version=POLICY_VERSION, action=action, file_id=file_id,
            impact_scope='file_wide', counts=refs['counts'], latest_versions=latest,
            reasons=[{'code':code} for code in ['internal_testing_retention']+sorted(set(reasons))],
            original_integrity=integrity, original_available=integrity=='valid',
            physical_deletion_available=False, automatic_deletion=False, retained_original=True,
            history_downloads_preserved=True, operation_preserves_history=True,
            can_reparse=reparse_reason is None, reparse_reason=reparse_reason,
            deletion_status='blocked' if reasons else 'retained')
        file_facts = {key:file[key] for key in ('id','project_id','filename','uploader_id','upload_item_id','sha256','size_bytes','file_type','metadata_revision','parse_revision','parse_status','storage_backend')}
        file_facts['object_identity'] = digest(file['object_key'])
        revision = digest(dict(assessment=value, file=file_facts, references=refs['facts']))
        value['assessment_revision'] = revision
        return value, dict(assessment=value, file=file_facts, references=refs['facts'])

    def assessment(self, project_id, file_id, action='delete'):
        with self.store.connection() as db:
            return self.assess_in_transaction(db, project_id, file_id, action)[0]

    def tasks(self, project_id, file_id, page=1, page_size=10):
        with self.store.connection() as db:
            file = self.file(db, project_id, file_id)
            refs = read_references(db, file, self.store.user_id)
            rows = task_views(refs)
            return dict(items=rows[(page-1)*page_size:page*page_size], total=len(rows), page=page,
                        page_size=page_size, counts=refs['counts'])

    @staticmethod
    def receipt(row):
        return dict(id=row['id'], file_id=row['file_id'], reason=row['reason'], status=row['status'],
                    requested_at=row['created_at'].isoformat(), resolved_at=row['resolved_at'].isoformat(),
                    policy_version=row['policy_version'], assessment_revision=row['assessment_revision'],
                    assessment=row['assessment_json']['assessment'])

    def history(self, project_id, file_id, page=1, page_size=10):
        with self.store.connection() as db:
            self.file(db, project_id, file_id)
            scope = (project_id, file_id, self.store.user_id)
            total = db.execute('SELECT count(*) AS n FROM file_deletion_requests WHERE project_id=%s AND file_id=%s AND requested_by=%s', scope).fetchone()['n']
            rows = db.execute('SELECT * FROM file_deletion_requests WHERE project_id=%s AND file_id=%s AND requested_by=%s ORDER BY created_at DESC,id LIMIT %s OFFSET %s', (*scope, page_size, (page-1)*page_size)).fetchall()
            return dict(items=[self.receipt(row) for row in rows],total=total,page=page,page_size=page_size)

    def request_deletion(self, project_id, file_id, request, key):
        if not isinstance(key,str) or not re.fullmatch(r'[\x21-\x7e]{1,128}',key):
            raise StorageError('task_input_invalid','请求标识无效。',422)
        request_digest = digest(request.model_dump())
        # connection(write=True) acquires the existing global advisory lock
        # before any business read. Never open a nested writer here.
        with self.store.connection(write=True) as db:
            self.file(db, project_id, file_id)
            old = db.execute('SELECT * FROM file_deletion_requests WHERE project_id=%s AND file_id=%s AND requested_by=%s AND idempotency_key=%s', (project_id,file_id,self.store.user_id,key)).fetchone()
            if old:
                if old['request_digest'] != request_digest:
                    raise StorageError('file_deletion_idempotency_conflict','同一操作标识已用于不同删除申请。',409)
                return self.receipt(old),200
            value,snapshot = self.assess_in_transaction(db,project_id,file_id,'delete')
            if request.expected_assessment_revision != value['assessment_revision']:
                raise conflict()
            now = datetime.now(timezone.utc)
            row = db.execute('''INSERT INTO file_deletion_requests(id,file_id,project_id,requested_by,idempotency_key,
                request_digest,reason,status,policy_version,assessment_revision,assessment_json,created_at,resolved_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                (str(uuid4()),file_id,project_id,self.store.user_id,key,request_digest,request.reason,value['deletion_status'],
                 POLICY_VERSION,value['assessment_revision'],Jsonb(snapshot),now,now)).fetchone()
            return self.receipt(row),201

    def guard_reparse(self, db, project_id, file_id, expected):
        value,snapshot = self.assess_in_transaction(db,project_id,file_id,'reparse')
        if expected is not None and expected != value['assessment_revision']:
            raise conflict()
        if 'integrity_unknown' in [reason['code'] for reason in value['reasons']]:
            raise StorageError('source_conflict','文件引用完整性无法确认。',409)
        return snapshot

    def record_reparse(self, db, project_id, file_id, task_id, snapshot, supplied):
        db.execute('''INSERT INTO file_reparse_assessments(task_id,file_id,project_id,actor_id,policy_version,
            assessment_revision,client_assessment_supplied,snapshot_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (task_id,file_id,project_id,self.store.user_id,POLICY_VERSION,snapshot['assessment']['assessment_revision'],
             supplied,Jsonb(snapshot),datetime.now(timezone.utc)))
