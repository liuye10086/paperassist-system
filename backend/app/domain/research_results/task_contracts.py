"""One fixed offline task identity shared by figures, reports and fact drafts."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from app.domain.bioinformatics.contracts import digest

RESEARCH_TASKS=('research_figure','research_report','research_fact_draft')


class ResearchInputVersion(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',frozen=True)
    kind: Literal['research_figure','research_report','research_fact_draft']
    schema_version: Literal[1]=1
    workflow_version: Literal['research_figure_v1','research_report_v1','research_results_methods_v1']
    source_sha256: str=Field(pattern=r'^[0-9a-f]{64}$')
    output_language: Literal['zh-CN','en']
    real_model_calls: Literal[False]=False
    real_network_calls: Literal[False]=False

    @model_validator(mode='after')
    def workflow(self):
        if self.workflow_version!=('research_results_methods_v1' if self.kind=='research_fact_draft' else self.kind+'_v1'):raise ValueError('Research workflow mismatch')
        return self


def input_version(task):
    from app.adapters.research_results_store import invalid
    snapshot=task['input_snapshot'];kind=task['task_type']
    if (kind not in RESEARCH_TASKS or snapshot.get('kind')!=kind or snapshot.get('project_id')!=task['project_id']
            or snapshot.get('real_model_calls') is not False or snapshot.get('real_network_calls') is not False
            or digest(snapshot)!=task['input_digest']):raise invalid()
    return ResearchInputVersion(kind=kind,workflow_version=task['workflow_version'],source_sha256=task['input_digest'],
        output_language=snapshot.get('output_language','zh-CN')).model_dump(mode='json')
