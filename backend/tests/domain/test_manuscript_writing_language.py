from copy import deepcopy
import pytest
from app.domain.literature.service import digest
from app.domain.manuscript_writing.language import inventory,validate_decisions,prepare_candidate,editable_fields
from tests.adapters.test_manuscript_full_docx import full_sample


def decisions(items):
    return dict(inventory_sha256=digest(items),decisions=[dict(location=i['location'],content_sha256=i['content_sha256'],decision='target_language',reason='Exact manual check',exceptions=[]) for i in items])


def test_inventory_contains_every_actual_export_text_including_tables_appendix_and_header():
    candidate,images=full_sample()
    items=inventory(candidate,images,[])
    texts=[i['text'] for i in items]
    for token in ('CAPTION-SENTINEL','PANEL-SENTINEL','ETHICS-MISSING-SENTINEL','SAMPLES-CONFLICT-SENTINEL','5.24','USER-ACKNOWLEDGEMENT','user keyword','SCI manuscript draft','Author A.'):
        assert any(token in text for text in texts),token
    assert len({i['location'] for i in items})==len(items)


@pytest.mark.parametrize('place',['column','cell','caption','group'])
def test_only_body_language_success_cannot_hide_mismatched_export_text(place):
    candidate,images=full_sample()
    group=candidate['results_groups'][0]
    if place=='column': group['tables'][0]['columns'][0]='样本量'
    elif place=='cell': group['tables'][0]['rows'][0][0]='均值'
    elif place=='caption': group['figures'][0]['caption']='中文图注'
    else: group['title']='中文分组'
    items=inventory(candidate,images,[])
    with pytest.raises(ValueError,match='non-target'):validate_decisions(items,decisions(items),'en')


def test_image_unknown_and_asset_hash_drift_are_not_approved_by_body_decisions():
    item=dict(location='image:x',kind='image',asset_sha256='a'*64,content_sha256=digest('image'),text='',language_known=False,no_text=False)
    with pytest.raises(ValueError,match='Unknown external'): validate_decisions([item],decisions([item]),'en')
    item['language_known']=True;body=decisions([item]);item['asset_sha256']='b'*64
    with pytest.raises(ValueError,match='inventory changed'): validate_decisions([item],body,'en')


def test_exceptions_are_local_with_reason_and_never_whole_prose():
    item=dict(location='x',kind='export_text',text='使用 mg 测量。',content_sha256=digest('使用 mg 测量。'))
    body=decisions([item])
    with pytest.raises(ValueError):validate_decisions([item],body,'zh-CN')
    body['decisions'][0]['exceptions']=[dict(start=3,end=5,kind='unit',reason='SI unit symbol remains exact')]
    validate_decisions([item],body,'zh-CN')
    body['decisions'][0]['exceptions'][0]['reason']=' '
    with pytest.raises(ValueError): validate_decisions([item],body,'zh-CN')
    text='An entire foreign paragraph with many unsupported words in it.'
    item.update(text=text,content_sha256=digest(text));body=decisions([item]);body['decisions'][0]['exceptions']=[dict(start=0,end=len(text),kind='proper_name',reason='Whole paragraph')]
    with pytest.raises(ValueError):validate_decisions([item],body,'zh-CN')


def test_table_translation_preserves_exact_numbers_and_scientific_body():
    candidate,_=full_sample();original=deepcopy(candidate)
    field=next(f for f in editable_fields(candidate) if '/columns/0' in f['path'])
    edit=dict(path=field['path'],original_sha256=field['original_sha256'],text='目标标签',reason='Explicit translation')
    changed=prepare_candidate(candidate,dict(edits=[edit]))
    assert candidate==original and changed['sections']==candidate['sections']
    field=next(f for f in editable_fields(candidate) if '/tables/0/title' in f['path'])
    edit.update(path=field['path'],original_sha256=field['original_sha256'],text='Table 987 changed')
    with pytest.raises(ValueError,match='numerical'):prepare_candidate(candidate,dict(edits=[edit]))


def test_short_scientific_paragraph_cannot_be_exempted_wholesale_or_in_chunks():
    candidate,images=full_sample();candidate['sections'][2]['paragraphs'][0]['text']='中文结果'
    items=inventory(candidate,images,[]);body=decisions(items)
    index=next(i for i,v in enumerate(items) if v['text']=='中文结果')
    for exceptions in ([dict(start=0,end=4,kind='proper_name',reason='Bad blanket')], [dict(start=0,end=2,kind='proper_name',reason='Bad chunk'),dict(start=2,end=4,kind='proper_name',reason='Bad chunk')]):
        body['decisions'][index]['exceptions']=exceptions
        with pytest.raises(ValueError,match='Whole prose'): validate_decisions(items,body,'en')

@pytest.mark.parametrize('place',['caption','panel','notice','issue'])
@pytest.mark.parametrize('split',[False,True])
def test_narrative_display_text_cannot_be_fully_exempted(place,split):
    candidate,images=full_sample();text='实验结果显著提高'
    if place=='caption': candidate['results_groups'][0]['figures'][0]['caption']=text
    elif place=='panel': candidate['results_groups'][0]['figures'][0]['panels'][0]['description']=text
    elif place=='notice': candidate['notice']=text
    else: candidate['issues'][0]['message']=text
    items=inventory(candidate,images,[]);body=decisions(items)
    index=next(i for i,item in enumerate(items) if text in item['text'])
    exact=items[index]['text'];start=exact.index(text);end=start+len(text)
    ranges=[(start,start+4),(start+4,end)] if split else [(start,end)]
    body['decisions'][index]['exceptions']=[dict(start=a,end=b,kind='proper_name',reason='Not a real proper name') for a,b in ranges]
    with pytest.raises(ValueError,match='Whole prose'): validate_decisions(items,body,'en')


def test_short_unit_and_named_label_need_explicit_matching_kind():
    item=dict(location='x',kind='figure_text',scope='label',text='mg',content_sha256=digest('mg'))
    body=decisions([item]);body['decisions'][0]['exceptions']=[dict(start=0,end=2,kind='unit',reason='Exact unit symbol')]
    validate_decisions([item],body,'zh-CN')
    item.update(scope='narrative',text='实验结论',content_sha256=digest('实验结论'));body=decisions([item])
    body['decisions'][0]['exceptions']=[dict(start=0,end=4,kind='unit',reason='Not a unit')]
    with pytest.raises(ValueError): validate_decisions([item],body,'en')


def test_actual_reference_metadata_remains_locally_reviewable_but_not_blanket():
    import re
    candidate,images=full_sample()
    reference=next(item for item in inventory(candidate,images,[]) if item['text'].startswith('(1) Author A.'))
    body=decisions([reference])
    body['decisions'][0]['exceptions']=[dict(start=m.start(),end=m.end(),kind='reference_metadata',reason='Verified original bibliographic metadata') for m in re.finditer(r'[A-Za-z][A-Za-z ]*',reference['text'])]
    validate_decisions([reference],body,'zh-CN')
    body['decisions'][0]['exceptions']=[dict(start=0,end=len(reference['text']),kind='reference_metadata',reason='Blanket reference exception')]
    with pytest.raises(ValueError):validate_decisions([reference],body,'zh-CN')
    forged=dict(reference,scope='narrative',narrative_ranges=[[0,len(reference['text'])]])
    with pytest.raises(ValueError):validate_decisions([forged],decisions([forged])|{'decisions':body['decisions']},'zh-CN')


@pytest.mark.parametrize('overlap',['title','caption'])
def test_actual_bibliography_position_wins_over_unrelated_narrative_substrings(overlap):
    candidate,images=full_sample()
    if overlap=='title':
        candidate['title']='Synthetic study';candidate['sections'][0]['paragraphs'][0]['text']=candidate['title']
    else:candidate['results_groups'][0]['figures'][0]['caption']='Synthetic study'
    candidate['references'][0]['text']='张三. Synthetic study. Journal.'
    item=next(item for item in inventory(candidate,images,[]) if item['text'].startswith('(1) 张三'))
    body=decisions([item]);body['decisions'][0]['exceptions']=[dict(start=4,end=6,kind='reference_metadata',reason='Verified original author name')]
    validate_decisions([item],body,'en')
    assert item['scope']=='reference_metadata' and item['narrative_ranges']==[]


def test_body_identical_to_reference_is_not_bibliographic_metadata():
    candidate,images=full_sample();candidate['references'][0]['text']='张三. Synthetic study. Journal.'
    text='(1) '+candidate['references'][0]['text']
    candidate['sections'][2]['paragraphs'][0]['text']=text
    matches=[item for item in inventory(candidate,images,[]) if item['text']==text]
    assert len(matches)==2
    assert [item['scope'] for item in matches]==['narrative','reference_metadata']
    for item in matches:
        body=decisions([item]);body['decisions'][0]['exceptions']=[dict(start=4,end=6,kind='reference_metadata',reason='Author metadata only at the actual reference position')]
        if item['scope']=='narrative':
            with pytest.raises(ValueError,match='actual reference'):validate_decisions([item],body,'en')
        else:validate_decisions([item],body,'en')
