"""Task contracts express lifecycle separately from the current work phase."""
import pytest
from pydantic import ValidationError


def test_display_states_use_lifecycle_before_the_retained_phase():
    from app.domain.tasks.contracts import display_status

    phases = ('parse', 'plan', 'compute', 'search', 'interpret', 'write', 'export', 'verify')
    for status in ('queued', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed'):
        assert {display_status(status, phase) for phase in phases} == {status}
    assert [display_status('running', phase) for phase in phases] == [
        'parsing', 'analyzing', 'computing', 'searching', 'analyzing',
        'generating_document', 'generating_document', 'analyzing',
    ]


def test_task_inputs_are_typed_by_the_existing_business_sources():
    from app.domain.tasks.contracts import TaskCreateRequest

    base = dict(file_id='file', analysis_run_id='run', expected_revision=1)
    assert TaskCreateRequest(task_type='boxplot', **base).figure_id is None
    assert TaskCreateRequest(task_type='explanation', figure_id='figure', **base).figure_id == 'figure'
    assert TaskCreateRequest(task_type='word_report', figure_id='figure', explanation_id='explanation', **base)
    invalid = [
        {'task_type': 'unimplemented'}, {'task_type': 'explanation'},
        {'task_type': 'word_report', 'figure_id': 'figure'},
        {'task_type': 'boxplot', 'figure_id': 'figure'},
        {'task_type': 'explanation', 'figure_id': 'figure', 'explanation_id': 'explanation'},
        {'task_type': 'boxplot', 'expected_revision': True},
        {'task_type': 'boxplot', 'expected_revision': '1'},
        {'task_type': 'boxplot', 'input_snapshot': {'untrusted': 'body'}},
    ]
    for changes in invalid:
        with pytest.raises(ValidationError):
            TaskCreateRequest(**{**base, **changes})


def test_transition_rules_require_explicit_wait_and_retry_reasons():
    from app.domain.tasks.service import validate_transition
    from app.core.exceptions import StorageError

    for old, new, reason in [
        ('queued', 'running', None), ('running', 'succeeded', None),
        ('running', 'waiting_input', 'input_required'),
        ('running', 'waiting_confirmation', 'submission_unknown'),
        ('running', 'waiting_confirmation', 'budget_exceeded'),
        ('running', 'failed', 'execution_failed'),
        ('waiting_input', 'queued', 'input_provided'),
        ('waiting_confirmation', 'queued', 'confirmation_received'),
        ('failed', 'queued', 'retry_requested'),
    ]:
        validate_transition(old, new, reason)
    for old, new, reason in [
        ('queued', 'succeeded', None), ('succeeded', 'queued', 'retry_requested'),
        ('waiting_input', 'running', None), ('failed', 'queued', None),
        ('waiting_confirmation', 'queued', 'input_provided'),
        ('running', 'failed', 'private-provider-error'),
    ]:
        with pytest.raises(StorageError) as rejected:
            validate_transition(old, new, reason)
        assert (rejected.value.code, rejected.value.status) == ('task_transition_invalid', 409)
