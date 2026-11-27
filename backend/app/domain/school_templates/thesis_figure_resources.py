"""Assign composed thesis figures to the current school template chapters."""
from app.adapters.research_intake_store import require_owner
from app.core.exceptions import StorageError
from app.domain.paper_materials import thesis_figure_chapters, thesis_target_id
from app.domain.research_intake.sci_resources import (
    FigureResourcesWrite, formal_figures, normalize_figure_placements, ordered_placements, resolve_placements,
)
from app.domain.research_results.figures import THESIS_FIGURE_ENTRYPOINT
from app.domain.storage_governance.guards import require_scope_open
from .service import SchoolTemplateService
from .thesis_requirements import bound_template


THESIS_FIGURE_PLACEMENTS = 'figure_placements'
_PLACEMENTS_REVISION = 'figure_placements_revision'


def _targets(template):
    if template is None:
        return []
    return [dict(id=thesis_target_id(template['confirmation_id'], chapter['id']),
                 label=chapter['title'].strip(), chapter_id=chapter['id'])
            for chapter in thesis_figure_chapters(template)]


def _figures(db, project, placements, *, include_catalog=False):
    selected_ids = [row['figure_id'] for row in placements]
    return formal_figures(db, project, selected_ids, include_catalog, entrypoint=THESIS_FIGURE_ENTRYPOINT)


def resolve_thesis_figures(db, assets, project, requirements, school):
    """Resolve saved assignments to the actual chapters in a frozen manuscript plan."""
    placements = normalize_figure_placements(db, project, requirements.get(THESIS_FIGURE_PLACEMENTS))
    if not placements:
        return [], False
    if not school or not school['ready']:
        return [], True
    targets = _targets(school)
    figures = _figures(db, project, placements)
    resolved = resolve_placements(targets, figures, ordered_placements(targets, placements))
    chapter_ids = {target['id']: target['chapter_id'] for target in targets}
    panel_ids = {figure['version_id']: figure['panel_file_ids'] for figure in figures}
    rows = [dict(row, chapter_id=chapter_ids[row['chapter_id']], panel_file_ids=panel_ids[row['figure_id']])
            for row in resolved]
    return rows, len(rows) != len(placements)


def _ready_template(schools, db, project_id, profile):
    try:
        template, row = bound_template(schools, db, project_id, profile)
        if template and schools.require_current(db, row)[1]['status'] == 'succeeded':
            return template
    except StorageError as exc:
        if exc.status != 404 and exc.code != 'task_source_conflict':
            raise
    return None


def remove_thesis_figure_placements(db, assets, project_id, version_ids):
    schools = SchoolTemplateService(assets)
    profile = schools.profile_view(db, project_id, include_hidden_binding=True, include_requirements=True)
    requirements = profile.get('requirements_json') or {}
    placements = requirements.get(THESIS_FIGURE_PLACEMENTS) or []
    remaining = [item for item in placements if item['figure_id'] not in version_ids]
    if len(remaining) != len(placements):
        schools.write_profile(db, project_id, profile, profile, profile['bound_confirmation_id'],
                              requirements={**requirements, THESIS_FIGURE_PLACEMENTS: remaining})


def thesis_figure_resources(store, project_id, changes: FigureResourcesWrite | None = None):
    if not store.customer or store.assignment is not None:
        raise StorageError('permission_denied', '只有项目所有者可以编排毕业论文图件。', 403)
    schools = SchoolTemplateService(store)
    with store.connection(write=changes is not None) as db:
        project = require_owner(db, store, project_id)
        if project['project_type'] != 'thesis':
            raise StorageError('customer_project_type_forbidden', '图件编排仅适用于毕业论文项目。', 403)
        if changes is not None:
            db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE', (project_id,)).fetchone()
        profile = schools.profile_view(db, project_id, include_requirements=True)
        revision = profile['revision']
        requirements = profile.get('requirements_json') or {}
        template = _ready_template(schools, db, project_id, profile)
        targets = _targets(template)
        saved = requirements.get(THESIS_FIGURE_PLACEMENTS)
        placements = ordered_placements(targets, normalize_figure_placements(db, project, saved))
        if changes is not None:
            requested = normalize_figure_placements(db, project, [item.model_dump(mode='json') for item in changes.placements])
            if len(requested) != len(changes.placements):
                raise StorageError('thesis_figure_resources_invalid', '同一张正图只能选择一个入稿章节。', 422)
            requested = ordered_placements(targets, requested)
            unchanged = saved is not None and placements == requested
            expected = changes.expected_revision
            replay = (unchanged and revision == expected + 1
                      and requirements.get(_PLACEMENTS_REVISION) == revision)
            if revision != expected and not replay:
                raise StorageError('thesis_requirements_changed', '毕业论文需求或学校资料已更新，请核对后继续。', 409)
            if template is None:
                raise StorageError('thesis_template_required', '请先确认并绑定可用的学校模板。', 409)
            placements = requested

        figures = _figures(db, project, placements, include_catalog=True)
        if changes is not None:
            resolved = resolve_placements(targets, figures, placements)
            if len(resolved) != len(placements):
                raise StorageError('thesis_figure_resources_invalid', '请核对选中的图件和所属章节。', 422)
            if not unchanged:
                selected_ids = {row['figure_id'] for row in resolved}
                panel_ids = {file_id for figure in figures if figure['version_id'] in selected_ids
                             for file_id in figure['panel_file_ids']}
                require_scope_open(db, project_id, file_ids=panel_ids)
                revision += 1
                requirements = requirements | {THESIS_FIGURE_PLACEMENTS: placements, _PLACEMENTS_REVISION: revision}
                schools.write_profile(db, project_id, profile, profile, template['confirmation_id'],
                                      requirements=requirements)
        return dict(revision=revision, template_id=template['confirmation_id'] if template else None,
                    chapters=[dict(id=target['id'], label=target['label']) for target in targets],
                    figures=figures, placements=placements)
