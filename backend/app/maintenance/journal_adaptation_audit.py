"""Audit owner-scoped frozen plans, exact display-only output and event history."""
from app.domain.journals.adaptation_service import AdaptationService
from app.domain.journals.adaptation_contracts import AdaptationRequest,SubmissionRequest
from app.domain.journals.submissions import SubmissionService
from app.domain.manuscripts.service import ManuscriptService
from app.domain.report_collections.service import scoped_store

def audit_journal_adaptations(db,*,limit=200):
    checks=[]
    for table,contract in [('journal_adaptations',AdaptationRequest),('journal_submission_events',SubmissionRequest)]:
        rows=db.execute('SELECT * FROM '+table+' ORDER BY id LIMIT %s',(limit,)).fetchall();total=db.execute('SELECT count(*) n FROM '+table).fetchone()['n'];invalid=0
        for row in rows:
            try:
                assets=scoped_store(row['user_id'],db.config);service=AdaptationService(assets);service.validate(row);request=contract.model_validate(row['request_json'])
                service.target_row(db,row['project_id'],row['target_id'])
                if table=='journal_adaptations':
                    service.adaptation_row(db,row['project_id'],row['id'])
                    if (service.store.require_task(db,row['task_id'])['status']=='succeeded')!=(row['result_json'] is not None):raise ValueError('Publication mismatch')
                    if row['result_json']:
                        output=row['result_json']['output'];ms=ManuscriptService(assets)
                        version=ms.version(db,row['project_id'],output['manuscript_id'],output['revision'])
                        if version['id']!=row['output_version_id']:raise ValueError('Output mismatch')
                else:
                    if row['snapshot_json']['target_id']!=row['target_id'] or row['snapshot_json']['corrects_event_id']!=row['corrects_event_id']:raise ValueError('Event mismatch')
                    if row['corrects_event_id'] and SubmissionService(assets).event_row(db,row['project_id'],row['corrects_event_id'])['target_id']!=row['target_id']:raise ValueError('Correction target mismatch')
            except Exception:invalid+=1
        checks.append(dict(table=table,column='sealed_adaptation_event',rows=len(rows),total=total,truncated=total>len(rows),invalid=invalid))
    return checks
