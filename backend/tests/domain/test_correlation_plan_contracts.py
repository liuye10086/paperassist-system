"""v3 selections, local checks, and immutable generation routing."""
import copy
import pytest
from pydantic import ValidationError
from app.domain.analysis_plan.contracts import AnalysisPlanCreateRequest

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

def selection(**changes):
    return dict(task_type='correlation',sheet_name='Sheet1',method='pearson',mode='pair',columns=['A','B'],
        units={'A':'cm','B':'kg'},missing_policy='complete_cases',assumptions=dict(independent_observations=True,
        relationship_form='linear',inference_assumptions_confirmed=True),**changes)

def research():
    return dict(question='关联程度',output_language='en',population='合成样本',study_design='横断面',
        observation_unit='每行一个受试者',observation_structure='independent',relationship_description='',output_requirements='')

def request():
    return dict(schema_version=3,dataset_id='data',expected_setup_revision=0,selection=selection(),
        research_request=research(),recommendation_ref=None)

def test_v3_selection_is_accepted_without_changing_selected_units():
    body=request()
    assert AnalysisPlanCreateRequest.model_validate(body).model_dump(mode='json') == body

@pytest.mark.parametrize('changes',[
    {'columns':['A','A']},{'columns':['A','B','C']},{'units':{'A':'cm'}},{'method':'kendall'},
    {'missing_policy':'pairwise'},{'assumptions':{'independent_observations':'true','relationship_form':'linear','inference_assumptions_confirmed':True}},
])
def test_invalid_correlation_selections_cannot_enter_plan(changes):
    body=request();body['selection'].update(changes)
    with pytest.raises(ValidationError): AnalysisPlanCreateRequest.model_validate(body)

def test_legacy_plan_cannot_acquire_correlation_selection_implicitly():
    body=request();body.pop('schema_version');body.pop('recommendation_ref')
    with pytest.raises(ValidationError): AnalysisPlanCreateRequest.model_validate(body)

def test_v3_needs_explicit_research_and_version_is_strict():
    for change in ({'research_request':None},{'schema_version':True},{'schema_version':2}):
        body={**request(),**change}
        with pytest.raises(ValidationError): AnalysisPlanCreateRequest.model_validate(body)
