"""Retain all local originals referenced by fixed rounds and historical saves."""
from .service import ReviewRoundService
from app.domain.report_collections.service import scoped_store

def read_refs(db,file,user):
    from app.domain.file_lifecycle.references import file_ids
    service=ReviewRoundService(scoped_store(user,db.config));result=[]
    rows=db.execute('SELECT * FROM review_rounds WHERE project_id=%s',(file['project_id'],)).fetchall()
    for row in rows:
        events=service.events(db,row)
        if file['id'] not in file_ids(row['snapshot_json']) and not any(file['id'] in file_ids(e['snapshot_json']) for e in events):continue
        record=dict(row,file_id=file['id'])
        try:
            service.round_row(db,row['project_id'],row['id']);service.fixed(db,row)
            record['_integrity_valid']=row['user_id']==user
        except Exception:record['_integrity_valid']=False
        result.append(record)
    from .revisions import RevisionService
    from .documents import ReviewDocumentService
    from .document_exports import ReviewDocumentExportService
    assets=scoped_store(user,db.config);revisions=RevisionService(assets)
    for row in db.execute('SELECT * FROM review_revision_runs WHERE project_id=%s',(file['project_id'],)).fetchall():
        base=db.execute('SELECT snapshot_json FROM manuscript_versions WHERE id=%s',(row['manuscript_version_id'],)).fetchone()
        if file['id'] not in file_ids(row['snapshot_json']) and (not base or file['id'] not in file_ids(base['snapshot_json'])):continue
        records=[dict(row,file_id=file['id'])]
        records.extend(dict(r,file_id=file['id']) for r in db.execute('SELECT * FROM review_documents WHERE revision_id=%s',(row['id'],)).fetchall())
        records.extend(dict(r,file_id=file['id']) for r in db.execute('SELECT e.* FROM review_document_exports e JOIN review_documents d ON d.id=e.document_id WHERE d.revision_id=%s',(row['id'],)).fetchall())
        for record in records:
            try:
                if 'output_version_id' in record:revisions.revision_row(db,row['project_id'],record['id'])
                elif 'document_id' in record:ReviewDocumentExportService(assets).row(db,row['project_id'],record['id'])
                else:ReviewDocumentService(assets).row(db,row['project_id'],record['id'])
                record['_integrity_valid']=record['user_id']==user
            except Exception:record['_integrity_valid']=False
            result.append(record)
    from .returns import ReviewReturnService
    from .progress import ReviewProgressService
    from .lineage import round_continuation
    from .science import ScienceService
    for table in ('review_round_user_returns','review_round_continuations','project_review_progress_events',
                  'review_opinion_task_links','review_analysis_adoptions'):
        for row in db.execute('SELECT * FROM '+table+' WHERE project_id=%s',(file['project_id'],)).fetchall():
            if file['id'] not in file_ids(row['snapshot_json']) and row.get('file_id')!=file['id']:
                continue
            record=dict(row,file_id=file['id'])
            try:
                if table=='review_round_user_returns':
                    returns=ReviewReturnService(assets)
                    returns.validate_return(db,returns.return_row(db,row['project_id'],row['id']))
                elif table=='review_round_continuations':
                    rounds=ReviewRoundService(assets)
                    round_continuation(rounds,db,rounds.round_row(db,row['project_id'],row['round_id']))
                elif table=='project_review_progress_events':
                    ReviewProgressService(assets).progress_row(db,row['project_id'],row['id'])
                else:
                    science=ScienceService(assets)
                    saved=science.science_row(db,row['project_id'],row['id'],table)
                    if table=='review_opinion_task_links':science.link_view(db,saved)
                    else:science.validate_adoption(db,saved)
                record['_integrity_valid']=row['user_id']==user
            except Exception:record['_integrity_valid']=False
            result.append(record)
    return result
