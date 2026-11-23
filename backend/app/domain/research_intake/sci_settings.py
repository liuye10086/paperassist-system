"""SCI project inputs and owner-scoped revision updates."""
from typing import Annotated, Literal

from psycopg.types.json import Jsonb
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.adapters.research_intake_store import now, require_owner
from app.core.exceptions import StorageError
from .paper_fields import ContentText, PaperKeywords, ShortText, unique_keywords


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


def settings_view(row):
    settings = row['settings']
    if settings is None or 'legacy_settings' not in settings:
        return row
    current = dict(settings)
    legacy = current.pop('legacy_settings')
    return dict(revision=row['revision'], settings=current, legacy_settings=legacy)


def sci_settings(store, project_id, changes: SciSettingsWrite | None = None):
    with store.connection(write=changes is not None) as db:
        project = require_owner(db, store, project_id)
        if project['project_type'] != 'sci':
            raise StorageError('sci_settings_unavailable', 'SCI 建项资料仅适用于 SCI 论文项目。', 403)
        query = '''SELECT revision, sci_settings_json AS settings
            FROM research_intakes WHERE project_id=%s AND owner_id=%s'''
        if changes is not None:
            query += ' FOR UPDATE'
        row = db.execute(query, (project_id, store.owner_id)).fetchone()
        if row is None:
            raise StorageError('research_intake_not_found', '项目尚无需求登记。', 404)
        current = settings_view(row)
        if changes is None:
            return current
        values = changes.settings.model_dump(mode='json')
        if current['settings'] == values and current['revision'] in (changes.expected_revision, changes.expected_revision + 1):
            return current
        if current['revision'] != changes.expected_revision:
            raise StorageError('sci_settings_revision_conflict', 'SCI 建项资料已更新，请核对最新版本。', 409)
        if isinstance(changes.settings, LegacySciProjectSettings):
            raise StorageError('sci_settings_required', '请填写完整的 SCI 建项资料。', 422)
        legacy = current.get('legacy_settings')
        if current['settings'] and 'main_results' in current['settings']:
            legacy = current['settings']
        if legacy is not None:
            values['legacy_settings'] = legacy
        updated = db.execute('''UPDATE research_intakes SET sci_settings_json=%s, revision=revision+1, updated_at=%s
            WHERE project_id=%s AND owner_id=%s RETURNING revision, sci_settings_json AS settings''',
            (Jsonb(values), now(), project_id, store.owner_id)).fetchone()
        return settings_view(updated)
