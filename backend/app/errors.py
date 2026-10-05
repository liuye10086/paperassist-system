"""Shared public errors; parameters never contain arbitrary input or exceptions."""
import logging
import re

from starlette.responses import JSONResponse


PUBLIC_CODES = frozenset('''
authentication_configuration authentication_required csrf_invalid database_configuration
empty_file explanation_incomplete explanation_invalid explanation_invalid_json
explanation_output_limit explanation_refused figure_changed figure_conflict figure_missing
figure_not_found file_changed file_missing file_not_found file_not_parsed file_too_large
invalid_analysis_selection invalid_column invalid_credentials invalid_current_password
invalid_recovery_code invalid_request invalid_workbook login_rate_limited missing_file
no_valid_records numeric_precision openai_connection openai_incomplete openai_not_configured
openai_not_found openai_request_failed parse_failed password_rate_limited plot_files_missing
plot_invalid_image plot_invalid_result plot_label_too_long plot_no_execution plot_output_limit
plot_result_mismatch project_language_invalid project_not_found project_query_invalid
project_summary_query_invalid project_type_immutable project_update_invalid report_changed
report_missing report_not_found report_render_failed report_source_changed report_source_conflict
result_mismatch result_not_found setup_conflict sheet_not_found source_conflict storage_unavailable
storage_version unsupported_file_type workbook_too_large internal_error not_found method_not_allowed
request_failed permission_denied ai_configured task_submitting task_running task_completed task_uncertain task_failed task_unknown
'''.split())

INTERNAL_MESSAGE = '服务暂时无法完成请求，请稍后重试。'


def safe_params(code, params=None):
    """Each parameter has a code-specific type and bound; no catch-all strings."""
    if not isinstance(params, dict):
        return {}
    result = {}
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
