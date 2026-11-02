from copy import deepcopy
import pytest
from pydantic import ValidationError
from app.domain.manuscripts.presentation_contracts import PresentationRequest
from app.domain.manuscripts.presentation import build_preview

def sample():
    def snap(lang,text):
        return dict(output_language=lang,title='Example',methods=[dict(id='p1',text=text,source_ids=['s1'],citations=[])],results_groups=[],references=[])
    request=PresentationRequest(base_version_id='zh',peer_version_id='en',config=dict(paragraph_groups=[dict(id='g',zh_ids=['p1'],en_ids=['p1'])]))
    return request,snap('zh-CN','浓度 5 mg，上升，NA。'),snap('en','Concentration 5 mg increased, NA.')

def checks(result):return {c['code']:c['status'] for c in result['checks']}

def test_pairing_preserves_frozen_text_and_detects_numeric_units_na_direction_and_sources():
    request,zh,en=sample();original=deepcopy(zh)
    result=build_preview(request,zh,en,'a'*64,'b'*64)
    assert checks(result)['group:g:numbers']=='passed'
    assert checks(result)['group:g:source_identity']=='passed'
    assert result['quality']['scientific_semantic']=='pending' and zh==original
    en['methods'][0].update(text='Concentration 6 μg decreased.',source_ids=['other'])
    result=build_preview(request,zh,en,'a'*64,'b'*64)
    for key in ('numbers','units','na','direction','source_identity'):assert checks(result)['group:g:'+key]=='conflict'

def test_one_to_many_missing_duplicate_and_citation_identity_reordering():
    request,zh,en=sample();en['methods']=[dict(id='e1',text='5 mg increased [9].',source_ids=['s1'],citations=[dict(project_reference_id='r1',number=9)]),dict(id='e2',text='NA.',source_ids=[],citations=[])]
    zh['methods'][0]['citations']=[dict(project_reference_id='r1',number=1)]
    for snapshot,paragraph in ((zh,zh['methods'][0]),(en,en['methods'][0])):
        plain=paragraph['text'].replace(' [9]','')
        snapshot['citation_snapshot']=dict(paragraphs=[dict(id='p1',fragments=[dict(kind='claim',text=plain,bindings=paragraph['citations'])])],output=dict(paragraphs=[dict(id='p1',text=paragraph['text'])]))
    request.config.paragraph_groups[0].en_ids=['e1','e2']
    result=build_preview(request,zh,en,'a'*64,'b'*64)
    assert checks(result)['group:g:citation_identity']=='passed'
    assert checks(result)['group:g:numbers']=='passed'
    request.config.paragraph_groups[0].zh_ids=['p1','p2'];request.config.paragraph_groups[0].en_ids=['e1']
    zh['methods'].append(dict(id='p2',text='',source_ids=[],citations=[]))
    assert build_preview(request,zh,en,'a'*64,'b'*64)['paragraph_groups'][0]['status']=='paired'
    request.config.paragraph_groups[0].en_ids=['missing']
    with pytest.raises(ValueError,match='paragraph'):build_preview(request,zh,en,'a'*64,'b'*64)
    with pytest.raises(ValidationError):PresentationRequest(base_version_id='z',config=dict(paragraph_groups=[dict(id='g',zh_ids=['1','2'],en_ids=['3','4'])]))

def test_declarations_require_real_sources_and_missing_school_material_stays_pending():
    with pytest.raises(ValidationError):PresentationRequest(base_version_id='z',config=dict(statements=[dict(kind='ethics',state='not_applicable')]))
    request,zh,en=sample();result=build_preview(request,zh,en,'a'*64,'b'*64)
    assert checks(result)['statement:ethics']=='pending'
    assert checks(result)['blind:images']=='pending'
    with pytest.raises(ValidationError):PresentationRequest(base_version_id='z',config=dict(authors=[dict(name='A',order=1,affiliation_ids=['missing'],source='provided')]))

def test_school_supplement_fixed_ids_length_scope_and_mandatory_abstracts():
    _,zh,_=sample()
    zh['thesis_context']=dict(chapters=[dict(id='az',purpose='abstract'),dict(id='ae',purpose='abstract'),dict(id='ap',purpose='manual')])
    zh['sections']=[dict(id='az',purpose='abstract',paragraphs=[]),dict(id='ae',purpose='abstract',paragraphs=[]),dict(id='ap',purpose='manual',paragraphs=[])]
    request=PresentationRequest(base_version_id='zh',config=dict(school=dict(supplements=[dict(chapter_id='ap',purpose='appendix',source='')],length_requirements=[dict(kind='minimum',value=10,scope='body',language='zh-CN',unit='characters',source='school'),dict(kind='maximum',value=5,scope='body',language='zh-CN',unit='characters',source='journal')])))
    result=build_preview(request,zh,None,'a'*64,None)
    assert checks(result)['school:supplement:ap']=='pending'
    assert checks(result)['school:length_conflict']=='conflict' and not result['can_export']
    request.config.school.exclude_chapter_ids=['ae']
    with pytest.raises(ValueError,match='abstracts'):build_preview(request,zh,None,'a'*64,None)

def test_terminology_citation_and_source_sha_mismatch_are_explicit():
    request,zh,en=sample()
    request.config=type(request.config).model_validate(dict(paragraph_groups=[dict(id='g',zh_ids=['p1'],en_ids=['p1'])],terminology=[dict(zh='浓度',en='dosage',state='known',source='user glossary')]))
    for snap,sha in ((zh,'a'*64),(en,'b'*64)):snap['sources']=[dict(id='s1',kind='analysis_run',sha256=sha)]
    zh['methods'][0]['citations']=[dict(project_reference_id='r1',number=1)]
    en['methods'][0]['citations']=[dict(project_reference_id='r2',number=1)]
    zh['methods'][0]['numeric_bindings']=[dict(fact_id='s1:/mean',value='5')]
    en['methods'][0]['numeric_bindings']=[dict(fact_id='s1:/median',value='5')]
    result=build_preview(request,zh,en,'a'*64,'b'*64)
    for key in ('term:浓度','citation_identity','source_identity','fact_identity'):assert checks(result)['group:g:'+key]=='conflict'
    assert not result['can_export']

def test_exact_citation_fragments_keep_parenthesized_scientific_number():
    request,zh,en=sample()
    for snapshot,language,count,display_number in ((zh,'zh',1,1),(en,'en',2,9)):
        binding=dict(project_reference_id='r1')
        claim=f'Measurement ({count}) mg'
        text=claim+f' ({display_number})'
        snapshot['methods'][0].update(text=text,citations=[binding])
        snapshot['citation_snapshot']=dict(paragraphs=[dict(id='p1',fragments=[dict(kind='claim',text=claim,bindings=[binding])])],output=dict(paragraphs=[dict(id='p1',text=text)]))
    result=build_preview(request,zh,en,'a'*64,'b'*64)
    assert checks(result)['group:g:numbers']=='conflict'
    en['citation_snapshot']['paragraphs'][0]['fragments'][0]['text']='Measurement (1) mg'
    en['methods'][0]['text']='Measurement (1) mg (9)'
    en['citation_snapshot']['output']['paragraphs'][0]['text']=en['methods'][0]['text']
    assert checks(build_preview(request,zh,en,'a'*64,'b'*64))['group:g:numbers']=='passed'
    en.pop('citation_snapshot')
    assert checks(build_preview(request,zh,en,'a'*64,'b'*64))['group:g:numbers']=='pending'

def school_length_sample():
    chapters=[dict(id='az',purpose='abstract',output_language='zh-CN'),dict(id='ae',purpose='abstract',output_language='en'),dict(id='body',purpose='results',output_language='zh-CN'),dict(id='omit',purpose='discussion',output_language='zh-CN'),dict(id='manual',purpose='manual',output_language='zh-CN')]
    texts=['甲乙','English abstract text','结果','排除后不应进入本次篇幅计数','人工内容待补充']
    sections=[dict(c,paragraphs=[dict(id='school:'+c['id']+(':'+ 'pending' if c['id']=='manual' else ':p'),text=text,source_ids=[],citations=[])]) for c,text in zip(chapters,texts)]
    return dict(title='工程稿',output_language='zh-CN',thesis_context=dict(chapters=chapters),sections=sections,results_groups=[],references=[])

def test_school_lengths_use_each_fixed_chapter_language_selection_and_manual_text():
    snapshot=school_length_sample()
    requirements=[dict(kind='maximum',value=2,scope='abstract',language='zh-CN',unit='characters',source='school'),dict(kind='maximum',value=3,scope='abstract',language='en',unit='words',source='school'),dict(kind='maximum',value=2,scope='body',language='zh-CN',unit='characters',source='school'),dict(kind='minimum',value=10,scope='whole',language='zh-CN',unit='characters',source='school')]
    request=PresentationRequest(base_version_id='zh',config=dict(school=dict(exclude_chapter_ids=['omit'],options=dict(manual_chapters=[dict(chapter_id='manual',text='真实附录文本')]),length_requirements=requirements)))
    result=build_preview(request,snapshot,None,'a'*64,None)
    items={c['code']:c for c in result['checks']}
    for i,count in ((0,2),(1,3),(2,2)):
        assert items['school:length:'+str(i)]['status']=='passed'
        assert items['school:length:'+str(i)]['actual']==count
    whole=items['school:length:3']
    assert whole['status']=='pending' and whole['actual']==10
    assert whole['count_projection']['chapter_ids']==['az','body','manual']
    assert whole['count_projection']['manual_chapter_ids']==['manual']
    assert 'authors' in whole['count_projection']['excluded_components']
    assert result['can_export'] is True
    request.config.school.include_chapter_ids=['az','ae','body','manual'];request.config.school.exclude_chapter_ids=[]
    assert checks(build_preview(request,snapshot,None,'a'*64,None))['school:length:2']=='passed'
    snapshot['sections'][2]['paragraphs'][0]['text']='结果 ABC'
    request.config.school.length_requirements=[type(request.config.school.length_requirements[0]).model_validate(dict(kind='maximum',value=3,scope='body',language='zh-CN',unit='words',source='school'))]
    item=next(c for c in build_preview(request,snapshot,None,'a'*64,None)['checks'] if c['code']=='school:length:0')
    assert item['actual']==3 and item['status']=='passed'
    assert item['count_projection']['count_method']=='zh_hanzi_latin_words'

def test_school_supplement_pending_placeholder_never_becomes_supplied_by_source():
    snapshot=school_length_sample()
    request=PresentationRequest(base_version_id='zh',config=dict(school=dict(supplements=[dict(chapter_id='manual',purpose='appendix',source='user-provided source')],options=dict(manual_chapters=[dict(chapter_id='manual',text='   ')]))))
    assert checks(build_preview(request,snapshot,None,'a'*64,None))['school:supplement:manual']=='pending'
    request.config.school.options.manual_chapters[0].text='真实人工附录'
    assert checks(build_preview(request,snapshot,None,'a'*64,None))['school:supplement:manual']=='passed'
    request.config.school.options.manual_chapters=[]
    snapshot['sections'][-1]['paragraphs'][0].update(id='school:manual:user',text='已提供的真实章节')
    assert checks(build_preview(request,snapshot,None,'a'*64,None))['school:supplement:manual']=='passed'

def test_actual_language_confirmation_reuses_exact_item_and_no_whole_prose_exemption():
    from app.domain.manuscripts.presentation import validate_language_confirmation
    from app.domain.manuscripts.presentation_contracts import PresentationLanguageReview
    from app.domain.literature.service import digest
    text='使用 mg 测量。'
    items=[dict(location='actual:1',kind='export_text',text=text,content_sha256=digest(text),target_language='zh-CN',scope='narrative',narrative_ranges=[[0,len(text)]],protected_identity=False),dict(location='actual:author',kind='export_text',text='Author A',content_sha256=digest('Author A'),target_language='zh-CN',protected_identity=True)]
    review=PresentationLanguageReview(source_export_id='source',source_sha256='a'*64,language_view='zh-CN',review_mode='identified',decisions=[dict(location='actual:1',content_sha256=items[0]['content_sha256'],decision='target_language',reason='人工逐项核对',exceptions=[dict(start=3,end=5,kind='unit',reason='SI单位')]),dict(location='actual:author',content_sha256=items[1]['content_sha256'],decision='provided_literal',reason='保留用户真实署名')])
    assert validate_language_confirmation(items,review)['decision_count']==2
    review.decisions[0].exceptions[0].start=0;review.decisions[0].exceptions[0].end=len(text);review.decisions[0].exceptions[0].kind='proper_name'
    with pytest.raises(ValueError):validate_language_confirmation(items,review)
    review.decisions=[]
    with pytest.raises(ValueError):validate_language_confirmation(items,review)
    with pytest.raises(ValidationError):PresentationRequest(base_version_id='z',config=dict(terminology=[dict(zh='甲',en='A',variants=['   '])]))

def test_confirmed_export_receipt_updates_checks_preserves_actual_counts_and_source_inventory():
    from app.domain.manuscripts.presentation_export import confirmed_metadata
    old_item=dict(location='actual:1',verification='pending_manual_review',content_sha256='a'*64)
    requirement=dict(scope='whole',language='en',unit='words',kind='maximum',value=100)
    actual=dict(code='school:length:0',status='passed',actual=25,requirement=requirement,count_projection=dict(scope='actual_docx_main_document'))
    old_checks=[dict(code='language:en',status='pending'),actual]
    prior=dict(binding=dict(id='old'),checks=old_checks,language_inventory=[old_item],blind=dict(known_identity_check='passed'))
    review=dict(source_export_id='source',source_sha256='b'*64,language_view='en',review_mode='identified',decisions=[dict(location='actual:1',content_sha256='a'*64,decision='target_language',reason='Exact human review',exceptions=[])])
    context=dict(binding=dict(id='new'),preview=dict(config=dict(language_review=review),checks=[dict(code='language:actual_export',status='passed'),dict(code='school:length:0',status='pending',requirement=requirement)],quality=dict(scientific_semantic='pending'),language_review=dict(status='confirmed',source_export_id='source',source_sha256='b'*64,inventory_sha256='c'*64,decision_count=1)))
    result=confirmed_metadata(context,prior)
    assert result['binding']==context['binding']
    assert result['checks']==[context['preview']['checks'][0],actual]
    assert result['language_review']['status']=='confirmed' and result['language_review']['source_checks']==old_checks
    assert result['quality']['language_review']=='confirmed_for_exact_output'
    assert result['language_inventory'][0]['verification']=='pending_manual_review'
    assert result['language_inventory'][0]['confirmation']['status']=='confirmed_for_exact_output'
    assert prior['language_inventory']==[old_item] and 'confirmation' not in old_item

def test_bilingual_preview_suppresses_hidden_peer_and_groups_without_visible_zh_anchor():
    from app.domain.manuscripts.presentation_export import preview_view
    def paragraph(identity):return dict(id=identity,text=identity)
    selected=dict(title='zh',output_language='zh-CN',sections=[dict(id='visible',paragraphs=[paragraph('z1'),paragraph('z3')]),dict(id='hidden-zh',paragraphs=[paragraph('z2'),paragraph('z4')])])
    peer=dict(title='en',output_language='en',sections=[dict(id='visible-en',paragraphs=[paragraph('eKeep'),paragraph('eByHidden'),paragraph('eFree')]),dict(id='hidden-en',paragraphs=[paragraph('ePeerHidden')])])
    config=dict(paragraph_groups=[dict(id='partial',zh_ids=['z1','z2'],en_ids=['eKeep'],status='paired'),dict(id='hidden',zh_ids=['z4'],en_ids=['eByHidden'],status='paired')],blind=dict(hidden_chapter_ids=['hidden-zh','hidden-en'],identity_terms=[],exceptions=[]))
    context=dict(selected=dict(snapshot_json=selected),base=dict(snapshot_json=selected),peer=dict(snapshot_json=peer),binding=dict(language_view='zh-CN-en',review_mode='blind'),preview=dict(config=config,checks=[],quality={}))
    result=preview_view(context)
    assert [p['id'] for p in result['preview_paragraphs']]==['z1','eKeep','z3','eFree']
