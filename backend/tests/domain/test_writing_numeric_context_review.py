"""Explicit provided-context decisions, never approval from model suggestions."""
from copy import deepcopy
import pytest
from app.domain.literature.service import digest
from app.domain.manuscript_writing.live_review_candidate import prepare, body_digest
from app.domain.manuscript_writing.live_review_contracts import ScientificReviewRequest
from app.domain.manuscript_review.writing_context import WritingCheckContext, load_writing_context
from app.domain.manuscript_review.checks import check_snapshot
from tests.domain.test_writing_live_review_candidate import sample


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def context_case(display='1.5', value='1.5'):
    raw, snap, bundle, body, resolve = sample()
    bundle['execution_contract'] = dict(schema_version=2)
    bundle['local_manifest']['numeric_context'] = dict(c1=dict(kind='provided_context',
        location='materials_and_methods[0]', origin='user_provided',
        text='The frozen multiplier is '+value+'.',
        values=[dict(fact_path='/numbers/0', value=value)]))
    text='Our n=12 and the provided multiplier is '+display+'.'
    raw['sections'][2]['paragraphs'][0]['text']=text
    raw['writing_provenance']['numeric_contract_version']=2
    decision=body['paragraphs'][2]
    decision.update(corrected_text=text, text_sha256=digest(text), classification='context_claim', claim=None,
        numeric_bindings=[dict(occurrence=0,value='12',kind='study',source_alias='s1',fact_path='/statistics/n',evidence_id=None),
            dict(occurrence=1,value=value,kind='context',source_alias='c1',fact_path='/numbers/0',evidence_id=None)])
    body['candidate_sha256']=digest(raw)
    body['consistency']['body_sha256']=body_digest(raw)
    return raw,snap,bundle,body,resolve


def test_explicit_context_claim_accepts_independent_study_and_provided_context_numbers():
    args=context_case();before=deepcopy(args[0])
    body=ScientificReviewRequest.model_validate(args[3]).model_dump(mode='json')
    candidate,_=prepare(*args[:3],body,args[4])
    paragraph=candidate['sections'][2]['paragraphs'][0]
    assert paragraph['numeric_bindings']==body['paragraphs'][2]['numeric_bindings']
    assert paragraph['source_ids']==[args[2]['local_manifest']['sources']['s1']]
    assert paragraph['citations']==[]
    assert paragraph['science_review']['classification']=='context_claim'
    assert args[0]==before and args[0]['sections'][2]['paragraphs'][0]['verification_status']=='pending'


@pytest.mark.parametrize('mutation',['missing','duplicate','order','alias','path','value','evidence','study_class','non_claim','unknown_kind'])
def test_context_decisions_reject_unresolved_or_misattributed_occurrences(mutation):
    raw,snap,bundle,body,resolve=context_case();decision=body['paragraphs'][2];bindings=decision['numeric_bindings']
    if mutation=='missing':bindings.pop()
    if mutation=='duplicate':bindings[1]['occurrence']=0
    if mutation=='order':bindings[0]['occurrence']=1;bindings[1]['occurrence']=0
    if mutation=='alias':bindings[1]['source_alias']='s1'
    if mutation=='path':bindings[1]['fact_path']='/numbers/1'
    if mutation=='value':bindings[1]['value']='12'
    if mutation=='evidence':bindings[1]['evidence_id']='new-evidence'
    if mutation=='study_class':decision['classification']='study_claim'
    if mutation=='non_claim':decision['classification']='non_claim'
    if mutation=='unknown_kind':bindings[1]['kind']='unchecked'
    with pytest.raises(ValueError):prepare(raw,snap,bundle,body,resolve)


@pytest.mark.parametrize('contract',[None,dict(schema_version=1)])
@pytest.mark.parametrize('new_field',['kind','classification'])
def test_legacy_contract_cannot_opt_into_context_decisions(contract,new_field):
    raw,snap,bundle,body,resolve=context_case()
    if contract is None:bundle.pop('execution_contract')
    else:bundle['execution_contract']=contract
    if new_field=='kind':body['paragraphs'][2]['classification']='mixed_claim'
    else:body['paragraphs'][2]['numeric_bindings'][1]['kind']='study'
    with pytest.raises(ValueError):prepare(raw,snap,bundle,body,resolve)


@pytest.mark.parametrize('display,value',[('− 1.5','-1.5'),('1e − 5','1e-5')])
def test_context_numbers_use_existing_signed_numeric_policy(display,value):
    prepare(*context_case(display,value))


@pytest.mark.parametrize('display',['−1.5','±1.5','−(1.5)'])
def test_context_kind_cannot_bypass_wrong_or_ambiguous_sign(display):
    with pytest.raises(ValueError):prepare(*context_case(display,'1.5'))


def test_mixed_claim_still_requires_new_literature_evidence_for_its_literature_number():
    raw,snap,bundle,body,resolve=context_case()
    _,_,_,original,_=sample();decision=body['paragraphs'][2]
    text='Our n=12, the provided multiplier is 1.5, and the reviewed publication reports 42.'
    raw['sections'][2]['paragraphs'][0]['text']=text
    decision.update(classification='mixed_claim',claim=original['paragraphs'][2]['claim'],corrected_text=text,text_sha256=digest(text))
    decision['numeric_bindings'].append(dict(occurrence=2,value='42',kind='literature',evidence_id='new-evidence',source_alias=None,fact_path=None))
    body['candidate_sha256']=digest(raw);body['consistency']['body_sha256']=body_digest(raw)
    candidate,_=prepare(raw,snap,bundle,body,resolve)
    assert [b['kind'] for b in candidate['sections'][2]['paragraphs'][0]['numeric_bindings']]==['study','context','literature']
    decision['numeric_bindings'][-1]['evidence_id']='e1'
    with pytest.raises(ValueError):prepare(raw,snap,bundle,body,resolve)


@pytest.mark.parametrize('reference',['Figure 1A','Figure 2','Figure 1B','Table 1'])
def test_figure_identity_is_checked_separately_from_study_and_context_occurrences(reference):
    raw,snap,bundle,body,resolve=context_case()
    group=dict(id='results',paragraphs=[],tables=[],figures=[dict(id='figure',number=1,source_ids=[],
        panels=[dict(label='A',description='Frozen panel')])])
    snap['base_snapshot']['results_groups']=[group]
    text='See '+reference+'; our n=12 and the provided multiplier is 1.5.'
    raw['sections'][2]['paragraphs'][0]['text']=text
    body['paragraphs'][2].update(corrected_text=text,text_sha256=digest(text))
    body['candidate_sha256']=digest(raw);body['consistency']['body_sha256']=body_digest(raw)
    if reference=='Figure 1A':
        candidate,_=prepare(raw,snap,bundle,body,resolve)
        assert len(candidate['sections'][2]['paragraphs'][0]['numeric_bindings'])==2
    else:
        with pytest.raises(ValueError,match='figure or table'):prepare(raw,snap,bundle,body,resolve)


def check_context():
    raw,snap,bundle,body,resolve=context_case()
    paragraph=deepcopy(raw['sections'][2]['paragraphs'][0])
    paragraph['numeric_bindings']=deepcopy(body['paragraphs'][2]['numeric_bindings'])
    sources={s['id']:deepcopy(s) for s in raw['sources']}
    paragraph['source_ids']=[bundle['local_manifest']['sources']['s1']]
    saved=dict(paragraph=deepcopy(paragraph),text=paragraph['text'],aliases=bundle['local_manifest']['sources'],
        numeric_context=deepcopy(bundle['local_manifest']['numeric_context']),numeric_contract_version=2,numeric_version=2)
    context=WritingCheckContext(paragraphs={paragraph['id']:saved},sources=sources,tables={})
    return raw,paragraph,context,sources


def test_checker_keeps_context_kind_separate_from_statistical_facts_and_literature():
    raw,paragraph,context,sources=check_context()
    _,bindings,reviewed_nonstudy=context.paragraph(paragraph,sources)
    assert bindings[0]==dict(fact_id='analysis_run:'+paragraph['source_ids'][0]+':/statistics/n',value='12')
    assert reviewed_nonstudy==[paragraph['numeric_bindings'][1]]
    assert reviewed_nonstudy[0]['kind']=='context' and 'evidence_id' not in {k:v for k,v in reviewed_nonstudy[0].items() if v is not None}
    raw['sections'][2]['paragraphs'][0]=paragraph
    assert not [i for i in check_snapshot(raw,writing_context=context) if i['category']=='numeric' and i['severity']=='error']


@pytest.mark.parametrize('mutation',['missing_catalog','wrong_path','wrong_value','legacy','unknown_kind'])
def test_checker_context_requires_its_original_frozen_catalog(mutation):
    _,paragraph,context,sources=check_context();saved=context.paragraphs[paragraph['id']]
    if mutation=='missing_catalog':saved.pop('numeric_context')
    if mutation=='wrong_path':saved['numeric_context']['c1']['values'][0]['fact_path']='/numbers/9'
    if mutation=='wrong_value':saved['numeric_context']['c1']['values'][0]['value']='12'
    if mutation=='legacy':saved.pop('numeric_contract_version')
    if mutation=='unknown_kind':paragraph['numeric_bindings'][1]['kind']='unchecked';saved['paragraph']=deepcopy(paragraph)
    with pytest.raises(ValueError):context.paragraph(paragraph,sources)


def test_legacy_science_request_dump_keeps_identical_fields_and_nulls():
    _,_,_,body,_=sample();before=deepcopy(body)
    assert ScientificReviewRequest.model_validate(body).model_dump(mode='json')==before
    assert set(body['paragraphs'][2]['numeric_bindings'][0])=={'occurrence','value','kind','source_alias','fact_path','evidence_id'}


def test_rewrite_loader_retains_each_paragraphs_original_context_alias_catalog(monkeypatch):
    raw,old_paragraph,_,_=check_context()
    _,snap,old_bundle,_,_=context_case()
    old=deepcopy(raw);old['sections'][2]['paragraphs'][0]=deepcopy(old_paragraph)
    old['writing_provenance'].update(request_id='old-request',review_id='old-science')
    new=deepcopy(old);new_paragraph=new['sections'][4]['paragraphs'][0]
    new_paragraph.update(text='The other provided multiplier is 2.5.',source_ids=[],citations=[],
        numeric_bindings=[dict(occurrence=0,value='2.5',kind='context',source_alias='c1',fact_path='/numbers/0',evidence_id=None)])
    new['writing_provenance'].update(request_id='new-request',review_id='new-science')
    new_bundle=deepcopy(old_bundle)
    new_bundle['local_manifest']['numeric_context']['c1'].update(text='The other multiplier is 2.5.',values=[dict(fact_path='/numbers/0',value='2.5')])
    bundles={'old-bundle':old_bundle,'new-bundle':new_bundle}
    snapshots={'new-request':dict(base_snapshot=old,execution=dict(bundle_id='new-bundle')),
        'old-request':dict(base_snapshot=snap['base_snapshot'],execution=dict(bundle_id='old-bundle'))}
    exact={'old-request':old,'new-request':new}
    decisions={'old-request':old_paragraph,'new-request':new_paragraph}
    validated=[]
    class Reviews:
        def __init__(self,assets):pass
        def row(self,db,project,identity,request_id,review_id):
            paragraph=decisions[request_id]
            return dict(reviewed_candidate_json=exact[request_id],report_json=dict(numeric_validation_version=2),
                request_json=dict(paragraphs=[dict(paragraph_id=paragraph['id'],corrected_text=paragraph['text'])]))
        def validate_frozen(self,db,project,identity,request_id,review):validated.append(request_id)
        def raw(self,db,project,identity,request_id):return dict(candidate_json=exact[request_id]),dict(input_snapshot=snapshots[request_id])
    class Bundles:
        def __init__(self,assets):pass
        def bundle(self,db,project,bundle_id):return bundles[bundle_id]
    monkeypatch.setattr('app.domain.manuscript_writing.live_review.LiveReviewService',Reviews)
    monkeypatch.setattr('app.domain.manuscript_writing.authorization.LiveWritingService',Bundles)
    manuscripts=type('Manuscripts',(),dict(assets=None))()
    context=load_writing_context(manuscripts,None,'project','manuscript',new)
    assert validated==['new-request','old-request']
    sources={s['id']:s for s in new['sources']}
    assert context.paragraph(old_paragraph,sources)[2][0]['value']=='1.5'
    assert context.paragraph(new_paragraph,sources)[2][0]['value']=='2.5'
