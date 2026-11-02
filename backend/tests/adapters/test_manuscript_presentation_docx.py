"""W2 derived documents preserve fixed prose and original artifacts."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

from docx import Document
import pytest

from tests.adapters.test_manuscript_docx import sample


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def config():
    return dict(paragraph_groups=[], terminology=[], figure_pairs=[], school=None,
                authors=[], affiliations=[], statements=[],
                blind=dict(identity_terms=[], hidden_chapter_ids=[], exceptions=[], manual_image_review=False))


def test_bilingual_derived_prose_is_adjacent_preserves_numbers_and_unpaired_text():
    from app.adapters.manuscript_docx import build_manuscript_docx
    from app.adapters.manuscript_presentation_docx import decorate_docx
    zh, images = sample('zh-CN'); en, _ = sample('en')
    zh['results_groups'][0]['paragraphs'][0]['text'] = '样本量 (1)，观测值为 0.0123。仅描述性结果。'
    en['results_groups'][0]['paragraphs'][0]['text'] = 'Sample size (1), observed value 0.0123. Descriptive results only.'
    en['methods'][0]['text'] = 'Provided method; no independent replication.'
    frozen = deepcopy((zh, en))
    c = config(); c['paragraph_groups'] = [
        dict(id='result', zh_ids=['group-1-result'], en_ids=['group-1-result'], status='paired'),
        dict(id='missing', zh_ids=[], en_ids=['methods-study_design'], status='missing')]
    raw = build_manuscript_docx(zh, images)
    derived, report = decorate_docx(raw, zh, en, c, 'zh-CN-en', 'identified')
    paragraphs = [p.text for p in Document(BytesIO(derived)).paragraphs]
    index = paragraphs.index(zh['results_groups'][0]['paragraphs'][0]['text'])
    assert paragraphs[index+1] == en['results_groups'][0]['paragraphs'][0]['text']
    assert en['methods'][0]['text'] in paragraphs
    assert '(1)' in paragraphs[index+1] and '0.0123' in paragraphs[index+1]
    assert any(i['target_language'] == 'en' and i['text'] == paragraphs[index+1] for i in report['language_inventory'])
    assert (zh, en) == frozen
    assert raw != derived


def test_blind_removes_split_identity_from_body_header_properties_and_comment_keeps_original():
    from app.adapters.manuscript_presentation_docx import blind_docx, inspect_docx
    from app.adapters.document_layout.package import read_package, write_package
    document = Document(); p = document.add_paragraph()
    p.add_run('作者：张'); p.add_run('三；n = 12')
    document.sections[0].header.paragraphs[0].text = '张三的论文'
    document.core_properties.author = '张三'
    stream = BytesIO(); document.save(stream)
    parts = read_package(stream.getvalue())
    parts['word/comments.xml'] = b'<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:comment w:id="0" w:author="\xe5\xbc\xa0\xe4\xb8\x89"><w:p><w:r><w:t>\xe5\xbc\xa0\xe4\xb8\x89</w:t></w:r></w:p></w:comment></w:comments>'
    original = write_package(parts)
    rules = config()['blind'] | {'identity_terms': ['张三']}
    derived, report = blind_docx(original, rules)
    assert report['known_identity_check'] == 'passed'
    assert inspect_docx(derived, rules)['remaining'] == []
    with ZipFile(BytesIO(original)) as z:
        assert '张三' in z.read('docProps/core.xml').decode()
    doc = Document(BytesIO(derived))
    assert 'n = 12' in doc.paragraphs[0].text
    assert '张三' not in doc.paragraphs[0].text
    assert doc.core_properties.author != '张三'


def test_image_identity_is_explicitly_pending_even_when_known_text_is_removed():
    from app.adapters.manuscript_docx import build_manuscript_docx
    from app.adapters.manuscript_presentation_docx import blind_docx
    snapshot, images = sample('zh-CN')
    _, report = blind_docx(build_manuscript_docx(snapshot, images), config()['blind'])
    assert report['images'] == 'pending_manual_review'
    assert report['anonymity_verified'] is False


def test_school_hidden_chapter_is_selected_by_identity_and_other_chapters_survive():
    from tests.adapters.test_school_docx import fixture, plan
    from app.adapters.school_docx import build_school_docx
    snapshot, analysis = fixture()
    school_plan = plan(snapshot, analysis, include_toc=False,
                       manual_chapters=[dict(chapter_id='declaration', text='PRIVATE DECLARATION')])
    original = deepcopy((snapshot, school_plan))
    raw = build_school_docx(snapshot, {}, school_plan, excluded_chapter_ids={'declaration'})
    text = '\n'.join(p.text for p in Document(BytesIO(raw)).paragraphs)
    assert 'PRIVATE DECLARATION' not in text and 'Declaration' not in text
    assert 'Study process' in text and 'n = 12' in text
    assert (snapshot, school_plan) == original


def test_bilingual_figure_reuses_same_png_and_original_table_with_both_captions():
    from app.adapters.manuscript_docx import build_manuscript_docx
    from app.adapters.manuscript_presentation_docx import decorate_docx
    zh,images=sample('zh-CN');en,_=sample('en')
    en['results_groups'][0]['figures'][0]['caption']='Saved English caption; exploratory only.'
    c=config();c['figure_pairs']=[dict(figure_id='pair',zh_figure_id='figure-1',en_figure_id='figure-1')]
    raw,_=decorate_docx(build_manuscript_docx(zh,images),zh,en,c,'zh-CN-en','identified',peer_images=images)
    doc=Document(BytesIO(raw));text='\n'.join(p.text for p in doc.paragraphs)
    assert 'Saved English caption; exploratory only.' in text and 'CAPTION-SENTINEL' in text
    assert len(doc.inline_shapes)==1 and doc.tables[0].cell(2,1).text=='5.24'
    with ZipFile(BytesIO(raw)) as archive:
        assert [archive.read(n) for n in archive.namelist() if n.startswith('word/media/')]==[images['figure-1']]


def test_actual_whole_count_includes_supplied_material_but_excludes_header_and_other_language():
    from app.domain.manuscripts.presentation_export import actual_checks
    limit=dict(scope='whole',language='zh-CN',unit='words',kind='minimum',value=3)
    context=dict(preview=dict(config=dict(school=dict(length_requirements=[limit])),checks=[dict(code='school:length:0',status='pending')]))
    inventory=[dict(location='word/document.xml:paragraph:1',text='结果 ABC',target_language='zh-CN'),
               dict(location='word/document.xml:paragraph:2',text='English abstract words',target_language='en'),
               dict(location='word/header1.xml:paragraph:0',text='不能算入的页眉',target_language='zh-CN')]
    check=actual_checks(context,inventory)[0]
    assert check['actual']==3 and check['status']=='passed'
    assert check['count_projection']['count_method']=='zh_hanzi_latin'
    assert 'statements' in check['count_projection']['includes']
    assert 'headers_footers' in check['count_projection']['excludes']
    assert context['preview']['checks'][0]['status']=='pending'


def test_sci_blind_hides_selected_section_in_both_languages_without_restoring_unmapped_peer():
    from app.adapters.manuscript_docx import build_manuscript_docx, SECTION_LABELS
    from app.adapters.manuscript_presentation_docx import decorate_docx
    zh,images=sample('zh-CN');en,_=sample('en')
    for snapshot in (zh,en):
        snapshot['sections']=[dict(id=key,paragraphs=[]) for key,_,_ in SECTION_LABELS]
        snapshot['sections'][0]['paragraphs']=[dict(id='title',text=snapshot['title'],source_ids=[],citations=[],origin='user_provided')]
        snapshot['sections'][2]['paragraphs']=[dict(id='identity-intro',text='PRIVATE-AFFILIATION-'+snapshot['output_language'],source_ids=[],citations=[],origin='user_provided')]
        snapshot['acknowledgements']='PRIVATE-THANKS'
    c=config();c['blind']['hidden_chapter_ids']=['introduction','acknowledgements']
    excluded=set(c['blind']['hidden_chapter_ids'])
    raw=build_manuscript_docx(zh,images,excluded_chapter_ids=excluded)
    assert 'PRIVATE-AFFILIATION' not in '\n'.join(p.text for p in Document(BytesIO(raw)).paragraphs)
    result,_=decorate_docx(raw,zh,en,c,'zh-CN-en','blind',excluded_chapter_ids=excluded)
    text='\n'.join(p.text for p in Document(BytesIO(result)).paragraphs)
    assert 'PRIVATE-AFFILIATION' not in text and 'PRIVATE-THANKS' not in text
    assert '合成队列样例' in text and 'Synthetic cohort' in text


def test_actual_language_rule_conflicts_and_unreviewed_images_are_not_accepted_as_human_review():
    from app.adapters.manuscript_presentation_docx import language_observations
    items=[dict(kind='export_text',location='p:1',text='整段中文不能作为英文正文通过。',content_sha256='a'*64,target_language='en',scope='narrative'),
           dict(kind='export_text',location='p:2',text='Author Name',content_sha256='b'*64,target_language='zh-CN',scope='label',protected_identity=True),
           dict(kind='image',location='image:1',text='',content_sha256='c'*64,target_language='en',language_known=False,no_text=False)]
    result=language_observations(items)
    assert [i['finite_check']['status'] for i in result]==['conflict','pending','pending']
    assert result[0]['verification']=='pending_manual_review'
    assert 'finite_check' not in items[0]


def test_school_decoration_keeps_layout_manifest_and_fixed_toc_targets():
    from tests.adapters.test_school_docx import fixture, plan
    from app.adapters.school_docx import build_school_docx
    from app.adapters.manuscript_presentation_docx import decorate_docx
    from docx.oxml.ns import qn
    snapshot, analysis = fixture()
    raw = build_school_docx(snapshot, {}, plan(snapshot, analysis))
    derived, _ = decorate_docx(raw, snapshot, None, config(), 'zh-CN', 'identified')
    with ZipFile(BytesIO(raw)) as before, ZipFile(BytesIO(derived)) as after:
        assert after.read('customXml/paperassist-layout.xml') == before.read('customXml/paperassist-layout.xml')
    heading = next(p for p in Document(BytesIO(derived)).paragraphs if p.text == 'Authorship and declarations')
    assert heading.style.name == 'PaperAssist display Heading 1'
    assert heading.style.base_style.name == 'Normal'
    original = Document(BytesIO(raw))
    source_style = original.styles['Heading 1']
    assert heading.style.element.find(qn('w:rPr')).xml == source_style.element.find(qn('w:rPr')).xml
    for child in source_style.element.find(qn('w:pPr')):
        if child.tag != qn('w:outlineLvl'):
            assert heading.style.element.find(qn('w:pPr')).find(child.tag).xml == child.xml
    confirmed = next(p for p in original.paragraphs if p.style.name == 'Heading 1')
    retained = next(p for p in Document(BytesIO(derived)).paragraphs if p.text == confirmed.text)
    assert retained._p.xml == confirmed._p.xml
    assert heading._p.find('./'+qn('w:pPr')+'/'+qn('w:outlineLvl')).get(qn('w:val')) == '9'


def test_actual_image_inventory_retains_both_known_language_assets_with_same_figure_id():
    from hashlib import sha256
    from app.adapters.document_layout.package import read_package, write_package
    from app.adapters.manuscript_presentation_docx import actual_image_inventory
    document = Document(); stream = BytesIO(); document.save(stream)
    parts = read_package(stream.getvalue())
    records = []
    for language in ('zh-CN', 'en'):
        data = ('saved-image-'+language).encode()
        parts['word/media/'+language+'.png'] = data
        records.append(dict(location='image:figure-1', kind='image', asset_sha256=sha256(data).hexdigest(),
                            target_language=language, language_known=True, no_text=False))
    inventory = actual_image_inventory(write_package(parts), records, 'zh-CN')
    assert len(inventory) == 2 and all(i['language_known'] for i in inventory)
    assert len({i['location'] for i in inventory}) == 2
    assert records[0]['location'] == records[1]['location'] == 'image:figure-1'
