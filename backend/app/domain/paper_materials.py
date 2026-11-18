"""Save owner-authored result notes on paper figures and tables."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.adapters.research_intake_store import require_owner
from app.core.exceptions import StorageError
from app.domain.files import require_file
from app.domain.research_intake.paper_fields import ContentText
from app.domain.school_templates.service import SchoolTemplateService
from app.domain.school_templates.thesis_requirements import bound_template
from app.domain.storage_governance.guards import require_scope_open


FileId = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r'^[^\x00]+$')]
TargetId = Annotated[str, StringConstraints(min_length=1, max_length=400, pattern=r'^[^\x00]+$')]
ResultText = Annotated[ContentText, StringConstraints(pattern=r'^[^\x00]+$')]
MATERIAL_KINDS = {'jpeg': 'figure', 'png': 'figure', 'tiff': 'figure', 'docx': 'table', 'xlsx': 'table'}


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


def sci_targets(db, project):
    settings = read_sci_settings(db, project)
    if settings.get('article_type') == 'research':
        return [dict(id=sci_target_id('figure', item['id']), label=sci_finding_label(position, project['default_output_language']))
                for position, item in enumerate(settings.get('figure_findings', []), 1)]
    if settings.get('article_type') == 'narrative_review':
        return [dict(id=sci_target_id('review', item['id']), label=item['heading'])
                for item in settings.get('review_sections', [])]
    return []


def thesis_targets(db, store, project_id):
    schools = SchoolTemplateService(store)
    try:
        profile = schools.profile_view(db, project_id, include_requirements=True)
        template, row = bound_template(schools, db, project_id, profile)
        if template is None:
            return []
        binding = template['confirmation_id']
        requirements = profile.get('requirements_json') or {}
        sections = requirements.get('chapter_plans', {}).get(binding, [])
        result_chapters = {item['chapter_id'] for item in sections if item['purpose'] == 'results'}
        result_chapters.difference_update(template['protected_chapter_purposes'])
        if not result_chapters:
            return []
        _, task = schools.require_current(db, row)
    except StorageError as exc:
        if exc.status == 404 or exc.code == 'task_source_conflict':
            return []
        raise
    if task['status'] != 'succeeded':
        return []
    return [dict(id=thesis_target_id(binding, chapter['id']), label=chapter['title'].strip())
            for chapter in template['chapters'] if chapter['id'] in result_chapters]


def paper_targets(db, store, project):
    if project['project_type'] == 'sci':
        return sci_targets(db, project)
    return thesis_targets(db, store, project['id'])


def note_view(row, target_labels):
    target_id = row['target_id']
    return dict(id=row['id'], file_id=row['file_id'], revision=row['revision'], result=row['result_text'],
                target_id=target_id, target_label=target_labels.get(target_id, row['target_label']),
                target_available=target_id in target_labels, worksheet_names=row['worksheet_names'])


def paper_material_rows(db, store, project_id, file_ids=None):
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
        targets = paper_targets(db, store, project)
        target_labels = {target['id']: target['label'] for target in targets}
        rows = paper_material_rows(db, store, project_id, file_ids)
        return dict(items=[note_view(row, target_labels) for row in rows], targets=targets)


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
        current = db.execute('''SELECT * FROM paper_material_notes
            WHERE project_id=%s AND owner_id=%s AND id=%s''', (*scope, note_id)).fetchone()
        file = require_file(db, project_id, changes.file_id, material_filter=store.material_filter)
        kind = MATERIAL_KINDS.get(file['file_type'])
        if kind is None:
            raise StorageError('paper_material_file_unsupported', '请选择支持的原始图表文件。', 422)
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
        targets = paper_targets(db, store, project) if changes.target_id is not None else []
        target_labels = {target['id']: target['label'] for target in targets}
        if same_note:
            return note_view(current, target_labels)
        if changes.target_id is not None and changes.target_id not in target_labels:
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
