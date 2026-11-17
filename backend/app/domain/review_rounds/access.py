"""Owner-scoped review task and source checks shared with task handlers."""
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.report_collections.service import scoped_store


def review_task_assets(db, task, config, directory=None):
    assets = scoped_store(task['user_id'], config, directory)
    owner = db.execute('SELECT role FROM users WHERE id=%s', (task['user_id'],)).fetchone()
    assets.customer = owner is not None and owner['role'] == 'customer'
    return assets


def require_review_document_versions(db, assets, project, pairs):
    if not assets.customer or not pairs:
        return
    rows = db.execute('''SELECT r.file_id,r.id FROM file_parse_results r JOIN files ON files.id=r.file_id
        JOIN tasks t ON t.id=r.task_id WHERE r.id=ANY(%s) AND files.project_id=%s
        AND t.project_id=files.project_id AND t.user_id=%s AND t.status='succeeded'
        AND t.workflow_version IN ('docx_document_v1','pdf_document_v1')'''+assets.material_filter,
        ([version_id for _,version_id in pairs],project,assets.owner_id)).fetchall()
    if {(row['file_id'],row['id']) for row in rows} != set(pairs):
        raise StorageError('document_version_not_found','文档解析版本不存在。',404)


def require_review_task(db, assets, task):
    project = task['project_id']
    if task['task_type'] == 'review_round_plan':
        from .service import ReviewRoundService, input_version

        service = ReviewRoundService(assets)
        row = service.round_row(db, project, input_version(task)['round_id'])
        service.events(db, row)
    elif task['task_type'] == 'review_revision':
        from .revisions import RevisionService, input_version

        service = RevisionService(assets)
        row = service.revision_row(db, project, input_version(task)['revision_id'])
        if row['result_json'] is not None:
            service.output(db, row)
    elif task['task_type'] == 'review_document_export':
        from .document_exports import ReviewDocumentExportService, input_version

        row = ReviewDocumentExportService(assets).row(db, project, input_version(task)['export_id'])
    else:
        raise source_conflict()
    if row['task_id'] != task['id']:
        raise source_conflict()
