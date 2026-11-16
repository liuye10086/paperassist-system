"""Research report narrative admission and task projections."""
from typing import Literal

from pydantic import field_validator

from app.domain.research_results.contracts import Hash, Identifier, ResearchReportRequest, StrictModel


TASK_TYPE = 'reader_report_narrative'
WORKFLOW = 'reader_report_narrative_v1'
CALL_KEY = 'reader-report-narrative-v1'
RETRYABLE_FAILURES = ('storage_unavailable', 'task_worker_interrupted', 'model_provider_unavailable')


class NarrativeRequest(StrictModel):
    report: ResearchReportRequest
    bundle_sha256: Hash
    confirmed_external_processing: Literal[True]

    @field_validator('confirmed_external_processing', mode='before')
    @classmethod
    def require_explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('Explicit boolean confirmation required')
        return value


class ReaderReportInputVersion(StrictModel):
    kind: Literal['reader_report_narrative'] = TASK_TYPE
    narrative_id: Identifier
    binding_sha256: Hash
    bundle_sha256: Hash
    workflow_version: Literal['reader_report_narrative_v1'] = WORKFLOW
