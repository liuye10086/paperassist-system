"""Read-only owner, frozen input, typed source and export-history audit."""
from app.domain.manuscripts.service import ManuscriptService
from app.domain.report_collections.service import scoped_store
from app.domain.literature.service import digest


def audit_manuscripts(db):
    services={};checks=[]
    def service(owner):
        if owner not in services: services[owner]=ManuscriptService(scoped_store(owner,db.config))
        return services[owner]
    for table in ('manuscripts','manuscript_versions','manuscript_sources','manuscript_citations','manuscript_exports'):
        rows=db.execute('SELECT * FROM '+table).fetchall();invalid=0
        for row in rows:
            try:
                if table=='manuscripts':
                    svc=service(row['user_id']);svc.root(db,row['project_id'],row['id'])
                    versions=db.execute('SELECT * FROM manuscript_versions WHERE manuscript_id=%s ORDER BY revision',(row['id'],)).fetchall()
                    if [r['revision'] for r in versions]!=list(range(1,row['current_revision']+1)): raise ValueError('History gap')
                    if versions[0]['request_digest']!=row['request_digest'] or versions[-1]['snapshot_json']['title']!=row['title']: raise ValueError('Root drift')
                else:
                    version=row if table=='manuscript_versions' else db.execute('SELECT * FROM manuscript_versions WHERE id=%s',(row['version_id'],)).fetchone()
                    if not version: raise ValueError('Missing parent')
                    svc=service(version['user_id']);svc.validate_version(db,version)
                    task=svc.store.require_task(db,version['task_id']);svc.verify_task(db,task)
                    if table=='manuscript_sources':
                        file=db.execute('SELECT project_id FROM files WHERE id=%s',(row['file_id'],)).fetchone()
                        if not file or file['project_id']!=version['project_id']: raise ValueError('Foreign source')
                    elif table=='manuscript_citations':
                        for name,identity in (('literature_claim_reviews',row['review_id']),('literature_citation_metadata_versions',row['metadata_version_id']),('project_references',row['project_reference_id'])):
                            actual=db.execute('SELECT project_id,user_id FROM '+name+' WHERE id=%s',(identity,)).fetchone()
                            if not actual or any(actual[k]!=version[k] for k in ('project_id','user_id')): raise ValueError('Foreign citation')
                    elif table=='manuscript_exports':
                        export_task=svc.store.require_task(db,row['task_id']);svc.verify_task(db,export_task)
                        if export_task['status']=='succeeded':
                            metadata,raw=svc.export(version['project_id'],version['manuscript_id'],row['id'],True)
            except Exception:
                invalid+=1
        checks.append(dict(table=table,column='owner_frozen_input_sources_and_history',rows=len(rows),invalid=invalid))
    return checks
