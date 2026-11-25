"""Owner-scoped assignments of saved SCI figures to the confirmed outline."""
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.exceptions import StorageError
from app.domain.paper_materials import FileId, MATERIAL_KINDS, PaperMaterialTarget, ResultText, TargetId
from app.domain.research_results.figures import SCI_FIGURE_ENTRYPOINT
from app.domain.storage_governance.guards import require_scope_open
from .paper_fields import ShortText
from .sci_settings import (
    FIGURE_WORKFLOW, SCI_FIGURE_PLACEMENTS, SciInput, load_sci_intake, save_sci_intake, sci_revision_conflict,
)
from .sci_templates import configured_template


class FigurePlacement(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    figure_id: FileId
    chapter_id: TargetId
    caption: ResultText


class SciFigurePlacement(FigurePlacement):
    model_config = SciInput.model_config

    chapter_id: ShortText


class FigureResourcesWrite(SciInput):
    expected_revision: int = Field(ge=0, lt=2_147_483_647)
    placements: list[FigurePlacement] = Field(max_length=100)

    @model_validator(mode='after')
    def unique_figures(self):
        if len({row.figure_id for row in self.placements}) != len(self.placements):
            raise ValueError('Each figure can be assigned to one chapter.')
        return self


class SciResourcesWrite(FigureResourcesWrite):
    expected_revision: int = Field(ge=1, lt=2_147_483_647)
    placements: list[SciFigurePlacement] = Field(max_length=100)


class SciResourceFigure(BaseModel):
    id: str
    title: str
    preview_url: str
    revision: int | None = None


class FigureResourcesState(BaseModel):
    revision: int
    template_id: str | None
    chapters: list[PaperMaterialTarget]
    figures: list[SciResourceFigure]
    placements: list[FigurePlacement]


class SciResourcesState(FigureResourcesState):
    placements: list[SciFigurePlacement]


def _chapters(project, template):
    language = 'en' if project['default_output_language'] == 'en' else 'zh'
    return [dict(id=row['id'], label=row[language]) for row in (template or {}).get('sections', [])
            if row['id'] not in ('title', 'references')]


def formal_figures(db, project, selected_ids, include_latest, *, entrypoint):
    # Original panels are also retained as members. Only the composite/output
    # PNG can be placed in the manuscript.
    rows = db.execute('''WITH latest AS (
        SELECT DISTINCT ON (v.root_id) v.id, v.root_id, v.revision, v.project_id, v.user_id, v.config_json,
            v.manifest_object_id, v.manifest_sha256, v.created_at
        FROM research_figure_versions v
        JOIN tasks t ON (t.id, t.project_id, t.user_id) = (v.task_id, v.project_id, v.user_id)
        WHERE v.project_id=%s AND v.user_id=%s AND (%s OR v.root_id=ANY(%s))
            AND t.task_type='research_figure' AND t.status='succeeded' AND t.result_research_figure_version_id=v.id
            AND t.input_snapshot->>'entrypoint'=%s
            AND NOT EXISTS (SELECT 1 FROM paper_figure_cancellations c WHERE c.root_id=v.root_id)
        ORDER BY v.root_id, v.revision DESC
    ) SELECT v.id, v.root_id, v.revision, v.config_json, v.manifest_sha256, m.id AS member_id
        FROM latest v
        JOIN storage_objects manifest ON manifest.id=v.manifest_object_id
            AND manifest.state='present' AND manifest.sha256=v.manifest_sha256
        JOIN storage_references manifest_ref
            ON (manifest_ref.object_id, manifest_ref.project_id, manifest_ref.owner_id) = (manifest.id, v.project_id, v.user_id)
        JOIN LATERAL (
            SELECT min(m.id) AS id FROM research_figure_members m
            WHERE (m.figure_version_id, m.project_id, m.user_id) = (v.id, v.project_id, v.user_id)
                AND m.role='figure' AND m.format='png'
            HAVING count(*) = 1
        ) selected_png ON true
        JOIN research_figure_members m ON m.id=selected_png.id
        JOIN storage_objects png ON png.id=m.storage_object_id AND png.state='present'
            AND png.sha256=m.sha256 AND png.size_bytes=m.size_bytes AND m.size_bytes>0
        JOIN storage_references png_ref
            ON (png_ref.object_id, png_ref.project_id, png_ref.owner_id) = (png.id, v.project_id, v.user_id)
        ORDER BY v.created_at DESC, v.id''',
        (project['id'], project['owner_id'], include_latest, selected_ids, entrypoint)).fetchall()
    base = f"/api/v1/projects/{project['id']}/{entrypoint.replace('_', '-')}"
    figures = []
    for row in rows:
        config = row['config_json']
        panels = [dict(label=panel['label'], description=panel.get('note', '')) for panel in config['panels']
                  if panel.get('label')]
        panel_file_ids = list(dict.fromkeys(panel['source']['source_id'] for panel in config['panels']
                                           if panel['source']['source_kind'] == 'original_file'))
        figures.append(dict(id=row['root_id'], version_id=row['id'], title=config['title'], revision=row['revision'],
            preview_url=f"{base}/{row['id']}/members/{row['member_id']}/download", panels=panels,
            source_kind='research_figure_version', sha256=row['manifest_sha256'], member_id=row['member_id'],
            panel_file_ids=panel_file_ids))
    return figures


def normalize_figure_placements(db, project, placements):
    """Use one placement per figure, including settings saved with version IDs."""
    if not placements:
        return []
    versions = {row['id']: row for row in db.execute('''SELECT id, root_id, revision FROM research_figure_versions
        WHERE project_id=%s AND user_id=%s AND id=ANY(%s)''',
        (project['id'], project['owner_id'], [item['figure_id'] for item in placements]))}
    current = {}
    for item in placements:
        version = versions.get(item['figure_id'])
        figure_id = version['root_id'] if version else item['figure_id']
        revision = version['revision'] if version else 0
        if figure_id not in current or revision > current[figure_id][0]:
            current[figure_id] = (revision, dict(item, figure_id=figure_id))
    return [item for _, item in current.values()]


def _legacy_figures(db, assets, project, selected_ids, include_catalog):
    image_types = [file_type for file_type, kind in MATERIAL_KINDS.items() if kind == 'figure']
    rows = db.execute('''SELECT files.id, files.filename, files.sha256, n.result_text, n.target_id
        FROM paper_material_notes n JOIN files ON (files.id, files.project_id) = (n.file_id, n.project_id)
        WHERE n.project_id=%s AND n.owner_id=%s AND files.file_type=ANY(%s) AND (%s OR files.id=ANY(%s))'''
        + assets.material_filter + ' ORDER BY files.uploaded_at, files.id',
        (project['id'], project['owner_id'], image_types, include_catalog, selected_ids)).fetchall()
    base = f"/api/v1/projects/{project['id']}/files"
    return [dict(id=row['id'], title=row['filename'], preview_url=f"{base}/{row['id']}/image-preview",
                 source_kind='original', sha256=row['sha256'], legacy_caption=row['result_text'],
                 legacy_target=row['target_id']) for row in rows]


def _figures(db, assets, project, placements, *, include_catalog):
    selected_ids = [row['figure_id'] for row in placements]
    if not selected_ids and not include_catalog:
        return []
    return (formal_figures(db, project, selected_ids, include_catalog, entrypoint=SCI_FIGURE_ENTRYPOINT)
            + _legacy_figures(db, assets, project, selected_ids, include_catalog))


def _legacy_placements(chapters, figures, article_type):
    if not chapters:
        return []
    chapter_ids = {chapter['id'] for chapter in chapters}
    default_chapter = 'results' if article_type == 'research' else 'themes'
    placements = []
    for figure in figures:
        if figure['source_kind'] != 'original':
            continue
        chapter = (figure['legacy_target'] or '').removeprefix('sci:section:')
        placements.append(dict(figure_id=figure['id'], chapter_id=chapter if chapter in chapter_ids else default_chapter,
                               caption=figure['legacy_caption']))
    return placements


def ordered_placements(chapters, placements):
    positions = {chapter['id']: index for index, chapter in enumerate(chapters)}
    return sorted(placements, key=lambda row: positions.get(row['chapter_id'], len(positions)))


def resolve_placements(chapters, figures, placements):
    labels = {chapter['id']: chapter['label'] for chapter in chapters}
    sources = {figure['id']: figure for figure in figures}
    rows = []
    for placement in placements:
        source = sources.get(placement['figure_id'])
        chapter_id = placement['chapter_id']
        if source is None or chapter_id not in labels:
            continue
        row = dict(**placement, chapter_label=labels[chapter_id], **{key: source[key] for key in (
            'title', 'source_kind', 'sha256', 'preview_url')})
        if source['source_kind'] == 'research_figure_version':
            if not placement['caption']:
                continue
            row.update(figure_id=source['version_id'], member_id=source['member_id'], panels=source['panels'])
        rows.append(row)
    return rows


def resolve_sci_figures(db, assets, project, settings, template):
    """Resolve explicit assignments for an immutable manuscript plan."""
    if not settings.get(FIGURE_WORKFLOW):
        return [], False
    placements = settings.get(SCI_FIGURE_PLACEMENTS)
    if not template or placements is None:
        return [], True
    placements = normalize_figure_placements(db, project, placements)
    chapters = _chapters(project, template)
    figures = _figures(db, assets, project, placements, include_catalog=False)
    rows = resolve_placements(chapters, figures, ordered_placements(chapters, placements))
    return rows, len(rows) != len(placements)


def remove_sci_figure_placements(db, project, version_ids):
    row = db.execute('''SELECT sci_settings_json AS settings FROM research_intakes
        WHERE project_id=%s AND owner_id=%s FOR UPDATE''', (project['id'], project['owner_id'])).fetchone()
    settings = (row['settings'] or {}) if row else {}
    placements = settings.get(SCI_FIGURE_PLACEMENTS) or []
    remaining = [item for item in placements if item['figure_id'] not in version_ids]
    if len(remaining) != len(placements):
        save_sci_intake(db, project, {**settings, SCI_FIGURE_PLACEMENTS: remaining})


def sci_resources(store, project_id, changes: SciResourcesWrite | None = None):
    if not store.customer or store.assignment is not None:
        raise StorageError('permission_denied', '只有项目所有者可以编排 SCI 图表。', 403)
    with store.connection(write=changes is not None) as db:
        project, row = load_sci_intake(db, store, project_id, lock=changes is not None)
        revision, settings = row['revision'], row['settings'] or {}
        kind = settings.get('article_type')
        template = configured_template(kind, settings.get('template_id'), settings.get('template_sections'))
        chapters = _chapters(project, template)
        saved = settings.get(SCI_FIGURE_PLACEMENTS)
        placements = ordered_placements(chapters, normalize_figure_placements(db, project, saved))
        if changes is not None:
            requested = normalize_figure_placements(db, project, [item.model_dump(mode='json') for item in changes.placements])
            if len(requested) != len(changes.placements):
                raise StorageError('sci_resources_invalid', '同一张正图只能选择一个入稿章节。', 422)
            requested = ordered_placements(chapters, requested)
            unchanged = saved is not None and placements == requested and settings.get(FIGURE_WORKFLOW)
            expected = changes.expected_revision
            if revision != expected and not (revision == expected + 1 and unchanged):
                raise sci_revision_conflict()
            placements = requested
        figures = _figures(db, store, project, placements, include_catalog=True)
        if changes is None and saved is None:
            placements = ordered_placements(chapters, _legacy_placements(chapters, figures, kind))
        if changes is not None and revision == expected:
            if template is None:
                raise StorageError('sci_template_unavailable', '请先确认 SCI 模板。', 422)
            resolved = resolve_placements(chapters, figures, placements)
            if len(resolved) != len(placements):
                raise StorageError('sci_resources_invalid', '请核对选中的图件、所属章节及图注。', 422)
            if not unchanged:
                originals = [row['figure_id'] for row in resolved if row['source_kind'] == 'original']
                require_scope_open(db, project_id, file_ids=originals)
                values = {**settings, FIGURE_WORKFLOW: True, SCI_FIGURE_PLACEMENTS: placements}
                revision = save_sci_intake(db, project, values)['revision']
        return dict(revision=revision, template_id=template['id'] if template else None, chapters=chapters,
                    figures=figures, placements=placements)
