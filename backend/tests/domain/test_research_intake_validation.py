from app.domain.research_intake.contracts import RequirementContent
from app.domain.research_intake.validation import requirement_gaps


def test_unspecified_material_classes_remain_explicit_pending_gaps():
    content=RequirementContent.model_validate({'schema_version':1,'services':['analysis'],
        'analysis_request':{'core_question':{'state':'known','value':'question'}},
        'schedule':{'priority':{'state':'known','value':'structure first'}}}).model_dump(mode='json')
    gaps=requirement_gaps(content)
    missing=[gap for gap in gaps if gap['path'].startswith('material_checklist.')]
    assert len(missing)==6
    assert all(gap['blocking'] for gap in missing)
