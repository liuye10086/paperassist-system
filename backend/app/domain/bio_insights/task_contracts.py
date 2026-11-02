"""Six exact offline task identities, shared without importing runtime adapters."""
from typing import Literal

from pydantic import model_validator

from app.domain.bioinformatics.contracts import digest
from .contracts import Hash, Identifier, Language, StrictModel

INSIGHT_TASKS=('bio_resource_import','bio_comparison','bio_result_import','bio_enrichment','bio_candidate','bio_insight_figure','bio_feature_extract','bio_integration')
TaskKind=Literal['bio_resource_import','bio_comparison','bio_result_import','bio_enrichment','bio_candidate','bio_insight_figure','bio_feature_extract','bio_integration']


class InsightTaskSnapshot(StrictModel):
    kind: TaskKind
    schema_version: Literal[1] = 1
    workflow_version: str
    project_id: Identifier
    resource_version_id: Identifier | None = None
    plan_version_id: Identifier | None = None
    run_id: Identifier | None = None
    source_digest: Hash
    output_language: Language = 'zh-CN'
    real_model_calls: Literal[False] = False
    real_network_calls: Literal[False] = False

    @model_validator(mode='after')
    def identity(self):
        if self.workflow_version!=self.kind+'_v1' and (self.kind!='bio_comparison' or self.workflow_version not in ('bio_comparison_v2','bio_comparison_qpcr_v1','bio_comparison_microbiome_v1')):raise ValueError('Insight workflow mismatch')
        resource=self.kind=='bio_resource_import'
        if resource:
            if not self.resource_version_id or self.plan_version_id or self.run_id:
                raise ValueError('Resource task requires exactly resource version identity')
        elif not self.plan_version_id or not self.run_id or self.resource_version_id:
            raise ValueError('Insight task requires exactly plan version and run identity')
        return self


class InsightInputVersion(StrictModel):
    kind: TaskKind
    schema_version: Literal[1] = 1
    workflow_version: str
    source_sha256: Hash
    source_digest: Hash
    output_language: Language
    real_model_calls: Literal[False] = False
    real_network_calls: Literal[False] = False

    @model_validator(mode='after')
    def workflow(self):
        if self.workflow_version!=self.kind+'_v1' and (self.kind!='bio_comparison' or self.workflow_version not in ('bio_comparison_v2','bio_comparison_qpcr_v1','bio_comparison_microbiome_v1')):raise ValueError('Insight workflow mismatch')
        return self


def input_version(task):
    snapshot=InsightTaskSnapshot.model_validate(task['input_snapshot'])
    if (snapshot.kind!=task['task_type'] or snapshot.project_id!=task['project_id']
            or snapshot.workflow_version!=task['workflow_version']
            or type(task['input_snapshot'].get('schema_version')) is not int
            or task['input_snapshot'].get('schema_version')!=1
            or task['input_snapshot'].get('output_language') not in ('zh-CN','en')
            or task['input_snapshot'].get('real_model_calls') is not False
            or task['input_snapshot'].get('real_network_calls') is not False
            or digest(task['input_snapshot'])!=task['input_digest']):
        raise ValueError('Invalid bio insight task input identity')
    return InsightInputVersion(kind=snapshot.kind,workflow_version=snapshot.workflow_version,
                              source_sha256=task['input_digest'],source_digest=snapshot.source_digest,
                              output_language=snapshot.output_language).model_dump(mode='json')
