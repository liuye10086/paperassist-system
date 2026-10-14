"""All parser failures stay public and carry an actionable category."""
import pytest
from app.core.errors import PUBLIC_CODES
from app.domain.tasks.errors import error_category


@pytest.fixture(autouse=True)
def postgres_schema():
    yield


@pytest.mark.parametrize('code,category',[('invalid_document','source'),('encrypted_document','source'),
    ('document_too_large','source'),('file_too_large','source'),('empty_file','source'),
    ('parse_environment_unavailable','configuration'),('parse_timeout','temporary'),
    ('parse_resource_limit','temporary'),('parse_process_failed','temporary'),('parse_output_invalid','output')])
def test_ocr_errors_remain_public_and_categorized(code,category):
    assert code in PUBLIC_CODES
    assert error_category(code)==category
