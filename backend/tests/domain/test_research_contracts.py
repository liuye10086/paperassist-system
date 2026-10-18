"""Exact declarations and legacy request material remain independent."""
import pytest
from pydantic import ValidationError
from app.domain.analysis_plan.contracts import AnalysisPlanCreateRequest
from app.domain.analysis_plan.research import ResearchRequest, missing_research


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def request(**changes):
    value=dict(question='  原始问题\n',output_language='en',population='样本',study_design='观察',
        observation_unit='每行一个',observation_structure='independent',relationship_description='',output_requirements='')
    return {**value,**changes}


def test_research_text_preserves_original_and_does_not_infer_structure():
    value=request(question='  配对实验原文\n',observation_structure='unknown',population='  ',study_design='')
    parsed=ResearchRequest.model_validate(value)
    assert parsed.model_dump()==value
    assert missing_research(value)==['population','study_design','observation_structure']


@pytest.mark.parametrize('changes',[
    {'question':'   '},{'question':'x'*4001},{'question':3},{'output_language':'fr'},
    {'population':'x'*2001},{'observation_structure':'randomized'},{'unknown_field':True},
])
def test_invalid_research_declarations_are_rejected(changes):
    with pytest.raises(ValidationError): ResearchRequest.model_validate(request(**changes))


def test_create_legacy_serialization_has_no_added_default_field():
    value=dict(dataset_id='data',expected_setup_revision=0,selection=dict(task_type='descriptive_boxplot',
        sheet_name='Sheet1',numeric_column='A',group_column=None,unit='',missing_policy='exclude_selected_missing'))
    assert AnalysisPlanCreateRequest.model_validate(value).model_dump(mode='json')==value
    with pytest.raises(ValidationError):
        AnalysisPlanCreateRequest.model_validate({**value,'research_request':None})
