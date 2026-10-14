"""Public profile contract; output numbers must always be finite."""
from typing import Literal
from pydantic import BaseModel, ConfigDict
from app.domain.analysis_sources import AnyDatasetAnalysisSource
from app.domain.dataset_preparation.contracts import PreparationUnit

RULES_VERSION = 'excel_profile_v1'
PAGE_SIZE = 20
IssueKind = Literal['missing', 'outlier', 'mixed_type', 'error', 'formula',
    'time_candidate', 'time_invalid', 'time_ambiguous', 'numeric_precision', 'duplicate']


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class NumericProfile(ProfileModel):
    status: Literal['ok', 'unavailable']
    n: int
    mean: float | None
    std: float | None
    min: float | None
    max: float | None
    q1: float | None
    median: float | None
    q3: float | None
    iqr: float | None
    lower_fence: str | None
    upper_fence: str | None
    outlier_count: int
    warnings: list[Literal['numeric_precision', 'numeric_unavailable', 'std_insufficient', 'metric_unavailable']]


class CategoryValue(ProfileModel):
    kind: Literal['text', 'boolean']
    value: str | bool
    count: int


class Categories(ProfileModel):
    distinct_count: int
    top: list[CategoryValue]
    other_count: int


class Temporal(ProfileModel):
    kind: Literal['date', 'datetime', 'time', 'duration']
    count: int
    min: str
    max: str


class TimeCandidates(ProfileModel):
    valid_count: int
    invalid_count: int
    ambiguous_count: int


class FieldProfile(ProfileModel):
    column: int
    letter: str
    name: str
    unit: PreparationUnit
    type_counts: dict[str, int]
    missing_count: int
    non_missing_count: int
    distinct_count: int
    numeric: NumericProfile | None
    categories: Categories | None
    temporal: list[Temporal]
    time_candidates: TimeCandidates
    issue_counts: dict[str, int]


class Profile(ProfileModel):
    schema_version: Literal[1] = 1
    rules_version: Literal['excel_profile_v1'] = RULES_VERSION
    source: AnyDatasetAnalysisSource
    filename: str
    sheet_name: str
    data_range: str | None
    record_count: int
    blank_row_count: int
    duplicate_groups: int
    duplicate_rows: int
    duplicate_extra_rows: int
    fields: list[FieldProfile]


class IssueItem(ProfileModel):
    row: int
    column: int | None
    coordinate: str | None
    kind: str | None
    value: str | bool | None
    group_first_row: int | None
    group_size: int | None


class IssuePage(ProfileModel):
    source: AnyDatasetAnalysisSource
    rules_version: Literal['excel_profile_v1'] = RULES_VERSION
    kind: IssueKind
    column: int | None
    page: int
    page_size: Literal[20] = PAGE_SIZE
    total: int
    items: list[IssueItem]
