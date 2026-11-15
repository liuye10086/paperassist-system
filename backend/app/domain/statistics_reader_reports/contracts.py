"""Explicit selections for a saved analysis or an ordered collection version."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.domain.research_results.contracts import Identifier, Language, StrictModel


class AnalysisSelection(StrictModel):
    kind: Literal['analysis']
    file_id: Identifier
    analysis_run_id: Identifier
    figure_id: Identifier | None
    explanation_id: Identifier | None

    @model_validator(mode='after')
    def exact_artifacts(self):
        if (self.figure_id is None) != (self.explanation_id is None):
            raise ValueError('Select both the figure and its matching explanation, or neither')
        return self


class CollectionSelection(StrictModel):
    kind: Literal['collection']
    collection_id: Identifier
    collection_version_id: Identifier


class StatisticsReportPrepareRequest(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    language: Language
    selection: Annotated[AnalysisSelection | CollectionSelection, Field(discriminator='kind')]
