"""Local fixed-version fact-draft DOCX; no source fetching or model processing."""
from datetime import datetime, timezone
import hashlib
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.image.image import Image
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor

from app.core.exceptions import StorageError


RENDERER_VERSION = 'manuscript_docx_v7'
CUSTOMER_RENDERER_VERSION = 'manuscript_docx_v8'
CUSTOMER_NARRATIVE_REVIEW_RENDERER_VERSION = 'manuscript_docx_v9'
CUSTOMER_ARTICLE_RENDERER_VERSION = 'manuscript_docx_v10'
CUSTOMER_RENDERER_VERSIONS = (
    CUSTOMER_RENDERER_VERSION, CUSTOMER_NARRATIVE_REVIEW_RENDERER_VERSION, CUSTOMER_ARTICLE_RENDERER_VERSION,
)

def customer_renderer_version(snapshot):
    if snapshot.get('sections') and not snapshot.get('thesis_context'):
        return CUSTOMER_ARTICLE_RENDERER_VERSION
    if snapshot.get('article_type') == 'narrative_review' and not snapshot.get('thesis_context'):
        return CUSTOMER_NARRATIVE_REVIEW_RENDERER_VERSION
    return CUSTOMER_RENDERER_VERSION


SECTION_LABELS = (
    ('title', 'Title', '标题'),
    ('abstract', 'Abstract', '摘要'),
    ('introduction', 'Introduction', '引言'),
    ('results', 'Results', '结果'),
    ('discussion', 'Discussion', '讨论'),
    ('materials_and_methods', 'Materials and methods', '材料与方法'),
    ('references', 'References', '参考文献'),
)


def _font(style, size):
    style.font.name = 'Arial'
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor(0, 0, 0)
    fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    fonts.set(qn('w:eastAsia'), 'SimSun')
    for key in ('asciiTheme', 'hAnsiTheme', 'eastAsiaTheme', 'cstheme'):
        fonts.attrib.pop(qn('w:' + key), None)


def _document():
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(2.2)
    section.left_margin = section.right_margin = Cm(2.3)
    section.header_distance = section.footer_distance = Cm(1)
    for name, size in (('Normal', 11), ('Title', 18), ('Heading 1', 14),
                       ('Heading 2', 12), ('Heading 3', 11), ('Caption', 10)):
        style = document.styles[name]
        _font(style, size)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.line_spacing = 1.15
    for name in ('Heading 1', 'Heading 2', 'Heading 3'):
        style = document.styles[name]
        style.font.bold = True
        style.paragraph_format.space_before = Pt(12)
        style.paragraph_format.keep_with_next = True
    document.styles['Title'].font.bold = True
    title_properties = document.styles['Title'].element.get_or_add_pPr()
    for border in list(title_properties.findall(qn('w:pBdr'))):
        title_properties.remove(border)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    page = OxmlElement('w:fldSimple')
    page.set(qn('w:instr'), 'PAGE')
    footer._p.append(page)
    # Stable properties and ZIP timestamps support retrying the same input.
    properties = document.core_properties
    properties.author = 'PaperAssist'
    properties.last_modified_by = 'PaperAssist'
    properties.created = properties.modified = datetime(2000, 1, 1, tzinfo=timezone.utc)
    return document


def _paragraph(document, item, bookmark_number):
    paragraph = document.add_paragraph(item['text'])
    identity = str(item['id'])
    start, end = OxmlElement('w:bookmarkStart'), OxmlElement('w:bookmarkEnd')
    start.set(qn('w:id'), str(bookmark_number))
    start.set(qn('w:name'), 'pa_' + hashlib.sha256(identity.encode()).hexdigest()[:32])
    end.set(qn('w:id'), str(bookmark_number))
    paragraph._p.insert(0, start)
    paragraph._p.append(end)


def _table(document, item, *, caption=None):
    document.add_paragraph(item['title'] if caption is None else caption, style='Caption').paragraph_format.keep_with_next = True
    columns = item['columns']
    if not columns or any(len(row) != len(columns) for row in item['rows']):
        raise StorageError('report_render_failed', '稿件表格结构无效。', 422)
    table = document.add_table(rows=1, cols=len(columns))
    table.style = 'Table Grid'
    table.autofit = False
    for column in table.columns:
        column.width = Cm(16.4 / len(columns))
    header = table.rows[0]
    repeat = OxmlElement('w:tblHeader')
    header._tr.get_or_add_trPr().append(repeat)
    for cell, value in zip(header.cells, columns):
        cell.text = str(value)
        for run in cell.paragraphs[0].runs:
            run.bold = True
    for values in item['rows']:
        row = table.add_row()
        # Allow continuation: the pinned PDF converter can otherwise discard
        # remaining rows when a table starts near the bottom of a page.
        for cell, value in zip(row.cells, values):
            cell.text = str(value)
    # Body paragraph spacing can continue alone onto the next page in the
    # pinned converter, creating an empty grid row under the repeated header.
    # Keep cell text splittable (including taller-than-page rows), but do not
    # carry the ordinary prose's trailing gap across a table page boundary.
    for row in table.rows:
        for cell in row.cells:
            cell.paragraphs[0].paragraph_format.space_after = Pt(0)
    document.add_paragraph().paragraph_format.space_after = Pt(0)


def _figure(document, figure, images, en):
    raw = images.get(figure['id'])
    if raw is None:
        raise StorageError('figure_missing', '稿件引用的图片不可用。', 409)
    if hashlib.sha256(raw).hexdigest() != figure['sha256']:
        raise StorageError('figure_changed', '图片与稿件冻结版本不一致。', 409)
    if figure.get('original_image_format') == 'tiff' and not figure.get('language_version_id'):
        from app.adapters.project_images import WORD_MAX_SIDE, tiff_as_png

        raw = tiff_as_png(raw, max_side=WORD_MAX_SIDE)
    elif figure.get('research_member_format') and not figure.get('language_version_id'):
        from app.adapters.research_report_images import as_png
        try:raw=as_png(raw,figure['research_member_format'])
        except (ValueError,OSError) as exc:raise StorageError('figure_changed','研究图件无法按固定格式读取。',409) from exc
    image = Image.from_blob(raw)
    scale = min(6.3 / image.px_width, 6.0 / image.px_height)
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.keep_with_next = True
    paragraph.add_run().add_picture(BytesIO(raw), width=Inches(image.px_width * scale),
                                   height=Inches(image.px_height * scale))
    caption = document.add_paragraph(
        ('Figure ' if en else '图 ') + str(figure['number']) + '  ' + figure['title'], style='Caption')
    caption.paragraph_format.keep_with_next = bool(figure['caption'])
    if figure['caption']:
        document.add_paragraph(figure['caption'], style='Caption')
    for panel in figure.get('panels', []):
        document.add_paragraph(panel['label'] + '  ' + panel['description'], style='Caption')


def _full_sections(snapshot):
    sections = snapshot['sections']
    article = snapshot.get('article_type')
    from app.domain.manuscript_writing.article_contract import STRUCTURES, labels as article_labels, matches_structure
    if article is not None and article not in STRUCTURES:
        raise StorageError('report_render_failed','文章类型不受支持。',422)
    section_labels = article_labels(article, snapshot) if article else SECTION_LABELS
    valid = isinstance(sections, list) and len(sections) == len(section_labels)
    if valid:
        valid = all(isinstance(section, dict) and section.get('id') == labels[0]
                    and isinstance(section.get('paragraphs'), list)
                    for section, labels in zip(sections, section_labels))
    if valid and article == 'narrative_review' and snapshot.get('paper_plan'):
        valid = matches_structure(snapshot)
    if valid:
        paragraphs = [item for section in sections for item in section['paragraphs']]
        valid = all(isinstance(item, dict) and isinstance(item.get('id'), str) and item['id']
                    and isinstance(item.get('text'), str) for item in paragraphs)
        valid = valid and len({item['id'] for item in paragraphs}) == len(paragraphs)
        title = sections[0]['paragraphs']
        valid = valid and len(title) == 1 and title[0]['text'] == snapshot['title']
    if not valid:
        raise StorageError('report_render_failed', '完整稿件章节或标题结构无效。', 422)
    return sections


def _references(document, snapshot, en, *, required=False):
    adapted = snapshot.get('journal_display_context', {}).get('frontiers_review', {}).get('reference_texts')
    for index, reference in enumerate(snapshot['references']):
        number = str(reference['number'])
        text = '(' + number + ') ' + reference['text'] if adapted is None else number + '. ' + adapted[index]
        document.add_paragraph(text)
    if required and not snapshot['references']:
        document.add_paragraph('No verified references have been selected; further material is required.'
                               if en else '尚未选择已核实参考文献，待补充。')


def _keywords(document, snapshot, en):
    if snapshot.get('keywords'):
        document.add_paragraph(('Keywords: ' if en else '关键词：')
                               + ('; ' if en else '；').join(snapshot['keywords']))


def _full_body(document, snapshot, sections, images, en, excluded_chapter_ids=frozenset()):
    from app.domain.manuscript_writing.article_contract import illustration_groups, labels as article_labels

    bookmark_number = 0
    planned_review = snapshot.get('paper_plan', {}).get('kind') == 'narrative_review'
    submission_layout = snapshot.get('journal_display_context', {}).get('frontiers_review', {}).get('submission_layout')
    if snapshot.get('journal_display_context') and snapshot.get('article_type', 'research') in ('research', 'narrative_review'):
        from app.domain.journals.display import display_sections
        projected=display_sections(snapshot)[1:]
    else:
        labels_for = article_labels(snapshot['article_type'], snapshot) if snapshot.get('article_type') else SECTION_LABELS
        projected=[dict(section,display_name=labels[1 if en else 2], heading_level=section.get('level', 1))
                   for section,labels in zip(sections[1:],labels_for[1:])]
    for section in projected:
        if section['id'] in excluded_chapter_ids or planned_review and section.get('parent_id') in excluded_chapter_ids:continue
        document.add_heading(section['display_name'], section.get('heading_level', 1))
        if section['id'] == 'references':
            _references(document, snapshot, en, required=True)
            continue
        for item in section['paragraphs']:
            bookmark_number += 1
            _paragraph(document, item, bookmark_number)
        if section['id'] == 'abstract':
            _keywords(document, snapshot, en)
        if not (submission_layout and planned_review):
            # The sections are the writing text; original result paragraphs
            # remain frozen evidence and must not replace a rewritten section.
            for group in illustration_groups(snapshot, section):
                if section['id'] == 'results' and not group.get('illustration_chapter_id') and (group['tables'] or group['figures']):
                    document.add_heading(group['title'], 2)
                for table in group['tables']:
                    _table(document, table)
                for figure in group['figures']:
                    _figure(document, figure, images, en)
    if snapshot.get('acknowledgements') and 'acknowledgements' not in excluded_chapter_ids:
        document.add_heading('Acknowledgements' if en else '致谢', 1)
        document.add_paragraph(snapshot['acknowledgements'])


def revised_manuscript_filename(snapshot):
    thesis = bool(snapshot.get('thesis_context'))
    if snapshot['output_language'] == 'en':
        return ('Revised thesis' if thesis else 'Revised manuscript') + '.docx'
    return ('毕业论文' if thesis else 'SCI论文') + '修订稿.docx'


def _reader_material_label(source, en):
    if source['kind'] in ('analysis_report', 'collection_report'):
        title = (source.get('content') or {}).get('title')
        return title or ('Analysis report' if en else '分析报告')
    if source['label'] and source['label'] not in (source['id'], source['sha256']):
        return source['label']
    return 'Source material' if en else '来源资料'


def _append_customer_review(document, snapshot, issues):
    from app.domain.manuscript_writing.context import normalize_sections
    from app.domain.review_rounds.document_display import customer_location, localized, section_label

    language = snapshot['output_language']
    en = language == 'en'
    review = snapshot['review']
    locations = {source['id']: _reader_material_label(source, en) for source in snapshot['sources']}
    for section in normalize_sections(snapshot):
        identity = section['id']
        title = section.get('title') or section_label(identity, language, snapshot.get('article_type'))
        if title:
            locations[identity] = title
        for number, paragraph in enumerate(section['paragraphs'], 1):
            locations[paragraph['id']] = customer_location(dict(kind='paragraph', section_id=identity,
                section_title=title, paragraph_number=number), language)
    for group in snapshot['results_groups']:
        for figure in group['figures']:
            caption = ('Figure ' if en else '图 ') + str(figure['number'])
            locations[figure['id']] = locations['caption:' + figure['id']] = caption

    def append(label, *parts):
        content = ' — '.join(part for part in parts if part)
        if content:
            document.add_paragraph(label + ' — ' + content if label else content)

    document.add_heading('Review notes' if en else '复核说明', 1)
    statuses = {'supplied': ('Supplied', '已提供'), 'selected': ('Selected', '已选用'),
                'pending': ('Pending', '待补充'), 'not_applicable': ('Not applicable', '不适用')}
    fields = {'unit': ('Unit', '单位'), 'display_precision': ('Display precision', '显示精度'),
              'object': ('Study object', '研究对象'), 'group': ('Group', '组别'), 'acronym': ('Abbreviation', '缩写'),
              'statistical_mark': ('Statistical notation', '统计标记'), 'error_bar': ('Error bars', '误差线')}
    for record in review['decisions']:
        status = localized(statuses.get(record['status'], ('Review item', '复核事项')), language)
        append(locations.get(record['target_id']), status, record['value'], record['reason'], record['evidence'])
    for item in review['metadata']:
        field = localized(fields.get(item['field'], ('Detail', '说明')), language)
        stale = ('New material requires renewed confirmation.' if en else '新资料需重新确认。') if item.get('stale') else ''
        append(locations.get(item['target_id']), field + ' ' + item['value'], item['evidence'], stale)
    for item in review['addendum']:
        document.add_paragraph(item['text'])
    for association in review['relationships']['associations']:
        related = association['method_ids'] + association['paragraph_ids'] + association['figure_ids']
        append(association['research_question'], ', '.join(locations[key] for key in related if key in locations), association['evidence'])
    for impact in review['report']['impacts']:
        source = locations.get(impact['source_id'])
        affected = ', '.join(locations[key] for key in impact['locations'] if key in locations)
        if source or affected:
            append('Items affected by the source change' if en else '资料变更影响', source, affected)
    seen = {item['message'] for item in issues}
    for item in review['report']['issues']:
        if item['message'] in seen:
            continue
        seen.add(item['message'])
        append(locations.get(item['location']), item['message'])


def build_manuscript_docx(snapshot, images, *, school_plan=None, source_map=None, excluded_chapter_ids=frozenset(),
                          customer_revision=False, customer_view=False, renderer_version=None, school_template=None):
    """Render only the frozen snapshot, retaining unresolved facts and original images."""
    from app.domain.journals.display import legacy_revision_without_journal_display
    snapshot=legacy_revision_without_journal_display(snapshot)
    if snapshot.get('schema_version') != 1 or snapshot.get('output_language') not in ('zh-CN', 'en'):
        raise StorageError('report_render_failed', '稿件版本格式不受支持。', 422)
    if snapshot.get('review'):
        report=snapshot['review']['report']
        if not report.get('can_publish') or any(i['severity']=='error' for i in report['issues']):
            raise StorageError('manuscript_review_blocked', '评审候选存在不可豁免的一致性问题，不能导出。', 409)
    if snapshot.get('illustration_check_version') is not None:
        from app.domain.manuscripts.illustrations import check_bindings
        if snapshot['illustration_check_version'] != 1 or check_bindings(snapshot['results_groups'], snapshot['output_language']):
            raise StorageError('report_render_failed', '正文图表引用与冻结编号或分面不一致，请核对后另存版本。', 422)
    school=bool(snapshot.get('thesis_context'))
    sections = snapshot['sections'] if school else _full_sections(snapshot) if 'sections' in snapshot else None
    if sections:
        from app.domain.manuscripts.illustrations import check_references, rendered_groups
        existing={(i['id'],tuple(i.get('values',[]))) for i in snapshot.get('issues',[])}
        unresolved=check_references(rendered_groups(snapshot),snapshot['output_language'])
        if any((i['id'],tuple(i['values'])) not in existing for i in unresolved):
            raise StorageError('report_render_failed', '完整稿正文出现未记录的图表或分面对应问题，请核对后另存版本。', 422)
    if school:
        if school_plan is None:raise StorageError('school_export_input_invalid','学校导出缺少固定排版配置。',422)
        from .school_docx import build_school_docx
        return build_school_docx(snapshot,images,school_plan,source_map=source_map,excluded_chapter_ids=excluded_chapter_ids,
                                 customer_revision=customer_revision,school_template=school_template)
    customer_view = customer_view or customer_revision
    document = _document()
    frontiers_layout = {}
    if snapshot.get('journal_display_context'):
        from app.domain.journals.display import context
        display = context(snapshot)
        styles = display['styles']
        frontiers_layout = display.get('frontiers_review', {})
        has_themes = snapshot.get('paper_plan', {}).get('kind') == 'narrative_review'
        for scope,names in [('body',('Normal',)),('heading',('Heading 1','Heading 2') if has_themes else ('Heading 1',))]:
            for name in names:
                style=document.styles[name]
                for field in ('font_size_pt','line_spacing','space_before_pt','space_after_pt'):
                    value=styles.get(scope+'_'+field)
                    if value is None:continue
                    if field=='font_size_pt':style.font.size=Pt(value)
                    else:setattr(style.paragraph_format,field.removesuffix('_pt'),Pt(value) if field.endswith('_pt') else value)
    en = snapshot['output_language'] == 'en'
    if 'title' not in excluded_chapter_ids:
        document.add_heading(snapshot['title'], level=sections[0].get('level', 0) if sections else 0)
    submission = None
    if frontiers_layout.get('submission_layout'):
        from app.domain.journals.frontiers_review import submission_content
        submission = submission_content(snapshot, excluded_chapter_ids)
        document.add_paragraph(
            f"Word count: {submission['words']} | Figures: {len(submission['figures'])} | Tables: {len(submission['tables'])}"
        )
    if customer_view and not sections:
        document.add_paragraph('This draft contains results and methods. The remaining sections are pending.'
                               if en else '本稿包含结果与方法，其余章节待补充。')
    elif not customer_view:
        document.add_paragraph(snapshot['notice'])
    if not customer_view and snapshot.get('journal_adaptation_provenance', {}).get('synthetic'):
        notice = ('Synthetic journal adaptation: synthetic guide or manuscript inputs were used. '
                  'This export is offline engineering evidence, not verified real journal compliance.'
                  if en else
                  '合成期刊适配：使用了合成指南或稿件输入。本导出仅为离线工程证据，不代表真实期刊要求已核验通过。')
        document.add_paragraph().add_run(notice).bold = True
    document.sections[0].header.paragraphs[0].text = (
        ('Revised manuscript' if en else 'SCI论文修订稿') if customer_revision else
        ('Manuscript' if en else 'SCI论文') if customer_view and sections else
        ('SCI manuscript draft' if en else 'SCI论文初稿') if sections else ('Research fact draft' if en else '研究事实稿'))
    bookmark_number = 0
    if sections:
        _full_body(document, snapshot, sections, images, en, excluded_chapter_ids)
    else:
        if snapshot.get('paper_plan') and 'abstract' not in excluded_chapter_ids:
            _keywords(document, snapshot, en)
        if 'results' not in excluded_chapter_ids:document.add_heading('Results' if en else '结果', 1)
        for group in snapshot['results_groups'] if 'results' not in excluded_chapter_ids else []:
            document.add_heading(group['title'], 2)
            for item in group['paragraphs']:
                bookmark_number += 1
                _paragraph(document, item, bookmark_number)
            for table in group['tables']:
                _table(document, table)
            for figure in group['figures']:
                _figure(document, figure, images, en)
        if 'materials_and_methods' not in excluded_chapter_ids:document.add_heading('Materials and methods' if en else '材料与方法', 1)
        for item in snapshot['methods'] if 'materials_and_methods' not in excluded_chapter_ids else []:
            bookmark_number += 1
            _paragraph(document, item, bookmark_number)
        if snapshot['references'] and 'references' not in excluded_chapter_ids:
            document.add_heading('References' if en else '参考文献', 1)
            _references(document, snapshot, en)
    customer_article = customer_view and renderer_version == CUSTOMER_ARTICLE_RENDERER_VERSION
    submission_article = customer_article and submission is not None
    issues = [] if submission_article else snapshot['issues']
    if customer_view:
        issues = [issue for issue in issues if issue['id'] != 'scope' or issue['message'] != snapshot['notice']]
        if customer_article:
            internal_limits = {prefix + source['id'] for source in snapshot['sources']
                               for prefix in ('uncomputed:', 'origin:')}
            issues = [issue for issue in issues if issue['id'] not in internal_limits]
        if (snapshot.get('article_type') == 'narrative_review'
                and renderer_version in (None, CUSTOMER_NARRATIVE_REVIEW_RENDERER_VERSION, CUSTOMER_ARTICLE_RENDERER_VERSION)):
            from app.domain.manuscripts.contracts import METHOD_FIELDS
            original_study_fields = {*METHOD_FIELDS, 'results'}
            issues = [issue for issue in issues if not (
                issue['kind'] == 'missing' and issue['field'] in original_study_fields
                and issue['id'] == 'missing:' + issue['field']
            )]
    if issues:
        document.add_heading('Items requiring review or additional material' if en else '待补充与待核实事项', 1)
        for issue in issues:
            document.add_paragraph(issue['message'])
            if issue.get('values'):
                document.add_paragraph(('Conflicting records: ' if en else '相互矛盾的记录：')
                                       + ' / '.join(issue['values']))
    if not submission_article and snapshot.get('review') and customer_view:
        _append_customer_review(document, snapshot, issues)
    elif not customer_view and snapshot.get('review'):
        review=snapshot['review']
        document.add_heading('Material confirmations and consistency review' if en else '资料确认与一致性复核',1)
        document.add_paragraph('User confirmation is not scientific verification. Original source bindings remain frozen; semantic correctness requires researcher review.'
                               if en else '用户确认不等于科研验证。原始来源绑定保持冻结；正文含义仍需研究人员核实。')
        for record in review['decisions']:
            document.add_paragraph(record['target_id']+' — '+record['status']+': '+record['value'])
            document.add_paragraph(('Reason / evidence: ' if en else '理由／证据：')+record['reason']+' / '+record['evidence'])
        for item in review['metadata']:
            text=item['target_id']+' — '+item['field']+': '+item['value']+'; '+item['evidence']
            if item.get('stale'):
                text+=' — '+('Stale confirmation: applies only to the original frozen fact; new material requires renewed confirmation.'
                             if en else '确认已过期：仅适用于原冻结事实；新资料须重新确认。')
            document.add_paragraph(text)
        for item in review['addendum']:
            document.add_paragraph(item['text'])
        for association in review['relationships']['associations']:
            document.add_paragraph(association['research_question']+' — '+', '.join(association['method_ids']+association['paragraph_ids']+association['figure_ids'])+'; '+association['evidence'])
        for impact in review['report']['impacts']:
            document.add_paragraph(('Impact pending review: ' if en else '影响待核对：')+impact['source_id']+' — '+', '.join(impact['locations']))
        # Preserve every distinct frozen caveat, including material and
        # uncertainty details that the general notice cannot replace. Exact
        # original issues (including their values) were already shown above.
        seen={(item['id'],item['message']) for item in snapshot['issues']}
        for item in review['report']['issues']:
            key=(item['location'],item['message'])
            if key in seen: continue
            seen.add(key)
            document.add_paragraph(item['location']+' — '+item['message'])
    if snapshot['sources'] and not customer_article:
        document.add_heading('Selected source materials' if en else '所选来源资料', 1)
        description = None
        if not customer_view:
            description = document.add_paragraph(
                'The saved manuscript workspace retains the exact source versions. User declarations, image observations and literature findings are separate from computed research results.'
                if en else '工作台中保留了此稿件的确切来源版本。用户声明、图像观察及文献发现与本研究计算结果分别记录。')
        seen = set()
        labels = []
        for source in snapshot['sources']:
            label = _reader_material_label(source, en) if customer_view else source['label']
            if label not in seen:
                labels.append(label)
                seen.add(label)
        materials = document.add_paragraph(('\n' if customer_view else '; ' if en else '；').join(labels))
        paragraphs = (description, materials) if description else (materials,)
        for paragraph in paragraphs:
            paragraph.paragraph_format.line_spacing = 1
            paragraph.paragraph_format.space_after = Pt(3)
            paragraph.paragraph_format.keep_together = True
            for run in paragraph.runs:
                run.font.size = Pt(10)
        if description:
            description.paragraph_format.keep_with_next = True
    if submission is not None:
        _frontiers_illustrations(document, submission)
    if frontiers_layout:
        _frontiers_word(document, frontiers_layout)
    return _save_document(document)


def _frontiers_illustrations(document, submission):
    from app.domain.journals.frontiers_review import caption_text

    if submission['figures']:
        document.add_heading('Figure captions', 1)
        for figure in sorted(submission['figures'], key=lambda item: item['number']):
            title = caption_text(figure, 'Figure')
            description = caption_text(figure, 'Figure', 'caption')
            legend = ' '.join(dict.fromkeys(text for text in (title, description) if text))
            p = document.add_paragraph(f"Figure {figure['number']}. {legend}".rstrip(), style='Caption')
            for panel in figure.get('panels', []):
                p.add_run(' ')
                label = panel['label'].strip().strip('()')
                p.add_run(f'({label})').bold = True
                p.add_run(' ' + panel['description'])
    if submission['tables']:
        document.add_heading('Tables', 1)
        document.add_paragraph()
        for table in sorted(submission['tables'], key=lambda item: item['number']):
            title = caption_text(table, 'Table')
            _table(document, table, caption=f"Table {table['number']}. {title}".rstrip())


def _frontiers_word(document, layout):
    single = layout.get('single_spacing')
    if single:
        from docx.enum.style import WD_STYLE_TYPE
        for style in document.styles:
            if style.type == WD_STYLE_TYPE.PARAGRAPH:
                style.paragraph_format.line_spacing = 1
    for section in document.sections:
        if layout.get('page_line_numbers'):
            line_numbers = OxmlElement('w:lnNumType')
            line_numbers.set(qn('w:countBy'), '1')
            line_numbers.set(qn('w:restart'), 'continuous')
            section._sectPr.insert_element_before(line_numbers, 'w:pgNumType', 'w:cols', 'w:formProt', 'w:vAlign',
                                                  'w:noEndnote', 'w:titlePg', 'w:textDirection', 'w:bidi',
                                                  'w:rtlGutter', 'w:docGrid')
    if single:
        for part in (document.part, *document.part.related_parts.values()):
            if part.content_type not in ('application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml',
                                         'application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml',
                                         'application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml'):
                continue
            for paragraph in part.element.iter(qn('w:p')):
                spacing = paragraph.get_or_add_pPr().get_or_add_spacing()
                spacing.set(qn('w:line'), '240')
                spacing.set(qn('w:lineRule'), 'auto')


def _save_document(document):
    stream = BytesIO()
    document.save(stream)
    stable = BytesIO()
    with ZipFile(BytesIO(stream.getvalue())) as original, ZipFile(stable, 'w', ZIP_DEFLATED) as result:
        for item in original.infolist():
            entry = ZipInfo(item.filename, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            result.writestr(entry, original.read(item.filename))
    return stable.getvalue()
