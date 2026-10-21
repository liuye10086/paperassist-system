from copy import deepcopy

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    # Pure composition/contract tests never open a database connection.
    yield None


def frozen(mode='full_draft', target=None):
    return dict(request_id='request',base_version_id='version',prompt_version='sci-writing-v1',policy_version='offline-only-v1',
        input=dict(base_revision=1,mode=mode,target_section=target,instructions='Write cautiously',keywords=[],acknowledgements=''),
        base_snapshot=dict(title='Frozen title',output_language='en',methods=[],results_groups=[],references=[],issues=[{'id':'missing:ethics'}],
            sources=[dict(id='stats',kind='analysis_run',role='computed_results',content=dict(statistics={'n':12,'p_value':{'value':0.05}}))],citation_snapshot=None))


def output(snapshot):
    from app.domain.manuscript_writing.context import normalize_sections
    sections=normalize_sections(snapshot['base_snapshot'])
    for section in sections:
        if section['id'] not in ('title','references'):
            section['paragraphs']=[dict(id='writing:'+section['id']+':1',text='Evidence requires review.',source_ids=[],citations=[],numeric_bindings=[])]
    if snapshot['input']['mode']=='rewrite_section':
        sections=[s for s in sections if s['id']==snapshot['input']['target_section']]
    return {'sections':sections}


def test_complete_candidate_preserves_facts_and_records_unverified_provenance():
    from app.domain.manuscript_writing.context import compose_candidate,validate_candidate
    snapshot=frozen(); candidate=compose_candidate(output(snapshot),snapshot,model_call_id='call')
    assert [s['id'] for s in candidate['sections']]==['title','abstract','introduction','results','discussion','materials_and_methods','references']
    assert candidate['sources']==snapshot['base_snapshot']['sources']
    assert candidate['issues']==snapshot['base_snapshot']['issues']
    assert candidate['writing_provenance']['verification_status']=='not_verified'
    assert candidate['writing_provenance']['model_call_id']=='call'
    from app.domain.literature.service import digest
    assert candidate['writing_provenance']['input_digest']==digest(snapshot)
    validate_candidate(candidate,snapshot)


def test_rewrite_preserves_every_other_section_and_stable_paragraph_ids():
    from app.domain.manuscript_writing.context import compose_candidate,normalize_sections
    snapshot=frozen('rewrite_section','discussion')
    snapshot['base_snapshot']['sections']=normalize_sections(snapshot['base_snapshot'])
    original=deepcopy(snapshot['base_snapshot']['sections'])
    original[4]['paragraphs']=[dict(id='stable-discussion',text='Old prose',origin='user',source_ids=[],citations=[])]
    snapshot['base_snapshot']['sections']=original
    result=output(snapshot);result['sections'][0]['paragraphs'][0]['id']='stable-discussion'
    candidate=compose_candidate(result,snapshot)
    assert candidate['sections'][:4]==original[:4]
    assert candidate['sections'][5:]==original[5:]
    assert candidate['sections'][4]['paragraphs'][0]['id']=='stable-discussion'


@pytest.mark.parametrize('mutation',['new_number','metadata_number','unknown_source','citation','extra_section','duplicate_id','references'])
def test_output_rejects_unbound_or_changed_frozen_material(mutation):
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen();result=output(snapshot);paragraph=result['sections'][4]['paragraphs'][0]
    if mutation=='new_number': paragraph['text']='n = 999'
    if mutation=='metadata_number':
        snapshot['base_snapshot']['sources'][0]['content']['setup_revision']=999
        paragraph.update(text='n = 999',source_ids=['stats'],numeric_bindings=[{'value':'999','source_id':'stats'}])
    if mutation=='unknown_source': paragraph['source_ids']=['unknown']
    if mutation=='citation': paragraph['citations']=[{'status':'supported'}]
    if mutation=='extra_section': result['sections'].append(deepcopy(result['sections'][4]))
    if mutation=='duplicate_id': result['sections'][3]['paragraphs'][0]['id']=paragraph['id']
    if mutation=='references': result['sections'][6]['paragraphs']=[deepcopy(paragraph)]
    with pytest.raises(ValueError): compose_candidate(result,snapshot)


def test_numbers_require_binding_to_actual_statistics_not_prose():
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen();result=output(snapshot);paragraph=result['sections'][3]['paragraphs'][0]
    paragraph.update(text='n = 12; P = 0.05',source_ids=['stats'],numeric_bindings=[{'value':'12','source_id':'stats'},{'value':'0.05','source_id':'stats'}])
    assert compose_candidate(result,snapshot)['sections'][3]['paragraphs'][0]['origin']=='model_generated'


def test_response_rejects_duplicate_keys_and_noncompleted():
    from app.domain.manuscript_writing.execution import parse_response
    response={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"sections":[],"sections":[]}'}]}]}
    with pytest.raises(ValueError): parse_response(response,frozen())


def test_request_target_gate():
    from app.domain.manuscript_writing.contracts import WritingRequest
    with pytest.raises(ValueError): WritingRequest(base_revision=1,mode='rewrite_section',instructions='Rewrite')
    with pytest.raises(ValueError): WritingRequest(base_revision=1,mode='full_draft',target_section='discussion')


def test_title_can_be_refined_with_a_single_traceable_paragraph():
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen();result=output(snapshot)
    result['sections'][0]['paragraphs'][0]['text']='Refined cautious title'
    assert compose_candidate(result,snapshot)['title']=='Refined cautious title'


def test_one_to_one_rewrite_cannot_replace_stable_paragraph_identity():
    from app.domain.manuscript_writing.context import compose_candidate,normalize_sections
    snapshot=frozen('rewrite_section','discussion');snapshot['base_snapshot']['sections']=normalize_sections(snapshot['base_snapshot'])
    snapshot['base_snapshot']['sections'][4]['paragraphs']=[dict(id='stable',text='Previous',origin='user_provided',source_ids=[],citations=[])]
    with pytest.raises(ValueError): compose_candidate(output(snapshot),snapshot)


def test_unreviewed_reworded_citation_text_cannot_keep_saved_support():
    from app.domain.manuscript_writing.context import compose_candidate,normalize_sections
    snapshot=frozen('rewrite_section','discussion');snapshot['base_snapshot']['sections']=normalize_sections(snapshot['base_snapshot'])
    original=dict(id='stable',text='Reviewed wording',origin='literature',source_ids=[],citations=[{'status':'supported','id':'review'}])
    snapshot['base_snapshot']['sections'][4]['paragraphs']=[original]
    result=output(snapshot);paragraph=result['sections'][0]['paragraphs'][0]
    paragraph.update(id='stable',text='Reworded claim',citations=original['citations'])
    with pytest.raises(ValueError): compose_candidate(result,snapshot)
    paragraph['citations']=[];paragraph['source_ids']=['stats']
    assert compose_candidate(result,snapshot)['sections'][4]['paragraphs'][0]['origin']=='model_generated'


def test_rewrite_preserves_base_keywords_and_acknowledgements():
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen('rewrite_section','discussion');snapshot['base_snapshot'].update(keywords=['Confirmed'],acknowledgements='Provided thanks')
    candidate=compose_candidate(output(snapshot),snapshot)
    assert candidate['keywords']==['Confirmed'] and candidate['acknowledgements']=='Provided thanks'


@pytest.mark.parametrize('language,text',[('en','Frozen reviewed finding (1)'),('zh-CN','已核验文献原句 (1)')])
def test_exact_reviewed_literature_can_move_to_introduction_with_binding(language,text):
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen();base=snapshot['base_snapshot'];base['output_language']=language
    binding={'review_id':'review','project_reference_id':'ref','metadata_version_id':'metadata','metadata':{'title':'Frozen'}}
    base['references']=[{'number':1,'project_reference_id':'ref','text':'Frozen reference'}]
    base['citation_snapshot']={'output':{'paragraphs':[{'id':'p','text':text}]},'paragraphs':[{'id':'p','fragments':[{'kind':'claim','text':text,'bindings':[binding]}]}]}
    result=output(snapshot)
    result['sections'][2]['paragraphs']=[dict(id='literature:p',text=text,source_ids=[],citations=[binding],numeric_bindings=[])]
    candidate=compose_candidate(result,snapshot)
    assert candidate['sections'][2]['paragraphs'][0]['citations']==[binding]
    assert candidate['references']==base['references']


def test_orphan_reference_is_removed_from_full_candidate():
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen();snapshot['base_snapshot']['references']=[{'number':1,'project_reference_id':'unused','text':'Unused reference'}]
    candidate=compose_candidate(output(snapshot),snapshot)
    assert candidate['references']==[] and candidate['sections'][6]['paragraphs']==[]


def test_substantive_introduction_requires_frozen_source_trace():
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen();result=output(snapshot)
    result['sections'][2]['paragraphs'][0]['text']='The intervention improves outcomes.'
    with pytest.raises(ValueError): compose_candidate(result,snapshot)


def test_reference_numbering_gaps_fail_closed():
    from app.domain.manuscript_writing.context import compose_candidate,WritingCitationScopeError
    snapshot=frozen();base=snapshot['base_snapshot']
    binding={'review_id':'review','project_reference_id':'ref','metadata_version_id':'metadata'}
    base['references']=[{'number':2,'project_reference_id':'ref','text':'Frozen reference'}]
    base['citation_snapshot']={'output':{'paragraphs':[{'id':'p','text':'Reviewed (2)'}]},'paragraphs':[{'id':'p','fragments':[{'kind':'claim','bindings':[binding]}]}]}
    result=output(snapshot);result['sections'][2]['paragraphs']=[dict(id='literature:p',text='Reviewed (2)',source_ids=[],citations=[binding],numeric_bindings=[])]
    with pytest.raises(WritingCitationScopeError): compose_candidate(result,snapshot)


def test_candidate_notice_replaces_only_legacy_two_section_scope_issue():
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen();snapshot['base_snapshot']['issues'].append({'id':'scope','kind':'limitation','message':'Only two sections'})
    candidate=compose_candidate(output(snapshot),snapshot)
    assert candidate['issues'][0]==snapshot['base_snapshot']['issues'][0]
    assert 'Only two sections' not in str(candidate['issues'])
    assert 'seven SCI sections' in candidate['notice']


@pytest.mark.parametrize('text',['样本量999','纳入9例','均值999.25','P值0.009','p<1e-05','效应量-2.5e-05','n999'])
def test_adjacent_unbound_numeric_assertions_are_rejected(text):
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen();result=output(snapshot)
    result['sections'][3]['paragraphs'][0].update(text=text,source_ids=['stats'])
    with pytest.raises(ValueError,match='Every numeric expression'):
        compose_candidate(result,snapshot)


@pytest.mark.parametrize('text,value',[
    ('样本量12例','12'),('P值0.05','0.05'),('p<0.05','0.05'),
    ('p=1e-05','1e-05'),('P值1e-05','1e-05'),('均值0.05','0.05'),('效应量-2.5e-05','-2.5e-05'),
])
def test_bound_chinese_p_values_and_scientific_notation_keep_exact_tokens(text,value):
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen();snapshot['base_snapshot']['sources'][0]['content']['statistics']['effect']=float(value)
    result=output(snapshot)
    result['sections'][3]['paragraphs'][0].update(text=text,source_ids=['stats'],numeric_bindings=[{'value':value,'source_id':'stats'}])
    assert compose_candidate(result,snapshot)['sections'][3]['paragraphs'][0]['text']==text


def test_exact_frozen_paragraph_with_adjacent_numbers_keeps_original_provenance():
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen()
    original=dict(id='result:stable',text='样本量999，p=1e-05；IL6已测量。',origin='computed_result',source_ids=['stats'],citations=[])
    snapshot['base_snapshot']['results_groups']=[dict(id='group',paragraphs=[original])]
    result=output(snapshot);result['sections'][3]['paragraphs']=[deepcopy(original)]
    assert compose_candidate(result,snapshot)['sections'][3]['paragraphs']==[original]


@pytest.mark.parametrize('text,value',[('The sample size was 12.','12'),('P = 0.05.','0.05'),('P = 1e-05.','1e-05')])
def test_sentence_period_is_not_part_of_a_bound_numeric_value(text,value):
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen();snapshot['base_snapshot']['sources'][0]['content']['statistics']['effect']=float(value)
    result=output(snapshot)
    result['sections'][3]['paragraphs'][0].update(text=text,source_ids=['stats'],numeric_bindings=[{'value':value,'source_id':'stats'}])
    assert compose_candidate(result,snapshot)['sections'][3]['paragraphs'][0]['text']==text


def test_numeric_tokens_keep_leading_decimal_and_scientific_notation():
    from app.domain.manuscript_writing.context import NUMBER
    assert NUMBER.findall('n=12. P=.5; x=-.5e-3; y=+1.2E+4.')==['12','.5','-.5e-3','+1.2E+4']
