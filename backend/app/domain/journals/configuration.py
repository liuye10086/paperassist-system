"""Read-only versioned policy seam; update dates come from saved versions."""
def configuration(db,project,user):
    dates={}
    for kind,table in [('profile','journal_profiles'),('guide','journal_guides')]:
        row=db.execute("SELECT max(snapshot_json->>'verified_on') AS date FROM "+table+' WHERE project_id=%s AND user_id=%s',(project,user)).fetchone()
        dates['latest_'+kind+'_verified_on']=row['date']
    return dict(source_policy=dict(version=1,mode='local_only',metrics_enabled=False),recommendation_policy=dict(version='journal_recommendation_v1',default_count=3,max_count=5),updates=dates)
