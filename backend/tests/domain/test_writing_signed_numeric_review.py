"""New approvals preserve signed science; no provider, rendering, or database."""
from copy import deepcopy
import json
import pytest
from app.domain.literature.service import digest
from app.domain.manuscript_writing.live_review_candidate import prepare,body_digest
from app.domain.manuscript_writing.language import prepare_candidate
from tests.domain.test_writing_live_review_candidate import sample


@pytest.fixture(autouse=True)
def postgres_schema():yield None


def science(display,bound,source,kind):
    raw,snap,bundle,body,_=sample();text='Observed value '+display+'.'
    decision=body['paragraphs'][2]
    decision.update(corrected_text=text,text_sha256=digest(text),classification=kind+'_claim',
        claim=None if kind=='study' else dict(claim_id='new',claim_revision=1,bindings=[]),
        numeric_bindings=[dict(occurrence=0,value=bound,kind=kind,
            source_alias='s1' if kind=='study' else None,fact_path='/statistics/coefficient' if kind=='study' else None,
            evidence_id='new-evidence' if kind=='literature' else None)])
    payload=json.loads(json.loads(bundle['wire_json'])['input'])
    payload['sources'][0]['facts']=[dict(fact_path='/statistics/coefficient',value=source)]
    wire=json.loads(bundle['wire_json']);wire['input']=json.dumps(payload);bundle['wire_json']=json.dumps(wire)
    corrected=deepcopy(raw);corrected['sections'][2]['paragraphs'][0]['text']=text
    body['consistency']['body_sha256']=body_digest(corrected)
    def resolve(decision,text):
        return dict(kind='claim',claim_id='new',claim_revision=1,text=text,bindings=[dict(evidence=[dict(id='new-evidence',quote='Observed value '+source+'.')])])
    return raw,snap,bundle,body,resolve


@pytest.mark.parametrize('kind',['study','literature'])
@pytest.mark.parametrize('display',['−12','－12','﹣12','- 12','− 12','±12','∓12'])
def test_new_science_rejects_negative_or_ambiguous_text_bound_as_positive(kind,display):
    with pytest.raises(ValueError):prepare(*science(display,'12','12',kind))


@pytest.mark.parametrize('kind',['study','literature'])
@pytest.mark.parametrize('display',['−12','－12','﹣12','- 12','− 12'])
def test_supported_negative_science_keeps_display_and_matches_negative_source(kind,display):
    candidate,_=prepare(*science(display,'-12','-12',kind))
    assert candidate['sections'][2]['paragraphs'][0]['text']=='Observed value '+display+'.'


@pytest.mark.parametrize('kind',['study','literature'])
@pytest.mark.parametrize('display',['＋12','﹢12','+ 12'])
def test_supported_positive_signs_match_positive_source(kind,display):
    prepare(*science(display,'12','12',kind))


@pytest.mark.parametrize('quote',['−12','－12','﹣12','- 12','±12','∓12'])
def test_literature_source_sign_cannot_be_ignored(quote):
    with pytest.raises(ValueError):prepare(*science('12','12',quote,'literature'))


def language_case(place,old,new):
    candidate=dict(results_groups=[dict(title='Results',tables=[dict(title='Table',columns=['Value'],rows=[[old]])],
        figures=[dict(title='Figure',caption=old,panels=[dict(label='A',description=old)])])])
    path={'caption':'/results_groups/0/figures/0/caption','cell':'/results_groups/0/tables/0/rows/0/0',
          'panel':'/results_groups/0/figures/0/panels/0/description'}[place]
    return candidate,dict(edits=[dict(path=path,original_sha256=digest(old),text=new,reason='Manual translation')])


@pytest.mark.parametrize('place',['caption','cell','panel'])
@pytest.mark.parametrize('old,new',[('−5 mg','5 mg'),('－5 mg','5 mg'),('﹣5 mg','5 mg'),('- 5 mg','5 mg'),('− 5 mg','+5 mg'),('＋5 mg','−5 mg'),('﹢5 mg','−5 mg'),('±5 mg','5 mg'),('∓5 mg','5 mg')])
def test_language_edits_cannot_delete_reverse_or_flatten_signs(place,old,new):
    with pytest.raises(ValueError):prepare_candidate(*language_case(place,old,new))


@pytest.mark.parametrize('place',['caption','cell','panel'])
def test_language_edits_allow_equivalent_negative_translation_without_changing_original(place):
    candidate,body=language_case(place,'测量 − 5 mg','Measured -5 mg');original=deepcopy(candidate)
    result=prepare_candidate(candidate,body)
    assert result!=candidate and candidate==original


def test_checker_projection_preserves_reference_marker_boundaries():
    from app.domain.manuscript_writing.numeric_review import checker_text
    assert checker_text('See Figure 1; value − 12.')=='See Figure 1; value -12.'


@pytest.mark.parametrize('old,new',[('Q3−Q1','Q3Q1'),('A + 5','A 5'),('±5 mg','±5 milligrams'),('∓5 mg','∓5 milligrams')])
def test_language_protects_standalone_operators_and_rejects_ambiguous_edits(old,new):
    with pytest.raises(ValueError):prepare_candidate(*language_case('caption',old,new))


@pytest.mark.parametrize('kind',['study','literature'])
def test_scientific_exponent_sign_whitespace_is_one_numeric_occurrence(kind):
    prepare(*science('1e − 5','1e-5','1e-5',kind))


@pytest.mark.parametrize('kind',['study','literature'])
def test_compound_signs_are_rejected_instead_of_dropping_an_operator(kind):
    with pytest.raises(ValueError):prepare(*science('− −12','-12','-12',kind))


@pytest.mark.parametrize('kind',['study','literature'])
@pytest.mark.parametrize('display',['−(12)','- (12)','+(12)','＋ （12）','﹢[12]','－ ［12］',
    '﹣{12}','− ｛12｝','-【12】','+ 〔12〕','−〈12〉','＋ 《12》','- ((12))','−\n( 12 )'])
def test_science_rejects_signed_parentheses_instead_of_extracting_positive_magnitude(kind,display):
    with pytest.raises(ValueError,match='parenthesized'):
        prepare(*science(display,'12','12',kind))


@pytest.mark.parametrize('quote',['−(12)','- (12)','＋ （12）','﹣【12】'])
def test_literature_signed_parentheses_evidence_is_not_a_positive_value(quote):
    raw,snap,bundle,body,resolve=science('12','12','12','literature')
    def resolve_signed_evidence(decision,text):
        fragment=resolve(decision,text)
        fragment['bindings'][0]['evidence'][0]['quote']='Observed value '+quote+'.'
        return fragment
    with pytest.raises(ValueError,match='parenthesized'):
        prepare(raw,snap,bundle,body,resolve_signed_evidence)


@pytest.mark.parametrize('kind',['study','literature'])
@pytest.mark.parametrize('display,bound',[('(12)','12'),('（12）','12'),('[12]','12'),('(−12)','-12')])
def test_unsigned_parentheses_and_direct_inner_negative_remain_supported(kind,display,bound):
    candidate,_=prepare(*science(display,bound,bound,kind))
    assert candidate['sections'][2]['paragraphs'][0]['text']=='Observed value '+display+'.'


@pytest.mark.parametrize('kind',['study','literature'])
def test_signed_parentheses_legacy_version_one_reconstruction_is_unchanged(kind):
    candidate,_=prepare(*science('−(12)','12','12',kind),numeric_version=1)
    assert candidate['sections'][2]['paragraphs'][0]['text']=='Observed value −(12).'
