"""Read-only bounded source and adoption integrity checks."""
from app.domain.manuscripts.school_changes import SchoolChangeService
from app.domain.report_collections.service import scoped_store

def audit_school_changes(db,limit=200):
    if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Invalid audit limit')
    rows=db.execute('SELECT * FROM manuscript_school_changes ORDER BY id LIMIT %s',(limit,)).fetchall()
    total=db.execute('SELECT count(*) AS n FROM manuscript_school_changes').fetchone()['n'];invalid=0;services={}
    for row in rows:
        try:
            if row['user_id'] not in services:services[row['user_id']]=SchoolChangeService(scoped_store(row['user_id'],db.config))
            service=services[row['user_id']];service.row(db,row['project_id'],row['manuscript_id'],row['id'])
            if row['adopted_revision'] is not None:service.manuscripts.version(db,row['project_id'],row['manuscript_id'],row['adopted_revision'])
        except Exception:invalid+=1
    return [dict(table='manuscript_school_changes',column='owner_input_parent_adoption',rows=len(rows),total=total,truncated=total>len(rows),invalid=invalid)]
