"""Read-only sealed journal request/result checks; no source or URL access."""
from app.domain.journals.service import input_version
from app.domain.journals.guides import GuideService as JournalService
from app.domain.report_collections.service import scoped_store
from app.domain.journals.contracts import ProfileRequest,RecommendationRequest
from app.domain.journals.recommendation import recommend


def audit_journals(db,*,limit=200):
    if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Audit limit must be 1..1000')
    checks=[]
    for table in ('journal_profiles','journal_recommendations','journal_material_refs'):
        total=db.execute('SELECT count(*) n FROM '+table).fetchone()['n'];rows=db.execute('SELECT * FROM '+table+' ORDER BY id LIMIT %s',(limit,)).fetchall();invalid=0
        for row in rows:
            try:
                service=JournalService(scoped_store(row['user_id'],db.config));service.project(db,row['project_id'])
                if table=='journal_material_refs':
                    from app.domain.journals.retention import ref_parent
                    parent,materials=ref_parent(service,db,row['project_id'],row)
                    if not any(m and m['file_id']==row['file_id'] for m in materials):raise ValueError('Material mismatch')
                else:
                    service.validate(row)
                    if table=='journal_profiles':
                        request=ProfileRequest.model_validate(row['request_json'])
                        if row['snapshot_json']['synthetic']!=(request.source_type=='synthetic'):raise ValueError('Synthetic level mismatch')
                    else:
                        RecommendationRequest.model_validate(row['request_json']);service.view(db,row)
                        task=service.store.require_task(db,row['task_id']);input_version(task)
                        if (task['status']=='succeeded')!=(row['result_json'] is not None):raise ValueError('Publication mismatch')
                        if row['result_json'] is not None and recommend(row['snapshot_json'])!=row['result_json']:raise ValueError('Result mismatch')
            except Exception:invalid+=1
        checks.append(dict(table=table,column='sealed_request_sources_result',rows=len(rows),total=total,truncated=total>len(rows),invalid=invalid))
    return checks
