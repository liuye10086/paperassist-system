"""Additive v3 derivations; v1/v2 object contracts remain unchanged."""
from typing import Literal
from pydantic import Field, model_validator
from app.domain.datasets.contracts import StrictModel, rectangle, a1
from app.domain.analysis_sources import DatasetAnalysisSource, PreparedDatasetAnalysisSource, PreparedDatasetAnalysisSourceV2, PreparedDatasetAnalysisSourceV3
from app.domain.dataset_preparation.quality_contracts import QualityRecipe, QualitySummary, QualityImpact, ManifestReference, PreparedSheetV2
from app.domain.dataset_preparation.filter_contracts import FilterRecipe, FilterSummary, FilterImpact

WORKFLOW_VERSION='dataset_preparation_v3'
PreparedSource=PreparedDatasetAnalysisSourceV3 | PreparedDatasetAnalysisSourceV2 | PreparedDatasetAnalysisSource

class DerivationManifest(StrictModel):
    schema_version: Literal[3] = 3
    transform_version: Literal['excel_prepare_v3'] = 'excel_prepare_v3'
    operation: Literal['population_filter','quality']
    root_source: DatasetAnalysisSource
    base_source: PreparedSource
    recipe: FilterRecipe | QualityRecipe
    summary: FilterSummary | QualitySummary
    entries: list[FilterImpact] | list[QualityImpact]

    @model_validator(mode='before')
    @classmethod
    def strict_schema(cls,v):
        if isinstance(v,dict) and 'schema_version' in v and type(v['schema_version']) is not int:raise ValueError('Invalid schema')
        return v

    @model_validator(mode='after')
    def coherent(self):
        filtering=self.operation=='population_filter'
        if (not isinstance(self.recipe,FilterRecipe if filtering else QualityRecipe)
            or not isinstance(self.summary,FilterSummary if filtering else QualitySummary)
            or len(self.entries)!=self.summary.impact_count
            or any(not isinstance(e,FilterImpact if filtering else QualityImpact) for e in self.entries)):
            raise ValueError('Operation and receipt mismatch')
        if filtering:
            if ([e.row for e in self.entries]!=sorted(set(e.row for e in self.entries))
                or sum(e.classification=='retained' for e in self.entries)!=self.summary.retained_record_count
                or sum(e.classification=='mismatch' for e in self.entries)!=self.summary.mismatch_excluded_row_count
                or sum(e.classification=='unknown' for e in self.entries)!=self.summary.unknown_excluded_row_count):raise ValueError('Invalid complete filter receipt')
            for entry in self.entries:
                if len(entry.evaluations)!=len(self.recipe.conditions):raise ValueError('Incomplete conditions')
                for e,c in zip(entry.evaluations,self.recipe.conditions):
                    if a1(e.coordinate)!=(entry.row,c.column):raise ValueError('Wrong source coordinate')
            for count in self.summary.condition_counts:
                if any(getattr(count,status+'_count')!=sum(e.evaluations[count.condition_index].status==status for e in self.entries) for status in ('true','false','unknown')):
                    raise ValueError('Condition counts differ')
        elif len({(e.operation,e.row,e.column) for e in self.entries})!=len(self.entries):raise ValueError('Duplicate impact')
        return self

class PreparedDatasetObjectV3(StrictModel):
    schema_version: Literal[3] = 3
    parent_source: DatasetAnalysisSource
    base_source: PreparedSource
    transform_version: Literal['excel_prepare_v3'] = 'excel_prepare_v3'
    operation: Literal['population_filter','quality']
    recipe: FilterRecipe | QualityRecipe
    sheet: PreparedSheetV2
    summary: FilterSummary | QualitySummary
    manifest: ManifestReference

    @model_validator(mode='before')
    @classmethod
    def strict_schema(cls,v):
        if isinstance(v,dict) and 'schema_version' in v and type(v['schema_version']) is not int:raise ValueError('Invalid schema')
        return v

    @model_validator(mode='after')
    def coherent(self):
        filtering=self.operation=='population_filter';start,end=rectangle(self.sheet.data_range)
        if (not isinstance(self.recipe,FilterRecipe if filtering else QualityRecipe)
            or not isinstance(self.summary,FilterSummary if filtering else QualitySummary)
            or self.summary.retained_record_count!=self.sheet.row_count
            or self.summary.root_record_count!=end[0]-start[0]+1 or self.manifest.entry_count!=self.summary.impact_count
            or self.parent_source.dataset_id!=self.base_source.parent_dataset_id
            or self.parent_source.dataset_version!=self.base_source.parent_dataset_version
            or (self.sheet.index,self.sheet.name)!=(self.parent_source.sheet_index,self.parent_source.sheet_name)):
            raise ValueError('Invalid derivation source/counts')
        for key in ('file_id','structure_id','source_sha256','sheet_index','sheet_name','parser_version'):
            if getattr(self.parent_source,key)!=getattr(self.base_source,key):raise ValueError('Root/base mismatch')
        if not filtering and [f.column for f in self.recipe.fields]!=[f.column for f in self.sheet.fields]:raise ValueError('Quality fields changed')
        return self
