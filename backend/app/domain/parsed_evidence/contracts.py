"""Read-only projections of stored evidence, never scientific interpretations."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.domain.datasets.contracts import StructureFormula


class Model(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)


class Origin(Model):
    project_id: str
    file_id: str
    version_id: str
    version: int
    kind: Literal['document_version', 'dataset_version', 'prepared_dataset_version']
    filename: str
    sha256: str
    source_sha256: str
    parent_version_id: str | None = None
    parent_object_download_url: str | None = None
    original_download_url: str
    object_download_url: str


class Location(Model):
    part: str | None = None
    path: str | None = None
    label: str | None = None
    page_number: int | None = None
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    polygon: list[list[float]] | None = None
    coordinate_system: str | None = None
    sheet_index: int | None = None
    sheet_name: str | None = None
    coordinate: str | None = None
    row: int | None = None
    column: int | None = None
    container_id: str | None = None


class Unit(Model):
    status: Literal['unconfirmed', 'confirmed'] = 'unconfirmed'
    value: str | None = None


class Value(Model):
    kind: str
    typed: str | bool | None
    raw_available: bool = False
    original_typed: str | bool | None = None
    raw_source_version_id: str | None = None
    raw_type: str | None = None
    raw: str | None = None
    number_format: str | None = None
    formula: StructureFormula | None = None
    unit: Unit = Field(default_factory=Unit)


class Association(Model):
    status: Literal['candidate'] = 'candidate'
    basis: Literal['adjacent_same_container', 'nearest_same_page']
    caption_id: str
    caption_text: str
    caption_source: Location
    target_id: str
    target_source: Location


class EvidenceCell(Model):
    location: Location
    value: Value


class Item(Model):
    id: str
    kind: Literal['text', 'table', 'cell', 'field', 'row', 'image']
    location: Location
    text: str | None = None
    value: Value | None = None
    cells: list[EvidenceCell] = Field(default_factory=list, max_length=256)
    rows: int | None = None
    columns: int | None = None
    image_id: str | None = None
    preview_url: str | None = None
    associations: list[Association] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class Scope(Model):
    kind: Literal['document', 'sheet']
    sheet_index: int | None = None
    sheet_name: str | None = None
    stored_range: str | None = None
    content_range: str | None = None
    data_range: str | None = None
    pages: list[int] = Field(default_factory=list)


class Pagination(Model):
    page: int
    page_size: Literal[20] = 20
    total: int
    returned: int
    has_more: bool


class Evidence(Model):
    schema_version: Literal[1] = 1
    source: Origin
    format: Literal['docx', 'pdf', 'ocr', 'xlsx', 'prepared_xlsx']
    parser_version: str
    scope: Scope
    counts: dict[str, int]
    count_semantics: Literal['stored_evidence_not_research_n'] = 'stored_evidence_not_research_n'
    pagination: Pagination
    items: list[Item] = Field(max_length=20)
    uncertainties: list[str]
    warnings: list['EvidenceWarning'] = Field(default_factory=list)


class EvidenceWarning(Model):
    code: str
    message: str
    count: int = Field(ge=0)
    scope: Literal['document', 'page']
    pages: list[int] = Field(max_length=100)
    location: Location | None = None


def response(origin, format, parser, scope, counts, items, uncertainties, page, *, warnings=None):
    selected = items[(page-1)*20:page*20]
    return Evidence(source=origin, format=format, parser_version=parser, scope=scope,
        counts=counts, pagination=Pagination(page=page, total=len(items), returned=len(selected),
        has_more=page*20<len(items)), items=selected, uncertainties=uncertainties,
        warnings=warnings or []).model_dump()
