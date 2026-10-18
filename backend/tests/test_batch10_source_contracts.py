from copy import deepcopy
import pytest
from app.domain.analysis_recommendation.contracts import parse_request,validate_draft
from tests.test_batch09_research_contracts import draft

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

def v5_request():
    return dict(schema_version=5,dataset_id='d',sheet_name='Sheet1',candidate_columns=['A'],output_language='en',research_summary='Use F1/S1/D1 age.')

def v5_draft():
    value=draft();value['schema_version']=5
    value['intent']['evidence']=[dict(start=0,end=17,quote='Use F1/S1/D1 age.')]
    value['source_reference']=dict(status='matched',references=[dict(code='F1',level='file'),dict(code='S1',level='sheet'),dict(code='D1',level='dataset')],evidence=[dict(start=4,end=12,quote='F1/S1/D1')])
    return value

def test_v5_source_reference_is_bounded_to_actual_summary():
    assert parse_request(v5_request()).schema_version==5
    assert validate_draft(v5_draft(),v5_request())['source_reference']['status']=='matched'

@pytest.mark.parametrize('change',['alias','quote','level','missing_evidence'])
def test_v5_rejects_forged_source_references(change):
    value=v5_draft();ref=value['source_reference']
    if change=='alias':ref['references'][0]['code']='F2'
    if change=='quote':ref['evidence'][0]['quote']='F2/S2/D2'
    if change=='level':ref['references'][0]['level']='dataset'
    if change=='missing_evidence':ref['evidence']=[]
    with pytest.raises(ValueError):validate_draft(value,v5_request())

def test_v5_manual_source_confirmation_is_separate_gate():
    from app.domain.analysis_plan.requirements import requirement_check,validate_requirement_resolutions
    from app.core.exceptions import StorageError
    research=dict(question='Age',output_language='en',population='Adults',study_design='cross-sectional',observation_unit='patient',observation_structure='independent',relationship_description='one row per person',output_requirements='')
    check=requirement_check({'file_id':'f'},None,research,schema_version=5)
    assert 'source_confirmation' in check['research_missing']
    with pytest.raises(StorageError):validate_requirement_resolutions(check,{})



def test_v5_policy_uses_existing_node_and_strict_output_contract():
    from tests.integration.test_analysis_recommendation import planning_policy
    from app.domain.analysis_recommendation.policy import validate_execution_policy
    value=planning_policy();value['policy'].update(prompt_version='analysis_recommendation_v5',output_format='analysis_recommendation_v5')
    assert validate_execution_policy(value)['policy']['model']=='gpt-5.6-sol'

def test_source_alias_cannot_match_prefix_of_another_material():
    from app.domain.analysis_recommendation.contracts import validate_source_reference
    value=dict(status='matched',references=[dict(code='F1',level='file')],evidence=[dict(start=4,end=7,quote='F10')])
    with pytest.raises(ValueError):validate_source_reference(value,'Use F10')
