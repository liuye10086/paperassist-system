"""Version-dispatched snapshots use the existing checkpoint and wait machinery."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.domain.dataset_preparation.quality_contracts import QualityRecipe, PreparedSource
from app.domain.dataset_preparation.service import PreparationDecisionRequest, PreparationState
from app.domain.analysis_sources import DatasetAnalysisSource

class QualityCreateRequest(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    base_dataset_id: str = Field(min_length=1,max_length=64)
    recipe: QualityRecipe

class QualityDecisionRequest(PreparationDecisionRequest):
    recipe: QualityRecipe | None = None

class QualityState(PreparationState):
    recipe: QualityRecipe

class QualitySnapshot(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    schema_version: Literal[2]
    kind: Literal['dataset_preparation']
    project_id: str
    filename: str
    source: PreparedSource
    root_source: DatasetAnalysisSource
    recipe: QualityRecipe
    workflow_version: Literal['dataset_preparation_v2']
