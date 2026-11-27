"""SCI project inputs and owner-scoped revision updates."""
from typing import Annotated, Literal

from psycopg.types.json import Jsonb
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.adapters.research_intake_store import now, require_owner
from app.core.exceptions import StorageError
from .paper_fields import ContentText, PaperKeywords, ShortText, unique_keywords
from .sci_templates import CUSTOM_SCI_SECTION, MAX_SCI_SECTIONS, configured_template, selected_template, templates_for


FIGURE_WORKFLOW = 'figure_workflow'
SCI_FIGURE_PLACEMENTS = 'sci_figure_placements'


class SciInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)


class JournalIntent(SciInput):
    choice: Literal['nature_subjournal', 'science', 'other']
    name: ShortText | None = None

    @model_validator(mode='after')
    def validate_choice(self):
        if self.choice == 'other' and self.name is None:
            raise ValueError('A specific journal name is required.')
        if self.choice == 'science' and self.name is not None:
            raise ValueError('Science is already a specific journal.')
        return self


class FigurePlan(SciInput):
    title: ShortText
    description: str = Field(min_length=1, max_length=2000)


class SciIntent(SciInput):
    target_journal: JournalIntent


class LegacySciProjectSettings(SciIntent):
    article_type: Literal['research', 'narrative_review']
    main_results: ContentText
    keywords: Annotated[list[ShortText], Field(min_length=1, max_length=30), AfterValidator(unique_keywords)]
    figure_plan: list[FigurePlan] = Field(min_length=1, max_length=30)


class SciRequirements(SciIntent):
    target_journal: JournalIntent | None = None
    proposed_title: ShortText
    keywords: PaperKeywords

    @model_validator(mode='after')
    def specific_journal(self):
        if self.target_journal and self.target_journal.choice != 'science' and self.target_journal.name is None:
            raise ValueError('A specific journal name is required.')
        return self


class FigureFinding(SciInput):
    id: ShortText
    finding: ContentText


class ReviewSection(SciInput):
    id: ShortText
    heading: ShortText
    content: ContentText


def unique_rows(items):
    if len({item.id for item in items}) != len(items):
        raise ValueError('Each requirement row must have a unique identity.')
    return items


class SciResearchRequirements(SciRequirements):
    article_type: Literal['research']
    figure_findings: Annotated[list[FigureFinding], AfterValidator(unique_rows)] = Field(default_factory=list)


class SciReviewRequirements(SciRequirements):
    article_type: Literal['narrative_review']
    review_sections: Annotated[list[ReviewSection], AfterValidator(unique_rows)] = Field(default_factory=list)


SciProjectSettings = Annotated[SciResearchRequirements | SciReviewRequirements, Field(discriminator='article_type')]
# Legacy payloads also let clients recover previously sent writes after an upgrade.
SciSettingsPayload = SciProjectSettings | LegacySciProjectSettings


class SciSettingsWrite(SciInput):
    expected_revision: int = Field(ge=1, lt=2_147_483_647)
    settings: SciSettingsPayload


class SciSettingsState(BaseModel):
    revision: int
    settings: SciSettingsPayload | None
    legacy_settings: LegacySciProjectSettings | None = None


class SciSectionHeading(SciInput):
    id: ShortText
    en: ShortText
    zh: ShortText
    level: int | None = Field(default=None, ge=1, le=9)


class SciReviewHeading(SciInput):
    id: ShortText
    heading: ShortText


class SciTemplateWrite(SciInput):
    expected_revision: int = Field(ge=1, lt=2_147_483_647)
    template_id: ShortText
    sections: list[SciSectionHeading] | None = Field(default=None, min_length=7, max_length=MAX_SCI_SECTIONS)
    review_headings: list[SciReviewHeading] | None = None
    combine_review_topics: bool | None = None
    figure_workflow: Literal[True] | None = None


def settings_view(row):
    settings = row['settings']
    if settings is None:
        return row
    current = dict(settings)
    supplemental_keys = ('legacy_settings', 'template_id', 'template_sections', 'combine_review_topics',
                         FIGURE_WORKFLOW, SCI_FIGURE_PLACEMENTS)
    supplemental = {key: current.pop(key) for key in supplemental_keys if key in current}
    return dict(revision=row['revision'], settings=current, **supplemental)


def sci_revision_conflict():
    return StorageError('sci_settings_revision_conflict', 'SCI 建项资料已更新，请核对最新版本。', 409)


def sci_target_journal_required():
    return StorageError('sci_target_journal_required', '请选择一个目标期刊。', 422)


def _invalid_outline():
    return StorageError('sci_template_outline_invalid', '请核对初稿的章节标题和顺序。', 422)


def _updated_template(settings, changes):
    article_type = (settings or {}).get('article_type')
    template = selected_template(article_type, changes.template_id)
    if template is None:
        raise StorageError('sci_template_unavailable', '请选择与论文类型匹配的 SCI 模板。', 422)
    values = dict(settings, template_id=changes.template_id)
    if changes.figure_workflow:
        values[FIGURE_WORKFLOW] = True
    if changes.template_id != settings.get('template_id'):
        values.pop('template_sections', None)
    if changes.combine_review_topics is not None:
        if article_type != 'narrative_review':
            raise _invalid_outline()
        if changes.combine_review_topics:
            values['combine_review_topics'] = True
        else:
            values.pop('combine_review_topics', None)
    if changes.sections is not None:
        sections = [section.model_dump(mode='json', exclude_none=True) for section in changes.sections]
        ids = [section['id'] for section in sections]
        required = {section['id'] for section in template['sections']}
        if (not required.issubset(ids) or len(set(ids)) != len(ids) or ids[0] != 'title' or ids[-1] != 'references'
                or any(not CUSTOM_SCI_SECTION.fullmatch(sid) for sid in set(ids) - required)
                or any(len({section[key] for section in sections}) != len(sections) for key in ('en', 'zh'))):
            raise _invalid_outline()
        for section in sections[1:]:
            if section.get('level') == 1:
                section.pop('level')
        if sections == template['sections']:
            values.pop('template_sections', None)
        else:
            values['template_sections'] = sections
    if changes.review_headings is not None:
        topics = {row['id']: row for row in settings.get('review_sections', [])}
        ids = [row.id for row in changes.review_headings]
        if article_type != 'narrative_review' or set(ids) != topics.keys() or len(ids) != len(topics):
            raise _invalid_outline()
        if topics:
            values['review_sections'] = [dict(topics[row.id], heading=row.heading) for row in changes.review_headings]
    count = len(values.get('template_sections', template['sections']))
    if article_type == 'narrative_review' and not values.get('combine_review_topics'):
        if count + max(1, len(values.get('review_sections', []))) > MAX_SCI_SECTIONS:
            raise _invalid_outline()
    return values


def load_sci_intake(db, store, project_id, *, lock=False):
    project = require_owner(db, store, project_id)
    if project['project_type'] != 'sci':
        raise StorageError('sci_settings_unavailable', 'SCI 建项资料仅适用于 SCI 论文项目。', 403)
    query = '''SELECT revision, sci_settings_json AS settings
        FROM research_intakes WHERE project_id=%s AND owner_id=%s'''
    if lock:
        query += ' FOR UPDATE'
    row = db.execute(query, (project_id, store.owner_id)).fetchone()
    if row is None:
        raise StorageError('research_intake_not_found', '项目尚无需求登记。', 404)
    return project, row


def save_sci_intake(db, project, values):
    return db.execute('''UPDATE research_intakes SET sci_settings_json=%s, revision=revision+1, updated_at=%s
        WHERE project_id=%s AND owner_id=%s RETURNING revision, sci_settings_json AS settings''',
        (Jsonb(values), now(), project['id'], project['owner_id'])).fetchone()


def sci_settings(store, project_id, changes: SciSettingsWrite | SciTemplateWrite | None = None):
    with store.connection(write=changes is not None) as db:
        project, row = load_sci_intake(db, store, project_id, lock=changes is not None)
        current = settings_view(row)
        if changes is None:
            return current
        revision, expected = current['revision'], changes.expected_revision
        if revision not in (expected, expected + 1):
            raise sci_revision_conflict()
        if isinstance(changes, SciTemplateWrite):
            try:
                values = _updated_template(row['settings'], changes)
            except StorageError as exc:
                if revision != expected:
                    raise sci_revision_conflict() from exc
                raise
            unchanged = values == row['settings']
        else:
            values = changes.settings.model_dump(mode='json')
            unchanged = current['settings'] == values
        if unchanged:
            return current
        if revision != expected:
            raise sci_revision_conflict()
        if isinstance(changes, SciSettingsWrite):
            if isinstance(changes.settings, LegacySciProjectSettings):
                raise StorageError('sci_settings_required', '请填写完整的 SCI 建项资料。', 422)
            if changes.settings.target_journal is None:
                raise sci_target_journal_required()
            legacy = current.get('legacy_settings')
            if current['settings'] and 'main_results' in current['settings']:
                legacy = current['settings']
            if legacy is not None:
                values['legacy_settings'] = legacy
            if selected_template(values['article_type'], current.get('template_id')) is not None:
                values['template_id'] = current['template_id']
                if 'template_sections' in current:
                    values['template_sections'] = current['template_sections']
                if current.get('combine_review_topics'):
                    values['combine_review_topics'] = True
            for key in (FIGURE_WORKFLOW, SCI_FIGURE_PLACEMENTS):
                if key in current:
                    values[key] = current[key]
        return settings_view(save_sci_intake(db, project, values))


def sci_template_settings(store, project_id, changes: SciTemplateWrite | None = None):
    state = sci_settings(store, project_id, changes)
    settings = state['settings'] or {}
    article_type = settings.get('article_type')
    selected = configured_template(article_type, state.get('template_id'), state.get('template_sections'))
    review_headings = [dict(id=row['id'], heading=row['heading']) for row in settings.get('review_sections', [])]
    return dict(revision=state['revision'], article_type=article_type,
                selected_template_id=state.get('template_id'), templates=templates_for(article_type),
                selected_sections=selected['sections'] if selected else None, review_headings=review_headings,
                combine_review_topics=state.get('combine_review_topics', False),
                figure_workflow=state.get(FIGURE_WORKFLOW, False))
