import pytest
from app.domain.tasks.errors import safe_error_code,error_category


@pytest.mark.parametrize('code,category',[
    ('bio_environment_unavailable','configuration'),('bio_parse_timeout','temporary'),
    ('bio_parse_resource_limit','temporary'),('bio_source_changed','source'),('bio_output_invalid','output')])
def test_bio_errors_retain_public_code_separate_from_category(code,category):
    assert safe_error_code(code)==code
    assert error_category(code)==category


def test_unknown_error_is_closed():
    assert safe_error_code({'unsafe':'value'})=='internal_error'
    assert error_category('bio_undeclared')=='internal'
