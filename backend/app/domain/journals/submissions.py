"""User-entered events only; task completion never calls this service."""
from uuid import uuid4
from .format_service import FormatService
from .adaptation_service import invalid
from .service import now
from app.domain.dataset_preparation.service import require_key

class SubmissionService(FormatService):
    def event_row(self,db,project,identity):return self.row(db,project,identity,'journal_submission_events')
    def listing(self,db,project):
        self.project(db,project)
        rows=db.execute('SELECT * FROM journal_submission_events WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id',(project,self.store.user_id)).fetchall()
        for row in rows:self.validate(row)
        items=[r['snapshot_json'] for r in rows];corrected={i['corrects_event_id'] for i in items};current={}
        for item in sorted(items,key=lambda i:(i['event_date'],i['created_at'],i['id']),reverse=True):
            if item['id'] not in corrected:current.setdefault(item['target_id'],item)
        return dict(items=items,current_by_target=current)
    def list_events(self,project):
        with self.store.connection() as db:return self.listing(db,project)
    def create_event(self,project,request,key):
        require_key(key);body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.project(db,project,True);old=self.replay(db,'journal_submission_events',project,key,body)
            if old:return old['snapshot_json'],200
            self.target_row(db,project,request.target_id)
            if request.corrects_event_id:
                original=self.event_row(db,project,request.corrects_event_id)
                if original['target_id']!=request.target_id:raise invalid('纠正必须属于同一固定目标。')
                if db.execute('SELECT id FROM journal_submission_events WHERE corrects_event_id=%s',(original['id'],)).fetchone():raise invalid('该记录已有纠正，请纠正最新记录。')
            version=None
            if request.manuscript:
                version=self.manuscript(db,project,request.manuscript.id,request.manuscript.revision)
                if version['id']!=request.manuscript.version_id:raise invalid('稿件版本不匹配。')
            if request.export_id:
                from app.domain.manuscripts.service import ManuscriptService
                if not version:raise invalid('关联导出须同时明确稿件版本。')
                export=db.execute('SELECT id FROM manuscript_exports WHERE id=%s AND version_id=%s',(request.export_id,version['id'])).fetchone()
                if not export:raise invalid('导出不属于所选稿件版本。')
                ManuscriptService(self.assets).export_view(db,version,export['id'])
            snap=body|dict(id=str(uuid4()),project_id=project,recorded_by=self.store.user_id,created_at=now().isoformat())
            self.insert(db,'journal_submission_events',project,key,body,snap,target_id=request.target_id,corrects_event_id=request.corrects_event_id,manuscript_id=version['manuscript_id'] if version else None,manuscript_version_id=version['id'] if version else None,export_id=request.export_id)
            return snap,201
    def summary(self,db,project):
        self.project(db,project)
        row=db.execute('SELECT * FROM journal_targets WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id LIMIT 1',(project,self.store.user_id)).fetchone()
        if not row:return None
        target=self.target_row(db,project,row['id'])['snapshot_json']
        return dict(target_id=row['id'],profile_name=target['candidate']['profile']['name'],recommendation_id=target['recommendation_id'],confirmed_at=target['confirmed_at'],progress=self.listing(db,project)['current_by_target'].get(row['id']))
