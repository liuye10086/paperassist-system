"""Independent machine candidates on one immutable processed cell axis."""
from typing import Literal
from pydantic import ConfigDict,Field
from .analysis_contracts import StrictModel,BioProcessedDatasetSourceV1,ENGINE_VERSION,Hash
from .contracts import digest,conflict
from .single_cell_resources import SingleCellRAnalysisLimits


class BioAnnotationRunRequest(StrictModel):
    name: str = Field(min_length=1,max_length=200)
    parent_processed_source: BioProcessedDatasetSourceV1
    reference_id: str = Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_.-]+$')
    seed: int = Field(default=0,ge=0,le=2147483647)


class BioAnnotationInputVersion(StrictModel):
    model_config=ConfigDict(strict=True,extra='forbid',frozen=True)
    schema_version: Literal[1] = 1
    kind: Literal['bio_annotation'] = 'bio_annotation'
    run_id: str
    parent_processed_source: BioProcessedDatasetSourceV1
    reference_id: str
    workflow_version: Literal['bio_annotation_v1'] = 'bio_annotation_v1'
    engine_version: Literal['visium_explore_v1.0.0'] = ENGINE_VERSION
    environment_digest: Hash
    output_language: Literal['zh-CN','en']


class BioAnnotationSnapshot(StrictModel):
    schema_version: Literal[1]
    kind: Literal['bio_annotation']
    workflow_version: Literal['bio_annotation_v1']
    project_id: str
    run_id: str
    name: str = Field(min_length=1,max_length=200)
    parent_processed_source: BioProcessedDatasetSourceV1
    reference: dict
    seed: int = Field(ge=0,le=2147483647)
    request_digest: Hash
    engine_version: Literal['visium_explore_v1.0.0']
    environment_digest: Hash
    code_digest: Hash
    output_language: Literal['zh-CN','en']
    limits: SingleCellRAnalysisLimits


def validate_snapshot(task):
    try:
        value=BioAnnotationSnapshot.model_validate(task['input_snapshot'])
        if (task['task_type']!='bio_annotation' or task['workflow_version']!=value.workflow_version or task['project_id']!=value.project_id
            or value.parent_processed_source.project_id!=value.project_id or task['input_digest']!=digest(task['input_snapshot'])
            or not isinstance(value.reference.get('reference_id'),str) or value.limits!=SingleCellRAnalysisLimits()):
            raise ValueError('Annotation source identity differs')
        return task['input_snapshot']
    except (KeyError,TypeError,ValueError) as exc:raise conflict('bio_input_integrity_changed') from exc


def input_version(task):
    value=validate_snapshot(task)
    return BioAnnotationInputVersion(**{key:value[key] for key in ('run_id','parent_processed_source','environment_digest','output_language')},
        reference_id=value['reference']['reference_id']).model_dump(mode='json')
