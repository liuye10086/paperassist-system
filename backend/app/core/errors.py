"""Shared public errors; parameters never contain arbitrary input or exceptions."""
import logging
import re

from starlette.responses import JSONResponse


PUBLIC_CODES = frozenset('''
school_change_invalid school_change_preview_conflict school_change_blocked
school_export_input_invalid
layout_docx_not_found layout_docx_not_ready layout_retry_not_allowed layout_field_update_failed layout_source_invalid layout_source_mismatch layout_target_invalid layout_formula_invalid layout_formula_too_wide
pdf_export_not_found pdf_source_not_found pdf_source_not_ready pdf_export_not_ready pdf_retry_not_allowed
pdf_renderer_unavailable pdf_conversion_failed pdf_conversion_timeout pdf_renderer_busy pdf_input_invalid pdf_renderer_mismatch
literature_assistance_not_authorized literature_assistance_invalid manuscript_writing_not_authorized manuscript_writing_invalid manuscript_writing_citation_scope manuscript_writing_base_incomplete
figure_language_unsupported figure_language_invalid_image figure_language_not_found manuscript_writing_language_invalid manuscript_writing_language_required manuscript_writing_review_invalid manuscript_writing_review_required manuscript_writing_material_blocked manuscript_writing_selection_invalid manuscript_writing_input_limit
ncbi_not_configured ncbi_unavailable ncbi_request_rejected ncbi_response_invalid
literature_not_found literature_source_conflict literature_revision_conflict literature_supplement_limit
literature_citation_conflict manuscript_not_found manuscript_revision_conflict
manuscript_review_input_invalid manuscript_review_not_found manuscript_review_blocked manuscript_review_v2_workflow_required
authentication_configuration authentication_required csrf_invalid database_configuration
empty_file explanation_input_limit explanation_not_configured explanation_incomplete explanation_invalid explanation_invalid_json
figure_projection_invalid
explanation_output_limit explanation_refused figure_changed figure_conflict figure_missing
figure_not_found file_changed file_missing file_not_found file_not_parsed file_too_large file_metadata_conflict file_query_invalid
image_not_found invalid_document encrypted_document document_too_large document_changed document_missing document_version_not_found
document_idempotency_conflict document_version_conflict document_parse_active
file_assessment_conflict file_deletion_idempotency_conflict
external_evidence_not_found external_evidence_revision_conflict
ocr_review_active
invalid_analysis_selection invalid_column invalid_credentials invalid_current_password
invalid_recovery_code invalid_request invalid_workbook login_rate_limited missing_file
no_valid_records numeric_precision openai_connection openai_incomplete openai_not_configured
openai_not_found openai_request_failed parse_failed password_rate_limited plot_files_missing
plot_invalid_image plot_invalid_result plot_label_too_long plot_no_execution plot_output_limit
plot_not_configured plot_input_limit plot_container_expired
plot_result_mismatch project_language_invalid project_not_found project_query_invalid
project_summary_query_invalid project_type_immutable project_update_invalid report_changed
report_missing report_not_found report_render_failed report_source_changed report_source_conflict
result_mismatch result_not_found setup_conflict sheet_not_found source_conflict storage_unavailable
storage_version unsupported_file_type workbook_too_large internal_error not_found method_not_allowed
request_failed permission_denied ai_configured task_submitting task_running task_completed task_uncertain task_failed task_unknown
task_not_found task_idempotency_conflict task_revision_conflict task_transition_invalid task_input_invalid task_source_conflict
task_worker_interrupted task_execution_failed task_owner_unavailable
file_batch_not_found file_batch_item_not_found file_batch_idempotency_conflict file_batch_item_conflict
file_batch_item_rejected file_upload_mismatch file_parse_pending
dataset_missing dataset_changed structure_version_conflict structure_task_pending preparation_invalid
parse_timeout parse_resource_limit parse_process_failed parse_environment_unavailable parse_output_invalid
model_usage_input_invalid model_budget_missing model_budget_exceeded model_budget_revision_conflict
model_call_idempotency_conflict model_usage_event_conflict model_call_transition_invalid model_call_not_found
model_policy_not_configured model_policy_invalid model_submission_unknown model_response_not_found model_observation_expired
numeric_type recommendation_not_configured recommendation_invalid correlation_invalid_input correlation_sample_size correlation_input_limit correlation_constant correlation_near_constant
group_type unit_conflict pair_id_missing pair_id_duplicate pair_id_type groups_missing group_not_selected
comparison_invalid_input comparison_sample_size comparison_input_limit comparison_constant comparison_near_constant
numeric_input_limit numeric_invalid_input numeric_sample_size numeric_rank numeric_constant numeric_perfect_fit
numeric_descriptive_limit numeric_row_limit numeric_effect_limit numeric_input_bytes_limit
numeric_output_limit numeric_output_missing numeric_output_invalid numeric_timeout_invalid
numeric_separation_check numeric_separation numeric_convergence numeric_unstable numeric_overflow numeric_failure
numeric_timeout numeric_environment_unavailable numeric_resource_limit numeric_encoding numeric_id_missing numeric_id_duplicate numeric_roles_missing
model_provider_unavailable model_authentication_failed model_permission_denied model_request_rejected model_response_invalid

collection_dependencies_missing collection_duplicate_figure collection_explanation_conflict collection_idempotency_conflict collection_input_invalid collection_legacy_numbering collection_not_found collection_plan_required collection_revision_conflict collection_source_conflict figure_missing projection_limit violin_unsupported_group
'''.split())

INTERNAL_MESSAGE = '服务暂时无法完成请求，请稍后重试。'

LAYOUT_EXPRESSION_PATHS = frozenset(f'formulas.{i}.expression' for i in range(40))
LAYOUT_TARGET_PATHS = frozenset(
    [f'formulas.{i}.anchor_id' for i in range(40)]
    + [f'references.{i}.{field}' for i in range(60) for field in ('anchor_id', 'target_id', 'kind')]
    + [f'headings.{i}.anchor_id' for i in range(100)]
    + [f'landscape_anchor_ids.{i}' for i in range(16)]
    + ['pagination.body_anchor_id', 'toc.depth']
)


def safe_params(code, params=None):
    """Each parameter has a code-specific type and bound; no catch-all strings."""
    if not isinstance(params, dict):
        return {}
    result = {}
    if code in ('layout_formula_invalid', 'layout_formula_too_wide', 'layout_target_invalid'):
        formula_error = code != 'layout_target_invalid'
        path = params.get('path')
        allowed_paths = LAYOUT_EXPRESSION_PATHS if formula_error else LAYOUT_TARGET_PATHS
        if isinstance(path, str) and len(path) <= 64 and path in allowed_paths:
            result['path'] = path
        formula_id = params.get('formula_id')
        if formula_error and isinstance(formula_id, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', formula_id):
            result['formula_id'] = formula_id
        position = params.get('position')
        if code == 'layout_formula_invalid' and type(position) is int and 0 <= position <= 2000:
            result['position'] = position
        # Raw reasons, source anchor strings and exception text are not public
        # location parameters. The UI uses the code plus these bounded fields.
        return result
    if code == 'figure_projection_invalid':
        reason = params.get('reason')
        allowed = {'missing_fields','missing_group','invalid_group','duplicate_x','invalid_numeric',
            'invalid_category','invalid_datetime','invalid_x_type','ordered_x_required','projection_empty',
            'projection_limit','violin_unsupported_group','violin_numeric_range','invalid_rule','invalid_row',
            'unsupported_projection'}
        return {'reason':reason} if isinstance(reason,str) and reason in allowed else {}
    numeric = {
        'file_too_large': {'max_bytes': (1, 2**63 - 1)},
        'numeric_precision': {'row': (1, 1_048_576)},
        'plot_label_too_long': {'max_chars': (1, 10000)},
        'openai_request_failed': {'provider_status': (400, 599)},
    }
    for name, (minimum, maximum) in numeric.get(code, {}).items():
        value = params.get(name)
        if type(value) is int and minimum <= value <= maximum:
            result[name] = value
    if code == 'numeric_precision':
        column = params.get('column')
        if isinstance(column, str) and re.fullmatch(r'[A-Z]{1,3}', column):
            result['column'] = column
    return result


def error_detail(code, message, params=None):
    if not isinstance(code, str) or code not in PUBLIC_CODES:
        code, message, params = 'internal_error', INTERNAL_MESSAGE, None
    return {'code': code, 'message': message, 'params': safe_params(code, params)}


def error_response(status, code, message, params=None, headers=None):
    response_headers = {**(headers or {}), 'Cache-Control': 'no-store'}
    return JSONResponse(status_code=status, content={'detail': error_detail(code, message, params)},
                        headers=response_headers)


def unexpected_error_response(exc):
    # Consume API exceptions before the server can log a raw exception body.
    logging.getLogger(__name__).error('Request failed (%s)', type(exc).__name__)
    return error_response(500, 'internal_error', INTERNAL_MESSAGE)


def fallback_error(status):
    """Framework errors must not echo arbitrary HTTPException.detail values."""
    return {
        400: ('invalid_request', '请求格式无效，请检查填写的内容后重试。'),
        401: ('authentication_required', '请登录后继续。'),
        403: ('permission_denied', '无权执行此操作。'),
        404: ('not_found', '请求的资源不存在。'),
        405: ('method_not_allowed', '该操作不受支持，请刷新页面后重试。'),
        422: ('invalid_request', '请求格式无效，请检查填写的内容后重试。'),
    }.get(status, ('internal_error', INTERNAL_MESSAGE) if status >= 500 else ('request_failed', '请求失败，请稍后重试。'))


def job_message(code, params=None):
    """Fields written together with a task message, without changing its lifecycle."""
    return {'message_code': code, 'message_params': safe_params(code, params)}
