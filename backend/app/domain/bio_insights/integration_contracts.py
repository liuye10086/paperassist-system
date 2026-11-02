"""Frozen correspondence and predeclared integration; no numeric dependencies."""
from typing import Literal
from pydantic import Field, model_validator
from .feature_contracts import FeatureModel, Id

SAMPLE_COLUMNS=('dataset_version','observation_id','donor_id','tissue','time','match_group','relationship','basis','independent_unit_verified')
OBJECT_COLUMNS=('source_dataset_version','source_id','source_namespace','source_species','source_version','target_dataset_version','target_id','target_namespace','target_species','target_version','relationship','basis','ambiguity','decision')

class IntegrationPair(FeatureModel):
    pair_id:Id
    left_source_id:Id
    left_feature_id:Id
    right_source_id:Id
    right_feature_id:Id

class ConcordanceSelection(FeatureModel):
    concordance_id:Id
    left_result_source_id:Id
    right_result_source_id:Id
    left_contrast_id:Id
    right_contrast_id:Id
    object_ids:list[Id]=Field(min_length=1,max_length=10000)
    direction_alignment:Literal['same','reverse','incomparable']
    comparison_basis:str=Field(min_length=1,max_length=4000)
    q_column:Literal['q_within_contrast','q_global_family','original_q','system_recomputed_q','q_value','fdr_q_value']='q_within_contrast'
    q_threshold:float=Field(default=.05,ge=0,le=1)
    minimum_absolute_effect:float=Field(default=0.,ge=0)
    @model_validator(mode='after')
    def unique(self):
        if len(self.object_ids)!=len(set(self.object_ids)):raise ValueError('duplicate_concordance_object')
        return self

class IntegrationConfig(FeatureModel):
    kind:Literal['integration']='integration'
    output_language:Literal['zh-CN','en']='zh-CN'
    processed_source_ids:list[Id]=Field(default_factory=list,max_length=10)
    sample_mapping_source_id:Id|None=None
    object_mapping_source_id:Id|None=None
    pairs:list[IntegrationPair]=Field(default_factory=list,max_length=10000)
    concordances:list[ConcordanceSelection]=Field(default_factory=list,max_length=100)
    mode:Literal['descriptive','inference']='descriptive'
    method:Literal['pearson','spearman']='pearson'
    analysis_layer:Literal['analysis','display']='analysis'
    missing_rule:Literal['pairwise_complete_finite']='pairwise_complete_finite'
    transform:Literal['none']='none'
    alternative:Literal['two-sided']='two-sided'
    correction:Literal['BH']='BH'
    seed:Literal[1729]=1729
    mapping_confirmed:bool=False
    partial_subset_confirmed:bool=False
    independence_confirmed:bool=False
    independence_basis:str=Field(default='',max_length=4000)
    @model_validator(mode='after')
    def coherent(self):
        if not self.pairs and not self.concordances:raise ValueError('integration_requires_predeclared_relations')
        if len(self.pairs)+sum(len(c.object_ids) for c in self.concordances)>10000:raise ValueError('integration_relation_limit')
        if len(self.processed_source_ids)!=len(set(self.processed_source_ids)):raise ValueError('duplicate_processed_source')
        if len({p.pair_id for p in self.pairs})!=len(self.pairs):raise ValueError('duplicate_pair_id')
        if len({(p.left_source_id,p.left_feature_id,p.right_source_id,p.right_feature_id) for p in self.pairs})!=len(self.pairs):raise ValueError('duplicate_pair')
        if len({c.concordance_id for c in self.concordances})!=len(self.concordances):raise ValueError('duplicate_concordance')
        if self.pairs and (not self.sample_mapping_source_id or not self.object_mapping_source_id):raise ValueError('correspondence_resources_required')
        if any(p.left_source_id not in self.processed_source_ids or p.right_source_id not in self.processed_source_ids or p.left_source_id==p.right_source_id for p in self.pairs):raise ValueError('pair_source_selection_invalid')
        if self.mode=='inference' and (not self.independence_confirmed or not self.independence_basis.strip()):raise ValueError('independent_units_confirmation_required')
        if self.mode=='inference' and self.method=='spearman' and len(self.pairs)>100:raise ValueError('spearman_inference_pair_budget_100')
        return self


def normalize_correspondence(kind, rows):
    columns=SAMPLE_COLUMNS if kind=='sample_correspondence' else OBJECT_COLUMNS
    output=[]
    for number,raw in enumerate(rows,1):
        if set(raw)!=set(columns):raise ValueError('correspondence_columns_mismatch')
        r={k:str(raw[k]) if raw[k] is not None else '' for k in columns}
        if any(len(v)>4000 for v in r.values()):raise ValueError('correspondence_cell_limit')
        required=set(columns)-({'donor_id','tissue','time'} if kind=='sample_correspondence' else set())
        if any(not r[k].strip() for k in required):raise ValueError('correspondence_required_value')
        if kind=='sample_correspondence':
            if r['relationship'] not in ('same_sample','same_donor_different_tissue','independent_experiment','partial','author_declared_matched_sample'):raise ValueError('sample_relationship_invalid')
            if r['independent_unit_verified'].lower() not in ('true','false','1','0'):raise ValueError('independent_unit_flag_invalid')
            r['independent_unit_verified']=r['independent_unit_verified'].lower() in ('true','1')
            r['donor_id']=r['donor_id'] or None
            if r['independent_unit_verified'] and not r['donor_id']:raise ValueError('verified_unit_requires_donor')
        else:
            for key in ('source_species','target_species'):
                r[key]=int(r[key])
                if r[key]<1:raise ValueError('mapping_species_invalid')
            if r['ambiguity'] not in ('none','one_to_many','many_to_one','unknown') or r['decision'] not in ('include','exclude','expand'):raise ValueError('mapping_decision_invalid')
        output.append(dict(row_number=number,**r))
        if len(output)>100000:raise ValueError('correspondence_row_limit')
    if not output:raise ValueError('empty_correspondence')
    return output
