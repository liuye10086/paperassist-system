from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.tasks.contracts import TaskView
from app.domain.tasks.wait_contracts import WaitView


def test_plan_task_and_wait_accept_matching_input_version():
    version = {'kind': 'analysis_plan', 'source': {
        'kind': 'prepared_dataset_version', 'schema_version': 1, 'file_id': 'f', 'dataset_id': 'd',
        'structure_id': 's', 'dataset_version': 1, 'source_sha256': 'a' * 64,
        'dataset_sha256': 'b' * 64, 'dataset_size_bytes': 10, 'dataset_schema_version': 1,
        'sheet_index': 0, 'sheet_name': 'Sheet1', 'parser_version': 'openpyxl-3.1.5-structure-v1',
        'parent_dataset_id': 'p', 'parent_dataset_version': 1,
        'transform_version': 'excel_prepare_v1'}, 'workflow_version': 'analysis_plan_v1'}
    now = datetime.now(timezone.utc)
    task = dict(id='t', project_id='p', task_type='analysis_plan', status='waiting_confirmation',
                phase='plan', display_status='waiting_confirmation', revision=2, current_attempt=1,
                retry_count=0, reason_code='confirmation_required', created_at=now,
                updated_at=now, input_version=version)
    assert TaskView.model_validate(task).input_version.kind == 'analysis_plan'
    wait = dict(id='w', kind='analysis_plan_confirmation', status='open', task_revision=2,
                input_version=version, reason_code='confirmation_required', error_code=None,
                created_at=now, resolved_at=None)
    assert WaitView.model_validate(wait).kind == 'analysis_plan_confirmation'
    with pytest.raises(ValidationError):
        TaskView.model_validate({**task, 'task_type': 'prepare_dataset'})
