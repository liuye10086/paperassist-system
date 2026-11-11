"""Explicit selections for reviewing and delivering published Bulk versions."""
from typing import Literal

from pydantic import Field, model_validator

from .contracts import BULK_CONTRAST_FIGURES, BULK_PROCESSED_FIGURES, BulkSelection, Hash, Identifier, StrictModel


def bulk_attachment_supported(kind, config, sources):
    """Recognize the native saved attachment contracts before checking bytes and exact lineage."""
    source_kinds = [source['source_kind'] for source in sources]
    result = 'bio_insight_result_version'
    if kind == 'candidate':
        return bool(config.get('bulk_selection')) and source_kinds == [result]
    if kind in ('ora', 'gsea_prerank'):
        return (config.get('bulk_enrichment') is not None and len(source_kinds) > 1
                and source_kinds.count(result) == 1
                and source_kinds.count('bio_resource_version') == len(source_kinds) - 1)
    if kind == 'figure':
        figure_type = config.get('figure_type')
        if figure_type in BULK_PROCESSED_FIGURES:
            return source_kinds == ['bio_processed_dataset_version']
        if (figure_type in BULK_CONTRAST_FIGURES
                or config.get('bulk_enrichment_render') is True and figure_type in ('enrichment', 'gsea')):
            return source_kinds == [result]
    return False


class BulkSensitivityRequest(StrictModel):
    baseline_version_id: Identifier
    scenario_version_id: Identifier
    baseline_selection: BulkSelection
    scenario_selection: BulkSelection


class BulkSensitivityQuery(BulkSensitivityRequest):
    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: int = Field(default=100, ge=1, le=100)


class BulkEvidenceSelection(StrictModel):
    kind: Literal['independent_analysis', 'experimental_material']
    source_id: Identifier
    note: str = Field(default='', max_length=1000)


class BulkDeliveryRequest(StrictModel):
    comparison_version_id: Identifier
    result_version_ids: list[Identifier] = Field(default_factory=list, max_length=20)
    selections: list[BulkSelection] = Field(default_factory=list, max_length=10)
    sensitivity: BulkSensitivityRequest | None = None
    evidence: list[BulkEvidenceSelection] = Field(default_factory=list, max_length=12)
    language: Literal['zh', 'en'] = 'zh'

    @model_validator(mode='after')
    def distinct_sources_and_selections(self):
        if self.comparison_version_id in self.result_version_ids or len(set(self.result_version_ids)) != len(self.result_version_ids):
            raise ValueError('Choose each attached result version once')
        if len({entry.contrast_id for entry in self.selections}) != len(self.selections):
            raise ValueError('Choose one filter per frozen contrast')
        if len({(entry.kind, entry.source_id) for entry in self.evidence}) != len(self.evidence):
            raise ValueError('Choose each evidence source once')
        if self.sensitivity and self.sensitivity.baseline_version_id != self.comparison_version_id:
            raise ValueError('Use the report comparison as the sensitivity baseline')
        return self


class BulkDownloadRequest(BulkDeliveryRequest):
    facts_digest: Hash
