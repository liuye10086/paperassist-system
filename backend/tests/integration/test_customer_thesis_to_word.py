"""Real customer and DOCX paths with an offline school-writing fixture."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from zipfile import ZipFile

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from fastapi.testclient import TestClient
from lxml import etree
from PIL import Image, ImageDraw
import pytest

from app.adapters.docx_parser import parse_docx
from app.adapters.school_template_parser import inspect_school_template
from app.db.database import database_connection
from app.domain.literature.service import digest
from app.domain.manuscript_writing.execution import run_manuscript_writing_task
from app.domain.school_templates.execution import run_school_template_task
from app.domain.tasks.execution import run_task
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.main import app
from tests.api.test_customer_workspace import sign_in
from tests.api.test_file_batches import register
from tests.api.test_manuscript_writing_live import request_v2
from tests.api.test_school_writing_live import SchoolFixture
from tests.domain.test_school_writing_live import synthetic_layout_cache
from tests.integration.test_customer_sci_to_word import (
    DOCX, assert_compatible_default_fonts, assert_customer_writing_queued, record_candidate_citation, request,
    selected_pubmed_reference,
)


SCHOOL = '合成学校'
TITLE = '合成工程论文'
ENGLISH_TITLE = 'Synthetic engineering thesis'
AUTHOR = '合成作者青竹'
SIGNATURE = '合成签名字样青竹'
HEADER_IDENTITY = '合成识别信息松柏'
DECLARATION = '此声明由测试人员提供，仅适用于合成工程资料。'
TEMPLATE_NAME = '学校模板示例姓名'
TEMPLATE_SIGNATURE = '学校模板示例签名'
REQUIREMENTS = '正文：宋体四号字。'
CHAPTER_PURPOSES = {
    '学位论文独创性声明': ('manual', 'zh-CN'),
    '摘要': ('abstract', 'zh-CN'),
    'Abstract': ('abstract', 'en'),
    '1 绪论': ('introduction', 'zh-CN'),
    '1 绪论（更新）': ('introduction', 'zh-CN'),
    '1.1 工程讨论': ('discussion', 'zh-CN'),
    '2 研究方法': ('materials_and_methods', 'zh-CN'),
    '3 结果': ('results', 'zh-CN'),
    '4 结论': ('conclusion', 'zh-CN'),
    '参考文献': ('references', 'zh-CN'),
}
CAPTION = '测试绘制的无文字合成图。'
METHOD = '合成流程方案要求记录5行测试数据。'
RESULT = '合成观察见图1。'
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def school_template_bytes(*, updated=False, incompatible=False):
    """Synthetic template with actual paragraph styles and section properties."""
    document = Document()
    for name, size in [('Normal', 11 if updated else 12), ('Title', 20),
                       ('Heading 1', 16), ('Heading 2', 14), ('Caption', 10)]:
        style = document.styles[name]
        style.font.name = 'Times New Roman'
        style.font.size = Pt(size)
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), '宋体')
    cover = document.sections[0]
    cover.page_width = Cm(21)
    cover.page_height = Cm(29.7)
    cover.top_margin = cover.bottom_margin = cover.left_margin = cover.right_margin = Cm(2.5)
    document.add_paragraph('合成模板封面', 'Title')
    author = document.add_paragraph('作者姓名：' + TEMPLATE_NAME)
    author.alignment = WD_ALIGN_PARAGRAPH.CENTER
    author.runs[0].font.size = Pt(18)

    front = document.add_section(WD_SECTION_START.NEW_PAGE)
    _numbered_section(front, 'lowerRoman')
    document.add_heading('学位论文独创性声明', 1)
    document.add_paragraph('作者签名：' + TEMPLATE_SIGNATURE)
    document.add_paragraph('中文题目示例', 'Title')
    document.add_heading('摘要', 1)
    document.add_paragraph('关键词：合成；工程')
    if not incompatible:
        document.add_paragraph('Example English title', 'Title')
        document.add_heading('Abstract', 1)
        document.add_paragraph('Keywords: synthetic; engineering')
    document.add_paragraph('目录')

    main = document.add_section(WD_SECTION_START.NEW_PAGE)
    _numbered_section(main, 'decimal')
    main.header.is_linked_to_previous = False
    main.header.paragraphs[0].text = HEADER_IDENTITY
    document.add_heading('1 绪论（更新）' if updated else '1 绪论', 1)
    document.add_paragraph('合成模板正文段落保留本段的属性来源，供测试人员根据已确认的样式核对生成文档。')
    document.add_heading('1.1 工程讨论', 2)
    document.add_heading('2 研究方法', 1)
    document.add_heading('3 结果', 1)
    document.add_paragraph('图3.1 合成示例题注', 'Caption')
    document.add_paragraph('表3.1 合成示例表标题', 'Caption')
    document.add_heading('4 结论', 1)
    document.add_heading('参考文献', 1)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _numbered_section(section, number_format):
    number = OxmlElement('w:pgNumType')
    number.set(qn('w:fmt'), number_format)
    number.set(qn('w:start'), '1')
    existing = section._sectPr.find(qn('w:pgNumType'))
    if existing is not None:
        section._sectPr.remove(existing)
    section._sectPr.insert_element_before(number, 'w:cols', 'w:docGrid')
    section.footer.is_linked_to_previous = False
    page = OxmlElement('w:fldSimple')
    page.set(qn('w:instr'), 'PAGE')
    section.footer.paragraphs[0]._p.append(page)


def template_confirmation(item, *, option='text-2'):
    analysis = item['analysis']
    chapters = [{key: chapter[key] for key in ('id', 'title', 'level')}
                for chapter in analysis['chapters'] if chapter['title'] != '目录']
    sources = {source['suggested_label']: source for source in item['front_matter_sources']}
    declaration = next(chapter['id'] for chapter in chapters if CHAPTER_PURPOSES[chapter['title']][0] == 'manual')
    author, signature = sources['作者姓名'], sources['作者签名']
    fields = [
        dict(id='author', label='作者姓名', kind='identity', required=True, source_id=author['id'],
             style_source_id=author['id'], section_id=author['section_id'], chapter_id=None),
        dict(id='signature', label='作者签名', kind='signature', required=True, source_id=signature['id'],
             style_source_id=None, section_id=signature['section_id'], chapter_id=declaration),
    ]
    return dict(
        analysis_sha256=item['analysis_sha256'], chapters=chapters,
        decisions=[dict(conflict_id=conflict['id'], option_id=option) for conflict in analysis['conflicts']],
        text_decisions=[dict(id=rule['id'], choice='attributes', source_sha256=rule['source_sha256'])
                        for rule in item['text_decision_options']],
        front_matter=dict(schema_version=1, cover_section_id=author['section_id'], fields=fields,
                          content_requirements=[dict(id='declaration', kind='declaration', required=True,
                                                     chapter_id=declaration, source_id=signature['id'])]),
    )


def school_options(chapters):
    by_title = {chapter['title']: chapter['id'] for chapter in chapters}
    return dict(
        include_toc=True, toc_depth=2, english_title=ENGLISH_TITLE,
        field_values=dict(author=AUTHOR, signature=SIGNATURE),
        manual_chapters=[dict(chapter_id=by_title['学位论文独创性声明'], text=DECLARATION)],
        keywords=[dict(chapter_id=by_title['摘要'], values=['合成工程', '格式核验']),
                  dict(chapter_id=by_title['Abstract'], values=['synthetic exercise', 'layout verification'])],
    )


def start_template(client, project, version, *, previous=None, **fixture):
    raw = school_template_bytes(**fixture)
    filename = f'synthetic-school-{version}.docx'
    uploads, batch, item, _ = register(client, {'id': project.rsplit('/', 1)[-1]}, raw, filename, key='upload-' + version)
    uploaded = request(client, 'POST', f"{uploads}/{batch['id']}/items/{item['client_id']}", status=202,
                       files={'file': (filename, raw)})
    file_task = uploaded['task']
    parsed = run_parse_file_task(file_task['id'], file_task['revision'], parser=parse_docx)
    assert parsed['status'] == 'succeeded', parsed
    data = dict(name='合成学校论文模板', school=SCHOOL, version_label=version,
                template_file_id=uploaded['file_id'], supplement_text=REQUIREMENTS)
    if previous is not None:
        data['previous_version_id'] = previous
    item = request(client, 'POST', project + '/school-templates', status=202, key='template-' + version, json=data)
    assert item['analysis'] is None and item['task']['status'] == 'queued'
    source = item['sources'][0]
    assert source['role'] == 'template' and source['sha256'] == sha256(raw).hexdigest()
    downloaded = client.get(source['download_url'])
    assert downloaded.status_code == 200 and downloaded.content == raw
    return item


def parse_template(client, project, item):
    task = item['task']
    result = run_school_template_task(task['id'], task['revision'], parser=inspect_school_template)
    assert result['status'] == 'succeeded', result
    return next(row for row in request(client, 'GET', project + '/school-templates')['items'] if row['id'] == item['id'])


def thesis_request(confirmation, profile, **materials):
    mappings = []
    groups = [group['id'] for group in materials.get('results_groups', [])]
    for chapter in confirmation['chapters']:
        purpose, language = CHAPTER_PURPOSES[chapter['title']]
        mappings.append(dict(chapter_id=chapter['id'], purpose=purpose, output_language=language,
                             result_group_ids=groups if purpose == 'results' else []))
    return dict(title=TITLE, output_language='zh-CN', sources=[], thesis=dict(
        confirmation_id=confirmation['id'], profile_revision=profile['revision'], chapter_mappings=mappings,
    )) | materials


def upload_illustration(client, project):
    image = Image.new('RGB', (300, 180), 'white')
    ImageDraw.Draw(image).line([(20, 150), (130, 105), (280, 40)], fill='navy', width=5)
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    png = buffer.getvalue()
    document = Document()
    document.add_paragraph(METHOD)
    document.add_picture(BytesIO(png))
    content = BytesIO()
    document.save(content)
    filename = 'synthetic-thesis-material.docx'
    uploads, batch, item, raw = register(client, {'id': project.rsplit('/', 1)[-1]}, content.getvalue(), filename, key='material')
    uploaded = request(client, 'POST', f"{uploads}/{batch['id']}/items/{item['client_id']}", status=202,
                       files={'file': (filename, raw)})
    task = uploaded['task']
    result = run_parse_file_task(task['id'], task['revision'], parser=parse_docx)
    assert result['status'] == 'succeeded', result
    file_id = uploaded['file_id']
    documents = project + f'/files/{file_id}/document-versions'
    document_id = request(client, 'GET', documents)['items'][0]['id']
    parsed_image = request(client, 'GET', documents + '/' + document_id)['images'][0]
    assert parsed_image['sha256'] == sha256(png).hexdigest()
    source = dict(kind='document_version', id=document_id, file_id=file_id)
    figure = request(client, 'POST', project + '/manuscript-figure-language-versions', status=201, key='figure', json=dict(
        source=source | dict(image_id=parsed_image['id']), original_sha256=parsed_image['sha256'],
        mode='no_text_confirmation', output_language='zh-CN', reason='人工核对合成图中没有文字。',
        title='合成方向图', caption=CAPTION,
    ))
    assert figure['sha256'] == parsed_image['sha256']
    return [source | dict(role='methods'), dict(kind='figure_language_version', id=figure['id'], file_id=file_id,
                                                role='image_observation')], png


class ThesisFixture(SchoolFixture):
    def __init__(self, quote):
        super().__init__()
        self.quote = quote

    def receipt(self):
        result = super().receipt()
        payload = json.loads(json.loads(self.posts[-1])['input'])
        content = result['response']['output'][0]['content'][0]
        output = json.loads(content['text'])
        sections = output['sections']
        for chapter, section in zip(payload['chapters'], sections):
            generated = section['paragraphs'][0]
            if chapter['purpose'] == 'abstract' and chapter['output_language'] == 'en':
                generated.update(text=self.quote, evidence_aliases=['e1'])
                if 'citation_anchors' in generated:
                    generated['citation_anchors'] = [dict(sentence=self.quote, evidence_aliases=['e1'])]
            if chapter['purpose'] == 'materials_and_methods':
                number = next(row for row in payload['numeric_context'] if row['text'].endswith(METHOD))
                generated.update(text=METHOD, study_numeric_bindings=[dict(source_alias=number['alias'], **number['values'][0])])
            if chapter['purpose'] == 'results':
                generated['text'] = RESULT
        content['text'] = json.dumps(output)
        return result


def write_candidate(client, root, sources, evidence, quote, *, use_skills, monkeypatch, tmp_path):
    previews = root + '/writing-previews'
    body = dict(
        schema_version=3, base_revision=1, mode='full_draft', output_language='zh-CN',
        selected_source_ids=[source['id'] for source in sources], selected_evidence_ids=[evidence['id']],
    )
    if use_skills:
        body['document_context_version'] = 'selected-text-v1'
    bundle = request(client, 'POST', previews, status=201, key='preview', json=body)
    assert bundle['execution_contract']['schema_version'] == 3
    skills = bundle['execution_contract'].get('skills_snapshot')
    envelope = json.loads(bundle['wire_json'])
    wire = json.loads(envelope['input'])
    if use_skills:
        assert skills is not None and skills['trace']['workflow'] == 'thesis_initial_draft'
        assert bundle['execution_contract']['school_presentation_version'] == 'school-presentation-v2'
        schema = envelope['text']['format']['schema']['$defs']['Presentation']['properties']
        for field in ('chapter_titles', 'figure_titles'):
            count = len(wire['draft_presentation'][field])
            assert schema[field]['minItems'] == schema[field]['maxItems'] == count
        assert wire['draft_presentation']['source_title'] == TITLE
        assert wire['sources'][0]['document_excerpt'] == METHOD
        monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', '')
        monkeypatch.setenv('PAPERASSIST_SKILLS_DIR', str(tmp_path / 'missing'))
        assert request(client, 'POST', previews, key='preview', json=body) == bundle
    else:
        assert TITLE not in bundle['wire_json'] and skills is None
    assert all(private not in bundle['wire_json'] for private in (TEMPLATE_SIGNATURE, AUTHOR, SIGNATURE))
    assert {chapter['output_language'] for chapter in wire['chapters']} == {'zh-CN', 'en'}
    assert {chapter['purpose'] for chapter in wire['chapters']}.isdisjoint({'manual', 'references'})
    assert wire['evidence'][0]['quote'] == quote
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
    authorization = root.split('/manuscripts/')[0] + '/writing-authorizations'
    frozen_bundle = dict(bundle_id=bundle['id'], bundle_sha256=bundle['bundle_sha256'])
    auth = request(client, 'POST', authorization, status=201, key='authorize', json=dict(
        schema_version=2, confirmed=True, tasks=[dict(logical_task_id='task-0', bundles=[frozen_bundle])],
    ))
    task = request(client, 'POST', root + '/writing-requests', status=202, key='write', json=request_v2(bundle, auth))['task']
    assert_customer_writing_queued(client, root, task)
    provider = ThesisFixture(quote)
    result = run_manuscript_writing_task(task['id'], task['revision'], provider=provider)
    assert result['status'] == 'succeeded', result
    assert provider.posts == [bundle['wire_json']]
    path = root + '/writing-requests/' + task['id']
    context = request(client, 'GET', path + '/review-context')
    provenance = context['candidate']['writing_provenance']
    assert provenance['provider_provenance'] == 'synthetic_fixture' and provenance['verification_status'] == 'pending'
    assert provenance.get('skills_trace') == (skills['trace'] if skills else None)
    paragraph = next(s for s in context['candidate']['sections'] if s.get('purpose') == 'abstract' and s['output_language'] == 'en')['paragraphs'][0]
    assert paragraph['suggested_evidence_aliases'] == ['e1'] and paragraph['citations'] == []
    return path, context


def review_science(client, path, context, citation):
    literature, search, reference, metadata, quote = citation
    sections = context['candidate']['sections']
    english = next(section for section in sections if section['purpose'] == 'abstract' and section['output_language'] == 'en')
    paragraph_id = english['paragraphs'][0]['id']
    bound = record_candidate_citation(client, literature, search, reference, context['claim_contexts'][paragraph_id], metadata, quote)
    paragraphs = [dict(paragraph_id=p['id'], text_sha256=digest(p['text']), classification='non_claim',
                       scientific_basis='核对句子仅描述合成工程测试。', numeric_bindings=[])
                  for section in sections for p in section['paragraphs'] if p['id'] in context['required_paragraph_ids']]
    next(p for p in paragraphs if p['paragraph_id'] == paragraph_id).update(
        classification='literature_claim', claim=bound,
        scientific_basis='核对英文摘要原文及所保留的合成文献来源。',
    )
    method = next(section for section in sections if section['purpose'] == 'materials_and_methods')['paragraphs'][0]
    alias, number = next((alias, row) for alias, row in context['local_manifest']['numeric_context'].items()
                         if row['text'].endswith(METHOD))
    next(p for p in paragraphs if p['paragraph_id'] == method['id']).update(
        classification='context_claim', scientific_basis='核对方法中的数值来自用户提供的合成流程方案。',
        numeric_bindings=[dict(kind='context', occurrence=0, source_alias=alias, **number['values'][0])],
    )
    consistency = dict(body_sha256=context['body_sha256'],
                       title=dict(subject=True, direction=True, strength=True, basis='题名与合成正文一致。'),
                       abstracts={chapter_id: dict(objective=True, methods=True, key_results=True, conclusion=True,
                                                  basis='已明确核对本摘要与合成正文。')
                                  for chapter_id in context['abstract_chapter_ids']})
    assert len(consistency['abstracts']) == 2
    data = dict(schema_version=3, candidate_sha256=context['candidate_sha256'], paragraphs=paragraphs, consistency=consistency)
    incomplete = data | dict(consistency=consistency | dict(abstracts={}))
    request(client, 'POST', path + '/reviews', status=422, key='missing-abstract-review', json=incomplete)
    review = request(client, 'POST', path + '/reviews', status=201, key='science', json=data)
    assert review['candidate']['references'][0]['project_reference_id'] == reference['id']
    return review


def language_decisions(inventory):
    decisions = []
    for item in inventory:
        decision = dict(location=item['location'], content_sha256=item['content_sha256'], decision='target_language',
                        reason='核对当前输出的文字及其章节语言。', exceptions=[])
        if item.get('protected_identity'):
            decision.update(decision='provided_literal', reason='保留人员明确提供的合成字样。')
        elif item['kind'] == 'image':
            assert item['language_known'] and item['no_text']
            decision.update(decision='no_text', reason='人工核对合成图片无文字。')
        elif item['scope'] == 'reference_metadata' and item['target_language'] == 'zh-CN':
            decision['exceptions'] = [dict(start=word.start(), end=word.end(), kind='reference_metadata',
                                           reason='保留合成来源原始著录。') for word in re.finditer(r'[A-Za-z]{2,}', item['text'])]
        decisions.append(decision)
    return decisions


def review_language_and_freeze(client, root, path, science, options):
    publish = dict(schema_version=2, expected_revision=1, review_id=science['id'], review_sha256=science['review_sha256'])
    blocked = request(client, 'POST', path + '/publish', status=409, key='early-publish', json=publish)
    assert blocked['detail']['code'] == 'manuscript_writing_language_required'
    preparation = dict(schema_version=3, review_id=science['id'], review_sha256=science['review_sha256'], school=options)
    context = request(client, 'POST', path + '/reviews/' + science['id'] + '/language-context', json=preparation)
    inventory = context['inventory']
    assert any(item.get('toc_target') for item in inventory)
    assert any(item['text'].startswith('Keywords:') and item['target_language'] == 'en' for item in inventory)
    assert any(item['text'].startswith('关键词：') and item['target_language'] == 'zh-CN' for item in inventory)
    assert any(item.get('protected_identity') and AUTHOR in item['text'] for item in inventory)
    data = preparation | dict(inventory_sha256=context['inventory_sha256'], decisions=language_decisions(inventory))
    request(client, 'POST', path + '/language-reviews', status=422, key='incomplete-language',
            json=data | dict(decisions=data['decisions'][1:]))
    language = request(client, 'POST', path + '/language-reviews', status=201, key='language', json=data)
    publish.update(language_review_id=language['id'], language_review_sha256=language['artifact_sha256'])
    published = request(client, 'POST', path + '/publish', status=201, key='publish', json=publish)['versions'][0]
    assert published['revision'] == 2 and published['snapshot'] == language['candidate']
    assert request(client, 'POST', path + '/publish', key='publish', json=publish)['versions'][0]['id'] == published['id']
    assert run_task(published['task_id'], 1)['status'] == 'succeeded'
    fixed = request(client, 'GET', root + '/versions/2')
    assert fixed['id'] == published['id'] and fixed['snapshot'] == published['snapshot']
    return fixed


def export_word(client, root, fixed, payload, key):
    endpoint = root + f"/versions/{fixed['revision']}/exports"
    created = request(client, 'POST', endpoint, status=201, key=key, json=payload)
    assert created['version_id'] == fixed['id']
    executed = run_task(created['task_id'], 1)
    assert executed['status'] == 'succeeded', executed
    saved = request(client, 'GET', root + '/exports/' + created['id'])
    download = client.get(saved['download_url'])
    assert download.status_code == 200, download.text
    assert download.headers['Content-Type'] == DOCX and '.docx' in download.headers['Content-Disposition']
    assert len(download.content) == saved['size_bytes'] and sha256(download.content).hexdigest() == saved['sha256']
    return saved, download.content


def assert_school_page_numbering(document_xml):
    page_numbers = document_xml.xpath('//w:sectPr/w:pgNumType', namespaces=NS)
    assert [(node.get(qn('w:fmt')), node.get(qn('w:start'))) for node in page_numbers] == [
        ('decimal', None), ('lowerRoman', '1'), ('lowerRoman', None), ('decimal', '1'),
    ]


def assert_school_word(ordinary, png, quote, reference):
    document = Document(BytesIO(ordinary))
    paragraphs = {p.text: p for p in document.paragraphs}
    cover = paragraphs['作者姓名：' + AUTHOR]
    assert cover.alignment == WD_ALIGN_PARAGRAPH.CENTER and cover.runs[0].font.size.pt == 18
    assert TITLE in paragraphs and DECLARATION in paragraphs and '作者签名：' + SIGNATURE in paragraphs
    assert not any(TEMPLATE_NAME in text or TEMPLATE_SIGNATURE in text for text in paragraphs)
    assert document.styles['Normal'].font.name == 'Times New Roman' and document.styles['Normal'].font.size.pt == 14
    assert document.styles['School Figure Caption'].font.size.pt == document.styles['School Table Caption'].font.size.pt == 10
    assert paragraphs['目录'].style.name == 'School Contents'
    assert paragraphs['1 绪论'].style.name == 'Heading 1' and paragraphs['1.1 工程讨论'].style.name == 'Heading 2'
    assert paragraphs['摘要'].style.name == 'School Chinese Abstract' and paragraphs['Abstract'].style.name == 'School English Abstract'
    assert ENGLISH_TITLE in paragraphs and '合成正文须由研究人员明确核对。' in paragraphs and quote + ' (1)' in paragraphs
    assert '关键词：合成工程；格式核验' in paragraphs and 'Keywords: synthetic exercise; layout verification' in paragraphs
    assert '合成观察见图3.1。' in paragraphs and paragraphs['图 3.1  合成方向图'].style.name == 'School Figure Caption'
    assert CAPTION in paragraphs and '[1] ' + reference in paragraphs
    assert_compatible_default_fonts(ordinary)
    with ZipFile(BytesIO(ordinary)) as archive:
        main = etree.fromstring(archive.read('word/document.xml'))
        assert_school_page_numbering(main)
        assert any(etree.fromstring(archive.read(name)).xpath('//w:fldSimple[@w:instr="PAGE"]', namespaces=NS)
                   for name in archive.namelist() if name.startswith('word/footer'))
        assert main.xpath('//w:instrText[contains(text(), "TOC")]', namespaces=NS)
        links = main.xpath('//w:hyperlink[starts-with(@w:anchor,"PATOC")]', namespaces=NS)
        headings = [link.xpath('.//w:t/text()', namespaces=NS)[0] for link in links]
        assert headings == ['1 绪论', '1.1 工程讨论', '2 研究方法', '3 结果', '4 结论', '参考文献']
        assert all(link.xpath('.//w:t/text()', namespaces=NS)[-1].isdigit() for link in links)
        assert links[1].getparent().xpath('./w:pPr/w:ind/@w:left', namespaces=NS) == ['240']
        assert HEADER_IDENTITY.encode() in b''.join(archive.read(name) for name in archive.namelist() if name.startswith('word/header'))
        assert png in [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
    assert (document.core_properties.author, document.core_properties.last_modified_by) == ('PaperAssist', 'PaperAssist')


def assert_historical_blind_export_stays_readable(client, root, fixed, options):
    """A signed presentation export rewritten into the stored shape of a pre-removal blind one."""
    from copy import deepcopy
    from psycopg.types.json import Jsonb
    presentation = request(client, 'POST', root + '/presentations', status=201, key='signed-config', json=dict(
        base_version_id=fixed['id'], config=dict(school=dict(options=options))))
    assert 'blind' not in presentation['config']
    signed, raw = export_word(client, root, fixed, dict(presentation_version_id=presentation['id'], language_view='zh-CN'), 'signed-word')
    assert signed['presentation']['binding']['review_mode'] == 'identified' and 'blind' not in signed['presentation']
    text = '\n'.join(p.text for p in Document(BytesIO(raw)).paragraphs)
    assert '作者姓名：' + AUTHOR in text and '[已隐去]' not in text
    with database_connection(write=True) as db:
        row = db.execute('SELECT e.metadata_json,t.id,t.input_snapshot FROM manuscript_exports e JOIN tasks t ON t.id=e.task_id WHERE e.id=%s',
                         (signed['id'],)).fetchone()
        snapshot = deepcopy(row['input_snapshot']); snapshot['presentation']['binding']['review_mode'] = 'blind'
        metadata = deepcopy(row['metadata_json']); metadata['presentation']['binding']['review_mode'] = 'blind'
        metadata['filename'] = '毕业论文盲审稿.docx'
        db.execute('UPDATE tasks SET input_snapshot=%s,input_digest=%s WHERE id=%s', (Jsonb(snapshot), digest(snapshot), row['id']))
        db.execute('UPDATE manuscript_exports SET metadata_json=%s WHERE id=%s', (Jsonb(metadata), signed['id']))
    listed = request(client, 'GET', root + f"/versions/{fixed['revision']}/exports")['items']
    historical = next(item for item in listed if item['id'] == signed['id'])
    assert historical['presentation']['binding']['review_mode'] == 'blind' and historical['filename'] == '毕业论文盲审稿.docx'
    assert request(client, 'GET', root + '/exports/' + signed['id'])['sha256'] == signed['sha256']
    assert client.get(historical['download_url']).content == raw
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='failed',error_code='storage_unavailable' WHERE id=%s", (row['id'],))
    task = request(client, 'GET', '/api/v1/tasks/' + row['id'])
    retried = client.post('/api/v1/tasks/' + row['id'] + '/retry', json=dict(expected_revision=task['revision']))
    assert retried.status_code == 422 and retried.json()['detail']['code'] == 'blind_review_removed', retried.text
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='succeeded',error_code=NULL WHERE id=%s", (row['id'],))


def adopt_template_update(client, project, root, fixed, parent_template, profile):
    templates = project + '/school-templates'
    versions = root + '/versions/2/school-changes'
    incompatible = parse_template(client, project, start_template(
        client, project, 'incompatible', previous=parent_template['id'], incompatible=True,
    ))
    invalid_confirmation = request(client, 'POST', templates + '/' + incompatible['id'] + '/confirm',
                                   status=201, key='confirm-incompatible', json=template_confirmation(incompatible))
    change = request(client, 'POST', versions, status=201, key='preview-incompatible', json=dict(
        kind='template_migration', target_confirmation_id=invalid_confirmation['id'],
    ))
    assert not change['can_adopt'] and any(issue['code'] == 'mapping_required' for issue in change['issues'])
    adopt = root + '/school-changes/' + change['id'] + '/adopt'
    response = request(client, 'POST', adopt, status=409, key='incompatible',
                       json=dict(mappings=change['mappings'], expected_revision=2, preview_sha256=change['preview_sha256']))
    assert response['detail']['code'] == 'school_change_blocked'
    assert request(client, 'GET', root)['current_revision'] == 2

    updated = parse_template(client, project, start_template(client, project, 'v2', previous=parent_template['id'], updated=True))
    assert updated['previous_version_id'] == parent_template['id'] and updated['analysis_sha256'] != parent_template['analysis_sha256']
    confirmed = request(client, 'POST', templates + '/' + updated['id'] + '/confirm', status=201, key='confirm-update',
                        json=template_confirmation(updated, option='openxml'))
    assert next(rule['value'] for rule in confirmed['rules'] if rule['id'] == 'body.font_size_pt') == 11
    before = request(client, 'GET', project + '/thesis-profile')
    assert before['bound_confirmation_id'] == profile['bound_confirmation_id'] == fixed['snapshot']['thesis_context']['confirmation_id']
    binding = dict(confirmation_id=confirmed['id'], expected_revision=before['revision'])
    assert request(client, 'POST', project + '/thesis-template-binding', json=binding)['bound_confirmation_id'] == confirmed['id']
    old = request(client, 'GET', root + '/versions/2')
    assert old['snapshot'] == fixed['snapshot'] and old['current_changes']
    request(client, 'POST', root + '/writing-previews', status=409, key='stale-template', json=dict(
        schema_version=3, base_revision=2, mode='full_draft', output_language='zh-CN',
        selected_source_ids=[], selected_evidence_ids=[],
    ))
    change = request(client, 'POST', versions, status=201, key='preview-update', json=dict(
        kind='template_migration', target_confirmation_id=confirmed['id'],
    ))
    assert change['can_adopt'], change['issues']
    assert any(difference['before'] == '1 绪论' and difference['after'] == '1 绪论（更新）' for difference in change['differences'])
    assert request(client, 'GET', root)['current_revision'] == 2
    adopted = request(client, 'POST', root + '/school-changes/' + change['id'] + '/adopt', status=201, key='adopt-update',
                      json=dict(mappings=change['mappings'], expected_revision=2, preview_sha256=change['preview_sha256']))['versions'][0]
    assert adopted['revision'] == 3 and adopted['parent_version_id'] == fixed['id']
    assert adopted['snapshot']['thesis_context']['confirmation_id'] == confirmed['id']
    assert adopted['snapshot']['references'] == fixed['snapshot']['references']
    assert 'writing_provenance' not in adopted['snapshot']
    assert adopted['snapshot']['school_change_provenance']['retained_writing_context'] == 1
    migrated_method = next(section for section in adopted['snapshot']['sections'] if section['purpose'] == 'materials_and_methods')
    frozen_method = next(section for section in fixed['snapshot']['sections'] if section['purpose'] == 'materials_and_methods')
    assert migrated_method['paragraphs'] == frozen_method['paragraphs']
    assert migrated_method['paragraphs'][0]['numeric_bindings'][0]['kind'] == 'context'
    assert run_task(adopted['task_id'], 1)['status'] == 'succeeded'
    plan = request(client, 'POST', root + '/versions/3/exports/preview',
                   json=dict(school=school_options(confirmed['chapters'])))['school']
    assert plan['report']['can_export'] and plan['styles']['body']['font_size_pt'] == 11
    assert plan['pagination_version'] == 2
    assert request(client, 'GET', root + '/versions/2')['snapshot'] == fixed['snapshot']


@pytest.mark.parametrize('use_skills', [False, True], ids=['original', 'skills'])
def test_customer_confirms_writes_reviews_and_downloads_frozen_thesis(monkeypatch, tmp_path, use_skills):
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'thesis_initial_draft' if use_skills else '')
    monkeypatch.setenv('PAPERASSIST_SKILLS_DIR', str(Path(__file__).resolve().parents[3] / 'SKILLS'))
    monkeypatch.delenv('PAPERASSIST_SKILLS_MANIFEST_SHA256', raising=False)
    monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields', synthetic_layout_cache)
    with TestClient(app) as client, TestClient(app) as foreign:
        sign_in(client, 'customer-thesis@manuscript.test', 'customer')
        sign_in(foreign, 'foreign-thesis@manuscript.test', 'customer')
        created = request(client, 'POST', '/api/v1/projects', status=201, key='thesis-project', json=dict(
            name=TITLE, research_topic='合成工程验收', project_type='thesis',
        ))
        project = '/api/v1/projects/' + created['id']
        manuscripts = project + '/manuscripts'
        profile = request(client, 'PUT', project + '/thesis-profile', json=dict(
            expected_revision=0, school=SCHOOL, department='合成院系', major='工程核验',
            degree_type='学术学位', education_level='硕士', applicable_version='测试版',
        ))
        assert profile['revision'] == 1 and profile['bound_confirmation_id'] is None
        assert not request(client, 'GET', manuscripts + '/config')['thesis']['ready']
        template = start_template(client, project, 'v1')
        confirm = project + '/school-templates/' + template['id'] + '/confirm'
        request(client, 'POST', confirm, status=409, key='before-parsing', json=dict(
            analysis_sha256='0' * 64, decisions=[], chapters=[dict(id='placeholder', title='绪论', level=1)],
        ))
        template = parse_template(client, project, template)
        conflict = template['analysis']['conflicts'][0]
        assert conflict['rule_id'] == 'body.font_size_pt'
        assert {item['value'] for item in conflict['options']} == {12, 14}
        assert template['analysis']['missing'] and template['analysis']['identity_fields']
        confirmation = template_confirmation(template)
        request(client, 'POST', confirm, status=409, key='unresolved-conflict', json=confirmation | dict(decisions=[]))
        checked = request(client, 'POST', confirm, status=201, key='confirm-template', json=confirmation)
        assert request(client, 'POST', confirm, key='confirm-template', json=confirmation) == checked
        assert request(client, 'GET', project + '/thesis-profile')['bound_confirmation_id'] is None
        assert not request(client, 'GET', manuscripts + '/config')['thesis']['ready']
        profile = request(client, 'POST', project + '/thesis-template-binding', json=dict(
            confirmation_id=checked['id'], expected_revision=profile['revision'],
        ))
        config = request(client, 'GET', manuscripts + '/config')['thesis']
        assert config['ready'] and config['confirmation_id'] == checked['id']
        assert template['sources'][0]['file_id'] in config['template_source_file_ids']
        sources, png = upload_illustration(client, project)
        draft, literature, search, reference, quote = selected_pubmed_reference(client, project, 'zh-CN')
        groups = [dict(id='fixture-figure', title='合成图片观察', analysis_run_ids=[], figure_ids=[sources[1]['id']])]
        data = thesis_request(checked, profile, sources=sources, methods=dict(study_design=METHOD),
                              method_source_ids=dict(study_design=[sources[0]['id']]),
                              citation_draft=draft, results_groups=groups)
        fact = request(client, 'POST', manuscripts, status=201, key='fact', json=data)
        base = fact['versions'][0]
        assert run_task(base['task_id'], 1)['status'] == 'succeeded'
        root = manuscripts + '/' + fact['id']
        missing = request(client, 'POST', root + '/versions/1/exports/preview', json={})['school']['report']['issues']
        required = {'school:field:author', 'school:field:signature', 'school:required-content:declaration'}
        assert {issue['id'] for issue in missing if issue['source_evidence']} >= required
        request(client, 'POST', root + '/versions/1/exports/preview', status=422,
                json=dict(school=dict(field_values={'unknown': 'invalid'})))

        selected = base['snapshot']['citation_snapshot']['paragraphs'][0]['fragments'][0]['bindings'][0]
        citation = (literature, search, reference, selected['metadata_source'], quote)
        path, context = write_candidate(client, root, sources, selected['evidence'][0], quote,
                                        use_skills=use_skills, monkeypatch=monkeypatch, tmp_path=tmp_path)
        reader = path + '/draft-reader'
        view = request(client, 'GET', reader + '?revision=1')
        assert view['can_revise']
        assert [section['heading'] for section in view['draft']['sections']] == [c['title'] for c in checked['chapters']]
        english = next(s for s in view['draft']['sections'] if s['heading'] == 'Abstract')
        assert english['output_language'] == 'en'
        excerpt = english['paragraphs'][0]['parts'][0]['citations'][0]['excerpts'][0]
        assert excerpt['quote'] == quote
        assert request(client, 'GET', project + '/draft-history')['items'][0]['request_id'] == view['request_id']
        for protected in (reader + '?revision=1', reader + '/word?revision=1', project + '/draft-history'):
            assert foreign.get(protected).status_code == 404
        assert client.get(reader + '/figures/1?revision=1').content == png
        school_word = client.get(reader + '/word?revision=1')
        assert school_word.status_code == 200, school_word.text[:500] if school_word.status_code != 200 else ''
        with ZipFile(BytesIO(school_word.content)) as archive:
            assert_school_page_numbering(etree.fromstring(archive.read('word/document.xml')))
            assert png in [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
        assert_compatible_default_fonts(school_word.content)
        candidate_doc = Document(BytesIO(school_word.content))
        assert len(candidate_doc.inline_shapes) == 1
        assert candidate_doc.styles['Normal'].font.size.pt == 14
        assert any(p.text == '摘要' and p.style.name == 'School Chinese Abstract' for p in candidate_doc.paragraphs)
        assert any(quote + '[1]' in p.text for p in candidate_doc.paragraphs)
        assert any(p.text == '[1] ' + base['snapshot']['references'][0]['text'] for p in candidate_doc.paragraphs)
        feedback = request(client, 'POST', path + '/draft-feedback', files={'file': ('意见.txt', '扩展结论。'.encode())})
        assert feedback == dict(text='扩展结论。')
        original_input = request(client, 'GET', path)['input']
        revise = original_input | dict(revision_of_request_id=view['request_id'], instructions=feedback['text'])
        if use_skills:
            monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'thesis_initial_draft')
        revision_bundle = request(client, 'POST', root + '/writing-previews', status=201, key='advisor-edits', json=revise)
        assert 'skills_snapshot' not in revision_bundle['execution_contract']
        original_draft = json.loads(json.loads(revision_bundle['wire_json'])['input'])['original_draft']
        assert any(p['text'] == quote for s in original_draft for p in s['paragraphs'])
        assert checked['id'] not in revision_bundle['wire_json']
        grant = dict(bundle_id=revision_bundle['id'], bundle_sha256=revision_bundle['bundle_sha256'])
        auth = request(client, 'POST', project + '/writing-authorizations', status=201, key='advisor-auth',
                       json=dict(schema_version=2, confirmed=True, tasks=[dict(logical_task_id='advisor', bundles=[grant])]))
        revised_task = request(client, 'POST', root + '/writing-requests', status=202, key='advisor-write',
                               json=dict(schema_version=2, authorization_id=auth['id'], logical_task_id='advisor', **grant))['task']

        class AdvisorRevision(ThesisFixture):
            def receipt(self):
                result = super().receipt()
                content = result['response']['output'][0]['content'][0]
                output = json.loads(content['text'])
                output['sections'][-1]['paragraphs'][0]['text'] = '根据导师意见补充了合成研究的局限。'
                content['text'] = json.dumps(output)
                return result

        revised_result = run_manuscript_writing_task(revised_task['id'], 1, provider=AdvisorRevision(quote))
        assert revised_result['status'] == 'succeeded', revised_result
        revised_reader = root + '/writing-requests/' + revised_task['id'] + '/draft-reader?revision=1'
        revised = request(client, 'GET', revised_reader)
        assert revised['previous_request_id'] == view['request_id'] and len(revised['changes']) == 1
        assert revised['changes'][0]['heading'] == '4 结论'
        assert revised['changes'][0]['after'] == ['根据导师意见补充了合成研究的局限。']
        assert [entry['request_id'] for entry in request(client, 'GET', project + '/draft-history')['items']] == [
            revised_task['id'], view['request_id']]
        science = review_science(client, path, context, citation)
        options = school_options(checked['chapters'])
        # Editing the first abstract's keywords last appends them after the second.
        options['keywords'].reverse()
        fixed = review_language_and_freeze(client, root, path, science, options)
        provenance = fixed['snapshot']['writing_provenance']
        reviewed_keywords = provenance['school_export_options']['keywords']
        assert {row['chapter_id']: row['values'] for row in reviewed_keywords} == {
            row['chapter_id']: row['values'] for row in options['keywords']
        }
        preview = request(client, 'POST', root + '/versions/2/exports/preview', json={})
        assert preview['school']['options']['keywords'] == reviewed_keywords
        export, ordinary = export_word(client, root, fixed, {}, 'ordinary-word')
        assert export['sha256'] == provenance['school_docx_sha256']
        assert fixed['snapshot']['school_content_report']['scientifically_verified'] is False
        assert export['school']['field_update']['status'] == 'updated' and not export['school']['field_update']['word_verified']
        assert required.isdisjoint(issue['id'] for issue in export['school']['report']['issues'])
        changed = options | dict(field_values=options['field_values'] | dict(author='changed'))
        request(client, 'POST', root + '/versions/2/exports', status=422, key='changed-identity', json=dict(school=changed))
        rejected = request(client, 'POST', root + '/presentations', status=422, key='blind-config', json=dict(
            base_version_id=fixed['id'], config=dict(school=dict(options=options), blind=dict(
                identity_terms=[HEADER_IDENTITY],
            )),
        ))
        assert rejected['detail']['code'] == 'blind_review_removed'
        rejected = request(client, 'POST', root + '/versions/2/exports', status=422, key='blind-word', json=dict(review_mode='blind'))
        assert rejected['detail']['code'] == 'blind_review_removed'
        assert 'presentation' not in export
        assert_historical_blind_export_stays_readable(client, root, fixed, options)
        assert_school_word(ordinary, png, citation[-1], fixed['snapshot']['references'][0]['text'])
        for url in (project + '/thesis-profile', template['sources'][0]['download_url'], root + '/versions/2',
                    export['download_url']):
            assert foreign.get(url).status_code == 404
        adopt_template_update(client, project, root, fixed, template, profile)
        assert client.get(export['download_url']).content == ordinary
        historic = request(client, 'GET', reader + '?revision=1')
        assert historic['draft'] == view['draft'] and not historic['can_revise']
        assert request(client, 'GET', project + '/draft-history')['items'][1]['published_revision'] == 2
        old_word = client.get(reader + '/word?revision=1')
        assert old_word.status_code == 200
        assert old_word.content == school_word.content
