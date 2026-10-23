"""Read-only audit of user-return producers, explicit lineage and user progress."""
from app.domain.report_collections.service import scoped_store
from app.domain.review_rounds.returns import ReviewReturnService
from app.domain.review_rounds.service import ReviewRoundService
from app.domain.review_rounds.lineage import round_continuation
from app.domain.review_rounds.progress import ReviewProgressService


def audit_review_continuations(db, *, limit=200):
    checks=[]
    for table in ('review_round_user_returns','review_round_continuations','project_review_progress_events'):
        rows=db.execute('SELECT * FROM '+table+' ORDER BY id LIMIT %s',(limit,)).fetchall()
        invalid=0
        for row in rows:
            try:
                assets=scoped_store(row['user_id'],db.config)
                if table=='review_round_user_returns':
                    service=ReviewReturnService(assets)
                    fixed=service.return_row(db,row['project_id'],row['id'])
                    service.validate_return(db,fixed,current=True)
                    if fixed['output_version_id']:
                        output=db.execute('SELECT * FROM manuscript_versions WHERE id=%s',(fixed['output_version_id'],)).fetchone()
                        service.manuscripts.validate_version(db,output)
                elif table=='review_round_continuations':
                    service=ReviewRoundService(assets)
                    fixed=service.round_row(db,row['project_id'],row['round_id'])
                    round_continuation(service,db,fixed)
                else:
                    ReviewProgressService(assets).progress_row(db,row['project_id'],row['id'])
            except Exception:
                invalid+=1
        total=db.execute('SELECT count(*) n FROM '+table).fetchone()['n']
        checks.append(dict(table=table,column='frozen_review_continuations',rows=len(rows),total=total,truncated=total>len(rows),invalid=invalid))
    return checks
