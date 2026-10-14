"""Atomic parser publication guarded by the existing execution lease."""
from datetime import timezone

import json

from psycopg.types.json import Jsonb

from app.adapters.excel import WorkbookPreview
from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.file_parsing import require_parse_source, sync_file_status


class FileParseStore:
    def __init__(self, repository):
        self.repository = repository

    def load(self, lease):
        repo = self.repository
        with repo.connection() as db:
            task = repo.require_lease(db, lease)
            repo.require_owner(db, task)
            snapshot = require_parse_source(db, task)
        return snapshot, repo.assets.original(snapshot['file'])

    def complete(self, lease, snapshot, preview):
        repo = self.repository
        # Validate before starting publication; JSON forbids nonfinite values.
        try:
            preview = WorkbookPreview.model_validate(preview.model_dump() if isinstance(preview, WorkbookPreview) else preview, strict=True)
            settings = snapshot['settings']['excel']
            if (preview.filename != snapshot['file']['filename'] or not preview.sheets
                    or len(preview.sheets) > settings['max_sheets']
                    or any(sheet.row_count < 0 or sheet.row_count > settings['max_rows']
                        or sheet.column_count < 0 or sheet.column_count > settings['max_columns']
                        or sheet.column_count != len(sheet.columns) or len(sheet.preview_rows) > 20
                        or any(len(row) != sheet.column_count for row in sheet.preview_rows)
                        for sheet in preview.sheets)):
                raise ValueError('Invalid finite preview')
            saved = {'preview': preview.model_dump(), 'parser_version': snapshot['parser_version'],
                     'settings': snapshot['settings'], 'source_sha256': snapshot['file']['sha256']}
            encoded = json.dumps(saved, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode('utf-8')) > snapshot['settings']['process']['max_output_bytes']:
                raise ValueError('Oversized result')
        except (TypeError, ValueError) as exc:
            raise StorageError('parse_output_invalid', '解析结果不完整，请检查文件后重试。', 422) from exc
        with repo.connection(write=True) as db:
            task = repo.require_lease(db, lease)
            repo.require_owner(db, task)
            if require_parse_source(db, task) != snapshot:
                raise source_conflict()
            repo.assets.original(snapshot['file'])
            repo.require_lease(db, lease)
            now = repo.now(db)
            updated = db.execute('''UPDATE file_parse_results SET completed_at=%s,result_json=%s
                WHERE id=%s AND task_id=%s AND result_json IS NULL''',
                (now, Jsonb(saved), snapshot['parse_id'], task['id']))
            if updated.rowcount != 1:
                raise source_conflict()
            db.execute('UPDATE files SET preview_json=%s WHERE id=%s', (preview.model_dump_json(), snapshot['file']['id']))
            repo._finish(db, task, 'succeeded', None)
            db.execute('UPDATE projects SET updated_at=GREATEST(updated_at,%s) WHERE id=%s', (now.astimezone(timezone.utc).isoformat(), task['project_id']))
            return TaskStore.public_task(task)

    def fail(self, lease, code):
        return self.repository.fail(lease, code)
