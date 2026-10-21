"""Read-only owner/base/candidate/report/publication integrity checks."""
from app.domain.manuscript_review.service import ReviewService
from app.domain.report_collections.service import scoped_store

def audit_manuscript_reviews(db):
    rows=db.execute('SELECT * FROM manuscript_reviews').fetchall();invalid=0
    for row in rows:
        try:
            service=ReviewService(scoped_store(row['user_id'],db.config))
            service.row(db,row['project_id'],row['manuscript_id'],row['id'])
            if row['published_revision']: service.manuscripts.version(db,row['project_id'],row['manuscript_id'],row['published_revision'])
        except Exception: invalid+=1
    return [dict(table='manuscript_reviews',column='owner_base_candidate_report_publication',rows=len(rows),invalid=invalid)]
