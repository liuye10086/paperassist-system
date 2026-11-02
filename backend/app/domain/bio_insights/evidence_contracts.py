"""Fixed candidate objects may be selected directly from processed feature axes."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

class Strict(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',frozen=True,allow_inf_nan=False)

class EvidenceCandidate(Strict):
    object_id:str=Field(min_length=1,max_length=200)
    source_id:str=Field(min_length=1,max_length=200)
    feature_id:str=Field(min_length=1,max_length=200)
    namespace:str=Field(min_length=1,max_length=200)
    species_taxon_id:int|None=Field(default=None,ge=1)
    reference_version:str|None=None
    condition:str|None=None
    expected_direction:Literal['up','down','none']|None=None
    mapping_evidence_source_id:str|None=None
    mapping_locator:str|None=None
    mapping_quote:str|None=None

class IndependentSupportRequest(Strict):
    evidence_source_id:str
    candidate_object_id:str
    result_source_id:str
    result_row_key:str
    material_source_ids:list[str]=Field(min_length=1,max_length=10)
    design_source_id:str
    overlap_audit_source_id:str
    numerator:str
    denominator:str
    q_threshold:float=Field(default=.05,ge=0,le=1)

class EvidenceMatrixConfig(Strict):
    kind:Literal['candidate']='candidate'
    schema_version:Literal[2]=2
    output_language:Literal['zh-CN','en']='zh-CN'
    candidates:list[EvidenceCandidate]=Field(min_length=1,max_length=100)
    evidence_source_ids:list[str]=Field(min_length=1,max_length=20)
    integration_result_source_ids:list[str]=Field(default_factory=list,max_length=10)
    independent_support_requests:list[IndependentSupportRequest]=Field(default_factory=list,max_length=20)
    ranking_mode:Literal['lexicographic']='lexicographic'

    @model_validator(mode='after')
    def coherent(self):
        if len({c.object_id for c in self.candidates})!=len(self.candidates):raise ValueError('duplicate_candidate_object')
        if len(set(self.evidence_source_ids))!=len(self.evidence_source_ids):raise ValueError('duplicate_evidence_source')
        for c in self.candidates:
            if c.object_id!=c.feature_id and (c.mapping_evidence_source_id not in self.evidence_source_ids or not c.mapping_locator or not c.mapping_quote):raise ValueError('explicit_alias_original_basis_required')
        for r in self.independent_support_requests:
            if r.evidence_source_id not in self.evidence_source_ids or r.candidate_object_id not in {c.object_id for c in self.candidates}:raise ValueError('support_request_identity_mismatch')
        return self

class IndependentDesignDocument(Strict):
    document_schema:Literal['independent_validation_design_v1']=Field(alias='schema')
    material_source_ids:list[str]=Field(min_length=1,max_length=10)
    object_id:str=Field(min_length=1,max_length=200)
    species_taxon_id:int=Field(ge=1)
    condition:str=Field(min_length=1,max_length=2000)
    numerator:str=Field(min_length=1,max_length=200)
    denominator:str=Field(min_length=1,max_length=200)

class DonorOverlapDocument(Strict):
    document_schema:Literal['donor_overlap_audit_v1']=Field(alias='schema')
    primary_donor_ids:list[str]=Field(min_length=1,max_length=10000)
    validation_donor_ids:list[str]=Field(min_length=1,max_length=10000)
    identity_basis:str=Field(min_length=1,max_length=4000)
    reviewer:str=Field(min_length=1,max_length=200)


def validate_support_document(content):
    import json
    if len(content)>1024*1024:raise ValueError('support_document_size_limit')
    value=json.loads(content)
    model={'independent_validation_design_v1':IndependentDesignDocument,'donor_overlap_audit_v1':DonorOverlapDocument}.get(value.get('schema'))
    if model is None:raise ValueError('support_document_schema_required')
    return model.model_validate(value)
