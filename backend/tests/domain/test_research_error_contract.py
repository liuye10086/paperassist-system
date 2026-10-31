import pytest
from app.core.errors import error_detail

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

@pytest.mark.parametrize('code',['research_source_conflict','research_source_not_found','research_source_incomplete',
    'research_source_unsupported','research_locator_invalid','research_source_limit_exceeded','research_fact_unresolved',
    'research_delivery_unavailable','research_figure_limit_exceeded','research_export_limit_exceeded','research_output_invalid'])
def test_research_errors_keep_actionable_code_without_untrusted_parameters(code):
    detail=error_detail(code,'请核对来源',{'private_path':'C:/secret'})
    assert detail=={'code':code,'message':'请核对来源','params':{}}
