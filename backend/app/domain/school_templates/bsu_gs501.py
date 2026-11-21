"""Explicit formatting selection for the official GS501 academic master's DOCX."""
from datetime import date
import re


PROFILE = 'bsu-gs501-academic-masters-2026'
TEMPLATE_SHA256 = '1e9d38b307dbef8c3bf97b85ba5def70eaf7e2dba50cf25da978e007fc907059'
SOURCE_PAGE = 'https://grs.bsu.edu.cn/cyxz/11439.htm'
GUIDE = '北京体育大学研究生学位论文撰写规范'
SUBMISSION_FORMS_RENDERER = 'bsu_gs501_submission_v1'
ORIGINALITY_TITLE = '北京体育大学学位论文原创性声明'
AUTHORIZATION_TITLE = '北京体育大学学位论文使用授权书'
TIMES = 'Times New Roman'
SONG = '宋体'

FORM_FIELD_LABELS = {
    '论文作者': 'author', '作者姓名': 'author', '姓名': 'author', '学号': 'student_id',
    '指导教师': 'supervisor', '导师姓名': 'supervisor',
    '培养单位': 'college', '一级学科': 'discipline', '二级学科': 'specialty',
    '申请学位': 'degree', '提交日期': 'submission_date', '年月': 'submission_date',
}
COMMITTEE_ROLES = ('主席', '评阅人', '委员', '秘书')
COMMITTEE_COLUMNS = ('name', 'title', 'office')
COMMITTEE_LABELS = {'': 'name', '姓名': 'name', '职称': 'title', '技术职称': 'title', '所在单位': 'office', '单位': 'office'}
FORM_SECTION_TITLES = {'section-3': ORIGINALITY_TITLE, 'section-4': AUTHORIZATION_TITLE}


def available(sources):
    return any(source['role'] == 'template' and source['sha256'] == TEMPLATE_SHA256 for source in sources)


def selected(snapshot):
    return (snapshot.get('thesis_context') or {}).get('confirmation', {}).get('format_profile') == PROFILE


def read_submission_template(assets, snapshot):
    """Read the retained upload using its sealed project object descriptor."""
    from app.adapters.task_store import source_conflict

    context = snapshot['thesis_context']
    template = next((source for source in context['source_files']
                     if source['role'] == 'template' and source['sha256'] == TEMPLATE_SHA256), None)
    if not selected(snapshot) or not template or template['file']['sha256'] != TEMPLATE_SHA256:
        raise source_conflict()
    return assets.original(template['file'])


def reviewed_submission_forms(proof):
    return (proof or {}).get('docx_renderer_version', '').endswith('+' + SUBMISSION_FORMS_RENDERER)


def submission_chapter(chapter, front):
    """Match declaration chapters already represented by the official pages."""
    if chapter['purpose'] != 'manual':
        return None
    title = re.sub(r'\s+', '', chapter['title'])
    if title in FORM_SECTION_TITLES.values():
        return title
    return next((FORM_SECTION_TITLES[field['section_id']] for field in (front or {}).get('fields', [])
                 if field['kind'] == 'signature' and field['chapter_id'] == chapter['id']
                 and field['section_id'] in FORM_SECTION_TITLES), None)


def form_field(field, source):
    for raw in (field['label'], source.get('suggested_label') or ''):
        label = re.sub(r'\s+', '', raw)
        key = FORM_FIELD_LABELS.get(label)
        if key:
            return key
        if field['section_id'] == 'section-2':
            label = label.removeprefix('答辩委员会')
            for role in COMMITTEE_ROLES:
                column = COMMITTEE_LABELS.get(label.removeprefix(role)) if label.startswith(role) else None
                if column:
                    return f'committee:{role}:{column}'
    return None


def submission_values(plan):
    values = {}
    options = plan['options']
    if plan.get('front_matter') is None:
        values = {key: value.strip() for key, value in options.get('manual_fields', {}).items()
                  if key in ('author', 'student_id', 'supervisor', 'submission_date')}
        values['college'] = options.get('manual_fields', {}).get('department', '').strip()
    for field in (plan.get('front_matter') or {}).get('fields', []):
        key = form_field(field, plan['front_matter_sources'][field['source_id']])
        value = options.get('field_values', {}).get(field['id'], '').strip()
        if key and value and field['section_id'] in ('section-1', 'section-2'):
            values.setdefault(key, ' '.join(value.split()))
    return values


def submission_month(value):
    if not value:
        return ''
    match = re.fullmatch(r'(\d{4})\s*[-年/]\s*(\d{1,2})(?:\s*[-月/]\s*(\d{1,2})\s*日?|\s*月)?', value)
    if match is None:
        return ''
    try:
        supplied = date(int(match[1]), int(match[2]), int(match[3] or 1))
    except ValueError:
        return ''
    return f'{supplied.year:04d} 年 {supplied.month:02d} 月'


def guide_source(page, text):
    return dict(part=GUIDE, path=f'印刷页 {page}', text=text)


def apply_styles(styles, sources):
    """Select Western faces by role while retaining the Chinese styles."""
    english_text = dict(font_latin=TIMES, font_size_pt=12, line_spacing='360', line_rule='auto')
    rules = {
        'body': (15, '正文西文用 Times New Roman。', dict(font_latin=TIMES)),
        'abstract_body_en': (28, '英文摘要正文使用 Times New Roman 小四、1.5 倍行距。', english_text),
        'keywords_en': (28, '英文关键词使用 Times New Roman 小四、1.5 倍行距，Key Words 加粗。', english_text),
        'reference_entry': (15, '参考文献正文宋体五号，西文使用 Times New Roman 五号，单倍行距。',
            dict(font_latin=TIMES, font_east_asia=SONG, font_size_pt=10.5, line_spacing='240', line_rule='auto')),
    }
    for name, (page, message, values) in rules.items():
        styles.setdefault(name, {}).update(values)
        sources.setdefault(name, {}).update({key: guide_source(page, message) for key in values})
    # The guide gives the shipped template precedence on conflicting type.
    for name, paragraph, message, values in (
        ('title_en', 25, '题名页英文题目使用 Times New Roman 三号。', dict(font_latin=TIMES, font_size_pt=16)),
        ('abstract_heading_en', 78, 'ABSTRACT 标题的西文字体为原模板直接指定的黑体，二号。',
            dict(font_latin='黑体', font_size_pt=22, line_spacing='240', line_rule='auto', alignment='center', space_after_lines='100')),
    ):
        styles.setdefault(name, {}).update(values)
        evidence = dict(part='word/document.xml', path=f'/w:document/w:body/w:p[{paragraph}]', text=message)
        sources.setdefault(name, {}).update({key: evidence for key in values})
