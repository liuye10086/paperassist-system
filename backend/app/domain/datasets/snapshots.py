"""Frozen file-only inputs and exact persisted source guards."""
from typing import Literal
from pydantic import Field
from app.domain.file_parsing import StrictModel, ParseProject, ParseFile, ParseSettings
from app.adapters.task_store import source_conflict


class StructureSnapshot(StrictModel):
    schema_version: Literal[1]
    kind: Literal['excel_structure']
    project: ParseProject
    file: ParseFile
    structure_id: str = Field(min_length=1)
    parser_version: Literal['openpyxl-3.1.5-structure-v1']
    settings: ParseSettings


def validate_snapshot(task):
    try:
        if task['task_type'] != 'extract_dataset' or task['workflow_version'] != 'excel_structure_v1':
            raise ValueError('Wrong structure workflow')
        snapshot = StructureSnapshot.model_validate(task['input_snapshot']).model_dump()
        if snapshot['project']['id'] != task['project_id']:
            raise ValueError('Wrong project')
        return snapshot
    except (ValueError, TypeError, KeyError) as exc:
        raise source_conflict() from exc


def structure_input_version(task):
    snapshot = validate_snapshot(task)
    return dict(kind='excel_structure', structure_id=snapshot['structure_id'],
                source_sha256=snapshot['file']['sha256'], parser_version=snapshot['parser_version'])


def require_structure_source(db, task):
    snapshot = validate_snapshot(task)
    file = db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',
                      (snapshot['file']['id'], task['project_id'])).fetchone()
    version = db.execute('SELECT * FROM file_structure_versions WHERE id=%s AND task_id=%s',
                         (snapshot['structure_id'], task['id'])).fetchone()
    if file and file['object_key'] is None:
        file = {**dict(file), 'object_key': f"files/{file['id']}.xlsx"}
    if (not file or not version or file['parse_status'] != 'parsed'
            or any(file[key] != value for key, value in snapshot['file'].items())
            or version['file_id'] != file['id'] or version['created_by'] != task['user_id']
            or version['source_sha256'] != snapshot['file']['sha256']
            or version['parser_version'] != snapshot['parser_version']
            or version['settings_json'] != snapshot['settings']):
        raise source_conflict()
    parent = db.execute('''SELECT id FROM file_structure_versions WHERE file_id=%s
        AND version<%s AND manifest_json IS NOT NULL ORDER BY version DESC LIMIT 1''',
        (file['id'], version['version'])).fetchone()
    if version['parent_id'] != (parent['id'] if parent else None):
        raise source_conflict()
    return snapshot
