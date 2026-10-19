"""Strict request and suggestion contracts bound to frozen evidence."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

WORKFLOW = 'literature_assistance_v1'


class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)


Text = Annotated[str, Field(min_length=1, max_length=10000)]
Identity = Annotated[str, Field(min_length=1, max_length=64, pattern=r'^\S+$')]


class SearchPlanRequest(Strict):
    kind: Literal['search_plan']
    research_topic: Text
    source_context: Annotated[str, Field(max_length=20000)]
    output_language: Literal['zh-CN','en']


class EvidenceReviewRequest(Strict):
    kind: Literal['evidence_review']
    claim_id: Identity
    claim_revision: int = Field(strict=True, ge=1)
    project_reference_id: Identity
    evidence_ids: list[Identity] = Field(min_length=1, max_length=20)
    output_language: Literal['zh-CN','en']

    @model_validator(mode='after')
    def unique_evidence(self):
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError('Evidence identifiers must be unique')
        return self


class EvidenceComparisonRequest(Strict):
    kind: Literal['evidence_comparison']
    claim_id: Identity
    claim_revision: int = Field(strict=True, ge=1)
    evidence_ids: list[Identity] = Field(min_length=2, max_length=20)
    output_language: Literal['zh-CN','en']

    @model_validator(mode='after')
    def unique_evidence(self):
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError('Evidence identifiers must be unique')
        return self


AssistanceRequest = Annotated[SearchPlanRequest | EvidenceReviewRequest | EvidenceComparisonRequest, Field(discriminator='kind')]
request_adapter = TypeAdapter(AssistanceRequest)


class AssistanceInputVersion(Strict):
    kind: Literal['literature_assistance']
    workflow_version: Literal['literature_assistance_v1']
    assistance_kind: Literal['search_plan','evidence_review','evidence_comparison']
    input_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    output_language: Literal['zh-CN','en']


class MeshCandidate(Strict):
    term: Text
    verified: Literal[False]


class SearchPlanResult(Strict):
    direction: Text
    terms: list[Text] = Field(min_length=1, max_length=100)
    synonyms: list[Text] = Field(max_length=100)
    mesh_candidates: list[MeshCandidate] = Field(max_length=100)
    query: Text
    explanation: Text


class EvidenceReviewResult(Strict):
    status: Literal['supported','partial','unsupported','needs_review']
    relevance: Literal['related','unrelated','uncertain']
    reason: Text
    narrowed_statement: str = Field(max_length=10000)
    limitations: list[Text] = Field(max_length=100)
    evidence_ids: list[Identity] = Field(max_length=100)


class EvidenceComparisonResult(EvidenceReviewResult):
    comparison: Literal['consistent','conflicting','incomparable','insufficient']

    @model_validator(mode='after')
    def unresolved_sources(self):
        if self.comparison != 'consistent' and self.status != 'needs_review':
            raise ValueError('Conflicting, incomparable or insufficient sources require review')
        return self


def result_text_format(payload):
    """Future batch06 create schema; existing snapshots and validators stay unchanged."""
    kind = payload['kind']
    result_type = {'search_plan': SearchPlanResult, 'evidence_review': EvidenceReviewResult,
                   'evidence_comparison': EvidenceComparisonResult}[kind]
    schema = result_type.model_json_schema()
    if kind == 'search_plan':
        verified = schema['$defs']['MeshCandidate']['properties']['verified']
        verified.pop('const')
        verified['enum'] = [False]
    else:
        selected = TypeAdapter(list[Identity]).validate_python([item['id'] for item in payload['material']['evidence']])
        if not 1 <= len(selected) <= 20 or len(set(selected)) != len(selected):
            raise ValueError('Selected evidence identifiers required')
        schema['properties']['evidence_ids']['items']['enum'] = selected
        schema['properties']['status']['description'] = (
            'supported: the supplied evidence supports the whole claim within its scope. '
            'partial: only part is supported; include a narrower statement and explicit limitations. '
            'unsupported: supplied evidence contradicts or does not support the claim, including unrelated evidence. '
            'needs_review: required material is missing or uncertain, or sources conflict or cannot be compared. '
            'Do not use needs_review merely because every suggestion requires human review.')
        schema['properties']['relevance']['description'] = 'Return only the enum; put explanations in reason.'
        if kind == 'evidence_comparison':
            schema['properties']['comparison']['description'] = (
                'consistent: comparable sources agree; conflicting: comparable sources disagree; '
                'incomparable: comparison conditions differ; insufficient: material is missing. '
                'All except consistent require status needs_review. Assess only selected excerpts and state scope limitations.')
    return {'format': {'type': 'json_schema', 'name': 'literature_' + kind + '_v1',
                       'strict': True, 'schema': schema}}


def validate_result(value, snapshot):
    if snapshot['input']['kind'] == 'search_plan':
        return SearchPlanResult.model_validate(value).model_dump(mode='json')
    comparison = snapshot['input']['kind'] == 'evidence_comparison'
    result = (EvidenceComparisonResult if comparison else EvidenceReviewResult).model_validate(value).model_dump(mode='json')
    ids = result['evidence_ids']
    actual = {item['id']: item for item in snapshot['material']['evidence']}
    if len(set(ids)) != len(ids) or not set(ids) <= set(snapshot['input']['evidence_ids']) or not set(ids) <= set(actual):
        raise ValueError('Unbound evidence identifier')
    if not ids and result['status']!='needs_review':
        raise ValueError('Missing evidence requires review')
    if comparison and result['status']!='needs_review' and len({actual[i]['project_reference_id'] for i in ids})<2:
        raise ValueError('Comparison conclusions require at least two references')
    if result['status'] in ('supported','partial'):
        if not ids or result['relevance'] != 'related':
            raise ValueError('Support requires related saved evidence')
        if any(actual[i]['reading_scope'] == 'abstract' for i in ids) and not result['limitations']:
            raise ValueError('Abstract-only evidence requires explicit scope limitations')
        if comparison and (len({actual[i]['project_reference_id'] for i in ids})<2 or not result['limitations']):
            raise ValueError('Comparison support requires multiple sources and explicit excerpt scope limits')
    if result['relevance'] == 'uncertain' and result['status'] != 'needs_review':
        raise ValueError('Uncertain relevance needs review')
    if result['status'] == 'partial' and not result['narrowed_statement'].strip():
        raise ValueError('Partial support requires a narrower statement')
    return result
