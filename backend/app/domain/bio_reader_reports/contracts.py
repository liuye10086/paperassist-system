"""Explicit, bounded native report selection; empty figures means original images."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.domain.bio_insights.bulk_delivery_contracts import BulkDownloadRequest
from app.domain.research_results.contracts import Identifier, Language, StrictModel


class FigureSelection(StrictModel):
    figure_version_ids: list[Identifier] = Field(max_length=50)

    @model_validator(mode='after')
    def unique_order(self):
        if len(set(self.figure_version_ids)) != len(self.figure_version_ids):
            raise ValueError('Select each fixed figure once')
        return self


class ProcessedSelection(FigureSelection):
    kind: Literal['processed']
    processed_version_id: Identifier
    annotation_version_id: Identifier | None


class InsightSelection(FigureSelection):
    kind: Literal['insight']
    result_version_id: Identifier


class BulkSelection(StrictModel):
    kind: Literal['bulk']
    delivery: BulkDownloadRequest


class BioReportPrepareRequest(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    language: Language
    selection: Annotated[ProcessedSelection | InsightSelection | BulkSelection, Field(discriminator='kind')]

    @model_validator(mode='after')
    def same_language(self):
        if not self.title.strip():
            raise ValueError('A report title is required')
        if self.selection.kind == 'bulk' and self.selection.delivery.language != ('zh' if self.language == 'zh-CN' else 'en'):
            raise ValueError('The Bulk preview and report must use the same language')
        return self
