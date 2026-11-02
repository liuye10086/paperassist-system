"""Typed source statements, separate from manual review and computed support."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
import re
import xml.etree.ElementTree as ET
from html import unescape

class Strict(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',frozen=True)

class EvidenceLocator(Strict):
    kind:Literal['xml_id','text']
    value:str=Field(min_length=1,max_length=1000)
    quote:str=Field(min_length=1,max_length=8000)

class TypedEvidence(Strict):
    evidence_type:Literal['disease_literature','expression_atlas','public_validation','knockout','mutation_literature']
    object_id:str=Field(min_length=1,max_length=200)
    namespace:str=Field(min_length=1,max_length=200)
    species_taxon_id:int|None=Field(default=None,ge=1)
    tissue:str|None=None
    cell_type:str|None=None
    condition:str|None=None
    dose:str|None=None
    time:str|None=None
    measurement_scale:str|None=None
    reference_version:str|None=None
    variant_id:str|None=None
    disease_id:str|None=None
    disease_scope:Literal['direct','descendant','unknown']='unknown'
    study_id:str=Field(min_length=1,max_length=500)
    cohort_id:str|None=None
    dependency_group:str=Field(min_length=1,max_length=500)
    shared_dataset_ids:list[str]=Field(default_factory=list,max_length=100)
    shared_donor_ids:list[str]|None=Field(default=None,max_length=10000)
    obtained_date:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    license:str=Field(min_length=1,max_length=2000)
    locators:list[EvidenceLocator]=Field(default_factory=list,max_length=30)
    statement:str=Field(min_length=1,max_length=8000)
    effect_direction:Literal['up','down','none']|None=None
    result_status:Literal['reported','not_significant','unknown']='unknown'
    human_review_status:Literal['not_reviewed','reviewed','disputed']='not_reviewed'
    independence_basis:str|None=None

    @model_validator(mode='after')
    def bounded(self):
        if len(self.model_dump_json().encode())>128*1024:raise ValueError('typed_evidence_too_large')
        return self


def _normalized(value):return re.sub(r'\s+',' ',unescape(value)).strip()


def verify_locators(content,filename,evidence):
    """Offline literal matching only. Never execute HTML/JS or fetch XML entities."""
    if len(content)>8*1024*1024:raise ValueError('evidence_original_size_limit')
    text=content.decode('utf-8-sig');root=None
    if any(l.kind=='xml_id' for l in evidence.locators):
        if not filename.lower().endswith('.xml') or re.search(r'<!\s*ENTITY',text,re.I):raise ValueError('unsafe_or_incompatible_xml')
        try:root=ET.fromstring(text)
        except ET.ParseError as exc:raise ValueError('evidence_xml_invalid') from exc
    matches=[]
    for locator in evidence.locators:
        if locator.kind=='xml_id':
            nodes=[n for n in root.iter() if n.get('id')==locator.value]
            if len(nodes)!=1:raise ValueError('evidence_locator_not_unique')
            excerpt=' '.join(nodes[0].itertext())
        else:
            if locator.value not in text:raise ValueError('evidence_locator_missing')
            # Text locator denotes a literal original segment; quote must occur in it.
            excerpt=locator.value
        if _normalized(locator.quote) not in _normalized(excerpt):raise ValueError('evidence_quote_mismatch')
        matches.append(locator.model_dump(mode='json'))
    return dict(locator_verified=bool(matches),matched_locators=matches,biological_claim_status='source_reported',system_computed=False)
