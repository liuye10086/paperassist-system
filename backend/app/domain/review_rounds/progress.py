"""User-entered project progress; SCI targets keep journal submission truth."""
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.core.exceptions import StorageError
from app.adapters.task_store import source_conflict
from app.domain.dataset_preparation.service import require_key
from app.domain.journals.display import synthetic_input
from app.domain.journals.service import now
from app.domain.journals.submissions import SubmissionService
from app.domain.literature.service import digest
from app.domain.manuscripts.service import ManuscriptService
from .return_contracts import ProgressRequest
from .service import ReviewRoundService


def invalid(message, code='review_progress_invalid', status=422):
    return StorageError(code,message,status)


class ReviewProgressService(ReviewRoundService):
    def references(self, db, project, request):
        round=self.round_row(db,project,request.round_id) if request.round_id else None
        version=None
        if request.manuscript:
            m=request.manuscript
            version=self.manuscript(db,project,m.id,m.revision)
            if version['id']!=m.version_id:
                raise invalid('所选公共稿件版本不匹配。')
            if round and round['snapshot_json']['manuscript']['id']!=m.id:
                raise invalid('进展关联的轮次与稿件必须属于同一稿件。')
        if request.export_id:
            if not version:
                raise invalid('关联导出须同时明确公共稿件版本。')
            export=db.execute('SELECT id FROM manuscript_exports WHERE id=%s AND version_id=%s',(request.export_id,version['id'])).fetchone()
            if not export:
                raise StorageError('not_found','导出不属于所选公共稿件版本。',404)
            view=ManuscriptService(self.assets).export_view(db,version,export['id'])
            if view['status']!='succeeded':
                raise invalid('关联导出尚未成功发布。')
        return round,version

    def progress_row(self, db, project, identity):
        self.project(db,project)
        row=db.execute('SELECT * FROM project_review_progress_events WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row:
            raise StorageError('not_found','用户项目进展不存在。',404)
        self.validate(row)
        request=ProgressRequest.model_validate(row['request_json'])
        snap=row['snapshot_json']
        round,version=self.references(db,project,request)
        if (request.target_id is not None or snap.get('source_kind')!='project'
            or snap.get('id')!=row['id'] or snap.get('project_id')!=project or snap.get('recorded_by')!=self.store.user_id
            or any(snap.get(k)!=v for k,v in row['request_json'].items() if k!='synthetic')
            or request.synthetic and snap.get('synthetic') is not True
            or row['round_id']!=request.round_id or row['corrects_event_id']!=request.corrects_event_id
            or row['export_id']!=request.export_id or row['manuscript_id']!=(version['manuscript_id'] if version else None)
            or row['manuscript_version_id']!=(version['id'] if version else None)):
            raise source_conflict()
        if round and round['snapshot_json']['synthetic'] and not snap.get('synthetic'):
            raise source_conflict()
        if version and synthetic_input(version['snapshot_json']) and not snap.get('synthetic'):
            raise source_conflict()
        if row['corrects_event_id']:
            original=self.progress_row(db,project,row['corrects_event_id'])
            if original['snapshot_json'].get('synthetic') and not snap.get('synthetic'):
                raise source_conflict()
        return row

    def journal_view(self, db, project, snapshot):
        journals=SubmissionService(self.assets)
        target=journals.target_row(db,project,snapshot['target_id'])
        synthetic=bool(snapshot.get('synthetic') or target['snapshot_json'].get('synthetic'))
        if snapshot.get('manuscript'):
            m=snapshot['manuscript']
            base=self.manuscript(db,project,m['id'],m['revision'])
            if base['id']!=m['version_id']:
                raise source_conflict()
            synthetic=bool(synthetic or synthetic_input(base['snapshot_json']))
        if snapshot.get('round_id'):
            round=self.round_row(db,project,snapshot['round_id'])
            synthetic=bool(synthetic or round['snapshot_json']['synthetic'])
        value=dict(round_id=None,manuscript=None,export_id=None,corrects_event_id=None)
        value.update(snapshot)
        return dict(value,source_kind='journal',synthetic=synthetic)

    def listing(self, project):
        with self.store.connection() as db:
            p=self.project(db,project)
            own=[self.progress_row(db,project,r['id'])['snapshot_json'] for r in db.execute('SELECT id FROM project_review_progress_events WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id',(project,self.store.user_id)).fetchall()]
            corrected={event['corrects_event_id'] for event in own if event.get('corrects_event_id')}
            current=next((event for event in sorted(own,key=lambda e:(e['event_date'],e['created_at'],e['id']),reverse=True) if event['id'] not in corrected),None)
            journal_items=[]
            current_by_target={}
            if p['project_type']=='sci':
                journals=SubmissionService(self.assets).listing(db,project)
                journal_items=[self.journal_view(db,project,event) for event in journals['items']]
                current_by_target={key:self.journal_view(db,project,event) for key,event in journals['current_by_target'].items()}
            items=sorted([*own,*journal_items],key=lambda e:(e['created_at'],e['id']),reverse=True)
            return dict(items=items,current=current,journal_current_by_target=current_by_target)

    def create(self, project, request, key):
        require_key(key)
        body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            p=self.project(db,project,True)
            round,version=self.references(db,project,request)
            synthetic=bool(request.synthetic or round and round['snapshot_json']['synthetic'] or version and synthetic_input(version['snapshot_json']))
            if request.target_id:
                if p['project_type']!='sci':
                    raise invalid('学校项目进展不使用期刊目标。')
                journals=SubmissionService(self.assets)
                target=journals.target_row(db,project,request.target_id)
                synthetic=bool(synthetic or target['snapshot_json'].get('synthetic'))
                if request.corrects_event_id:
                    original=journals.event_row(db,project,request.corrects_event_id)
                    synthetic=bool(synthetic or self.journal_view(db,project,original['snapshot_json'])['synthetic'])
            else:
                old=db.execute('SELECT * FROM project_review_progress_events WHERE project_id=%s AND user_id=%s AND idempotency_key=%s',(project,self.store.user_id,key)).fetchone()
                if old:
                    if old['request_digest']!=digest(body):
                        raise invalid('标识已用于不同进展记录。','task_idempotency_conflict',409)
                    return self.progress_row(db,project,old['id'])['snapshot_json'],200
                if p['project_type']=='sci' and not request.corrects_event_id and db.execute('SELECT id FROM journal_targets WHERE project_id=%s AND user_id=%s LIMIT 1',(project,self.store.user_id)).fetchone():
                    raise invalid('SCI已有固定期刊目标，请明确选择目标并沿用投稿进展记录。')
                if request.corrects_event_id:
                    original=self.progress_row(db,project,request.corrects_event_id)
                    if db.execute('SELECT id FROM project_review_progress_events WHERE corrects_event_id=%s',(original['id'],)).fetchone():
                        raise invalid('该记录已有纠正，请明确纠正最新记录。','review_progress_correction_conflict',409)
                    synthetic=bool(synthetic or original['snapshot_json']['synthetic'])
                identity=str(uuid4())
                timestamp=now()
                snap=body|dict(id=identity,project_id=project,recorded_by=self.store.user_id,created_at=timestamp.isoformat(),source_kind='project',synthetic=synthetic)
                fields=dict(id=identity,project_id=project,user_id=self.store.user_id,idempotency_key=key,
                            request_json=Jsonb(body),request_digest=digest(body),snapshot_json=Jsonb(snap),snapshot_sha256=digest(snap),created_at=timestamp,
                            corrects_event_id=request.corrects_event_id,round_id=request.round_id,
                            manuscript_id=version['manuscript_id'] if version else None,manuscript_version_id=version['id'] if version else None,export_id=request.export_id)
                db.execute('INSERT INTO project_review_progress_events('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))
                return self.progress_row(db,project,identity)['snapshot_json'],201
        # The existing journal service owns SCI target writes and corrections.
        # Passing the explicit user contract preserves its synthetic/round refs
        # in that single truth, without a duplicate project progress row.
        delegated=request.model_copy(update={'synthetic':synthetic})
        saved,status=SubmissionService(self.assets).create_event(project,delegated,key)
        with self.store.connection() as db:
            return self.journal_view(db,project,saved),status
