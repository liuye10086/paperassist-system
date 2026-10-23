"""Read-only audit of scoped frozen review rounds and explicit plan history."""
from app.domain.review_rounds.service import ReviewRoundService,input_version
from app.domain.review_rounds.contracts import CreateRequest,ItemEdit
from app.domain.report_collections.service import scoped_store

def audit_review_rounds(db,*,limit=200):
    rows=db.execute('SELECT * FROM review_rounds ORDER BY id LIMIT %s',(limit,)).fetchall();invalid=0
    for row in rows:
        try:
            service=ReviewRoundService(scoped_store(row['user_id'],db.config))
            CreateRequest.model_validate(row['request_json']);service.round_row(db,row['project_id'],row['id']);service.fixed(db,row)
            state,events=service.state(db,row)
            if [e['revision'] for e in events]!=list(range(1,len(events)+1)):raise ValueError('History gap')
            if events:
                original={i['id']:(i['original_text'],i['source_id'],i['source_location']) for i in events[0]['snapshot_json']['items']}
                for event in events:
                    if {i['id']:(i['original_text'],i['source_id'],i['source_location']) for i in event['snapshot_json']['items']}!=original:raise ValueError('Original changed')
                    for item in event['snapshot_json']['items']:
                        ItemEdit.model_validate({k:item[k] for k in ItemEdit.model_fields})
                        if item['status']=='completed':raise ValueError('False completion')
        except Exception:invalid+=1
    total=db.execute('SELECT count(*) n FROM review_rounds').fetchone()['n']
    return [dict(table='review_rounds',column='frozen_review_history',rows=len(rows),total=total,truncated=total>len(rows),invalid=invalid)]
