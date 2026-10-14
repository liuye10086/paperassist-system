"""PDF parsing keeps the real task projection's fixed input identity."""
from datetime import datetime, timezone

import pytest

from app.adapters.task_store import TaskStore


@pytest.fixture(autouse=True)
def postgres_schema():
    # Pure projection; no database access is needed for this contract.
    yield


def test_pdf_task_projection_preserves_parser_and_source_identity():
    from app.domain.documents.service import document_snapshot
    now = datetime.now(timezone.utc)
    snapshot = document_snapshot('project', dict(id='file', filename='sample.pdf',
                            sha256='a' * 64, size_bytes=100, file_type='pdf',
                            storage_backend='local', object_key='uploads/sample.pdf'),
                            'parse', 1)
    task = dict(id='task', project_id='project', task_type='parse_file',
                status='queued', phase='parse', revision=1, current_attempt=0,
                reason_code=None, created_at=now, updated_at=now,
                workflow_version='pdf_document_v1', input_snapshot=snapshot)
    view = TaskStore.public_task(task)
    assert view['display_status'] == 'queued'
    assert view['input_version'] == dict(kind='parse_file', parse_id='parse',
                                         source_sha256='a' * 64,
                                         parser_version='pdfplumber-0.11.10-evidence-v2')
