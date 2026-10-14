"""File metadata services; business sources and asset bytes remain immutable."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from app.core.exceptions import StorageError


PURPOSES = ('raw_data', 'figure', 'methods', 'school_template', 'paper', 'revision_material')
Purpose = Literal['raw_data', 'figure', 'methods', 'school_template', 'paper', 'revision_material']


class FileError(BaseModel):
    code: str
    message: str
    params: dict = Field(default_factory=dict)


class ProjectFile(BaseModel):
    id: str
    project_id: str
    filename: str
    file_type: Literal['xlsx', 'docx', 'pdf', 'png', 'jpeg']
    size_bytes: int
    sha256: str
    uploaded_at: str
    parse_status: Literal['queued', 'parsing', 'parsed', 'failed']
    error: FileError | None


class UploadBatchSummary(BaseModel):
    created_at: str
    item_count: int = Field(ge=1, le=10)
    item_position: int = Field(ge=1, le=10)


class FileMetadata(ProjectFile):
    parse_revision: int = Field(ge=0)
    purposes: list[Purpose]
    metadata_revision: int = Field(ge=1)
    uploader_recorded: bool
    upload_batch: UploadBatchSummary | None = None


class FilePage(BaseModel):
    items: list[FileMetadata]
    total: int
    page: int
    page_size: int


class FileSource(BaseModel):
    kind: Literal['legacy_excel', 'excel_parse', 'docx_parse', 'pdf_parse', 'ocr_parse'] = 'legacy_excel'
    preview_available: bool
    preview_row_limit: Literal[20] | None = 20
    parser_version: str | None = None


class FileReferences(BaseModel):
    structure_versions: int = Field(ge=0)
    dataset_versions: int = Field(ge=0)
    prepared_dataset_versions: int = Field(default=0, ge=0)
    analysis_setups: int = Field(ge=0)
    analysis_runs: int = Field(ge=0)
    figures: int = Field(ge=0)
    explanations: int = Field(ge=0)
    reports: int = Field(ge=0)
    tasks: int = Field(ge=0)
    legacy_jobs: int = Field(ge=0)
    active_tasks: int = Field(ge=0)
    recovery_candidates: int = Field(ge=0)


class FileRetention(BaseModel):
    policy: Literal['internal_testing_keep'] = 'internal_testing_keep'
    automatic_deletion: Literal[False] = False
    deletion_available: Literal[False] = False


class FileDetails(FileMetadata):
    source: FileSource
    references: FileReferences
    retention: FileRetention = Field(default_factory=FileRetention)


class FilePurposesInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: StrictInt = Field(ge=1)
    purposes: list[Purpose] = Field(max_length=6)

    @field_validator('purposes')
    @classmethod
    def unique_purposes(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('文件用途不可重复。')
        return value


def require_project(db, store, project_id):
    scope = ' AND owner_id=%s' if store.owner_id is not None else ''
    params = (project_id, store.owner_id) if store.owner_id is not None else (project_id,)
    if db.execute('SELECT id FROM projects WHERE id=%s' + scope, params).fetchone() is None:
        raise StorageError('project_not_found', '项目不存在，请刷新项目列表。', 404)


def require_file(db, project_id, file_id, *, lock=False):
    row = db.execute('SELECT * FROM files WHERE project_id=%s AND id=%s' + (' FOR UPDATE' if lock else ''),
                     (project_id, file_id)).fetchone()
    if row is None:
        raise StorageError('file_not_found', '当前项目中没有此文件。', 404)
    return row


def batch_summaries(db, store, project_id, rows):
    if not rows:
        return {}
    summaries = db.execute('''SELECT f.id AS file_id,b.created_at,i.ordinal+1 AS item_position,
        (SELECT count(*) FROM file_upload_items registered WHERE registered.batch_id=b.id) AS item_count
        FROM files f JOIN file_upload_items i ON i.id=f.upload_item_id AND i.file_id=f.id
        JOIN file_upload_batches b ON b.id=i.batch_id
        WHERE f.project_id=%s AND b.project_id=f.project_id AND b.user_id=%s AND f.id=ANY(%s)''',
        (project_id, store.owner_id, [row['id'] for row in rows]))
    return {row['file_id']: {'created_at': row['created_at'].astimezone(timezone.utc).isoformat(), 'item_count': row['item_count'],
                            'item_position': row['item_position']} for row in summaries}


def metadata_record(db, store, row, summaries=None):
    if summaries is None:
        summaries = batch_summaries(db, store, row['project_id'], [row])
    assigned = {item['purpose'] for item in db.execute('SELECT purpose FROM file_purposes WHERE file_id=%s', (row['id'],))}
    return {**store.file_record(row), 'purposes': [purpose for purpose in PURPOSES if purpose in assigned],
            'metadata_revision': row['metadata_revision'], 'parse_revision': row['parse_revision'],
            'uploader_recorded': row['uploader_id'] is not None, 'upload_batch': summaries.get(row['id'])}


def query_files(store, project_id, *, page=1, page_size=10):
    if (type(page) is not int or not 1 <= page <= 1_000_000
            or type(page_size) is not int or not 1 <= page_size <= 100):
        raise StorageError('file_query_invalid', '页码须为1–1000000，页面大小须为1–100。', 422)
    with store.connection() as db:
        require_project(db, store, project_id)
        total = db.execute('SELECT count(*) AS n FROM files WHERE project_id=%s', (project_id,)).fetchone()['n']
        rows = db.execute('SELECT * FROM files WHERE project_id=%s ORDER BY uploaded_at DESC,id ASC LIMIT %s OFFSET %s',
                          (project_id, page_size, (page - 1) * page_size)).fetchall()
        summaries = batch_summaries(db, store, project_id, rows)
        return {'items': [metadata_record(db, store, row, summaries) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


REFERENCES = '''WITH runs AS (
    SELECT r.id FROM analysis_runs r JOIN files f ON f.id=r.file_id
    WHERE f.project_id=%s AND f.id=%s
), linked_figures AS (
    SELECT f.id,f.analysis_run_id FROM figures f JOIN runs r ON r.id=f.analysis_run_id
), linked_explanations AS (
    SELECT e.id,e.analysis_run_id FROM explanations e JOIN linked_figures f
    ON f.id=e.figure_id AND f.analysis_run_id=e.analysis_run_id
), linked_tasks AS (
    SELECT t.id,t.status,t.figure_candidate FROM tasks t WHERE t.project_id=%s AND (
        t.input_snapshot->'file'->>'id'=%s OR t.input_snapshot->'result'->>'file_id'=%s
        OR t.input_snapshot->'source'->>'file_id'=%s
        OR t.input_snapshot->'result'->>'id' IN (SELECT id FROM runs))
), legacy_jobs AS (
    SELECT j.id FROM figure_jobs j JOIN runs r ON r.id=j.analysis_run_id
    UNION ALL
    SELECT j.id FROM explanation_jobs j JOIN linked_figures f
    ON f.id=j.figure_id AND f.analysis_run_id=j.analysis_run_id
)
SELECT
    (SELECT count(*) FROM analysis_setups WHERE file_id=%s) AS analysis_setups,
    (SELECT count(*) FROM runs) AS analysis_runs,
    (SELECT count(*) FROM linked_figures) AS figures,
    (SELECT count(*) FROM linked_explanations) AS explanations,
    (SELECT count(*) FROM reports p JOIN linked_explanations e ON e.id=p.explanation_id
        AND e.analysis_run_id=p.analysis_run_id) AS reports,
    (SELECT count(*) FROM linked_tasks) AS tasks,
    (SELECT count(*) FROM legacy_jobs) AS legacy_jobs,
    (SELECT count(*) FROM linked_tasks WHERE status IN ('queued','running','waiting_input','waiting_confirmation')) AS active_tasks,
    (SELECT count(*) FROM linked_tasks WHERE figure_candidate IS NOT NULL) AS recovery_candidates
'''


def read_file_details(store, project_id, file_id):
    with store.connection() as db:
        require_project(db, store, project_id)
        row = require_file(db, project_id, file_id)
        result = metadata_record(db, store, row)
        references = dict(db.execute(REFERENCES, (project_id, file_id, project_id, file_id, file_id, file_id, file_id)).fetchone())
        references['structure_versions'] = db.execute('SELECT count(*) AS n FROM file_structure_versions WHERE file_id=%s',(file_id,)).fetchone()['n']
        references['dataset_versions'] = db.execute('SELECT count(*) AS n FROM dataset_versions WHERE file_id=%s',(file_id,)).fetchone()['n']
        references['prepared_dataset_versions'] = db.execute('SELECT count(*) AS n FROM prepared_dataset_versions WHERE file_id=%s',(file_id,)).fetchone()['n']
        parse = db.execute('SELECT parser_version FROM file_parse_results WHERE file_id=%s ORDER BY version DESC', (file_id,)).fetchone()
        return FileDetails(**result, source=FileSource(kind='ocr_parse' if row['file_type'] in ('png','jpeg') else 'pdf_parse' if row['file_type']=='pdf' else 'docx_parse' if row['file_type']=='docx' else 'excel_parse' if parse else 'legacy_excel',
            preview_row_limit=None if row['file_type'] in ('docx','pdf','png','jpeg') else 20,
            parser_version=parse['parser_version'] if parse else None,
            preview_available=bool(db.execute('SELECT id FROM file_parse_results WHERE file_id=%s AND result_json IS NOT NULL',(file_id,)).fetchone()) if row['file_type'] in ('docx','pdf','png','jpeg') else row['parse_status'] == 'parsed' and row['preview_json'] is not None), references=references)


def assign_file_purposes(store, project_id, file_id, changes: FilePurposesInput):
    with store.connection(write=True) as db:
        require_project(db, store, project_id)
        row = require_file(db, project_id, file_id, lock=True)
        current = metadata_record(db, store, row)
        if changes.expected_revision != row['metadata_revision']:
            if changes.expected_revision < row['metadata_revision'] and set(changes.purposes) == set(current['purposes']):
                return current
            raise StorageError('file_metadata_conflict', '文件用途已更新，请重新载入后修改。', 409)
        # Preserve existing assignment provenance for purposes kept in the set.
        for purpose in current['purposes']:
            if purpose not in changes.purposes:
                db.execute('DELETE FROM file_purposes WHERE file_id=%s AND purpose=%s', (file_id, purpose))
        now = datetime.now(timezone.utc).isoformat()
        for purpose in changes.purposes:
            if purpose not in current['purposes']:
                db.execute('INSERT INTO file_purposes(file_id,purpose,assigned_by,assigned_at) VALUES (%s,%s,%s,%s)',
                           (file_id, purpose, store.owner_id, now))
        updated = db.execute('UPDATE files SET metadata_revision=metadata_revision+1 WHERE id=%s RETURNING *', (file_id,)).fetchone()
        return metadata_record(db, store, updated)
