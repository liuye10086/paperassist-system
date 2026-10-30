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
    if code in ('storage_quota_exceeded', 'storage_disk_insufficient'):
        return 'configuration'
    if code in ('storage_accounting_unknown','storage_deletion_pending','storage_deletion_scope_unknown'):
        return 'source'
    if code in ('pdf_conversion_timeout','pdf_renderer_busy','ncbi_unavailable', 'model_provider_unavailable', 'parse_timeout', 'parse_resource_limit', 'parse_process_failed', 'storage_unavailable',
            'numeric_timeout', 'numeric_failure'):
        return 'temporary'
    if code in ('model_authentication_failed', 'authentication_required', 'invalid_credentials'):
        return 'authentication'
    if code in ('model_permission_denied', 'permission_denied', 'task_owner_unavailable'):
        return 'permission'
    if code in ('model_submission_unknown','model_observation_expired'):
        return 'submission_unknown'
    if code in ('model_budget_missing', 'model_budget_exceeded'):
        return 'budget'
    if code == 'task_worker_interrupted':
        return 'interrupted'
    if code in ('model_configuration_disabled','pdf_renderer_unavailable','pdf_renderer_mismatch','literature_assistance_not_authorized', 'manuscript_writing_not_authorized', 'ncbi_not_configured', 'ncbi_request_rejected', 'model_request_rejected', 'model_policy_not_configured', 'model_policy_invalid', 'numeric_timeout_invalid',
            'openai_not_configured', 'explanation_not_configured', 'plot_not_configured', 'recommendation_not_configured',
            'authentication_configuration', 'database_configuration', 'parse_environment_unavailable', 'numeric_environment_unavailable'):
        return 'configuration'
    if code in ('layout_source_invalid','layout_source_mismatch','layout_target_invalid','layout_formula_invalid','layout_formula_too_wide','pdf_input_invalid','literature_source_conflict', 'literature_revision_conflict', 'model_response_not_found', 'plot_container_expired', 'task_source_conflict',
            'numeric_input_limit', 'numeric_descriptive_limit', 'numeric_row_limit', 'numeric_effect_limit', 'numeric_input_bytes_limit', 'numeric_sample_size',
            'source_conflict', 'dataset_missing', 'dataset_changed', 'structure_version_conflict', 'structure_task_pending', 'file_changed', 'file_missing', 'figure_changed', 'figure_missing',
            'report_changed', 'report_missing', 'report_source_changed', 'report_source_conflict',
            'invalid_workbook', 'workbook_too_large', 'parse_failed', 'encrypted_document',
            'invalid_document', 'document_too_large', 'document_changed', 'document_missing', 'file_too_large', 'empty_file'):
        return 'source'
    if code in ('layout_field_update_failed','pdf_conversion_failed','literature_assistance_invalid', 'manuscript_writing_invalid', 'manuscript_writing_citation_scope', 'ncbi_response_invalid', 'recommendation_invalid', 'model_response_invalid', 'explanation_incomplete', 'explanation_invalid',
            'numeric_output_limit', 'numeric_output_missing', 'numeric_output_invalid', 'result_mismatch',
            'explanation_invalid_json', 'explanation_output_limit', 'explanation_refused',
            'plot_files_missing', 'plot_invalid_image', 'plot_invalid_result', 'plot_no_execution',
            'plot_output_limit', 'plot_result_mismatch', 'report_render_failed', 'parse_output_invalid'):
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
