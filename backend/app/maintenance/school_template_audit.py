"""Bounded read-only verification; results contain counts and no source text."""
from app.domain.school_templates.service import SchoolTemplateService
from app.domain.report_collections.service import scoped_store


def audit_school_templates(db,*,limit=200):
    if type(limit) is not int or not 1<=limit<=1000: raise ValueError('Audit limit must be 1..1000')
    checks=[];services={}
    def service(owner):
        if owner not in services: services[owner]=SchoolTemplateService(scoped_store(owner,db.config))
        return services[owner]
    for table in ('school_template_versions','school_template_sources','school_template_confirmations','thesis_profiles'):
        key='project_id' if table=='thesis_profiles' else 'id'
        total=db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']
        rows=db.execute('SELECT * FROM '+table+' ORDER BY '+key+' LIMIT %s',(limit,)).fetchall();invalid=0
        for row in rows:
            try:
                svc=service(row['user_id']);svc.project(db,row['project_id'])
                if table=='thesis_profiles':
                    if row['bound_confirmation_id']:
                        confirmation=db.execute('SELECT * FROM school_template_confirmations WHERE id=%s AND project_id=%s AND user_id=%s',(row['bound_confirmation_id'],row['project_id'],row['user_id'])).fetchone()
                        if not confirmation:raise ValueError('Foreign confirmation')
                        version=svc.row(db,row['project_id'],confirmation['template_version_id']);svc.validate(db,version);svc.confirmation(db,version)
                else:
                    version=row if table=='school_template_versions' else svc.row(db,row['project_id'],row['template_version_id'])
                    sources,task=svc.validate(db,version);svc.confirmation(db,version)
                    if svc.current_changes(db,version,sources):raise ValueError('Changed original')
                    if (task['status']=='succeeded')!=(version['analysis_json'] is not None):raise ValueError('Publication differs')
            except Exception:invalid+=1
        checks.append(dict(table=table,column='owner_frozen_sources_confirmation',rows=len(rows),total=total,truncated=total>len(rows),invalid=invalid))
    return checks
