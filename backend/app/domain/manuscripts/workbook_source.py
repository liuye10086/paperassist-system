"""Freeze a manuscript selection of an existing, successful Excel parse."""
from app.adapters.excel import HIDDEN_SHEET_WARNING, WorkbookPreview
from app.adapters.task_store import source_conflict
from app.domain.file_parsing import require_parse_source
from app.domain.literature.service import digest


def read_workbook_source(service, project, file, parse_id):
    with service.store.connection() as db:
        row = db.execute('SELECT * FROM file_parse_results WHERE id=%s AND file_id=%s',
                         (parse_id, file['id'])).fetchone()
        if not row:
            raise source_conflict()
        task = service.store.require_task(db, row['task_id'])
        if task['project_id'] != project or task['status'] != 'succeeded' or task['workflow_version'] != 'parse_file_v1':
            raise source_conflict()
        snapshot = require_parse_source(db, task)
    saved = row['result_json']
    if (not isinstance(saved, dict) or saved.get('source_sha256') != file['sha256']
            or saved.get('settings') != snapshot['settings'] or saved.get('parser_version') != snapshot['parser_version']):
        raise source_conflict()
    try:
        preview = WorkbookPreview.model_validate(saved['preview'], strict=True)
        if preview.filename != file['filename']:
            raise ValueError('Workbook filename changed')
    except (KeyError, ValueError) as exc:
        raise source_conflict() from exc
    service.assets.original(file)

    items = []
    partial = False
    for sheet in preview.sheets:
        if not sheet.columns or HIDDEN_SHEET_WARNING in sheet.warnings:
            continue
        items.append(dict(kind='text', text=sheet.name))
        partial |= sheet.row_count > len(sheet.preview_rows)
        for row_values in [sheet.columns, *sheet.preview_rows]:
            cells = []
            for value in row_values:
                if isinstance(value, str) and value.startswith('='):
                    # Never send spreadsheet formulas or give their caches the meaning of results.
                    value = None
                    partial = True
                cells.append('' if value is None else str(value))
            if any(cells):
                items.append(dict(kind='text', text='\t'.join(cells)))
    checksum = digest(saved)
    return dict(source=dict(file_id=file['id'], file_type='xlsx', version=row['version'],
                            version_id=parse_id, source_sha256=file['sha256'], sha256=checksum),
                items=items, text_truncated=partial), checksum
