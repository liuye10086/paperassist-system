"""Public task and wait types must represent the actual spatial workflows."""
import pytest
from pydantic import TypeAdapter

from app.domain.tasks.contracts import TaskType
from app.domain.tasks.wait_contracts import WaitView


@pytest.mark.parametrize('kind', ['bio_analysis', 'bio_figure'])
def test_spatial_task_type_is_available_to_public_task_views(kind):
    assert TypeAdapter(TaskType).validate_python(kind) == kind


def test_qc_confirmation_has_a_distinct_public_wait_kind():
    kind_type = WaitView.model_fields['kind'].annotation
    assert TypeAdapter(kind_type).validate_python('bio_analysis_confirmation') == 'bio_analysis_confirmation'
