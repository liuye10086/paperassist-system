"""Known parsed identity sources stay local; general format notes remain data."""
from copy import deepcopy
import pytest

@pytest.fixture(autouse=True)
def postgres_schema():yield None

@pytest.mark.parametrize('mixed',[False,True])
def test_known_signature_source_note_cannot_be_selected_for_external_advice(mixed):
    from tests.adapters.test_school_front_matter import synthetic
    from app.domain.school_templates.suggestion_validation import material
    analysis=synthetic()
    note=next(n for n in analysis['notes'] if n['text']=='作者签名：示例签名')
    if mixed:note['text']+='。正文：小四号字。'
    before=deepcopy(analysis)
    with pytest.raises(ValueError,match='identity'):
        material(analysis,[note['id']])
    assert analysis==before

def test_general_signature_requirement_at_another_source_remains_eligible():
    from tests.adapters.test_school_front_matter import synthetic
    from app.domain.school_templates.suggestion_validation import material
    analysis=synthetic();note=dict(id='supplement',text='签名须人工填写。',source=dict(part='word/document.xml',path='/w:document/w:body/w:p[30]',text='签名须人工填写。'))
    analysis['notes'].append(note);before=deepcopy(analysis)
    assert material(analysis,['supplement'])['notes']==[dict(alias='n1',text=note['text'])]
    assert analysis==before
