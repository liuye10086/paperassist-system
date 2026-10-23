from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile
import json

from lxml import etree as E
import pytest
from PIL import Image

from app.domain.literature.service import digest
from tests.domain.test_thesis_chapters import school

NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W='{'+NS['w']+'}'
TEMPLATE='9de691486c50471b124fd4378d09b9b5f45d81404ad8108e91f3116520b974fa'


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def fixture():
    value=school();context=value['thesis_context']
    def section(number,end,fmt,start=None,linked=False):
        return dict(id='section-'+str(number),page=dict(width_cm=21,height_cm=29.7,margin_top_cm=2.5,margin_bottom_cm=2,margin_left_cm=2.5,margin_right_cm=2),source=dict(part='word/document.xml',path=f'/w:document/w:body/w:p[{end}]/w:pPr/w:sectPr',text='section'),page_number=dict(format=fmt,start=start,mode='restart' if start else 'continue_or_default'),break_type=None,different_first_page=False,different_odd_even_pages=False,
            headers=[dict(type='default',text='School header',fields=[],linked_to_previous=linked)],footers=[dict(type='default',text='',fields=['PAGE'],linked_to_previous=linked)])
    sections=[section(1,2,'upperRoman'),section(2,20,'upperRoman','1'),section(3,500,'decimal','1')]
    sections[0]['different_first_page']=True
    analysis=dict(parser_version='school-template-v1',sections=sections,chapters=[dict(id=c['id'],title=c['title'],level=c['level'],source=dict(part='word/document.xml',path=f'/w:document/w:body/w:p[{5 if c["purpose"]=="manual" else 30+index} ]'.replace(' ]',']'),text=c['title'])) for index,c in enumerate(context['chapters'])],
        notes=[dict(id='latin',text='（文中的英文一律采用“Times New Roman”字体）',source=dict(part='word/document.xml',path='/w:body/w:p[54]',text='英文要求')),
               dict(id='line',text='一级标题：所有文字都是黑体黑体，三号字，居中，行间距：1.5倍行距',source=dict(part='word/document.xml',path='/w:body/w:p[94]',text='一级标题要求')),
               dict(id='footnote',text='凡正文引用他人观点，要在当页进行脚注标注，所有参考文献标注序号顺序为[1][2][3]',source=dict(part='word/document.xml',path='/w:body/w:p[242]',text='脚注规范')),
               dict(id='labels',text='图表编号对应章节号，第4章的图表从4.1开始编',source=dict(part='word/document.xml',path='/w:body/w:p[121]',text='章号图表'))],raw_styles=[],defaults={})
    rules=[]
    for category in ('body','heading1','heading2','heading3','figure_caption','table_caption','abstract_heading_zh','abstract_heading_en','references_heading','acknowledgements_heading','title_zh','title_en','toc_heading','keywords_zh','keywords_en'):
        for key,v in dict(font_east_asia='宋体' if category=='body' else '黑体',font_latin='宋体',font_size_pt=12 if category=='body' else 16,line_spacing='440' if category=='body' else '240',line_rule='exact' if category=='body' else 'auto',alignment='both' if category=='body' else 'center').items():
            rules.append(dict(id=category+'.'+key,category=category,value=v,source=dict(part='word/document.xml',path='/p/'+category,text='fixed style')))
    context['confirmation']['rules']=rules
    context['confirmation']['analysis_sha256']=digest(analysis)
    context['source_files'][0]['sha256']=TEMPLATE
    context['confirmation_sha256']=digest(context['confirmation'])
    value['sections'][4]['title']=context['chapters'][4]['title']='4 Observed findings'
    context['confirmation']['chapters'][4]['title']='4 Observed findings'
    context['confirmation_sha256']=digest(context['confirmation'])
    return value,analysis


def plan(value,analysis,**options):
    from app.domain.manuscripts.school_export import compile_school_export
    defaults=dict(manual_fields={},manual_chapters=[],english_title='',keywords=[],include_toc=True,toc_depth=3)
    return compile_school_export(value,analysis,defaults|options)


def parts(raw):
    with ZipFile(BytesIO(raw)) as z:return {n:z.read(n) for n in z.namelist()}


def text(raw):
    return ''.join(E.fromstring(parts(raw)['word/document.xml']).xpath('//w:t/text()',namespaces=NS))


def test_plan_retains_fixed_sources_and_user_text_decisions_without_mutating_manuscript():
    value,analysis=fixture();original=deepcopy(value)
    p=plan(value,analysis)
    assert value==original
    assert p['analysis_sha256']==digest(analysis) and p['snapshot_sha256']==digest(value)
    assert p['styles']['body']['font_latin']=='Times New Roman'
    assert p['styles']['heading1']['line_spacing']=='360'
    assert len(p['rule_decisions'])==2
    assert p['report']['scientifically_verified'] is False
    assert any(i['kind']=='manual' for i in p['report']['issues'])


def test_new_source_uses_only_explicit_text_decisions_and_attributes_remain_selectable():
    value,analysis=fixture();context=value['thesis_context'];context['source_files'][0]['sha256']='a'*64
    # A different source SHA never inherits the old template's special decision.
    p=plan(value,analysis)
    assert p['styles']['body']['font_latin']=='宋体' and p['styles']['heading1']['line_spacing']=='240'


def test_explicit_confirmations_preserve_unconflicted_spacing_attributes():
    value,analysis=fixture();context=value['thesis_context']
    analysis['raw_styles']=[dict(id='h1',name='heading 1',based_on=None,properties={'pPr.spacing.beforeLines':'200','pPr.spacing.afterLines':'200'}),dict(id='t',name='Title',based_on=None,properties={'pPr.spacing.beforeLines':'100','pPr.spacing.afterLines':'100'})]
    analysis['notes'].append(dict(id='spacing',text='一级标题段前2行，段后2行。',source={'part':'word/document.xml','path':'/p[1]','text':'原规范'}))
    context['confirmation']['analysis_sha256']=digest(analysis)
    context['confirmation']['text_decisions']=[dict(id='latin_font',choice='text',source_sha256='b'*64,evidence={}),dict(id='heading1_line_spacing',choice='attributes',source_sha256='c'*64,evidence={})]
    context['confirmation_sha256']=digest(context['confirmation'])
    p=plan(value,analysis)
    assert p['styles']['heading1']['space_before_lines']=='200'
    assert p['styles']['title_zh']['space_after_lines']=='100'
    assert not any(i['id']=='school:template-support' for i in p['report']['issues'])
    context['source_files'][0]['sha256']='d'*64
    p=plan(value,analysis)
    assert p['styles']['heading1']['space_before_lines']=='200'
    assert p['styles']['title_zh']['space_after_lines']=='100'
    context['confirmation']['text_decisions']=[dict(id='latin_font',choice='text',source_sha256='b'*64,evidence={}),dict(id='heading1_line_spacing',choice='attributes',source_sha256='c'*64,evidence={})]
    context['confirmation_sha256']=digest(context['confirmation'])
    p=plan(value,analysis)
    assert p['styles']['body']['font_latin']=='Times New Roman' and p['styles']['heading1']['line_spacing']=='240'
    context['source_files'][0]['sha256']=TEMPLATE
    context['confirmation']['text_decisions'][0]['choice']='attributes';context['confirmation_sha256']=digest(context['confirmation'])
    p=plan(value,analysis)
    assert p['styles']['body']['font_latin']=='宋体' and p['styles']['heading1']['line_spacing']=='240'


@pytest.mark.parametrize('mutation',['analysis','chapter','manual'])
def test_plan_rejects_wrong_original_analysis_structure_or_manual_target(mutation):
    value,analysis=fixture();options={}
    if mutation=='analysis':analysis['parser_version']='changed'
    elif mutation=='chapter':value['sections'][2]['title']='changed'
    else:options['manual_chapters']=[dict(chapter_id='outcomes',text='Overwrite research')]
    from app.core.exceptions import StorageError
    with pytest.raises((ValueError,StorageError)):plan(value,analysis,**options)


def test_school_docx_uses_frozen_order_styles_and_explicit_manual_content():
    from app.adapters.manuscript_docx import build_manuscript_docx
    value,analysis=fixture();original=deepcopy(value)
    p=plan(value,analysis,manual_fields={'author':'测试作者'},manual_chapters=[dict(chapter_id='declaration',text='用户自行提供的声明文本\n签名：待填写')])
    raw=build_manuscript_docx(value,{},school_plan=p);content=text(raw)
    assert value==original
    assert '用户自行提供的声明文本' in content and '测试作者' in content
    assert 'SCI论文初稿' not in content and 'SCI manuscript draft' not in content
    positions=[content.index(c['title']) for c in value['thesis_context']['chapters']]
    assert positions==sorted(positions)
    root=E.fromstring(parts(raw)['word/document.xml'])
    assert content.index('Contents')>content.index('Declaration') and content.index('Contents')<content.index('Research context')
    toc=root.xpath('//w:body/w:p[w:r/w:t="Contents"]',namespaces=NS)[0]
    assert toc[0].tag==W+'pPr'
    manual=root.xpath('//w:body/w:p[w:r/w:t="用户自行提供的声明文本"]',namespaces=NS)[0]
    assert not manual.xpath('.//w:br',namespaces=NS)
    assert root.xpath('//w:body/w:p[w:r/w:t="签名：待填写"]',namespaces=NS)
    styles=E.fromstring(parts(raw)['word/styles.xml'])
    normal=styles.xpath('//w:style[@w:styleId="Normal"]',namespaces=NS)[0]
    assert normal.xpath('./w:rPr/w:rFonts/@w:ascii',namespaces=NS)==['Times New Roman']
    assert root.xpath('//w:sectPr/w:pgNumType[@w:fmt="decimal"][@w:start="1"]',namespaces=NS)
    assert root.xpath('//w:sectPr/w:pgNumType[@w:fmt="upperRoman"]',namespaces=NS)
    assert build_manuscript_docx(value,{},school_plan=p)==raw


def test_nested_heading_retains_body_section_without_inheriting_body_indent():
    from app.adapters.manuscript_docx import build_manuscript_docx
    value,analysis=fixture()
    for collection in (value['sections'],value['thesis_context']['chapters'],value['thesis_context']['confirmation']['chapters']):collection[3]['level']=2
    value['thesis_context']['confirmation_sha256']=digest(value['thesis_context']['confirmation'])
    raw=build_manuscript_docx(value,{},school_plan=plan(value,analysis));p=parts(raw)
    root=E.fromstring(p['word/document.xml'])
    assert len(root.xpath('//w:sectPr',namespaces=NS))==8
    styles=E.fromstring(p['word/styles.xml'])
    assert styles.xpath('//w:style[@w:styleId="Heading2"]/w:pPr/w:ind/@w:firstLineChars',namespaces=NS)==['0']


def test_school_soft_breaks_keep_source_bookmark_without_expanding_short_lines():
    from app.adapters.manuscript_docx import build_manuscript_docx
    value,analysis=fixture();item=value['sections'][3]['paragraphs'][0]
    item['text']='A supplied method line.\nShort supplied continuation.'
    original=deepcopy(value)
    raw=build_manuscript_docx(value,{},school_plan=plan(value,analysis));p=parts(raw)
    settings=E.fromstring(p['word/settings.xml'])
    assert settings.xpath('./w:compat/w:doNotExpandShiftReturn[not(@w:val="0")]',namespaces=NS)
    root=E.fromstring(p['word/document.xml'])
    paragraph=root.xpath('//w:body/w:p[w:r/w:t="A supplied method line."]',namespaces=NS)[0]
    assert len(paragraph.xpath('./w:bookmarkStart',namespaces=NS))==1
    assert paragraph.xpath('.//w:br',namespaces=NS)
    assert value==original


def test_figures_tables_and_visible_references_follow_school_chapter_number_once():
    from app.adapters.manuscript_docx import build_manuscript_docx
    value,analysis=fixture();stream=BytesIO();Image.new('RGB',(40,20),'white').save(stream,format='PNG');png=stream.getvalue()
    group=value['results_groups'][0]
    group['tables']=[dict(id='table-one',number=1,title='Table 1. Actual observations',columns=['n'],rows=[[12]])]
    group['figures']=[dict(id='fig-one',number=1,title='Actual figure',caption='Provided caption',panels=[],sha256=sha256(png).hexdigest(),source_ids=['run'])]
    value['sections'][4]['paragraphs'].append(dict(id='table-ref',origin='user',text='See Table 1 and Figure 1.',source_ids=[],citations=[],numeric_bindings=[]))
    p=plan(value,analysis);raw=build_manuscript_docx(value,{'fig-one':png},school_plan=p);content=text(raw)
    assert 'Table 4.1' in content and 'Figure 4.1' in content
    assert 'See Table 4.1 and Figure 4.1.' in content
    assert content.count('Actual observations')==1 and content.count('Actual figure')==1
    assert 'Table 4.1  Actual observations' in content
    root=E.fromstring(parts(raw)['word/document.xml'])
    image_paragraph=root.xpath('//w:drawing/ancestor::w:p',namespaces=NS)[0]
    assert image_paragraph.xpath('./w:pPr/w:spacing/@w:lineRule',namespaces=NS)==['auto']
    assert group['figures'][0]['number']==1
    assert any(sha256(b).digest()==sha256(png).digest() for n,b in parts(raw).items() if n.startswith('word/media/'))


def test_numbering_continues_across_result_subsections_of_one_chapter():
    value,analysis=fixture()
    first=value['results_groups'][0];first['figures']=[dict(id='figure-a',number=1)]
    second=deepcopy(first);second.update(id='second',figures=[dict(id='figure-b',number=2)])
    value['results_groups'].append(second)
    for collection in (value['sections'],value['thesis_context']['chapters']):
        collection[3].update(title='4.1 First observations',purpose='results',level=2,result_group_ids=['evidence'])
        collection[4].update(title='4.2 Other observations',purpose='results',level=2,result_group_ids=['second'])
    for index in (3,4):
        value['thesis_context']['confirmation']['chapters'][index].update({k:value['sections'][index][k] for k in ('title','level')})
    value['thesis_context']['confirmation_sha256']=digest(value['thesis_context']['confirmation'])
    p=plan(value,analysis)
    assert p['label_map']['figures']=={'1':'4.1','2':'4.2'}


def test_frozen_citation_is_real_footnote_with_school_bibliography_and_page_restart():
    from app.adapters.manuscript_docx import build_manuscript_docx
    value,analysis=fixture();value['references']=[dict(number=1,project_reference_id='ref',text='Verified citation source')]
    value['sections'][1]['paragraphs']=[dict(id='reference:1',origin='literature',text='Verified citation source',source_ids=[],citations=[],numeric_bindings=[])]
    value['sections'][2]['paragraphs']=[dict(id='lit',origin='literature',text='Reviewed finding [1].',citations=[dict(project_reference_id='ref')],source_ids=[],numeric_bindings=[])]
    raw=build_manuscript_docx(value,{},school_plan=plan(value,analysis));p=parts(raw)
    footnotes=E.fromstring(p['word/footnotes.xml'])
    assert footnotes.xpath('count(//w:footnote[@w:id="1"])',namespaces=NS)==1
    assert 'Verified citation source' in ''.join(footnotes.xpath('//w:t/text()',namespaces=NS))
    assert E.fromstring(p['word/document.xml']).xpath('//w:footnoteReference[@w:id="1"]',namespaces=NS)
    paragraph=E.fromstring(p['word/document.xml']).xpath('//w:footnoteReference[@w:id="1"]/../..',namespaces=NS)[0]
    assert paragraph[-1].tag==W+'bookmarkEnd'
    assert E.fromstring(p['word/settings.xml']).xpath('//w:footnotePr/w:numRestart[@w:val="eachPage"]',namespaces=NS)
    sections=E.fromstring(p['word/document.xml']).xpath('//w:sectPr',namespaces=NS)
    assert all(s.xpath('./w:footnotePr/w:numRestart[@w:val="eachPage"]',namespaces=NS) for s in sections)
    assert '[1] Verified citation source' in text(raw)


def test_actual_field_cache_is_required_and_receipt_never_claims_word_acceptance(monkeypatch):
    from app.adapters.manuscript_docx import build_manuscript_docx
    from app.adapters.school_docx import complete_school_fields
    from app.core.exceptions import StorageError
    value,analysis=fixture();p=plan(value,analysis);raw=build_manuscript_docx(value,{},school_plan=p)
    monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields',lambda content:dict(source_sha256='wrong',fields={},toc_lines=[]))
    with pytest.raises(StorageError):complete_school_fields(raw,p)
    def actual(content):
        files=parts(content);manifest=json.loads(E.fromstring(files['customXml/paperassist-layout.xml']).text)
        return dict(source_sha256=sha256(content).hexdigest(),fields={},toc_lines=['Frozen chapter\t1' for _ in manifest['toc_targets']])
    monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields',actual)
    completed,receipt=complete_school_fields(raw,p)
    assert receipt['status']=='updated' and receipt['software']=='LibreOffice'
    assert receipt['word_verified'] is False and receipt['page_count'] is None
    assert receipt['toc_entries']>0 and 'Frozen chapter' in text(completed)


def test_no_toc_does_not_invent_renderer_result_or_call_converter(monkeypatch):
    from app.adapters.manuscript_docx import build_manuscript_docx
    from app.adapters.school_docx import complete_school_fields
    value,analysis=fixture();p=plan(value,analysis,include_toc=False);raw=build_manuscript_docx(value,{},school_plan=p)
    def forbidden(*args,**kwargs):raise AssertionError('no directory conversion requested')
    monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields',forbidden)
    completed,receipt=complete_school_fields(raw,p)
    assert completed==raw and receipt['status']=='not_requested'
