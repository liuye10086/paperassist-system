"""Save owner-authored result notes on paper figures and tables."""
import re
from typing import Annotated
from unicodedata import normalize

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.adapters.research_intake_store import require_owner
from app.core.exceptions import StorageError
from app.domain.files import require_file
from app.domain.school_templates.service import SchoolTemplateService
from app.domain.school_templates.thesis_requirements import bound_template
from app.domain.storage_governance.guards import require_scope_open


FileId = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r'^[^\x00]+$')]
TargetId = Annotated[str, StringConstraints(min_length=1, max_length=400, pattern=r'^[^\x00]+$')]
ResultText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000, pattern=r'^[^\x00]*$')]
MATERIAL_KINDS = {'jpeg': 'figure', 'png': 'figure', 'tiff': 'figure', 'docx': 'table', 'xlsx': 'table'}
DEFAULT_REVIEW_TOPIC = 'sci:review-topic'
REVIEW_FIGURE_SECTIONS = ('introduction', 'discussion', 'conclusion')


def review_topic_heading(language):
    return 'Review of the evidence' if language == 'en' else '研究进展'


def review_section_labels(language):
    from app.domain.manuscript_writing.article_contract import labels
    return {sid: en if language == 'en' else zh for sid, en, zh in labels('narrative_review')
            if sid in REVIEW_FIGURE_SECTIONS}


class PaperMaterialWrite(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    expected_revision: int = Field(ge=0, lt=2_147_483_647)
    file_id: FileId
    result: ResultText
    target_id: TargetId | None = None
    worksheet_names: list[Annotated[str, StringConstraints(min_length=1, max_length=128)]] | None = Field(
        default=None, min_length=1, max_length=12)


class PaperMaterialTarget(BaseModel):
    id: str
    label: str


class PaperMaterialNote(BaseModel):
    id: str
    file_id: str
    revision: int
    result: str
    target_id: str | None
    target_label: str | None
    target_available: bool
    worksheet_names: list[str] | None = None


class PaperMaterialsView(BaseModel):
    items: list[PaperMaterialNote]
    targets: list[PaperMaterialTarget]
    review_figure_placement: bool
    figure_targets: list[PaperMaterialTarget]
    template_source_file_ids: list[str]


def paper_project(db, store, project_id):
    if store.assignment is not None:
        raise StorageError('permission_denied', '只有项目所有者可以访问图表备注。', 403)
    project = require_owner(db, store, project_id)
    if project['project_type'] not in ('sci', 'thesis'):
        raise StorageError('paper_materials_unavailable', '图表备注仅适用于 SCI 论文和毕业论文项目。', 403)
    return project


def read_sci_settings(db, project):
    row = db.execute('SELECT sci_settings_json FROM research_intakes WHERE project_id=%s AND owner_id=%s',
                     (project['id'], project['owner_id'])).fetchone()
    return (row['sci_settings_json'] if row else None) or {}


def sci_target_id(kind, row_id):
    return f'sci:{kind}:{row_id}'


def sci_finding_label(number, language):
    return f'Finding {number}' if language == 'en' else f'发现 {number}'


def thesis_target_id(confirmation_id, chapter_id):
    return f'thesis:results:{confirmation_id}:{chapter_id}'


def sci_targets(settings, project):
    if settings.get('article_type') == 'research':
        return [dict(id=sci_target_id('figure', item['id']), label=sci_finding_label(position, project['default_output_language']))
                for position, item in enumerate(settings.get('figure_findings', []), 1)]
    if settings.get('article_type') == 'narrative_review':
        language = project['default_output_language']
        native = [dict(id=sci_target_id('section', sid), label=label)
                  for sid, label in review_section_labels(language).items()]
        themes = [dict(id=sci_target_id('review', item['id']), label=item['heading'])
                  for item in settings.get('review_sections', [])]
        return [native[0], *(themes or [dict(id=DEFAULT_REVIEW_TOPIC, label=review_topic_heading(language))]), *native[1:]]
    return []


def chapter_heading(title):
    heading = normalize('NFKC', title).strip()
    heading = re.sub(r'^(?:第[一二三四五六七八九十百零〇\d]+[章节]|chapter\s+(?:\d+|[ivxlcdm]+)\b|\d+(?:\.\d+)*)[\s.、:-]*',
                     '', heading, flags=re.I)
    heading = re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])', '', heading)
    return re.sub(r'\s*\((?:根据实际情况填写|按实际情况填写)\)$', '', heading).strip()


def thesis_figure_chapters(template):
    chapters = []
    excluded_level = None
    for chapter in template['chapters']:
        if excluded_level is not None and chapter['level'] > excluded_level:
            continue
        excluded_level = None
        heading = chapter_heading(chapter['title'])
        front_or_back = re.fullmatch(
            r'(?:.*(?:原创性声明|独创性声明|授权声明|授权书)|声明|封面|扉页|(?:中文|英文|内容)?摘要|致谢|参考文献|'
            r'参考资料|文献目录|(?:图表?|表格?)?目录|关键词|附录(?:\s*[A-Z一二三四五六七八九十\d])?|个人简历|'
            r'(?:(?:chinese|english)\s+)?abstract|references|bibliography|acknowledg[e]?ments|table of contents|'
            r'contents|list of (?:figures|tables)|declaration(?: of .*)?|title page|cover|appendices|appendix(?: [A-Z])?)',
            heading, flags=re.I)
        if chapter['id'] in template['protected_chapter_purposes'] or front_or_back:
            excluded_level = chapter['level']
            continue
        chapters.append(chapter)
    return chapters


def thesis_targets(db, store, project_id):
    schools = SchoolTemplateService(store)
    try:
        profile = schools.profile_view(db, project_id, include_requirements=True)
        template, row = bound_template(schools, db, project_id, profile)
        if template is None:
            return [], [], []
        binding = template['confirmation_id']
        requirements = profile.get('requirements_json') or {}
        sections = requirements.get('chapter_plans', {}).get(binding, [])
        result_chapters = {item['chapter_id'] for item in sections if item['purpose'] == 'results'}
        result_chapters.difference_update(template['protected_chapter_purposes'])
        sources, task = schools.require_current(db, row)
    except StorageError as exc:
        if exc.status == 404 or exc.code == 'task_source_conflict':
            return [], [], []
        raise
    if task['status'] != 'succeeded':
        return [], [], []
    def target(chapter):
        return dict(id=thesis_target_id(binding, chapter['id']), label=chapter['title'].strip())
    return ([target(chapter) for chapter in template['chapters'] if chapter['id'] in result_chapters],
            [target(chapter) for chapter in thesis_figure_chapters(template)],
            [source['file_id'] for source in sources if source['role'] in ('template', 'supplement')])


def paper_targets(db, store, project, settings):
    if project['project_type'] == 'sci':
        targets = sci_targets(settings, project)
        return targets, targets, []
    return thesis_targets(db, store, project['id'])


def note_view(row, target_labels):
    target_id = row['target_id']
    return dict(id=row['id'], file_id=row['file_id'], revision=row['revision'], result=row['result_text'],
                target_id=target_id, target_label=target_labels.get(target_id, row['target_label']),
                target_available=target_id in target_labels, worksheet_names=row['worksheet_names'])


def paper_material_rows(db, store, project_id, file_ids=None, *, include_uploaded_figures=False):
    if include_uploaded_figures:
        return db.execute('''SELECT files.id AS file_id, files.filename, files.file_type,
            n.result_text, n.target_id, n.worksheet_names FROM files
            LEFT JOIN paper_material_notes n ON n.file_id=files.id AND n.project_id=files.project_id AND n.owner_id=%s
            WHERE files.project_id=%s AND (n.id IS NOT NULL OR files.file_type IN ('png','jpeg','tiff'))'''
            + store.material_filter + ' ORDER BY files.uploaded_at, files.id', (store.owner_id, project_id)).fetchall()
    query = '''SELECT n.*, files.filename, files.file_type FROM paper_material_notes n
        JOIN files ON files.id=n.file_id AND files.project_id=n.project_id
        WHERE n.project_id=%s AND n.owner_id=%s''' + store.material_filter
    parameters = (project_id, store.owner_id)
    if file_ids is not None:
        query += ' AND n.file_id=ANY(%s)'
        parameters += (file_ids,)
    return db.execute(query + ' ORDER BY files.uploaded_at DESC, files.id', parameters).fetchall()


def list_paper_materials(store, project_id, file_ids=None):
    with store.connection() as db:
        project = paper_project(db, store, project_id)
        settings = read_sci_settings(db, project) if project['project_type'] == 'sci' else {}
        targets, figure_targets, template_ids = paper_targets(db, store, project, settings)
        target_labels = {target['id']: target['label'] for target in targets}
        figure_labels = {target['id']: target['label'] for target in figure_targets}
        rows = paper_material_rows(db, store, project_id, file_ids)
        return dict(items=[note_view(row, figure_labels if MATERIAL_KINDS.get(row['file_type']) == 'figure'
                                     else target_labels) for row in rows], targets=targets, figure_targets=figure_targets,
                    review_figure_placement=settings.get('article_type') == 'narrative_review', template_source_file_ids=template_ids)


def paper_worksheets(store, project_id, file_id):
    from app.domain.manuscripts.paper_tables import worksheet_previews

    with store.connection() as db:
        paper_project(db, store, project_id)
        file = dict(require_file(db, project_id, file_id, material_filter=store.material_filter))
    if file['file_type'] != 'xlsx':
        raise StorageError('paper_material_file_unsupported', '请选择 Excel 原件。', 422)
    return dict(sheets=worksheet_previews(store.original(file), file['filename']))


def save_paper_material(store, project_id, note_id, changes: PaperMaterialWrite):
    with store.connection(write=True) as db:
        project = paper_project(db, store, project_id)
        scope = (project_id, store.owner_id)
        db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE', (project_id,))
        current = db.execute('''SELECT * FROM paper_material_notes
            WHERE project_id=%s AND owner_id=%s AND id=%s''', (*scope, note_id)).fetchone()
        file = require_file(db, project_id, changes.file_id, material_filter=store.material_filter)
        kind = MATERIAL_KINDS.get(file['file_type'])
        if kind is None:
            raise StorageError('paper_material_file_unsupported', '请选择支持的原始图表文件。', 422)
        settings = read_sci_settings(db, project) if project['project_type'] == 'sci' else {}
        review_figure = kind == 'figure' and settings.get('article_type') == 'narrative_review'
        optional_caption = kind == 'figure' and (review_figure or project['project_type'] == 'thesis')
        if not changes.result and not optional_caption:
            raise StorageError('task_input_invalid', '请填写资料说明。', 422)
        if current and current['file_id'] != changes.file_id:
            previous = require_file(db, project_id, current['file_id'], material_filter=store.material_filter)
            if MATERIAL_KINDS.get(previous['file_type']) != kind:
                raise StorageError('paper_material_file_kind_changed', '请选择与原素材同类的图表文件。', 422)

        worksheets = changes.worksheet_names
        if current and current['file_id'] == changes.file_id and 'worksheet_names' not in changes.model_fields_set:
            worksheets = current['worksheet_names']
        revision = current['revision'] if current else 0
        saved_worksheets = current['worksheet_names'] if current else None
        same_note = (current is not None
                     and (changes.file_id, changes.result, changes.target_id) ==
                     (current['file_id'], current['result_text'], current['target_id'])
                     and sorted(worksheets or []) == sorted(saved_worksheets or []))
        # The committed revision and its content are enough to recognize an exact
        # retry, even if its target became unavailable after the first save.
        if revision != changes.expected_revision and not (same_note and revision == changes.expected_revision + 1):
            raise StorageError('paper_material_revision_conflict', '图表备注已更新，请核对当前版本。', 409)
        targets, figure_targets, _ = paper_targets(db, store, project, settings) if changes.target_id is not None else ([], [], [])
        if kind == 'figure':
            targets = figure_targets
        target_labels = {target['id']: target['label'] for target in targets}
        if same_note:
            return note_view(current, target_labels)
        if changes.target_id is not None and (changes.target_id not in target_labels or
                not review_figure and (changes.target_id.startswith('sci:section:') or changes.target_id == DEFAULT_REVIEW_TOPIC)):
            raise StorageError('paper_material_target_unavailable', '所选小节已变化，请从当前小节中重新选择。', 409)
        if db.execute('''SELECT 1 FROM paper_material_notes
            WHERE project_id=%s AND owner_id=%s AND file_id=%s AND id<>%s''', (*scope, file['id'], note_id)).fetchone():
            raise StorageError('paper_material_file_in_use', '此文件已有图表备注，请选择其他文件。', 409)

        require_scope_open(db, project_id, file_ids=(file['id'],))
        if file['file_type'] == 'xlsx' and (worksheets is not None or changes.target_id is not None):
            from app.domain.manuscripts.paper_tables import validate_worksheets

            worksheets = validate_worksheets(store.original(dict(file)), file['filename'], worksheets)
        elif worksheets is not None:
            raise StorageError('paper_material_file_unsupported', '工作表仅适用于 Excel 原件。', 422)
        values = (changes.file_id, changes.result, changes.target_id, worksheets)
        label = target_labels.get(changes.target_id)
        if current:
            row = db.execute('''UPDATE paper_material_notes SET file_id=%s, result_text=%s, target_id=%s,
                worksheet_names=%s, target_label=%s, revision=revision+1
                WHERE project_id=%s AND owner_id=%s AND id=%s RETURNING *''',
                (*values, label, *scope, note_id)).fetchone()
        else:
            row = db.execute('''INSERT INTO paper_material_notes(project_id, owner_id, id, file_id, result_text,
                target_id, worksheet_names, target_label, revision)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1) RETURNING *''',
                (*scope, note_id, *values, label)).fetchone()
        return note_view(row, target_labels)
