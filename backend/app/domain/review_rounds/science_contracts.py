"""Narrow links to existing public tasks and receipt-backed local analyses."""
from typing import Literal
from pydantic import Field
from .contracts import Strict, Location


class TaskLinkRequest(Strict):
    plan_revision: int = Field(ge=1)
    item_id: str
    task_id: str
    purpose: Literal['retrieval', 'statistics', 'projection', 'plot', 'writing', 'revision']


class StatisticsTaskRequest(Strict):
    plan_revision: int = Field(ge=1)
    item_id: str
    file_id: str
    expected_setup_revision: int = Field(ge=1)


class AnalysisAdoptionRequest(Strict):
    plan_revision: int = Field(ge=1)
    item_id: str
    task_link_id: str
    supersedes_source_ids: list[str] = Field(default_factory=list)
    affected_locations: list[Location] = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)


class ProjectionTaskRequest(Strict):
    plan_revision: int = Field(ge=1)
    item_id: str = Field(min_length=1, max_length=64)
    file_id: str = Field(min_length=1, max_length=64)
    analysis_run_id: str = Field(min_length=1, max_length=64)
    figure_config_version_id: str = Field(min_length=1, max_length=64)


class PlotTaskRequest(ProjectionTaskRequest):
    projection_id: str = Field(min_length=1, max_length=64)
    projection_input_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    external_processing: dict


class FigureAdoptionRequest(Strict):
    plan_revision: int = Field(ge=1)
    expected_current_revision: int = Field(ge=1)
    item_id: str
    task_link_id: str
    supersedes_figure_id: str
    affected_locations: list[Location] = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)
