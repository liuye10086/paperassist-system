"""Synthetic source-bound front matter; no real school/identity acceptance."""
from copy import deepcopy
from io import BytesIO
from os import environ
from pathlib import Path
import sys

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from docx.oxml.ns import qn

from app.core.exceptions import StorageError
from app.domain.literature.service import digest
from tests.adapters.test_school_docx import fixture, plan, parts, text, NS


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def synthetic(label='培养类型', size=18, alignment=WD_ALIGN_PARAGRAPH.CENTER):
    doc=Document();p=doc.add_paragraph(label+'：示例值不能作为本人信息')
    p.alignment=alignment;p.paragraph_format.space_after=Pt(8)
    p.add_run().font.size=Pt(size)
    p.runs[0].font.size=Pt(size)
    doc.add_heading('学位论文独创性声明',1)
    doc.add_paragraph('作者签名：示例签名')
    doc.add_heading('致谢',1)
    doc.add_paragraph('封面')
    stream=BytesIO();doc.save(stream)
    from app.adapters.school_template_parser import inspect_school_template
    return inspect_school_template(stream.getvalue(),'synthetic.docx')


def configured():
    value,analysis=fixture();parsed=synthetic()
    analysis['front_matter_sources']=parsed['front_matter_sources']
    source=analysis['front_matter_sources'][0]['id']
    signature=analysis['front_matter_sources'][2]['id']
    fm=dict(schema_version=1,cover_section_id='section-1',fields=[
        dict(id='degree',label='培养类型',kind='text',required=True,source_id=source,style_source_id=source,section_id='section-1',chapter_id=None),
        dict(id='signature',label='作者签名',kind='signature',required=True,source_id=signature,style_source_id=None,section_id='section-1',chapter_id='declaration')],
        content_requirements=[dict(id='declare',kind='declaration',required=True,chapter_id='declaration',source_id=signature)])
    value['thesis_context']['confirmation']['front_matter']=fm
    value['thesis_context']['confirmation']['analysis_sha256']=digest(analysis)
    value['thesis_context']['confirmation_sha256']=digest(value['thesis_context']['confirmation'])
    return value,analysis,fm


def test_two_synthetic_sources_retain_different_labels_and_styles_and_cover_is_incomplete():
    a=synthetic();b=synthetic('论文类别',14,WD_ALIGN_PARAGRAPH.RIGHT)
    assert a['front_matter_sources'][0]['suggested_label']=='培养类型'
    assert b['front_matter_sources'][0]['suggested_label']=='论文类别'
    assert a['front_matter_sources'][0]['style']['font_size_pt']==18
    assert b['front_matter_sources'][0]['style']['alignment']=='right'
    assert a['front_matter_sources'][0]['style_sources']['font_size_pt']['path']
    assert any(i['id']=='cover_rules' for i in a['missing'])


@pytest.mark.skipif(sys.platform!='linux',reason='Existing fenced parser requires Linux')
def test_existing_linux_isolation_returns_valid_front_source_contract():
    from app.adapters.school_template_process import inspect_school_template_isolated
    from app.adapters.school_template_parser import RESULT_KEYS
    doc=Document();doc.add_paragraph('Synthetic field: never copy example identity');doc.add_heading('Introduction',1)
    stream=BytesIO();doc.save(stream)
    result=inspect_school_template_isolated(stream.getvalue(),'synthetic.docx')
    assert set(result)==RESULT_KEYS
    assert result['front_matter_sources'][0]['suggested_label']=='Synthetic field'


def test_dynamic_required_values_and_signature_remain_missing_with_nonempty_declaration():
    value,analysis,_=configured();before=deepcopy((value,analysis))
    p=plan(value,analysis,manual_chapters=[dict(chapter_id='declaration',text='本人提供的声明正文')],field_values={'degree':'合成学位'})
    ids={i['id'] for i in p['report']['issues']}
    assert p['schema_version']==2
    assert 'school:field:signature' in ids and 'school:field:degree' not in ids
    assert not any(i.startswith('school:manual:') or i.startswith('school:keywords:') for i in ids)
    assert next(i for i in p['report']['issues'] if i['id']=='school:field:signature')['source_evidence']
    assert (value,analysis)==before
    from app.adapters.manuscript_docx import build_manuscript_docx
    from lxml import etree as E
    raw=build_manuscript_docx(value,{},school_plan=p)
    assert '培养类型：合成学位' in text(raw) and '作者签名：待填写' in text(raw)
    assert '示例签名' not in text(raw) and '示例值不能作为本人信息' not in text(raw)
    root=E.fromstring(parts(raw)['word/document.xml'])
    para=root.xpath('//w:body/w:p[w:r/w:t="培养类型：合成学位"]',namespaces=NS)[0]
    assert para.xpath('./w:pPr/w:jc/@w:val',namespaces=NS)==['center']
    assert para.xpath('./w:r/w:rPr/w:sz/@w:val',namespaces=NS)==['36']


@pytest.mark.parametrize('mutation',['source','style','section','chapter','duplicate','unknown_value'])
def test_unfrozen_references_and_unknown_values_are_rejected(mutation):
    value,analysis,fm=configured();options={}
    if mutation=='unknown_value':options['field_values']={'alien':'not accepted'}
    else:
        if mutation=='source':fm['fields'][0]['source_id']='invented'
        if mutation=='style':fm['fields'][0]['style_source_id']='invented'
        if mutation=='section':fm['fields'][0]['section_id']='invented'
        if mutation=='chapter':fm['content_requirements'][0]['chapter_id']='invented'
        if mutation=='duplicate':fm['fields'].append(deepcopy(fm['fields'][0]))
        value['thesis_context']['confirmation_sha256']=digest(value['thesis_context']['confirmation'])
    with pytest.raises((StorageError,ValueError)):plan(value,analysis,**options)


def test_empty_field_contract_does_not_invent_manual_fields_or_keyword_limits():
    value,analysis,fm=configured();fm['fields']=[];fm['content_requirements']=[]
    value['thesis_context']['confirmation_sha256']=digest(value['thesis_context']['confirmation'])
    p=plan(value,analysis)
    assert p['front_matter']['fields']==[]
    assert not any(i['id'].startswith(('school:manual:','school:keywords:','school:manual-chapter:')) for i in p['report']['issues'])


def test_second_template_changes_order_field_names_styles_and_cover_section():
    from app.adapters.manuscript_docx import build_manuscript_docx
    from lxml import etree as E
    value,analysis,fm=configured()
    other=synthetic('论文类别',14,WD_ALIGN_PARAGRAPH.RIGHT)
    analysis['front_matter_sources']=other['front_matter_sources']
    fm['cover_section_id']='section-2'
    fm['fields'][0].update(id='category',label='论文类别')
    fm['fields'].insert(0,dict(id='optional',label='可选联系字段',kind='text',required=False,source_id=fm['fields'][0]['source_id'],style_source_id=None,section_id='section-1',chapter_id=None))
    value['thesis_context']['confirmation']['analysis_sha256']=digest(analysis)
    value['thesis_context']['confirmation_sha256']=digest(value['thesis_context']['confirmation'])
    before=deepcopy(value)
    p=plan(value,analysis,field_values={'category':'合成类别','signature':'用户签名文字'})
    assert p['sections'][0]['id']=='section-2'
    assert not any(i['id']=='school:field:optional' for i in p['report']['issues'])
    raw=build_manuscript_docx(value,{},school_plan=p);content=text(raw)
    assert content.index('可选联系字段：待填写')<content.index('论文类别：合成类别')<content.index('作者签名：用户签名文字')
    root=E.fromstring(parts(raw)['word/document.xml'])
    para=root.xpath('//w:body/w:p[w:r/w:t="论文类别：合成类别"]',namespaces=NS)[0]
    assert para.xpath('./w:pPr/w:jc/@w:val',namespaces=NS)==['right']
    assert para.xpath('./w:r/w:rPr/w:sz/@w:val',namespaces=NS)==['28']
    assert value==before


def test_required_content_missing_and_signature_values_are_separate_checks():
    value,analysis,fm=configured()
    p=plan(value,analysis,field_values={'signature':'手工文字'})
    ids={i['id'] for i in p['report']['issues']}
    assert 'school:required-content:declare' in ids
    assert 'school:signature-review:signature' in ids and 'school:field:signature' not in ids
    fm['content_requirements'][0].update(kind='acknowledgements')
    value['thesis_context']['confirmation_sha256']=digest(value['thesis_context']['confirmation'])
    with pytest.raises(StorageError):plan(value,analysis)


def test_sealed_v2_plan_rejects_page_source_forgery():
    from app.domain.manuscripts.school_export import validate_school_export
    value,analysis,_=configured();p=plan(value,analysis)
    p['front_matter_sections']['section-1']['page']['width_cm']=99
    with pytest.raises(StorageError):validate_school_export(p,value,analysis)


def test_field_target_in_reference_chapter_is_rendered_after_references():
    from app.adapters.manuscript_docx import build_manuscript_docx
    value,analysis,fm=configured();fm['fields'][0]['chapter_id']='bibliography'
    value['thesis_context']['confirmation_sha256']=digest(value['thesis_context']['confirmation'])
    raw=build_manuscript_docx(value,{},school_plan=plan(value,analysis,field_values={'degree':'用户补充'}))
    assert '培养类型：用户补充' in text(raw)


def test_legacy_options_normalization_removes_only_new_empty_default():
    from app.domain.manuscripts.service import ManuscriptService
    value,_=fixture();version={'snapshot_json':value}
    old={'manual_fields':{'author':'','student_id':'','department':'','major':'','class_name':'','supervisor':'','submission_date':''},'manual_chapters':[],'english_title':'','keywords':[],'include_toc':True,'toc_depth':3}
    normalized=ManuscriptService.school_options(None,version,{'school':{}})
    assert normalized==old and 'field_values' not in normalized
    assert normalized['include_toc'] is True and normalized['toc_depth']==3 and 'author' in normalized['manual_fields']
    with pytest.raises(StorageError):ManuscriptService.school_options(None,version,{'school':{'field_values':{'x':'y'}}})


def test_school_options_accept_supplied_acknowledgements_but_not_body_overrides():
    from app.domain.manuscripts.service import ManuscriptService

    value, _ = fixture()
    value['thesis_context']['chapters'].extend([
        {'id': 'thanks', 'purpose': 'acknowledgements'},
        {'id': 'body', 'purpose': 'discussion'},
    ])
    version = {'snapshot_json': value}
    text_option = {'chapter_id': 'thanks', 'text': '感谢公开提供研究材料的各团队。'}
    payload = {'school': {'manual_chapters': [text_option]}}
    assert ManuscriptService.school_options(None, version, payload)['manual_chapters'] == [text_option]
    with pytest.raises(StorageError):
        ManuscriptService.school_options(None, version, {'school': {'manual_chapters': [text_option | {'chapter_id': 'body'}]}})


GS501_PROFILE = 'bsu-gs501-academic-masters-2026'
GS501_TEMPLATE_SHA = '1e9d38b307dbef8c3bf97b85ba5def70eaf7e2dba50cf25da978e007fc907059'


def bsu_material():
    value, analysis, front = configured()
    context = value['thesis_context']
    context['confirmation']['format_profile'] = GS501_PROFILE
    context['source_files'][0]['sha256'] = GS501_TEMPLATE_SHA
    value['output_language'] = 'zh-CN'
    for index, (identity, title, language) in enumerate((('abstract-zh', '摘  要', 'zh-CN'), ('abstract-en', 'ABSTRACT', 'en')), 1):
        chapter = dict(id=identity, title=title, purpose='abstract', output_language=language, level=1, result_group_ids=[])
        context['chapters'].insert(index, chapter)
        value['sections'].insert(index, dict(chapter, paragraphs=[dict(id=identity+':p1', text='English abstract text.' if language=='en' else '中文摘要正文。', citations=[])]))
        analysis['chapters'].append(dict(id=identity,title=title,level=1,source=dict(part='word/document.xml', path='/w:body/w:p[10]', text=title)))
    context['confirmation']['chapters'] = [{k: c[k] for k in ('id','title','level')} for c in context['chapters']]
    value['references'] = [dict(number=1,text='Journal reference.')]
    front['fields'][0].update(kind='identity', label='论文作者')
    committee = deepcopy(front['fields'][0])
    committee.update(id='committee', kind='text', label='答辩委员会', required=False, section_id='section-2')
    analysis['front_matter_sources'].append(dict(id='committee-source', section_id='section-2', suggested_label='答辩委员会', style={}, source=dict(part='word/document.xml', text='答辩委员会')))
    committee.update(source_id='committee-source', style_source_id=None)
    front['fields'].append(committee)
    context['confirmation']['analysis_sha256'] = digest(analysis)
    context['confirmation_sha256'] = digest(context['confirmation'])
    return value, analysis


def test_gs501_format_uses_english_roles_and_live_section_headers():
    from app.adapters.school_docx import build_school_docx, final_school_source_map
    from lxml import etree as E

    value, analysis = bsu_material()
    options = dict(english_title='English thesis title', keywords=[dict(chapter_id='abstract-en', values=['Example','Methods','Results'])])
    planned = plan(value, analysis, **options)
    assert planned['format_profile'] == GS501_PROFILE
    source_map = []
    raw = build_school_docx(value, {}, planned, source_map=source_map)
    package = parts(raw)
    document = E.fromstring(package['word/document.xml'])
    styles = E.fromstring(package['word/styles.xml'])
    header_cache = {}
    for name in package:
        if not name.startswith('word/header'):
            continue
        header = E.fromstring(package[name])
        fields = header.xpath('//w:fldSimple', namespaces=NS)
        if fields:
            field, = fields
            instruction = field.get(qn('w:instr'))
            assert instruction.startswith('STYLEREF "')
            style_name = instruction.split('"')[1]
            style_id, = styles.xpath('//w:style[w:name/@w:val=$name]/@w:styleId', namespaces=NS, name=style_name)
            paragraph, = document.xpath('//w:body/w:p[w:pPr/w:pStyle/@w:val=$style]', namespaces=NS, style=style_id)
            displayed = ''.join(field.xpath('.//w:t/text()', namespaces=NS))
            assert displayed == ''.join(paragraph.xpath('.//w:t/text()', namespaces=NS))
            header_cache[displayed] = style_id
    assert {'摘  要', 'ABSTRACT', '目录', 'Research context', 'Closing observations'} <= set(header_cache)
    assert 'Declaration' not in header_cache
    assert any(row.get('generated_field') and row['target_language']=='en' and row['text']=='ABSTRACT' for row in source_map if row['location'].startswith('word/header'))
    assert any(row['text']=='目录' and row.get('generated_field') for row in final_school_source_map(raw,raw,source_map,'zh-CN'))
    for style, face, size in [('SchoolEnglishAbstract','黑体','44'),('SchoolEnglishTitle','Times New Roman','32'),('SchoolEnglishAbstractBody','Times New Roman','24'),('SchoolEnglishKeywords','Times New Roman','24'),('SchoolReferenceEntry','Times New Roman','21')]:
        assert styles.xpath('//w:style[@w:styleId=$style]/w:rPr/w:rFonts/@w:ascii', namespaces=NS, style=style)==[face]
        assert styles.xpath('//w:style[@w:styleId=$style]/w:rPr/w:sz/@w:val', namespaces=NS, style=style)==[size]
    assert document.xpath('//w:p[w:pPr/w:pStyle/@w:val="SchoolEnglishKeywords"]/w:r[w:rPr/w:b]/w:t/text()', namespaces=NS)==['Key Words']
    assert document.xpath('//w:sectPr/w:pgNumType[@w:fmt="decimal"]/@w:start', namespaces=NS)==['1']


def test_gs501_blind_keeps_front_pages_and_removes_the_supplied_identity_values():
    from app.adapters.school_docx import build_school_docx

    value, analysis = bsu_material()
    options = dict(field_values={'degree':'Private Author Example','committee':'Private Committee Example','signature':'Private Signature Example'})
    planned = plan(value, analysis, **options)
    identified = text(build_school_docx(value, {}, planned))
    blinded = text(build_school_docx(value, {}, planned, mask_identity=True))
    assert all(v in identified and v not in blinded for v in options['field_values'].values())
    assert '论文作者：XXX' in blinded and '作者签名：待填写' not in blinded
    assert all(c['title'] in blinded for c in value['sections'])
    with pytest.raises(StorageError):
        build_school_docx(value, {}, planned, mask_identity=True, excluded_chapter_ids={'background'})


def test_gs501_final_blind_scrubs_confirmed_values_outside_their_front_fields():
    from app.adapters.manuscript_presentation_docx import blind_docx
    from app.adapters.school_docx import build_school_docx
    from app.domain.school_templates.bsu_gs501 import blind_terms

    value, analysis = bsu_material()
    value['sections'][1]['paragraphs'][0]['text'] = '示例中误留 Private Author Example。'
    options = dict(field_values={'degree': 'Private Author Example', 'signature': 'Private Signature Example'})
    planned = plan(value, analysis, **options)
    raw = build_school_docx(value, {}, planned, mask_identity=True)
    rules = dict(identity_terms=[], exceptions=[], manual_image_review=False)
    blinded, receipt = blind_docx(raw, blind_terms(planned, rules), replacement='XXX')
    assert '示例中误留 XXX。' in text(blinded)
    assert not any(value.encode() in part for value in options['field_values'].values() for part in parts(blinded).values())
    assert receipt['known_identity_check'] == 'passed'


def test_gs501_profile_cannot_be_used_by_other_word_sources_or_forged_in_a_plan():
    from app.domain.manuscripts.school_export import validate_school_export

    value, analysis = bsu_material()
    planned = plan(value, analysis)
    planned.pop('format_profile')
    with pytest.raises(StorageError):
        validate_school_export(planned, value, analysis)
    value['thesis_context']['source_files'][0]['sha256'] = 'e'*64
    with pytest.raises(StorageError):
        plan(value, analysis)


def test_gs501_submission_forms_reuse_original_layout_and_fill_only_known_slots():
    from hashlib import sha256
    from lxml import etree as E

    from app.adapters.manuscript_presentation_docx import blind_docx, decorate_docx
    from app.adapters.school_docx import build_school_docx
    from app.domain.manuscripts.school_export import compile_school_export
    from app.domain.school_templates.bsu_gs501 import blind_terms

    source_path = environ.get('PAPERASSIST_TEST_GS501_SOURCE')
    if not source_path:
        pytest.skip('Requires the locally retained official GS501 upload.')
    template = Path(source_path).read_bytes()
    assert sha256(template).hexdigest() == GS501_TEMPLATE_SHA
    original = E.fromstring(parts(template)['word/document.xml'])
    value, analysis = bsu_material()
    declaration = value['thesis_context']['chapters'][0]
    declaration['title'] = value['sections'][0]['title'] = '北京体育大学学位论文原创性声明'
    value['sections'][0]['paragraphs'] = [dict(id='temporary-declaration', text='开发测试声明文字。', citations=[])]
    confirmation = value['thesis_context']['confirmation']
    confirmation['chapters'][0]['title'] = declaration['title']
    cover_author = next(f for f in confirmation['front_matter']['fields'] if f['id']=='degree')
    cover_author.update(kind='text', label='姓名')
    confirmation['front_matter']['fields'].append(dict(cover_author, id='date', label='提交日期', kind='date'))
    committee = next(f for f in confirmation['front_matter']['fields'] if f['id']=='committee')
    for identity, label in (('chair_name', '主席姓名'), ('chair_title', '主席职称'), ('chair_office', '主席所在单位')):
        confirmation['front_matter']['fields'].append(dict(committee, id=identity, label=label))
    value['thesis_context']['confirmation_sha256'] = digest(confirmation)
    options = dict(english_title='Frozen English title', include_toc=False,
                   field_values={'degree': '确认作者姓名', 'signature': '不能作为签名的测试字样', 'committee': '委员会测试字样',
                                 'chair_name': '已确认主席姓名', 'chair_title': '教授', 'chair_office': '北京体育大学',
                                 'date': '2026年11月17日'})
    body_text = '冻结文本中曾出现确认作者姓名和配置作者姓名。'
    value['sections'][1]['paragraphs'][0]['text'] = body_text
    planned = compile_school_export(value, analysis, options, submission_forms=True)
    assert planned['submission_forms_source_sha256'] == GS501_TEMPLATE_SHA
    png = parts(template)
    logos = {sha256(png[name]).hexdigest() for name in ('word/media/image1.jpeg', 'word/media/image2.jpeg', 'word/media/image3.jpeg')}
    rules = dict(identity_terms=[], exceptions=[], manual_image_review=False)
    authors = [dict(name='配置作者姓名', order=1, corresponding=False, affiliation_ids=[])]
    config = dict(authors=authors, affiliations=[], statements=[], blind=rules)

    for blind in (False, True):
        raw = build_school_docx(value, {}, planned, school_template=template, mask_identity=blind)
        document = E.fromstring(parts(raw)['word/document.xml'])
        front = document.find(qn('w:body'))[:63]
        assert [node.tag for node in front] == [node.tag for node in original.find(qn('w:body'))[:63]]
        assert [node.get(qn('w:val')) for paragraph in front for node in paragraph.iter(qn('w:gridSpan'))] == ['3', '3', '3']
        assert len([node for paragraph in front for node in paragraph.iter(qn('w:sectPr'))]) == 4
        assert logos <= {sha256(data).hexdigest() for name, data in parts(raw).items() if name.startswith('word/media/')}
        assert not any('/embeddings/' in name for name in parts(raw))
        declarations = original.find(qn('w:body'))[39:63]
        assert [''.join(el.itertext()) for el in front[39:63]] == [''.join(el.itertext()) for el in declarations]
        content = text(raw)
        assert 'Frozen English title' in content and 'English title（英文）' not in content
        assert content.count(declaration['title']) == 1
        assert '开发测试声明文字。' not in content and '不能作为签名的测试字样' not in content and '委员会测试字样' not in content
        assert ('确认作者姓名' in ''.join(front[13].itertext())) is (not blind)
        assert ('2026 年 11 月' in ''.join(front[17].itertext())) is (not blind)
        assert ('2026 年 11 月' in ''.join(front[38].itertext())) is (not blind)
        chair = ''.join(front[32].itertext())
        assert all((value in chair) is (not blind) for value in ('已确认主席姓名', '教授', '北京体育大学'))
        assert content.count('XXX') == (5 if blind else 0)
        decorated, _ = decorate_docx(raw, value, None, config, 'zh-CN', 'blind' if blind else 'identified', defer_blind=blind)
        if blind:
            assert '作者信息与声明' not in text(decorated)
            filtered, receipt = blind_docx(decorated, blind_terms(planned, rules, authors=authors), replacement='XXX')
            assert receipt['known_identity_check'] == 'passed'
            assert '冻结文本中曾出现XXX和XXX。' in text(filtered)
            assert '北京体育大学学位论文原创性声明' in text(filtered)
        else:
            assert '作者信息与声明' in text(decorated)

    protected = blind_terms(planned, rules)['identity_terms']
    assert '已确认主席姓名' in protected and '北京体育大学' not in protected
    with pytest.raises(StorageError):
        build_school_docx(value, {}, planned, school_template=template + b'changed')


@pytest.mark.parametrize('entered, expected', [
    ('2026-11-17', '2026 年 11 月'), ('2026年11月17日', '2026 年 11 月'),
    ('2026/6', '2026 年 06 月'), ('2026-02-31', ''), ('不明确', ''),
])
def test_gs501_submission_date_keeps_year_and_month_from_valid_input(entered, expected):
    from app.domain.school_templates.bsu_gs501 import submission_month

    assert submission_month(entered) == expected


def test_gs501_exact_language_review_keeps_legacy_forms_and_rechecks_known_names():
    from unittest.mock import Mock

    from app.adapters.manuscript_presentation_docx import blind_docx
    from app.adapters.school_docx import build_school_docx
    from app.domain.manuscripts.presentation_export import reviewed_school_submission_forms, verify_gs501_reviewed_output
    from app.domain.school_templates.bsu_gs501 import blind_terms

    value, analysis = bsu_material()
    value['sections'][1]['paragraphs'][0]['text'] = '另存正文的配置作者姓名。'
    planned = plan(value, analysis, include_toc=False)
    draft = build_school_docx(value, {}, planned, mask_identity=True)
    rules = dict(identity_terms=[], exceptions=[], manual_image_review=False)
    authors = [dict(name='配置作者姓名')]
    context = dict(
        base=dict(id='base'),
        selected=dict(snapshot_json=value),
        binding=dict(review_mode='blind'),
        preview=dict(config=dict(blind=rules, authors=authors, language_review=dict(source_export_id='earlier'))),
    )
    db = Mock()
    db.execute.return_value.fetchone.return_value = dict(metadata_json={'school': {'plan': planned}})
    assert reviewed_school_submission_forms(db, context) is False

    with pytest.raises(StorageError) as error:
        verify_gs501_reviewed_output(context, planned, draft)
    assert error.value.code == 'gs501_reviewed_output_stale'
    clean, _ = blind_docx(draft, blind_terms(planned, rules, authors=authors), replacement='XXX')
    verify_gs501_reviewed_output(context, planned, clean)
