import pytest
from app.domain.analysis_recommendation.contracts import parse_request, validate_draft


def request():
    return dict(schema_version=4,dataset_id='d',sheet_name='Sheet1',candidate_columns=['A'],
                output_language='en',research_summary='Describe age.')


def draft():
    from app.domain.analysis_recommendation.contracts import ModelingRoles
    roles={k:[] if k=='covariate_columns' else None for k in ModelingRoles.model_fields}
    return dict(schema_version=4,method='descriptive',mode=None,columns=['A'],roles=roles,
                output_language='en',rationale=['Describe age'],assumptions=['Confirm design'],missing_information=[],
                intent=dict(objective='Describe age',material_relationship='Selected table',field_roles=[dict(column='A',role='outcome')],
                    population_conditions=[],chart_preferences=['boxplot'],explanation_focus=['distribution'],output_language='en',
                    missing_information=[],conflicts=[],evidence=[dict(start=0,end=12,quote='Describe age')]))


def test_v4_same_response_contains_bounded_intent_and_method():
    assert parse_request(request()).schema_version==4
    assert validate_draft(draft(),request())['intent']['objective']=='Describe age'


@pytest.mark.parametrize('mutation',['quote','column','chart','language','incompatible_chart','expression'])
def test_v4_rejects_forged_or_unapproved_intent(mutation):
    value=draft()
    if mutation=='quote':value['intent']['evidence'][0]['quote']='Invented'
    if mutation=='column':value['intent']['field_roles'][0]['column']='B'
    if mutation=='chart':value['intent']['chart_preferences']=['cox']
    if mutation=='language':value['intent']['output_language']='zh-CN'
    if mutation=='incompatible_chart':value['intent']['chart_preferences']=['forest']
    if mutation=='expression':value['intent']['population_conditions']=['__import__("os").system("whoami")']
    with pytest.raises(ValueError):validate_draft(value,request())


def test_v4_materials_cannot_claim_data_and_missing_selection_waits():
    from app.domain.analysis_plan.requirements import RequirementCreateRequest, requirement_check
    research=dict(question='Recompute externally supplied graph',output_language='en',population='',study_design='',
        observation_unit='',observation_structure='unknown',relationship_description='',output_requirements='')
    value=dict(schema_version=4,input_kind='materials',file_id=None,dataset_id=None,expected_setup_revision=0,selection=None,
        research_request=research,evidence_version_ids=['e'])
    parsed=RequirementCreateRequest.model_validate(value)
    check=requirement_check(None,None,parsed.research_request)
    assert set(check['research_missing'])>={'source','selection','study_design'}
    with pytest.raises(ValueError):RequirementCreateRequest.model_validate({**value,'dataset_id':'invented'})


def test_origin_requires_exact_controlled_parent_not_merely_same_root(monkeypatch):
    from types import SimpleNamespace
    from app.domain.analysis_plan.requirements_service import validate_origin_reference
    from app.core.exceptions import StorageError
    original=dict(kind='prepared_dataset_version',dataset_id='original',file_id='f')
    filtered=dict(kind='prepared_dataset_version',dataset_id='filtered',file_id='f')
    view=dict(source=original,task=dict(project_id='p'),recommendation=dict(sha256='a'*64))
    monkeypatch.setattr('app.domain.analysis_recommendation.service.RecommendationService.get',lambda self,id:view)
    monkeypatch.setattr('app.domain.dataset_preparation.service.DatasetPreparationService.load_version',lambda *args:(None,None,dict(base_source=original)))
    assets=SimpleNamespace(owner_id='u',db_config=None,directory=None)
    service=SimpleNamespace(assets=assets)
    # Service constructors need no connection for the stubbed immutable reads.
    monkeypatch.setattr('app.domain.analysis_recommendation.service.RecommendationService.__init__',lambda self,assets:None)
    monkeypatch.setattr('app.domain.dataset_preparation.service.DatasetPreparationService.__init__',lambda self,assets:None)
    reference=dict(task_id='r',sha256='a'*64)
    validate_origin_reference(service,'p',filtered,reference)
    for source in (original,{**filtered,'file_id':'different'}):
        with pytest.raises(StorageError):validate_origin_reference(service,'p',source,reference)
    monkeypatch.setattr('app.domain.dataset_preparation.service.DatasetPreparationService.load_version',lambda *args:(None,None,dict(base_source=filtered)))
    with pytest.raises(StorageError):validate_origin_reference(service,'p',filtered,reference)
