"""One capability policy shared by intake and existing writing entry points."""
from app.core.exceptions import StorageError


def capabilities(project):
    return {'requirements':True,'research_design':True,'bio_import':True,'analysis':True,
            'legacy_writing':project['project_type'] in ('sci','thesis')}


def delivery_capabilities(project,deliveries):
    supported={'analysis':True,'sci_draft':project['project_type']=='sci','thesis_draft':project['project_type']=='thesis'}
    return [{**dict(row),'selected':row['active'],'workflow_available':supported[row['kind']]} for row in deliveries]


def require_legacy_writing(store, project_id):
    project = store.project(project_id)
    if not capabilities(project)['legacy_writing']:
        raise StorageError('research_writing_unavailable','研究项目的交付已登记，实际稿件流程将在后续批次开放。',409)
    return project


def require_legacy_writing_db(db, project_id, owner_id):
    row = db.execute('SELECT project_type FROM projects WHERE id=%s AND owner_id=%s',(project_id,owner_id)).fetchone()
    if row is None:
        raise StorageError('project_not_found','项目不存在。',404)
    if row['project_type'] == 'research':
        raise StorageError('research_writing_unavailable','研究项目的交付已登记，实际稿件流程将在后续批次开放。',409)
    return dict(row)


require_legacy_writing_project=require_legacy_writing_db
