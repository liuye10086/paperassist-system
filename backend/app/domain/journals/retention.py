"""Small file-retention bridge for sealed journal materials and tasks."""
from .guides import GuideService
from app.domain.report_collections.service import scoped_store


def read_refs(db,file,user):
    rows=[dict(r) for r in db.execute('SELECT * FROM journal_material_refs WHERE file_id=%s',(file['id'],))]
    service=GuideService(scoped_store(user,db.config))
    for row in rows:
        try:
            parent,material=ref_parent(service,db,file['project_id'],row)
            row['_integrity_valid']=row['user_id']==user and any(m and m['file_id']==file['id'] for m in material)
            row['snapshot_json']=parent['snapshot_json']
        except Exception:row['_integrity_valid']=False
    return rows


def validate_task(db,task):
    if task['task_type']=='journal_adaptation':
        from .adaptation_service import AdaptationService,input_version
        service=AdaptationService(scoped_store(task['user_id'],db.config))
        service.adaptation_row(db,task['project_id'],input_version(task)['adaptation_id']);return
    if task['task_type']=='journal_format_check':
        from .format_service import FormatService,input_version
        service=FormatService(scoped_store(task['user_id'],db.config))
        service.check_row(db,task['project_id'],input_version(task)['check_id']);return
    service=GuideService(scoped_store(task['user_id'],db.config))
    row=service.row(db,task['project_id'],task['input_snapshot']['recommendation_id'],'journal_recommendations');service.view(db,row)

def ref_parent(service,db,project,row):
    if row.get('guide_id'):
        parent=service.row(db,project,row['guide_id'],'journal_guides')
    elif row['profile_id']:parent=service.row(db,project,row['profile_id'],'journal_profiles')
    else:parent=service.row(db,project,row['recommendation_id'],'journal_recommendations')
    material=[parent['snapshot_json']['material']] if row.get('guide_id') or row['profile_id'] else parent['snapshot_json']['materials']
    return parent,material
