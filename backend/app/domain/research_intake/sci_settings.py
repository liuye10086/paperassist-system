"""SCI project inputs and owner-scoped revision updates."""
from typing import Annotated, Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.adapters.research_intake_store import now, require_owner
from app.core.exceptions import StorageError


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


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


class SciProjectSettings(SciInput):
    article_type: Literal['research', 'narrative_review']
    main_results: str = Field(min_length=1, max_length=20000)
    target_journal: JournalIntent
    keywords: list[ShortText] = Field(min_length=1, max_length=30)
    figure_plan: list[FigurePlan] = Field(min_length=1, max_length=30)

    @model_validator(mode='after')
    def unique_keywords(self):
        if len({keyword.lower() for keyword in self.keywords}) != len(self.keywords):
            raise ValueError('Keywords must be unique.')
        return self


class SciSettingsWrite(SciInput):
    expected_revision: int = Field(ge=1, lt=2_147_483_647)
    settings: SciProjectSettings


class SciSettingsState(BaseModel):
    revision: int
    settings: SciProjectSettings | None


def sci_settings(store, project_id, changes: SciSettingsWrite | None = None):
    with store.connection(write=changes is not None) as db:
        project = require_owner(db, store, project_id)
        if project['project_type'] != 'sci':
            raise StorageError('sci_settings_unavailable', 'SCI 建项资料仅适用于 SCI 论文项目。', 403)
        current = db.execute('''SELECT revision, sci_settings_json AS settings
            FROM research_intakes WHERE project_id=%s AND owner_id=%s''', (project_id, store.owner_id)).fetchone()
        if current is None:
            raise StorageError('research_intake_not_found', '项目尚无需求登记。', 404)
        if changes is None:
            return current
        values = changes.settings.model_dump(mode='json')
        if current['settings'] == values and current['revision'] in (changes.expected_revision, changes.expected_revision + 1):
            return current
        if current['revision'] != changes.expected_revision:
            raise StorageError('sci_settings_revision_conflict', 'SCI 建项资料已更新，请核对最新版本。', 409)
        return db.execute('''UPDATE research_intakes SET sci_settings_json=%s, revision=revision+1, updated_at=%s
            WHERE project_id=%s AND owner_id=%s RETURNING revision, sci_settings_json AS settings''',
            (Jsonb(values), now(), project_id, store.owner_id)).fetchone()
