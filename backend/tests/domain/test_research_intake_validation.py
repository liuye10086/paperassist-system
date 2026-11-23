from app.domain.research_intake.contracts import RequirementContent
from app.domain.research_intake.validation import requirement_gaps


def test_study_species_round_trip_and_legacy_requirement_shape():
    legacy = RequirementContent(schema_version=1)
    assert 'study_species' not in legacy.model_dump(mode='json')
    content = RequirementContent(schema_version=1, study_species=['人类', '小鼠', '家兔'])
    assert RequirementContent.model_validate(content.model_dump()).study_species == ['人类', '小鼠', '家兔']


def test_unspecified_material_classes_remain_explicit_pending_gaps():
    content=RequirementContent.model_validate({'schema_version':1,'services':['analysis'],
        'analysis_request':{'core_question':{'state':'known','value':'question'}},
        'schedule':{'priority':{'state':'known','value':'structure first'}}}).model_dump(mode='json')
    gaps=requirement_gaps(content)
    missing=[gap for gap in gaps if gap['path'].startswith('material_checklist.')]
    assert len(missing)==6
    assert all(gap['blocking'] for gap in missing)
