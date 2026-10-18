"""Strict additive contracts for explicit, incremental quality derivations."""
from typing import Literal
from pydantic import Field, model_validator
from app.domain.datasets.contracts import StrictModel, rectangle, a1
from app.domain.analysis_sources import DatasetAnalysisSource, PreparedDatasetAnalysisSource, PreparedDatasetAnalysisSourceV2
from app.domain.dataset_preparation.contracts import PreparedSheet, validate_value

WORKFLOW_VERSION = 'dataset_preparation_v2'
TRANSFORM_VERSION = 'excel_prepare_v2'
RULES_VERSION = 'quality_rules_v1'
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
PreparedSource = PreparedDatasetAnalysisSourceV2 | PreparedDatasetAnalysisSource

class QualityFieldRule(StrictModel):
    column: int = Field(ge=1, le=256)
    trim_text: bool = False
    missing_markers: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def coherent(self):
        if len(set(self.missing_markers)) != len(self.missing_markers) or any(not 1 <= len(v) <= 160 for v in self.missing_markers):
            raise ValueError('Invalid missing markers')
        return self

class ManualExclusion(StrictModel):
    row: int = Field(ge=1, le=100000)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def coherent(self):
        if not self.reason.strip():
            raise ValueError('An explicit user reason is required')
        return self

class QualityRecipe(StrictModel):
    fields: list[QualityFieldRule] = Field(min_length=1, max_length=256)
    manual_exclusions: list[ManualExclusion] = Field(default_factory=list, max_length=100000)
    duplicate_policy: Literal['retain', 'exact'] = 'retain'
    missing_policy: Literal['retain'] = 'retain'
    outlier_policy: Literal['manual_only'] = 'manual_only'

    @model_validator(mode='after')
    def coherent(self):
        columns = [f.column for f in self.fields]
        if columns != sorted(set(columns)) or len({e.row for e in self.manual_exclusions}) != len(self.manual_exclusions):
            raise ValueError('Duplicate or unordered quality rules')
        return self

class PreparedSheetV2(PreparedSheet):
    active_source_rows: list[int] = Field(max_length=100000)

    @property
    def row_count(self):
        return len(self.active_source_rows)

    @model_validator(mode='after')
    def active_rows_match(self):
        start, end = rectangle(self.data_range)
        if self.active_source_rows != sorted(set(self.active_source_rows)) or any(type(r) is not int or not start[0] <= r <= end[0] for r in self.active_source_rows):
            raise ValueError('Invalid active source rows')
        active = set(self.active_source_rows)
        if any(c.row not in active for c in self.cells):
            raise ValueError('Excluded row has stored cells')
        return self

class QualityOverview(StrictModel):
    record_count: int = Field(ge=0, le=100000)
    missing_cell_count: int = Field(ge=0)
    missing_row_count: int = Field(ge=0)
    blank_row_count: int = Field(ge=0)
    duplicate_group_count: int = Field(ge=0)
    duplicate_member_count: int = Field(ge=0)
    duplicate_extra_row_count: int = Field(ge=0)
    outlier_candidate_count: int = Field(ge=0)

class QualitySummary(StrictModel):
    root_record_count: int = Field(ge=1, le=100000)
    base_record_count: int = Field(ge=1, le=100000)
    retained_record_count: int = Field(ge=0, le=100000)
    inherited_excluded_row_count: int = Field(ge=0)
    manual_excluded_row_count: int = Field(ge=0)
    duplicate_excluded_row_count: int = Field(ge=0)
    cumulative_excluded_row_count: int = Field(ge=0)
    changed_cell_count: int = Field(ge=0)
    retained_changed_cell_count: int = Field(ge=0)
    excluded_changed_cell_count: int = Field(ge=0)
    changed_row_count: int = Field(ge=0)
    trimmed_cell_count: int = Field(ge=0)
    missing_marker_cell_count: int = Field(ge=0)
    impact_count: int = Field(ge=0)
    before_quality: QualityOverview
    after_quality: QualityOverview

    @model_validator(mode='after')
    def coherent(self):
        if (self.root_record_count - self.inherited_excluded_row_count != self.base_record_count
                or self.base_record_count - self.manual_excluded_row_count - self.duplicate_excluded_row_count != self.retained_record_count
                or self.root_record_count - self.cumulative_excluded_row_count != self.retained_record_count
                or self.changed_cell_count != self.retained_changed_cell_count + self.excluded_changed_cell_count
                or self.impact_count != self.changed_cell_count + self.manual_excluded_row_count + self.duplicate_excluded_row_count
                or self.before_quality.record_count != self.base_record_count or self.after_quality.record_count != self.retained_record_count):
            raise ValueError('Quality counts are inconsistent')
        return self

class QualityImpact(StrictModel):
    row: int = Field(ge=1, le=100000)
    column: int | None = Field(default=None, ge=1, le=256)
    coordinate: str | None = None
    operation: Literal['manual_exclusion', 'cell_change', 'duplicate_exclusion']
    reason: str | None = None
    reason_origin: Literal['user', 'rule']
    before: dict[str, str | bool | None] | None = None
    after: dict[str, str | bool | None] | None = None
    operations: list[Literal['trim_text', 'missing_marker']] = Field(default_factory=list)
    retained_row: int | None = Field(default=None, ge=1, le=100000)
    final_retained: bool

    @model_validator(mode='after')
    def coherent(self):
        if self.operation == 'cell_change':
            if self.column is None or self.coordinate is None or a1(self.coordinate) != (self.row,self.column) or self.reason_origin != 'rule' or self.retained_row is not None:
                raise ValueError('Invalid cell impact')
            if self.operations not in (['trim_text'], ['missing_marker'], ['trim_text','missing_marker']):
                raise ValueError('Invalid ordered operations')
            for value in (self.before,self.after):
                if value is None or set(value) != {'kind','value'} or value['kind'] not in ('text','blank'):
                    raise ValueError('Invalid text change')
                validate_value(value['kind'],value['value'])
            if self.before == self.after:
                raise ValueError('Unchanged cell impact')
        elif self.column is not None or self.coordinate is not None or self.before is not None or self.after is not None or self.operations or self.final_retained:
            raise ValueError('Invalid row impact')
        if self.operation == 'manual_exclusion' and (self.reason_origin != 'user' or not self.reason or not self.reason.strip() or len(self.reason)>500 or self.retained_row is not None):
            raise ValueError('Invalid manual reason')
        if self.operation == 'duplicate_exclusion' and (self.reason_origin != 'rule' or self.retained_row is None or self.retained_row >= self.row):
            raise ValueError('Invalid duplicate evidence')
        return self

class ManifestReference(StrictModel):
    object_key: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size_bytes: int = Field(gt=0, le=MAX_MANIFEST_BYTES)
    entry_count: int = Field(ge=0)

class QualityManifest(StrictModel):
    schema_version: Literal[1] = 1
    transform_version: Literal['excel_prepare_v2'] = TRANSFORM_VERSION
    root_source: DatasetAnalysisSource
    base_source: PreparedSource
    recipe: QualityRecipe
    summary: QualitySummary
    entries: list[QualityImpact]

    @model_validator(mode='before')
    @classmethod
    def strict_schema(cls,value):
        if isinstance(value,dict) and 'schema_version' in value and type(value['schema_version']) is not int:
            raise ValueError('Invalid manifest schema version')
        return value

    @model_validator(mode='after')
    def coherent(self):
        if len(self.entries) != self.summary.impact_count:
            raise ValueError('Manifest count mismatch')
        identities=[(e.operation,e.row,e.column) for e in self.entries]
        if len(set(identities)) != len(identities):
            raise ValueError('Duplicate impact identity')
        return self

class PreparedDatasetObjectV2(StrictModel):
    schema_version: Literal[2] = 2
    parent_source: DatasetAnalysisSource
    base_source: PreparedSource
    transform_version: Literal['excel_prepare_v2'] = TRANSFORM_VERSION
    recipe: QualityRecipe
    sheet: PreparedSheetV2
    summary: QualitySummary
    manifest: ManifestReference

    @model_validator(mode='before')
    @classmethod
    def strict_schema(cls,value):
        if isinstance(value,dict) and 'schema_version' in value and type(value['schema_version']) is not int:
            raise ValueError('Invalid prepared schema version')
        return value

    @model_validator(mode='after')
    def coherent(self):
        start,end=rectangle(self.sheet.data_range)
        if (self.summary.retained_record_count != self.sheet.row_count or self.summary.root_record_count != end[0]-start[0]+1
                or self.manifest.entry_count != self.summary.impact_count
                or [f.column for f in self.recipe.fields] != [f.column for f in self.sheet.fields]
                or self.parent_source.dataset_id != self.base_source.parent_dataset_id
                or self.parent_source.dataset_version != self.base_source.parent_dataset_version
                or (self.sheet.index,self.sheet.name) != (self.parent_source.sheet_index,self.parent_source.sheet_name)):
            raise ValueError('Derived source mismatch')
        for field in ('file_id','structure_id','source_sha256','sheet_index','sheet_name','parser_version'):
            if getattr(self.parent_source,field) != getattr(self.base_source,field):
                raise ValueError('Root and base mismatch')
        return self
