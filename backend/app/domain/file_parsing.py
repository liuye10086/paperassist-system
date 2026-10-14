"""Frozen, strict file-only parser input, separate from statistical snapshots."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import ExcelSettings
from app.core.exceptions import StorageError

PARSER_VERSION = 'openpyxl-3.1.5-preview-v1'
PROCESS_SETTINGS = {'timeout_seconds': 60, 'cpu_seconds': 30,
                    'memory_bytes': 536870912, 'max_output_bytes': 4194304}
RETRYABLE_CODES = frozenset({'parse_timeout', 'parse_resource_limit', 'parse_process_failed',
    'parse_environment_unavailable', 'storage_unavailable', 'task_worker_interrupted', 'task_execution_failed'})


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)


class ParseProject(StrictModel):
    id: str = Field(min_length=1)


class ParseFile(StrictModel):
    id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size_bytes: int = Field(ge=1, le=10485760)
    file_type: Literal['xlsx']
    storage_backend: Literal['local']
    object_key: str = Field(min_length=1)


class ParseExcelSettings(StrictModel):
    max_upload_bytes: int = Field(gt=0, le=10485760)
    max_uncompressed_bytes: int = Field(gt=0, le=67108864)
    max_sheets: int = Field(gt=0, le=50)
    max_rows: int = Field(gt=0, le=100000)
    max_columns: int = Field(gt=0, le=256)
    max_cells: int = Field(gt=0, le=1000000)


class ParseProcessSettings(StrictModel):
    timeout_seconds: Literal[60]
    cpu_seconds: Literal[30]
    memory_bytes: Literal[536870912]
    max_output_bytes: Literal[4194304]

    @field_validator('timeout_seconds', 'cpu_seconds', 'memory_bytes', 'max_output_bytes', mode='before')
    @classmethod
    def exact_integer(cls, value):
        if type(value) is not int:
            raise ValueError('Integer process limits are required')
        return value


class ParseSettings(StrictModel):
    excel: ParseExcelSettings
    process: ParseProcessSettings


class ParseFileSnapshot(StrictModel):
    schema_version: Literal[1]
    kind: Literal['parse_file']
    project: ParseProject
    file: ParseFile
    parse_id: str = Field(min_length=1)
    parser_version: Literal['openpyxl-3.1.5-preview-v1']
    settings: ParseSettings

    @field_validator('schema_version', mode='before')
    @classmethod
    def exact_schema_version(cls, value):
        if type(value) is not int:
            raise ValueError('An integer schema version is required')
        return value


def validate_snapshot(task):
    from app.adapters.task_store import source_conflict
    try:
        if task['task_type'] != 'parse_file' or task['workflow_version'] not in ('parse_file_v1', 'docx_document_v1', 'pdf_document_v1', 'ocr_document_v1'):
            raise ValueError('Wrong parse workflow')
        from app.domain.documents.snapshots import DocxFileSnapshot, PdfFileSnapshot
        from app.domain.documents.ocr_snapshots import OcrFileSnapshot
        model = OcrFileSnapshot if task['workflow_version']=='ocr_document_v1' else PdfFileSnapshot if task['workflow_version'] == 'pdf_document_v1' else DocxFileSnapshot if task['workflow_version'] == 'docx_document_v1' else ParseFileSnapshot
        snapshot = model.model_validate(task['input_snapshot']).model_dump()
        if snapshot['project']['id'] != task['project_id']:
            raise ValueError('Wrong project')
        return snapshot
    except (ValueError, TypeError, KeyError) as exc:
        raise source_conflict() from exc


def parse_input_version(task):
    snapshot = validate_snapshot(task)
    return {'kind': 'parse_file', 'parse_id': snapshot['parse_id'],
            'source_sha256': snapshot['file']['sha256'], 'parser_version': snapshot['parser_version']}


def require_parse_source(db, task):
    from app.adapters.task_store import source_conflict
    snapshot = validate_snapshot(task)
    file = db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',
                      (snapshot['file']['id'], task['project_id'])).fetchone()
    result = db.execute('SELECT * FROM file_parse_results WHERE id=%s AND task_id=%s',
                        (snapshot['parse_id'], task['id'])).fetchone()
    if (not file or not result or any(file[key] != value for key, value in snapshot['file'].items())
            or result['file_id'] != file['id'] or result['version'] != snapshot.get('parse_version', 1)
            or result['source_sha256'] != snapshot['file']['sha256']
            or result['parser_version'] != snapshot['parser_version']
            or result['settings_json'] != snapshot['settings']):
        raise source_conflict()
    return snapshot


def sync_file_status(db, task, status, error=None):
    from app.core.errors import error_detail
    import json
    file_id = task['input_snapshot']['file']['id']
    details = error_detail(error, '文件解析失败，请检查文件或重试。') if error else None
    db.execute('''UPDATE files SET parse_status=%s,parse_revision=parse_revision+1,error_json=%s
        WHERE id=%s AND project_id=%s AND parse_status<>%s
        AND NOT EXISTS (SELECT 1 FROM file_parse_results newer JOIN file_parse_results current ON current.task_id=%s
            WHERE newer.file_id=files.id AND newer.version>current.version)''',
        (status, json.dumps(details, ensure_ascii=False) if details else None,
         file_id, task['project_id'], status, task['id']))
