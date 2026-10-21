from copy import deepcopy
import pytest
from tests.domain.test_writing_live_candidates import fixture
from app.domain.manuscript_writing.live_execution import compose_live_candidate
from app.domain.manuscript_writing.live_review_candidate import prepare,body_digest,finish,citation_body
from app.domain.manuscript_writing.live_review_contracts import ScientificReviewRequest
from app.domain.literature.service import digest

@pytest.fixture(autouse=True)
def postgres_schema(): yield None

def sample():
    snap,bundle,output=fixture()
    p=output['sections'][2]['paragraphs'][0]
    p.update(text='Our n=12, published n=42 and n=42.',source_aliases=['s1'],evidence_aliases=['e1'],study_numeric_bindings=[dict(source_alias='s1',fact_path='/statistics/n',value='12')])
    raw=compose_live_candidate(output,snap,bundle,'call','synthetic_fixture')
    body=dict(schema_version=2,candidate_sha256=digest(raw),paragraphs=[dict(paragraph_id=p['id'],text_sha256=digest(p['text']),classification='non_claim',scientific_basis='Manual classification',numeric_bindings=[]) for s in raw['sections'] if s['id']!='references' for p in s['paragraphs']],
        consistency=dict(body_sha256=body_digest(raw),title=dict(subject=True,direction=True,strength=True,basis='Body compared'),abstract=dict(objective=True,methods=True,key_results=True,conclusion=True,basis='Body compared')))
    body['paragraphs'][2].update(classification='mixed_claim',claim=dict(claim_id='new',claim_revision=1,bindings=[dict(review_id='new-review',metadata_version_id='meta')]),numeric_bindings=[
        dict(occurrence=0,value='12',kind='study',source_alias='s1',fact_path='/statistics/n'),
        dict(occurrence=1,value='42',kind='literature',evidence_id='new-evidence'),dict(occurrence=2,value='42',kind='literature',evidence_id='new-evidence')])
    body=ScientificReviewRequest.model_validate(body).model_dump(mode='json')
    def resolve(decision,text):
        return dict(kind='claim',claim_id='new',claim_revision=1,text=text,bindings=[dict(evidence=[dict(id='new-evidence',quote='Public source with 42 observations.')])])
    return raw,snap,bundle,body,resolve

def test_mixed_numbers_bind_every_occurrence_to_distinct_frozen_or_new_reviewed_source():
    raw,snap,bundle,body,resolve=sample()
    candidate,_=prepare(raw,snap,bundle,body,resolve)
    assert candidate['sections'][2]['paragraphs'][0]['numeric_bindings']==body['paragraphs'][2]['numeric_bindings']
    assert raw['sections'][2]['paragraphs'][0]['verification_status']=='pending'

@pytest.mark.parametrize('mutation',['missing','duplicate','path','study_value','literature_value','old_evidence','alias_only','classification','extra','swap'])
def test_mixed_number_misattribution_is_rejected(mutation):
    raw,snap,bundle,body,resolve=sample();p=body['paragraphs'][2];b=p['numeric_bindings']
    if mutation=='missing': b.pop()
    if mutation=='duplicate': b[2]['occurrence']=1
    if mutation=='path': b[0]['fact_path']='/statistics/mean'
    if mutation=='study_value': b[0]['value']='42'
    if mutation=='literature_value': b[1]['value']='12'
    if mutation=='old_evidence': b[1]['evidence_id']='old-evidence'
    if mutation=='alias_only': b[1]['evidence_id']='e1'
    if mutation=='classification': p['classification']='literature_claim'
    if mutation=='extra': b.append(dict(b[0],occurrence=3))
    if mutation=='swap': b[0]['kind']='literature';b[0]['evidence_id']='new-evidence'
    with pytest.raises(ValueError): prepare(raw,snap,bundle,body,resolve)

def test_rewrite_rejects_changed_references_and_keeps_untouched_sections():
    raw,snap,bundle,body,resolve=sample()
    snap['input'].update(mode='rewrite_section',target_section='discussion')
    body['paragraphs']=[body['paragraphs'][4]]
    candidate,fragments=prepare(raw,snap,bundle,body,resolve)
    # No reference in this base. The frozen malformed legacy citation stub is not used.
    snap['base_snapshot']['references']=[];raw['references']=[];candidate['references']=[]
    out,_=finish(candidate,raw,snap,body,None,{},'review')
    assert out['sections'][:4]==raw['sections'][:4]
    assert out['sections'][5:]==raw['sections'][5:]
    raw['references']=[dict(number=1,text='Retained reference',project_reference_id='r')]
    with pytest.raises(ValueError): finish(candidate,raw,snap,body,None,{},'review')

def test_reviewed_title_must_fit_existing_immutable_manuscript_contract():
    raw,snap,bundle,body,resolve=sample()
    candidate,_=prepare(raw,snap,bundle,body,resolve)
    candidate['sections'][0]['paragraphs'][0]['text']='a'*201
    with pytest.raises(ValueError): finish(candidate,raw,snap,body,None,{},'review')


@pytest.mark.parametrize('version',[1,2])
@pytest.mark.parametrize('language',['en','zh-CN'])
def test_science_notice_updates_new_composition_only_and_preserves_raw(version,language):
    raw,snap,bundle,body,resolve=sample()
    snap['input']['output_language']=language
    snap['base_snapshot']['notice']='Legacy partial fact draft'
    snap['base_snapshot']['issues']=[dict(id='scope',kind='limitation',field='scope',message='Legacy partial fact draft',values=[])]
    raw=compose_live_candidate(raw['writing_provenance']['raw_output'],snap,bundle,'call','synthetic_fixture',composition_version=version)
    body['candidate_sha256']=digest(raw);before=deepcopy(raw)
    candidate,_=prepare(raw,snap,bundle,body,resolve)
    reviewed,_=finish(candidate,raw,snap,body,None,{},'review')
    if version==1:
        assert reviewed['notice']==raw['notice']
        assert reviewed['issues']==raw['issues']
    else:
        assert ('Explicit human scientific review recorded' if language=='en' else '已记录对新文本的人工科学审核') in reviewed['notice']
        assert ('Scientific review pending' if language=='en' else '科学审核待完成') not in reviewed['notice']
        assert reviewed['issues'][0]['message']==reviewed['notice']
    assert raw==before
