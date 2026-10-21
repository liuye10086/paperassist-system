"""Read-only integrity audit of frozen writing requests and published candidates."""
from app.domain.manuscript_writing.service import WritingService
from app.domain.report_collections.service import scoped_store

def audit_manuscript_writing(db):
    rows=db.execute('SELECT * FROM manuscript_writing_requests').fetchall();invalid=0
    for row in rows:
        try:
            service=WritingService(scoped_store(row['user_id'],db.config))
            saved,task=service.row(db,row['project_id'],row['manuscript_id'],row['task_id'])
            if (saved['candidate_json'] is not None)!=(task['status']=='succeeded'): raise ValueError('Candidate completion drift')
            base=service.manuscripts.version(db,row['project_id'],row['manuscript_id'],row['request_json']['base_revision'])
            if base['id']!=row['base_version_id'] or base['snapshot_json']!=row['input_snapshot']['base_snapshot']: raise ValueError('Base drift')
            if row['published_revision']:
                version=service.manuscripts.version(db,row['project_id'],row['manuscript_id'],row['published_revision'])
                if task['status']!='succeeded' or version['parent_version_id']!=base['id']: raise ValueError('Published binding drift')
                if task['input_snapshot']['schema_version']==1 and version['snapshot_json']!=row['candidate_json']: raise ValueError('Published binding drift')
        except Exception: invalid+=1
    orphan=db.execute("SELECT count(*) AS n FROM tasks t LEFT JOIN manuscript_writing_requests w ON w.task_id=t.id WHERE t.task_type='manuscript_writing' AND w.task_id IS NULL").fetchone()['n']
    return [dict(table='manuscript_writing_requests',column='owner_frozen_candidate_publication',rows=len(rows),invalid=invalid),dict(table='tasks',column='manuscript_writing_binding',rows=len(rows)+orphan,invalid=orphan)] + audit_live(db) + audit_reviews(db) + audit_language(db) + audit_figure_languages(db)

def audit_reviews(db):
    from app.domain.manuscript_writing.live_review import LiveReviewService
    rows=db.execute('SELECT * FROM manuscript_writing_reviews').fetchall();invalid=0
    for row in rows:
        try:
            service=LiveReviewService(scoped_store(row['user_id'],db.config))
            review=service.row(db,row['project_id'],row['manuscript_id'],row['request_id'],row['id'])
            service.validate_frozen(db,row['project_id'],row['manuscript_id'],row['request_id'],review)
        except Exception: invalid+=1
    return [dict(table='manuscript_writing_reviews',column='immutable_exact_manual_science',rows=len(rows),invalid=invalid)]


def audit_live(db):
    from app.domain.manuscript_writing.authorization import LiveWritingService
    from app.domain.literature.service import digest
    from app.domain.manuscript_writing.policy import MAX_POSTS, TASK_CAP, BATCH_CAP
    checks=[]
    for table in ('manuscript_writing_bundles','manuscript_writing_authorizations','manuscript_writing_authorized_tasks','manuscript_writing_call_admissions'):
        rows=db.execute('SELECT * FROM '+table).fetchall();invalid=0
        for row in rows:
            try:
                service=LiveWritingService(scoped_store(row['user_id'],db.config))
                if table=='manuscript_writing_bundles':
                    bundle=service.bundle(db,row['project_id'],row['id'])
                    version=service.manuscripts.version(db,row['project_id'],row['manuscript_id'],bundle['request_json']['base_revision'])
                    if version['id']!=row['base_version_id'] or version['snapshot_json']!=bundle['base_snapshot']: raise ValueError('Bundle base drift')
                elif table=='manuscript_writing_authorizations':
                    auth=service.authorization(db,row['project_id'],row['id'])
                    if auth['max_posts']!=MAX_POSTS or auth['cap_micro_usd']!=BATCH_CAP or len(auth['manifest_json']['tasks'])!=4: raise ValueError('Authorization policy drift')
                    if auth['status']=='active' and auth['closed_at'] is not None or auth['status']!='active' and auth['closed_at'] is None: raise ValueError('Authorization state drift')
                elif table=='manuscript_writing_authorized_tasks':
                    auth=service.authorization(db,row['project_id'],row['authorization_id'])
                    task=next(t for t in auth['manifest_json']['tasks'] if t['logical_task_id']==row['logical_task_id'])
                    if task['bundles']!=row['bundles_json'] or row['cap_micro_usd']!=TASK_CAP: raise ValueError('Grant drift')
                    for ref in row['bundles_json']:
                        if service.bundle(db,row['project_id'],ref['bundle_id'])['bundle_sha256']!=ref['bundle_sha256']: raise ValueError('Grant material drift')
                else:
                    call=db.execute('SELECT * FROM model_calls WHERE id=%s',(row['model_call_id'],)).fetchone()
                    task=service.store.require_task(db,call['task_id']);execution=task['input_snapshot']['execution']
                    bundle=service.bundle(db,row['project_id'],row['bundle_id'])
                    if any(call[k]!=row[k] for k in ('project_id','user_id')) or any(execution[k]!=row[k] for k in ('authorization_id','logical_task_id','bundle_id')) or row['reserved_micro_usd']!=bundle['reserved_micro_usd']: raise ValueError('Admission scope drift')
                    if row['status']=='reserved' and call['status']!='reserved' or row['status']=='released' and call['status']!='released' or row['status']=='submission_started' and call['status'] in ('reserved','released'): raise ValueError('Submission fence drift')
            except Exception: invalid+=1
        checks.append(dict(table=table,column='frozen_scope_admission',rows=len(rows),invalid=invalid))
    return checks


def audit_language(db):
    from app.domain.manuscript_writing.language_service import LanguageReviewService
    rows=db.execute('SELECT * FROM manuscript_writing_language_reviews').fetchall();invalid=0
    for row in rows:
        try:
            LanguageReviewService(scoped_store(row['user_id'],db.config)).language_row(db,row['project_id'],row['manuscript_id'],row['request_id'],row['id'])
        except Exception: invalid+=1
    return [dict(table='manuscript_writing_language_reviews',column='immutable_exact_export_language',rows=len(rows),invalid=invalid)]


def audit_figure_languages(db):
    from app.domain.manuscripts.figure_language import FigureLanguageService
    rows=db.execute('SELECT * FROM manuscript_figure_language_versions').fetchall();invalid=0
    for row in rows:
        try:
            FigureLanguageService(scoped_store(row['user_id'],db.config)).row(db,row['project_id'],row['id'])
        except Exception: invalid+=1
    return [dict(table='manuscript_figure_language_versions',column='immutable_source_geometry_asset',rows=len(rows),invalid=invalid)]
