"""Read-only audit of scoped task links and receipt-backed analysis adoption."""
from app.domain.report_collections.service import scoped_store
from app.domain.review_rounds.science import ScienceService


def audit_review_science(db, *, limit=200):
    checks = []
    for table in ('review_opinion_task_links', 'review_analysis_adoptions'):
        rows = db.execute('SELECT * FROM ' + table + ' ORDER BY id LIMIT %s', (limit,)).fetchall()
        invalid = 0
        for row in rows:
            try:
                service = ScienceService(scoped_store(row['user_id'], db.config))
                scoped = service.science_row(db, row['project_id'], row['id'], table)
                if table == 'review_opinion_task_links':
                    service.link_view(db, scoped)
                else:
                    service.validate_adoption(db, scoped)
            except Exception:
                invalid += 1
        total = db.execute('SELECT count(*) AS n FROM ' + table).fetchone()['n']
        checks.append(dict(table=table, column='frozen_scientific_receipts', rows=len(rows), total=total,
                           truncated=total > len(rows), invalid=invalid))
    return checks
