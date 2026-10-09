"""Fixed public error codes and categories; never persist provider text."""
from app.core.errors import PUBLIC_CODES
from typing import Literal


ErrorCategory = Literal['temporary', 'authentication', 'permission',
    'configuration', 'source', 'output', 'submission_unknown', 'budget', 'interrupted', 'internal']
RetryReason = Literal['temporary_provider_error', 'worker_interrupted', 'manual_retry']


def safe_error_code(code):
    if code is None:
        return None
    return code if isinstance(code, str) and code in PUBLIC_CODES else 'internal_error'


def error_category(code):
    code = safe_error_code(code)
    if code is None:
        return None
    if code == 'model_provider_unavailable':
        return 'temporary'
    if code in ('model_authentication_failed', 'authentication_required', 'invalid_credentials'):
        return 'authentication'
    if code in ('model_permission_denied', 'permission_denied', 'task_owner_unavailable'):
        return 'permission'
    if code == 'model_submission_unknown':
        return 'submission_unknown'
    if code in ('model_budget_missing', 'model_budget_exceeded'):
        return 'budget'
    if code == 'task_worker_interrupted':
        return 'interrupted'
    if code in ('model_request_rejected', 'model_policy_not_configured', 'model_policy_invalid',
            'openai_not_configured', 'explanation_not_configured', 'plot_not_configured',
            'authentication_configuration', 'database_configuration'):
        return 'configuration'
    if code in ('model_response_not_found', 'plot_container_expired', 'task_source_conflict',
            'source_conflict', 'file_changed', 'file_missing', 'figure_changed', 'figure_missing',
            'report_changed', 'report_missing', 'report_source_changed', 'report_source_conflict'):
        return 'source'
    if code in ('model_response_invalid', 'explanation_incomplete', 'explanation_invalid',
            'explanation_invalid_json', 'explanation_output_limit', 'explanation_refused',
            'plot_files_missing', 'plot_invalid_image', 'plot_invalid_result', 'plot_no_execution',
            'plot_output_limit', 'plot_result_mismatch', 'report_render_failed'):
        return 'output'
    return 'internal'


def classify_read_error(code, status_code=None):
    # Only known provider failures from safe GET/download operations qualify.
    if code == 'model_provider_request_failed':
        if status_code is None or status_code in (429, 500, 502, 503, 504):
            return 'model_provider_unavailable'
        return {401: 'model_authentication_failed', 403: 'model_permission_denied'}.get(
            status_code, 'model_request_rejected')
    return safe_error_code(code) or 'internal_error'
