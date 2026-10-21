from copy import deepcopy
import importlib.util
import pytest

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def sample():
    return dict(schema_version=1, project_id='p', workflow_version='manuscript_fact_draft_v1', title='Study', output_language='en', notice='Draft', methods=[dict(id='methods:study_design',text='Observational study',origin='user_provided',source_ids=[],citations=[])], results_groups=[dict(id='g',title='Group',paragraphs=[dict(id='p',text='Mean = 27.555',origin='computed_result',source_ids=['run'],citations=[],numeric_bindings=[dict(fact_id='analysis_run:run:/overall/mean',value='27.555')])],tables=[],figures=[])], references=[], citation_snapshot=None, issues=[], sources=[dict(id='run',kind='analysis_run',role='computed_results',sha256='a'*64,content=dict(overall=dict(mean=27.555,median=27.555,n=12),setup_revision=9))])


def modules():
    assert importlib.util.find_spec('app.domain.manuscript_review') is not None, 'Material review domain is missing'
    from app.domain.manuscript_review.facts import extract_facts, relationships
    from app.domain.manuscript_review.checks import check_snapshot
    return extract_facts, relationships, check_snapshot


def test_fact_identity_includes_source_and_exact_numeric_leaf_path():
    facts, _, _ = modules()
    result = facts(sample())
    assert {f['id'] for f in result} == {'analysis_run:run:/overall/mean','analysis_run:run:/overall/median','analysis_run:run:/overall/n'}
    assert all('setup_revision' not in f['path'] for f in result)
    copy = sample();copy['sources'][0]['kind']='figure'
    assert facts(copy)==[]


@pytest.mark.parametrize('rendered,precision,blocked',[('27.555',None,False),('27.56','2',False),('27.57','2',True),('27.56',None,True)])
def test_exact_fact_rounding_requires_explicit_evidence(rendered,precision,blocked):
    _, _, check = modules();snapshot=sample()
    paragraph=snapshot['results_groups'][0]['paragraphs'][0]
    paragraph['text']='Mean = '+rendered
    paragraph['numeric_bindings'][0]['value']=rendered
    metadata=[] if precision is None else [dict(target_id='analysis_run:run:/overall/mean',field='display_precision',value=precision,evidence='Protocol specifies decimal places')]
    report=check(snapshot,metadata=metadata)
    assert any(i['severity']=='error' and i['category']=='numeric' for i in report)==blocked


def test_equal_other_metric_cannot_supply_implicit_binding_or_precision():
    _, _, check=modules();snapshot=sample()
    p=snapshot['results_groups'][0]['paragraphs'][0]
    p['text']='Mean = 27.56';p['numeric_bindings']=[dict(source_id='run',value='27.56')]
    issues=check(snapshot,metadata=[dict(target_id='analysis_run:run:/overall/median',field='display_precision',value='2',evidence='Median display rule')])
    assert any(i['category']=='numeric' and i['severity']=='error' for i in issues)


def test_checks_use_actual_sections_and_do_not_semantically_clear_free_prose():
    _, _, check=modules();snapshot=sample()
    from app.domain.manuscript_writing.context import normalize_sections
    snapshot['sections']=normalize_sections(snapshot)
    snapshot['sections'][3]['paragraphs']=[dict(id='displayed',text='Treatment always cures disease. Figure 99.',origin='model_generated',source_ids=[],citations=[],numeric_bindings=[])]
    issues=check(snapshot)
    assert any(i['category']=='illustration' and i['location']=='displayed' for i in issues)
    assert any(i['category']=='uncertainty' and i['location']=='displayed' for i in issues)
    assert not any(i['location']=='p' for i in issues)


def test_impacts_link_actual_paragraphs_and_captions_with_conservative_fallback():
    _, relations, _=modules()
    from app.domain.manuscript_review.impacts import affected_locations
    snapshot=sample();snapshot['results_groups'][0]['figures']=[dict(id='f',source_ids=['run'])]
    result=affected_locations([dict(id='run',reasons=['newer_analysis_run'])],relations(snapshot))
    assert {'p','caption:f'} <= set(result[0]['locations'])
    unknown=affected_locations([dict(id='unknown',reasons=['citation_current_changed'])],relations(snapshot))
    assert unknown[0]['scope']=='conservative' and unknown[0]['locations']


def test_unbound_caption_and_table_numbers_are_not_silently_accepted():
    _, _, check=modules();snapshot=sample()
    snapshot['results_groups'][0]['figures']=[dict(id='f',number=1,caption='Mean = 999',caption_status='supplied',caption_origin='user_provided',source_ids=['run'],panels=[])]
    snapshot['results_groups'][0]['tables']=[dict(id='t',number=1,title='Table 1',columns=['metric','value'],rows=[['Mean','999']],source_ids=['run'])]
    issues=check(snapshot)
    assert any(i['category']=='numeric' and i['location'].startswith('table:t') and i['severity']=='error' for i in issues)
    assert any(i['category']=='numeric' and i['location']=='caption:f' for i in issues)

def test_unchanged_legacy_source_binding_requires_human_mapping_but_new_correction_requires_path():
    _, _, check=modules();snapshot=sample()
    p=snapshot['results_groups'][0]['paragraphs'][0]
    p['numeric_bindings']=[dict(source_id='run',value='27.555')]
    assert not any(i['severity']=='error' for i in check(snapshot))
    assert any(i['category']=='numeric' and i['severity']=='human_review' for i in check(snapshot))
    assert any(i['severity']=='error' for i in check(snapshot,strict_locations=['p']))


def test_unchanged_recorded_unmatched_reference_remains_visible_without_waiver_on_edits():
    _, _, check=modules();snapshot=sample()
    p=snapshot['methods'][0];p['text']='Original study mentions Figure 99.'
    from app.domain.manuscripts.illustrations import check_references
    snapshot['issues']=check_references(snapshot['results_groups'],'en',snapshot['methods'])
    original=check(snapshot)
    assert any(i['category']=='illustration' and i['severity']=='human_review' for i in original)
    assert any(i['category']=='illustration' and i['severity']=='error' for i in check(snapshot,strict_locations=[p['id']]))

def review_input(base=None,request=None):
    from app.domain.manuscript_review.contracts import ReviewRequest
    return dict(review_id='review',base_version_id='v1',base_snapshot=base or sample(),input=ReviewRequest.model_validate(request or dict(base_revision=1)).model_dump(mode='json'),created_by='user',created_at='2026-10-20T00:00:00+00:00',source_state=dict(changes=[]),selected_sources=[])


def test_successive_review_preserves_prior_metadata_decisions_and_relationships():
    from app.domain.manuscript_review.composition import compose
    metadata=dict(target_id='analysis_run:run:/overall/mean',field='display_precision',value='2',evidence='Protocol precision')
    snapshot=sample();p=snapshot['results_groups'][0]['paragraphs'][0];p['text']='Mean = 27.56';p['numeric_bindings'][0]['value']='27.56'
    first,_=compose(review_input(snapshot,dict(base_revision=1,metadata=[metadata])))
    second,report=compose(review_input(first,dict(base_revision=2)))
    assert second['review']['metadata']==first['review']['metadata']
    assert not any(i['severity']=='error' for i in report['issues'])
    assert second['results_groups']==first['results_groups']


def test_changed_source_metadata_is_kept_but_marked_stale_not_reused():
    from app.domain.manuscript_review.composition import compose
    first,_=compose(review_input(request=dict(base_revision=1,metadata=[dict(target_id='analysis_run:run:/overall/mean',field='display_precision',value='2',evidence='Protocol precision')])))
    frozen=review_input(first,dict(base_revision=2));frozen['source_state']['changes']=[dict(id='run',reasons=['newer_analysis_run'])]
    second,_=compose(frozen)
    assert second['review']['metadata'][0]['stale'] is True


def test_supplied_methods_can_contain_user_record_numbers_without_becoming_computed_facts():
    from app.domain.manuscript_review.composition import compose
    snapshot=sample();snapshot['issues']=[dict(id='missing:ethics',message='Ethics missing',values=[])]
    frozen=review_input(snapshot,dict(base_revision=1,decisions=[dict(target_id='missing:ethics',status='supplied',value='Approval IRB-2026-123 on 2026-10-20',reason='Record checked',evidence='Signed approval document')]))
    candidate,report=compose(frozen)
    assert report['can_publish']
    assert candidate['methods'][-1]['origin']=='user_provided'
    assert all('2026' not in f['value'] for f in candidate['review']['facts'])
    assert any(i['category']=='numeric' and i['severity']=='human_review' for i in report['issues'])

def test_equal_metric_explicit_binding_does_not_relabel_mean_as_median():
    _,_,check=modules();snapshot=sample()
    p=snapshot['results_groups'][0]['paragraphs'][0]
    p['numeric_bindings'][0]['fact_id']='analysis_run:run:/overall/median'
    assert any(i['severity']=='error' and i['category']=='numeric' for i in check(snapshot))


def test_writing_after_review_preserves_history_without_claiming_old_report_checks_new_prose():
    from app.domain.manuscript_review.composition import compose
    from app.domain.manuscript_writing.context import compose_candidate,normalize_sections
    reviewed,_=compose(review_input())
    frozen=dict(request_id='writing',base_version_id='v2',input=dict(base_revision=2,mode='full_draft',target_section=None,keywords=[],acknowledgements=''),base_snapshot=reviewed)
    sections=normalize_sections(reviewed)
    for section in sections:
        if section['id'] not in ('title','references'):
            section['paragraphs']=[dict(id='new:'+section['id'],text='Missing facts require review.',source_ids=[],citations=[],numeric_bindings=[])]
    candidate=compose_candidate(dict(sections=sections),frozen)
    assert 'review_provenance' not in candidate and 'review' not in candidate
    assert candidate['review_history'][-1]['provenance']==reviewed['review_provenance']
    assert candidate['review_history'][-1]['review']==reviewed['review']
    assert candidate['review_history'][-1]['applies_to_current_text'] is False
    assert candidate['review_history'][-1]['status']=='historical_requires_recheck'

def test_missing_caption_decision_targets_actual_displayed_caption():
    from app.domain.manuscript_review.composition import compose
    snapshot=sample();snapshot['results_groups'][0]['figures']=[dict(id='image',number=1,caption='',caption_status='missing',source_ids=[],panels=[])]
    snapshot['issues']=[dict(id='missing:caption:image',message='Caption missing',values=[])]
    frozen=review_input(snapshot,dict(base_revision=1,decisions=[dict(target_id='missing:caption:image',status='supplied',value='User supplied observation',reason='Checked image record',evidence='Saved source caption')]))
    candidate,report=compose(frozen)
    assert candidate['results_groups'][0]['figures'][0]['caption']=='User supplied observation'
    assert not any(i['id']=='missing:caption:image' for i in candidate['issues'])
    assert report['can_publish']


def test_selected_conflict_value_must_be_one_of_original_choices():
    from app.domain.manuscript_review.composition import compose
    snapshot=sample();snapshot['issues']=[dict(id='conflict:study_design',message='Conflicting design',values=['randomized','observational'])]
    frozen=review_input(snapshot,dict(base_revision=1,decisions=[dict(target_id='conflict:study_design',status='selected',value='unrecorded',reason='Choice',evidence='Record')]))
    with pytest.raises(ValueError,match='Selected'):
        compose(frozen)

@pytest.mark.parametrize('text',['Evidence [999, 1000].','Evidence [999-1001].','Evidence [999–1001].'])
def test_compound_reference_markers_cannot_bypass_support_guards(text):
    _,_,check=modules();snapshot=sample();snapshot['methods'][0]['text']=text
    assert any(i['category']=='reference' and i['severity']=='error' for i in check(snapshot))

@pytest.mark.parametrize('text,bindings',[
    ('Mean = 30; Median = 27.555',[('mean','27.555'),('median','30')]),
    ('Mean = 27.555; Median = 30',[('median','30'),('mean','27.555')]),
])
def test_distinct_metric_values_cannot_be_swapped_or_bindings_reordered(text,bindings):
    from app.domain.manuscript_review.composition import compose
    snapshot=sample();snapshot['sources'][0]['content']['overall']['median']=30
    correction=dict(paragraph_id='p',text=text,source_ids=['run'],numeric_bindings=[dict(fact_id='analysis_run:run:/overall/'+metric,value=value) for metric,value in bindings])
    _,report=compose(review_input(snapshot,dict(base_revision=1,corrections=[correction])))
    assert not report['can_publish']
    assert any(i['category']=='numeric' and i['severity']=='error' for i in report['issues'])


@pytest.mark.parametrize('marker',['[999]','[999, 1000]','[999-1001]','[999–1001]'])
def test_supplied_caption_reference_numbers_require_frozen_support(marker):
    from app.domain.manuscript_review.composition import compose
    snapshot=sample();snapshot['results_groups'][0]['figures']=[dict(id='image',number=1,caption='',caption_status='missing',source_ids=[],panels=[])]
    snapshot['issues']=[dict(id='missing:caption:image',message='Caption missing',values=[])]
    decision=dict(target_id='missing:caption:image',status='supplied',value='Measured signal '+marker+'.',reason='User confirmation',evidence='User text is not citation support')
    _,report=compose(review_input(snapshot,dict(base_revision=1,decisions=[decision])))
    assert not report['can_publish']
    assert any(i['category']=='reference' and i['location']=='caption:image' and i['severity']=='error' for i in report['issues'])


def test_displayed_panel_reference_numbers_require_frozen_support():
    _,_,check=modules();snapshot=sample()
    snapshot['results_groups'][0]['figures']=[dict(id='image',number=1,caption='Observation',caption_status='supplied',source_ids=[],panels=[dict(label='A',description='Measured signal [999, 1000].')])]
    assert any(i['category']=='reference' and i['location']=='panel:image:0' and i['severity']=='error' for i in check(snapshot))

def rounded_reviewed_writing_input(mode='full_draft',target=None):
    from app.domain.manuscript_review.composition import compose
    from app.domain.manuscript_writing.context import normalize_sections
    snapshot=sample()
    reviewed,report=compose(review_input(snapshot,dict(base_revision=1,metadata=[dict(target_id='analysis_run:run:/overall/mean',field='display_precision',value='2',evidence='Two decimal places')],corrections=[dict(paragraph_id='p',text='Mean = 27.56',source_ids=['run'],numeric_bindings=[dict(fact_id='analysis_run:run:/overall/mean',value='27.56')])])))
    assert report['can_publish']
    reviewed['sections']=normalize_sections(reviewed)
    reviewed['sections'][4]['paragraphs']=[dict(id='discussion',text='Missing discussion facts require review.',source_ids=[],citations=[],numeric_bindings=[],origin='model_generated')]
    frozen=dict(request_id='new-writing',base_version_id='reviewed-version',input=dict(base_revision=2,mode=mode,target_section=target,keywords=[],acknowledgements=''),base_snapshot=reviewed)
    sections=deepcopy(reviewed['sections'])
    if mode=='rewrite_section':sections=[s for s in sections if s['id']==target]
    return frozen,dict(sections=sections)


def test_full_writing_can_echo_exact_reviewed_rounded_paragraph_without_relabeling():
    from app.domain.manuscript_writing.context import compose_candidate,validate_candidate
    frozen,output=rounded_reviewed_writing_input()
    candidate=compose_candidate(output,frozen)
    assert candidate['sections'][3]==frozen['base_snapshot']['sections'][3]
    validate_candidate(candidate,frozen)
    assert candidate['review_history'][-1]['applies_to_current_text'] is False


def test_local_section_rewrite_preserves_non_target_reviewed_rounded_paragraph():
    from app.domain.manuscript_writing.context import compose_candidate,validate_candidate
    frozen,output=rounded_reviewed_writing_input('rewrite_section','discussion')
    output['sections'][0]['paragraphs'][0]['text']='Missing facts need additional review.'
    candidate=compose_candidate(output,frozen)
    assert candidate['sections'][3]==frozen['base_snapshot']['sections'][3]
    validate_candidate(candidate,frozen)


@pytest.mark.parametrize('mutation',['text','value','fact_id','source_ids','identity'])
def test_full_writing_cannot_reuse_old_review_binding_permission_for_modified_paragraph(mutation):
    from app.domain.manuscript_writing.context import compose_candidate
    frozen,output=rounded_reviewed_writing_input()
    p=output['sections'][3]['paragraphs'][0]
    if mutation=='text':p['text']='Mean = 27.57'
    if mutation=='value':p['numeric_bindings'][0]['value']='27.57'
    if mutation=='fact_id':p['numeric_bindings'][0]['fact_id']='analysis_run:run:/overall/median'
    if mutation=='source_ids':p['source_ids']=[]
    if mutation=='identity':p['id']='other-id'
    with pytest.raises(ValueError):compose_candidate(output,frozen)
