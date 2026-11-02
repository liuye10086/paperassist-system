"""W1 opt-in structure/range behavior. Synthetic prose, never a provider response."""
from copy import deepcopy
from io import BytesIO
import json

import pytest
from docx import Document


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def base():
    return dict(schema_version=1,title='Frozen title',output_language='en',workflow_version='manuscript_v1',
                methods=[],results_groups=[],references=[],issues=[],sources=[],citation_snapshot=None,
                notice='Engineering fixture')


def request(kind='research', **changes):
    from app.domain.manuscript_writing.live_contracts import preview_data
    return preview_data(dict(schema_version=4,base_revision=1,mode='full_draft',article_type=kind,
                             output_language='en',selected_source_ids=[],selected_evidence_ids=[]) | changes)


def prepared(kind='research', draft=None, **changes):
    from app.domain.manuscript_writing.bundle import build_bundle
    from app.domain.manuscript_writing.frozen import contract
    b=base() if draft is None else draft
    req=request(kind,**changes)
    frozen=contract(schema_version=4,document_kind='thesis' if b.get('thesis_context') else 'sci')
    bundle=build_bundle(b,req,execution_contract=frozen)
    bundle['id']='bundle'
    snapshot=dict(request_id='request',base_version_id='v1',base_snapshot=b,input=req)
    return snapshot,bundle,json.loads(json.loads(bundle['wire_json'])['input'])


def generated(payload):
    return dict(sections=[dict(id=sid,paragraphs=[dict(id='p:'+sid,text='Not provided; requires verification.',
        source_aliases=[],evidence_aliases=[],study_numeric_bindings=[])]) for sid in payload['writing_scope']['output_section_ids']])


@pytest.mark.parametrize('kind',['research','brief','narrative_review','methods'])
def test_four_types_execute_compose_and_render_type_headings(kind):
    from app.domain.manuscript_writing.live_execution import compose_live_candidate,validate_live_candidate
    from app.domain.manuscript_writing.article_contract import labels
    from app.adapters.manuscript_docx import build_manuscript_docx
    snap,bundle,payload=prepared(kind)
    result=compose_live_candidate(generated(payload),snap,bundle,'call','synthetic_fixture')
    validate_live_candidate(result,snap,bundle)
    assert result['article_type']==kind
    document=Document(BytesIO(build_manuscript_docx(result,{})))
    headings=[p.text for p in document.paragraphs if p.style.name=='Heading 1']
    assert all(label[1] in headings for label in labels(kind)[1:])
    assert result['writing_provenance']['verification_status']=='pending'


def test_narrative_review_cannot_relabel_computed_study_results():
    b=base();b['sources']=[dict(id='stats',kind='analysis_run',role='computed_results',content={'statistics':{'n':12}})]
    with pytest.raises(ValueError,match='[Ll]iterature|review'):
        prepared('narrative_review',b,selected_source_ids=['stats'])


def test_narrative_review_allows_acquired_literature_source():
    b=base();b['sources']=[dict(id='lit',kind='literature',role='literature',content={'text':'A reviewed article.'})]
    snap,bundle,payload=prepared('narrative_review',b,selected_source_ids=['lit'])
    assert payload['sources'][0]['role']=='literature'


def test_methods_no_validation_does_not_allow_performance_claim():
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    snap,bundle,payload=prepared('methods');out=generated(payload)
    next(s for s in out['sections'] if s['id']=='validation')['paragraphs'][0]['text']='The method outperformed all alternatives.'
    with pytest.raises(ValueError,match='[Vv]alidation'):
        compose_live_candidate(out,snap,bundle,'call','synthetic_fixture')


def published_base():
    from app.domain.manuscript_writing.context import normalize_sections
    b=base();b['sections']=normalize_sections(b)
    for section in b['sections']:
        if section['id'] not in ('title','references'):
            section['paragraphs']=[dict(id='stable:'+section['id'],text='Original requires verification.',origin='user_provided',source_ids=[],citations=[],numeric_bindings=[])]
    return b


def test_results_discussion_preserve_every_other_section_and_ids():
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    b=published_base();snap,bundle,payload=prepared(draft=b,mode='results_discussion')
    out=generated(payload)
    for s in out['sections']:s['paragraphs'][0]['id']='stable:'+s['id']
    result=compose_live_candidate(out,snap,bundle,'call','synthetic_fixture')
    for old,new in zip(b['sections'],result['sections']):
        if old['id'] not in ('results','discussion'):assert old==new
        else:assert new['paragraphs'][0]['id']==old['paragraphs'][0]['id']


def test_polish_rejects_replaced_identity_and_outside_paragraph_scope():
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    b=published_base();snap,bundle,payload=prepared(draft=b,mode='polish',target_sections=['discussion'],target_paragraph_ids=['stable:discussion'])
    out=generated(payload)
    with pytest.raises(ValueError,match='identit|plan'):
        compose_live_candidate(out,snap,bundle,'call','synthetic_fixture')
    out['sections'][0]['paragraphs'][0]['id']='stable:discussion'
    result=compose_live_candidate(out,snap,bundle,'call','synthetic_fixture')
    assert result['sections'][3]==b['sections'][3]


def test_restructure_requires_explicit_lineage_and_preserves_non_target():
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    b=published_base();plan=[dict(id='expanded:discussion',section_id='discussion',source_paragraph_ids=['stable:discussion'])]
    snap,bundle,payload=prepared(draft=b,mode='expand_restructure',target_sections=['discussion'],target_paragraph_ids=['stable:discussion'],paragraph_plan=plan)
    out=generated(payload);out['sections'][0]['paragraphs'][0]['id']='expanded:discussion'
    result=compose_live_candidate(out,snap,bundle,'call','synthetic_fixture')
    assert result['writing_provenance']['paragraph_lineage']==plan
    assert result['sections'][3]==b['sections'][3]
    out['sections'][0]['paragraphs'][0]['id']='unplanned'
    with pytest.raises(ValueError,match='identit|plan'):
        compose_live_candidate(out,snap,bundle,'call','synthetic_fixture')


def test_old_contracts_remain_explicitly_opt_in():
    from app.domain.manuscript_writing.live_contracts import preview_data
    from app.domain.manuscript_writing.frozen import contract
    assert contract(schema_version=2)['schema_version']==2
    assert contract(schema_version=3)['schema_version']==3
    with pytest.raises(ValueError):preview_data(dict(schema_version=2,base_revision=1,mode='polish',output_language='en',selected_source_ids=[],selected_evidence_ids=[]))


def test_review_literature_source_can_reach_candidate_and_stays_pending():
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    b=base();b['sources']=[dict(id='lit',kind='literature',role='literature',content={})]
    snap,bundle,payload=prepared('narrative_review',b,selected_source_ids=['lit'])
    out=generated(payload);out['sections'][4]['paragraphs'][0]['source_aliases']=['s1']
    candidate=compose_live_candidate(out,snap,bundle,'call','synthetic_fixture')
    assert candidate['sections'][4]['paragraphs'][0]['source_ids']==['lit']
    assert candidate['sections'][4]['paragraphs'][0]['verification_status']=='pending'


def test_noncontiguous_polish_keeps_unselected_paragraph_at_its_original_position():
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    b=published_base();discussion=next(s for s in b['sections'] if s['id']=='discussion')
    discussion['paragraphs']=[dict(id=pid,text='Original requires verification.',origin='user_provided',source_ids=[],citations=[],numeric_bindings=[]) for pid in ['first','protected-middle','last']]
    snap,bundle,payload=prepared(draft=b,mode='polish',target_sections=['discussion'],target_paragraph_ids=['first','last'])
    p=generated(payload)['sections'][0]['paragraphs'][0]
    out=dict(sections=[dict(id='discussion',paragraphs=[dict(p,id='first'),dict(p,id='last')])])
    candidate=compose_live_candidate(out,snap,bundle,'call','synthetic_fixture')
    ps=next(s for s in candidate['sections'] if s['id']=='discussion')['paragraphs']
    assert [p['id'] for p in ps]==['first','protected-middle','last']
    assert ps[1]==discussion['paragraphs'][1]


def test_new_article_type_can_be_read_rewritten_checked_and_language_inventoried():
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    from app.domain.manuscript_writing.context import normalize_sections
    from app.domain.manuscript_review.checks import check_snapshot
    from app.domain.manuscript_writing.language import inventory
    snap,bundle,payload=prepared('narrative_review');b=compose_live_candidate(generated(payload),snap,bundle,'call','synthetic_fixture')
    assert [s['id'] for s in normalize_sections(b)]==[s['id'] for s in b['sections']]
    assert not [i for i in check_snapshot(b) if i['location']=='sections' and i['severity']=='error']
    assert any(i['text']=='Thematic synthesis' for i in inventory(b,{},[]))
    snap,bundle,payload=prepared('narrative_review',b,mode='rewrite_section',target_section='themes')
    out=generated(payload);out['sections'][0]['paragraphs'][0]['id']='p:themes'
    candidate=compose_live_candidate(out,snap,bundle,'next','synthetic_fixture')
    assert candidate['sections'][3]==b['sections'][3]


def test_school_subset_alias_composition_and_science_review_recognize_schema4():
    from tests.domain.test_school_writing_live import material
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    from app.domain.manuscript_writing.school_live import is_school
    from app.domain.manuscript_writing.numeric_contract import is_numeric_v2
    from app.domain.manuscript_writing.live_review_candidate import prepare,body_digest,target_ids
    from app.domain.literature.service import digest
    b,_,_=material();target=next(s for s in b['sections'] if s['purpose']=='materials_and_methods')
    target['paragraphs']=[dict(id=pid,text='Original requires verification.',origin='user_provided',source_ids=[],citations=[],numeric_bindings=[]) for pid in ['school-first','school-protected','school-last']]
    snap,bundle,payload=prepared(draft=b,document_kind='thesis',mode='polish',target_sections=[target['id']],target_paragraph_ids=['school-first','school-last'])
    assert is_school(bundle) and is_numeric_v2(bundle)
    aliases={pid:a for a,pid in bundle['local_manifest']['writing_paragraph_aliases'].items()}
    p=generated(payload)['sections'][0]['paragraphs'][0]
    out=dict(sections=[dict(id=payload['writing_scope']['output_section_ids'][0],paragraphs=[dict(p,id=aliases[pid]) for pid in ['school-first','school-last']])])
    candidate=compose_live_candidate(out,snap,bundle,'call','synthetic_fixture')
    ps=next(s for s in candidate['sections'] if s['id']==target['id'])['paragraphs']
    assert [p['id'] for p in ps]==['school-first','school-protected','school-last'] and ps[1]==target['paragraphs'][1]
    assert candidate['sections'][0]==b['sections'][0]
    body=dict(schema_version=3,candidate_sha256=digest(candidate),paragraphs=[dict(paragraph_id=p['id'],text_sha256=digest(p['text']),corrected_text=None,classification='non_claim',scientific_basis='Synthetic check',claim=None,numeric_bindings=[]) for p in ps if p['id'] in target_ids(candidate,snap)],consistency=dict(body_sha256=body_digest(candidate),title=dict(subject=True,direction=True,strength=True,basis='Checked'),abstracts={}))
    reviewed,_=prepare(candidate,snap,bundle,body,lambda *args:None)
    assert reviewed['sections'][0]==b['sections'][0]


def test_configuration_contract_preserves_explicit_root_kind():
    from app.domain.manuscript_writing.frozen import contract
    old=contract(schema_version=2)
    config=dict(document_kind='thesis',bundle=dict(models=dict(writing=dict(execution=dict(policy=old['policy'],input_token_allowance=old['max_input_allowance'],task_limit_micro_usd=old['task_limit_micro_usd'])),batch_max_posts=old['batch_max_posts'],max_corrections=old['max_corrections'],batch_cap_micro_usd=old['batch_cap_micro_usd']),prompts=dict(writing_instruction='')))
    assert contract(config,schema_version=4,document_kind='sci')['document_kind']=='sci'


def test_schema4_science_review_cannot_edit_preserved_paragraph_or_references():
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    from app.domain.manuscript_writing.live_review_candidate import finish
    b=published_base();snap,bundle,payload=prepared(draft=b,mode='polish',target_sections=['discussion'])
    out=generated(payload);out['sections'][0]['paragraphs'][0]['id']='stable:discussion'
    raw=compose_live_candidate(out,snap,bundle,'call','synthetic_fixture');candidate=deepcopy(raw)
    candidate['sections'][3]['paragraphs'][0]['text']='Unexpected non-target change'
    with pytest.raises(ValueError,match='[Nn]on-target|preserv'):
        finish(candidate,raw,snap,dict(consistency=dict(body_sha256='frozen'),paragraphs=[]),None,{},'review',school_bundle=bundle)


def test_methods_ordinary_computed_statistics_do_not_establish_performance_validation():
    b=base();b['sources']=[dict(id='stats',kind='analysis_run',role='computed_results',content={'statistics':{'n':12}})]
    snap,bundle,payload=prepared('methods',b,selected_source_ids=['stats'])
    assert payload['validation_available'] is False


def test_school_article_structure_wire_omits_protected_chapter_titles():
    from tests.domain.test_school_writing_live import material
    b,_,_=material();protected_title=next(s['title'] for s in b['sections'] if s['purpose']=='manual')
    snap,bundle,payload=prepared(draft=b,document_kind='thesis')
    assert protected_title not in [s['heading'] for s in payload['article_structure']]


def test_schema4_numeric_catalog_remains_available_at_scientific_review():
    from app.domain.manuscript_writing.numeric_contract import is_numeric_v2
    _,bundle,_=prepared()
    assert is_numeric_v2(bundle)


@pytest.mark.parametrize('kind',['narrative_review','methods'])
def test_new_article_reference_section_is_in_actual_language_inventory(kind):
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    from app.domain.manuscript_writing.language import inventory
    snap,bundle,payload=prepared(kind);candidate=compose_live_candidate(generated(payload),snap,bundle,'call','synthetic_fixture')
    candidate['references']=[dict(number=1,text='Acquired paper metadata',project_reference_id='paper')]
    items=inventory(candidate,{},[])
    assert any(i['text']=='(1) Acquired paper metadata' and i['scope']=='reference_metadata' for i in items)


def test_invalid_sci_scope_preview_is_a_422_input_error(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from app.core.exceptions import StorageError
    from app.domain.manuscript_writing import authorization as auth
    db=SimpleNamespace(execute=lambda *args:SimpleNamespace(fetchone=lambda:None))
    service=auth.LiveWritingService.__new__(auth.LiveWritingService)
    service.store=SimpleNamespace(user_id='owner',connection=lambda **kwargs:nullcontext(db),require_task=lambda *args:dict(status='succeeded'))
    service.manuscripts=SimpleNamespace(root=lambda *args:dict(current_revision=1),version=lambda *args:dict(id='version',task_id='task',snapshot_json=published_base()))
    monkeypatch.setattr(auth,'resolve_document_context',lambda *args,**kwargs:dict(document_kind='sci'))
    monkeypatch.setattr(auth,'resolve',lambda *args:None)
    monkeypatch.setattr(auth,'changes',lambda *args:[])
    body=request(mode='rewrite_section',target_section='unknown-section')
    with pytest.raises(StorageError) as error:service.preview('project','manuscript',body,'preview-key')
    assert error.value.status==422


def test_methods_explicit_computed_validation_selection_is_frozen_pending_review():
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    b=base();b['sources']=[dict(id='stats',kind='analysis_run',role='computed_results',content={'statistics':{'n':12}})]
    snap,bundle,payload=prepared('methods',b,selected_source_ids=['stats'],validation_source_ids=['stats'])
    assert payload['validation_available'] is True
    assert payload['validation_source_aliases']==['s1']
    assert bundle['local_manifest']['validation_source_ids']==['stats']
    out=generated(payload);validation=next(s for s in out['sections'] if s['id']=='validation')['paragraphs'][0]
    validation.update(text='Validation records contain n=12; interpretation requires review.',source_aliases=['s1'],study_numeric_bindings=[dict(source_alias='s1',fact_path='/statistics/n',value='12')])
    candidate=compose_live_candidate(out,snap,bundle,'call','synthetic_fixture')
    assert next(s for s in candidate['sections'] if s['id']=='validation')['paragraphs'][0]['verification_status']=='pending'


def test_methods_reject_literature_or_unselected_validation_sources():
    b=base();b['sources']=[dict(id='lit',kind='literature',role='literature',content={})]
    with pytest.raises(ValueError,match='[Vv]alidation'):
        prepared('methods',b,selected_source_ids=['lit'],validation_source_ids=['lit'])
    with pytest.raises(ValueError,match='[Vv]alidation'):
        prepared('methods',b,validation_source_ids=['lit'])


def test_schema4_wire_reuses_exact_numeric_instruction_and_rebuilds_consistently():
    from app.domain.manuscript_writing.numeric_contract import EXACT_INSTRUCTION
    from app.domain.manuscript_writing.frozen import validate_wire
    from app.domain.manuscript_writing.bundle import validate_bundle
    snap,bundle,_=prepared()
    assert EXACT_INSTRUCTION in json.loads(bundle['wire_json'])['instructions']
    validate_wire(bundle['wire_json'],bundle['execution_contract'])
    validate_bundle(dict(bundle,base_snapshot=snap['base_snapshot'],request_json=snap['input']))


def test_legacy_numeric_preview_rejects_nonresearch_article_and_keeps_research():
    from app.core.exceptions import StorageError
    from app.domain.manuscript_writing.bundle import build_bundle
    from app.domain.manuscript_writing.live_contracts import preview_data
    from app.domain.manuscript_writing.frozen import contract
    request=preview_data(dict(schema_version=2,base_revision=1,mode='full_draft',output_language='en',selected_source_ids=[],selected_evidence_ids=[]))
    legacy=contract(schema_version=2)
    assert build_bundle(base(),request,execution_contract=legacy)['execution_contract']['schema_version']==2
    for kind in ('brief','narrative_review','methods'):
        with pytest.raises(StorageError) as error:
            build_bundle(dict(base(),article_type=kind),request,execution_contract=legacy)
        assert error.value.status==422


def cited_base(with_study_number=False):
    from app.domain.literature_citations.formatter import render_paragraphs
    b=published_base()
    claim='Prior work included (12) participants and supports this mechanism' if with_study_number else 'Prior work supports this mechanism'
    binding=dict(review_id='review',project_reference_id='ref',metadata_version_id='metadata',metadata=dict(article_type='journal',title='Frozen source',authors=[dict(family='Doe',initials='J')],journal_abbreviation='J Test',year='2026',volume='1',pages='1-2'),evidence=[dict(id='ev',quote='Existing evidence from (12) participants supports this mechanism.',reading_scope='abstract')])
    paragraphs=[dict(id='prior',fragments=[dict(kind='claim',text=claim,bindings=[binding]),dict(kind='text',text='.')])]
    rendered=render_paragraphs(paragraphs)
    b['citation_snapshot']=dict(paragraphs=paragraphs,output=rendered)
    b['references']=rendered['references']
    target=next(s for s in b['sections'] if s['id']=='discussion')['paragraphs'][0]
    target.update(text=rendered['paragraphs'][0]['text'],origin='literature',citations=[binding])
    return b,claim+'.'


def test_polish_projects_selected_citation_prose_without_server_number_and_requires_new_review():
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    b,plain=cited_base();snap,bundle,payload=prepared(draft=b,mode='polish',target_sections=['discussion'],selected_evidence_ids=['ev'])
    contexts=[p for s in payload['context'] for p in s['paragraphs']]
    assert any(p['text']==plain and p['id']=='stable:discussion' for p in contexts)
    out=generated(payload);out['sections'][0]['paragraphs'][0].update(id='stable:discussion',text='Earlier work supports this mechanism.',evidence_aliases=['e1'])
    candidate=compose_live_candidate(out,snap,bundle,'call','synthetic_fixture')
    p=next(s for s in candidate['sections'] if s['id']=='discussion')['paragraphs'][0]
    assert p['citations']==[] and p['verification_status']=='pending'


def test_polish_does_not_treat_parenthesized_study_count_as_server_citation():
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    b,plain=cited_base(True);snap,bundle,payload=prepared(draft=b,mode='polish',target_sections=['discussion'],selected_evidence_ids=['ev'])
    assert any(p['text']==plain and '(12)' in p['text'] for s in payload['context'] for p in s['paragraphs'])
    out=generated(payload);out['sections'][0]['paragraphs'][0].update(id='stable:discussion',text='Earlier work supports this mechanism.',evidence_aliases=['e1'])
    with pytest.raises(ValueError,match='Polish must preserve'):
        compose_live_candidate(out,snap,bundle,'call','synthetic_fixture')


def test_brief_chinese_limit_counts_each_han_character():
    from app.domain.manuscript_writing.live_execution import compose_live_candidate
    snap,bundle,payload=prepared('brief',output_language='zh-CN',brief_limits=dict(max_words=8,max_figures=None))
    out=generated(payload)
    for section in out['sections']:section['paragraphs'][0]['text']='待核实'
    with pytest.raises(ValueError,match='Brief word limit exceeded'):
        compose_live_candidate(out,snap,bundle,'call','synthetic_fixture')
