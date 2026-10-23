"""Resolve typed manuscript/review intents before applying file-scoped retention."""
from app.adapters.task_store import source_conflict
from app.domain.report_collections.service import scoped_store

TYPES = frozenset(('manuscript_draft', 'manuscript_docx', 'manuscript_writing', 'literature_search',
                   'review_round_plan', 'review_revision', 'review_document_export', 'pdf_export'))


def task_material(db, task, user, project):
    if task['user_id'] != user or task['project_id'] != project:
        raise source_conflict()
    assets = scoped_store(user, db.config)
    from app.domain.manuscripts.service import ManuscriptService
    manuscripts = ManuscriptService(assets)
    kind = task['task_type']
    if kind == 'literature_search':
        from app.domain.literature.service import LiteratureService, require_snapshot
        LiteratureService(assets).require_search(db, project, task['id'])
        return require_snapshot(task)
    if kind in ('manuscript_draft', 'manuscript_docx'):
        return manuscripts.verify_task(db, task)['snapshot_json']
    if kind == 'manuscript_writing':
        from app.domain.manuscript_writing.service import WritingService, require_snapshot
        snap = require_snapshot(task)
        WritingService(assets).row(db, project, snap['manuscript_id'], task['id'])
        return snap
    if kind == 'review_round_plan':
        from app.domain.review_rounds.service import ReviewRoundService, input_version
        service = ReviewRoundService(assets)
        row = service.round_row(db, project, input_version(task)['round_id'])
        base = service.fixed(db, row)
        return dict(base=base['snapshot_json'], inputs=row['snapshot_json'],
                    history=[event['snapshot_json'] for event in service.events(db, row)])
    if kind == 'review_revision':
        from app.domain.review_rounds.revisions import RevisionService, input_version
        service = RevisionService(assets)
        row = service.revision_row(db, project, input_version(task)['revision_id'])
        base = manuscripts.version(db, project, row['manuscript_id'], row['snapshot_json']['manuscript']['revision'])
        return dict(base=base['snapshot_json'], inputs=row['snapshot_json'], result=row['result_json'])
    if kind == 'review_document_export':
        from app.domain.review_rounds.document_exports import ReviewDocumentExportService, input_version
        service = ReviewDocumentExportService(assets)
        row = service.row(db, project, input_version(task)['export_id'])
        document = service.documents.row(db, project, row['document_id'])
        revision = db.execute('SELECT task_id FROM review_revision_runs WHERE id=%s', (document['revision_id'],)).fetchone()
        if not revision:
            raise source_conflict()
        return dict(document=row['snapshot_json'], revision=task_material(db, service.store.require_task(db, revision['task_id']), user, project))
    if kind == 'pdf_export':
        from app.domain.pdf_exports.service import PdfExportService, input_version
        service = PdfExportService(assets)
        row = service.row(db, project, input_version(task)['export_id'])
        tables = {'manuscript_export': 'manuscript_exports', 'review_document_export': 'review_document_exports'}
        table = tables.get(row['source_kind'])
        if not table:
            # Other export families keep their existing source-resolution path.
            return task['input_snapshot']
        source = db.execute('SELECT task_id FROM ' + table + ' WHERE id=%s', (row['source_id'],)).fetchone()
        if not source:
            raise source_conflict()
        return task_material(db, service.store.require_task(db, source['task_id']), user, project)
    raise source_conflict()
