"""Read-only bounded integrity audit; no URLs, models or public review publication."""
from app.domain.journals.format_service import FormatService,input_version
from app.domain.journals.format_contracts import GuideRequest,TargetRequest,FormatCheckRequest
from app.domain.report_collections.service import scoped_store
from app.domain.literature.service import digest

def audit_journal_formats(db,*,limit=200):
    if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Audit limit must be 1..1000')
    checks=[]
    for table,contract in [('journal_guides',GuideRequest),('journal_targets',TargetRequest),('journal_format_checks',FormatCheckRequest)]:
        total=db.execute('SELECT count(*) n FROM '+table).fetchone()['n'];rows=db.execute('SELECT * FROM '+table+' ORDER BY id LIMIT %s',(limit,)).fetchall();invalid=0
        for row in rows:
            try:
                service=FormatService(scoped_store(row['user_id'],db.config));service.project(db,row['project_id']);service.validate(row);request=contract.model_validate(row['request_json']);snap=row['snapshot_json']
                if table=='journal_guides':
                    profile=service.row(db,row['project_id'],row['profile_id'],'journal_profiles')['snapshot_json']
                    if snap['profile_id']!=row['profile_id'] or snap['requirements_version']!=row['requirements_version'] or (profile['synthetic'] and not snap['synthetic']):raise ValueError('Guide scope/level mismatch')
                    if digest(dict(requirements=snap['requirements'],source_version=snap['source_version'],article_types=snap['article_types']))!=row['requirements_version']:raise ValueError('Requirements version mismatch')
                elif table=='journal_targets':service.target_row(db,row['project_id'],row['id'])
                else:
                    service.check_row(db,row['project_id'],row['id']);task=service.store.require_task(db,row['task_id']);input_version(task)
                    if (task['status']=='succeeded')!=(row['result_json'] is not None):raise ValueError('Check publication mismatch')
                    if row['result_json'] is not None and service.compute(db,row)!=row['result_json']:raise ValueError('Check result mismatch')
            except Exception:invalid+=1
        checks.append(dict(table=table,column='sealed_guide_target_check',rows=len(rows),total=total,truncated=total>len(rows),invalid=invalid))
    return checks
