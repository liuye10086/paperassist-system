"""V3 snapshots keep operation identity separate from revised predicates."""
from typing import Literal
from pydantic import Field, model_validator
from app.domain.datasets.contracts import StrictModel
from app.domain.analysis_sources import DatasetAnalysisSource
from app.domain.dataset_preparation.derivation_contracts import PreparedSource
from app.domain.dataset_preparation.quality_contracts import QualityRecipe
from app.domain.dataset_preparation.filter_contracts import FilterRecipe
from app.domain.dataset_preparation.service import PreparationDecisionRequest, PreparationState

class FilterCreateRequest(StrictModel):
    base_dataset_id: str = Field(min_length=1,max_length=64)
    recipe: FilterRecipe

class DerivationDecisionRequest(PreparationDecisionRequest):
    recipe: FilterRecipe | QualityRecipe | None = None

class DerivationState(PreparationState):
    recipe: FilterRecipe | QualityRecipe

class DerivationSnapshot(StrictModel):
    schema_version: Literal[3]
    kind: Literal['dataset_preparation']
    project_id: str
    filename: str
    source: PreparedSource
    root_source: DatasetAnalysisSource
    operation: Literal['population_filter','quality']
    recipe: FilterRecipe | QualityRecipe
    workflow_version: Literal['dataset_preparation_v3']

    @model_validator(mode='after')
    def coherent(self):
        if not isinstance(self.recipe,FilterRecipe if self.operation=='population_filter' else QualityRecipe):raise ValueError('Wrong recipe for operation')
        return self
