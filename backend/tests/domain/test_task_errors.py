import pytest


@pytest.mark.parametrize('code,status,expected', [
    ('model_provider_request_failed', None, 'model_provider_unavailable'),
    *[('model_provider_request_failed', value, 'model_provider_unavailable') for value in (429, 500, 502, 503, 504)],
    ('model_provider_request_failed', 401, 'model_authentication_failed'),
    ('model_provider_request_failed', 403, 'model_permission_denied'),
    ('model_provider_request_failed', 400, 'model_request_rejected'),
    ('model_response_not_found', 404, 'model_response_not_found'),
    ('secret raw text', 500, 'internal_error'),
])
def test_read_error_classification(code, status, expected):
    from app.domain.tasks.errors import classify_read_error
    assert classify_read_error(code, status) == expected


def test_unknown_codes_are_safe_and_categories_are_fixed():
    from app.domain.tasks.errors import safe_error_code, error_category
    assert safe_error_code('secret') == 'internal_error'
    assert safe_error_code(None) is None
    assert error_category('model_provider_unavailable') == 'temporary'
    assert error_category('plot_container_expired') == 'source'
    assert error_category('plot_invalid_result') == 'output'
