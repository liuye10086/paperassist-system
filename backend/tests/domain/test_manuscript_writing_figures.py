from copy import deepcopy
import pytest
from tests.domain.test_manuscript_writing import frozen,output,postgres_schema

def fixture():
    snapshot=frozen()
    snapshot['base_snapshot']['results_groups']=[dict(id='main',paragraphs=[],tables=[],figures=[dict(id='image',number=1,panels=[dict(label='A',description='Material')])])]
    return snapshot

@pytest.mark.parametrize('text',['See Figure 12 for the frozen image.','见图12。','See Figure 1B.'])
def test_generated_body_cannot_introduce_unmatched_figure_even_with_numeric_fact(text):
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=fixture();result=output(snapshot)
    result['sections'][3]['paragraphs'][0].update(text=text,source_ids=['stats'],numeric_bindings=[dict(value='12',source_id='stats')])
    with pytest.raises(ValueError):compose_candidate(result,snapshot)

def test_real_figure_and_panel_ordinals_are_not_statistical_values():
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=fixture();result=output(snapshot)
    result['sections'][3]['paragraphs'][0].update(text='See Figure 1A for the saved image; n = 12.',source_ids=['stats'],numeric_bindings=[dict(value='12',source_id='stats')])
    candidate=compose_candidate(result,snapshot)
    assert candidate['sections'][3]['paragraphs'][0]['text'].startswith('See Figure 1A')

def test_existing_unresolved_reference_is_retained_without_new_false_support():
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=fixture()
    paragraph=dict(id='methods:provided',text='See Figure 99C.',origin='user_provided',source_ids=[],citations=[])
    snapshot['base_snapshot']['methods']=[paragraph]
    snapshot['base_snapshot']['issues'].append(dict(id='body-reference:methods:provided:0',kind='conflict',field='methods:provided',values=['Figure 99C'],message='Verify figure'))
    result=output(snapshot);result['sections'][5]['paragraphs']=[deepcopy(paragraph)]
    assert compose_candidate(result,snapshot)['issues']==snapshot['base_snapshot']['issues']
