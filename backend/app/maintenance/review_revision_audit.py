"""Read-only integrity audit of actual revisions and independent results."""
from app.domain.report_collections.service import scoped_store
from app.domain.review_rounds.revisions import RevisionService
from app.domain.review_rounds.documents import ReviewDocumentService
from app.domain.review_rounds.document_exports import ReviewDocumentExportService
from app.domain.manuscripts.service import ManuscriptService

def audit_review_revisions(db,*,limit=200):
    checks=[]
    for table in ('review_revision_runs','review_documents','review_document_exports'):
        rows=db.execute('SELECT * FROM '+table+' ORDER BY id LIMIT %s',(limit,)).fetchall();invalid=0
        for row in rows:
            try:
                assets=scoped_store(row['user_id'],db.config)
                if table=='review_revision_runs':
                    service=RevisionService(assets);fixed=service.revision_row(db,row['project_id'],row['id'])
                    if fixed['result_json']:
                        result=fixed['result_json']
                        if not result['actual_changes'] or any(i['severity']=='error' for i in result['public_issues']):raise ValueError('Invalid completion')
                        for item in result['items']:
                            if item['status']=='completed' and not any(c['item_id']==item['id'] and c['before']!=c['after'] for c in result['actual_changes']):raise ValueError('False completion')
                        ManuscriptService(assets).version(db,row['project_id'],row['manuscript_id'],result['output']['revision'])
                elif table=='review_documents':ReviewDocumentService(assets).row(db,row['project_id'],row['id'])
                else:ReviewDocumentExportService(assets).row(db,row['project_id'],row['id'])
            except Exception:invalid+=1
        total=db.execute('SELECT count(*) n FROM '+table).fetchone()['n']
        checks.append(dict(table=table,column='frozen_review_results',rows=len(rows),total=total,truncated=total>len(rows),invalid=invalid))
    return checks
