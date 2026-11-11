"""Sample-level V2 contracts, independent of the spatial V1 vocabulary."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

Identifier=Annotated[str,Field(min_length=1,max_length=200,pattern=r'^[^/\\\x00-\x1f]+$')]


class QuantitativeModel(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',frozen=True,allow_inf_nan=False)


class SampleKey(QuantitativeModel):
    processed_version_id: Identifier
    sample_id: Identifier


class SampleGroup(QuantitativeModel):
    label: Identifier
    sample_keys: list[SampleKey]=Field(min_length=1,max_length=10000)


class QuantitativeContrast(QuantitativeModel):
    contrast_id: Identifier
    name: str=Field(min_length=1,max_length=500)
    groups: list[SampleGroup]=Field(min_length=2,max_length=6)


class SampleExclusion(SampleKey):
    reason: str=Field(min_length=1,max_length=1000)


class QuantitativeCovariate(QuantitativeModel):
    field: Identifier
    kind: Literal['categorical','continuous']
    name: str=Field(min_length=1,max_length=200)
    reference_level: str | None=Field(default=None,min_length=1,max_length=200)

    @model_validator(mode='after')
    def valid_reference(self):
        if self.kind=='continuous' and self.reference_level is not None:
            raise ValueError('continuous_covariate_has_no_reference_level')
        return self


class QuantitativeComparisonConfig(QuantitativeModel):
    kind: Literal['comparison']='comparison'
    schema_version: Literal[2]=2
    mode: Literal['bulk_counts','continuous']
    design: Literal['independent','paired','multiple']
    method: Literal['deseq2_wald','welch_t','mann_whitney_u','paired_t','wilcoxon','welch_anova','kruskal_wallis']
    analysis_layer: Literal['raw_counts','analysis','display']
    contrasts: list[QuantitativeContrast]=Field(min_length=1,max_length=10)
    family_contrast_ids: list[Identifier]=Field(min_length=1,max_length=10)
    inference_unit: Literal['biological','technical']
    inference_goal: Literal['inference','exploratory']
    independence_confirmed: bool=False
    independence_basis: str=Field(default='',max_length=4000)
    technical_exploration_confirmed: bool=False
    design_basis: str=Field(min_length=1,max_length=4000)
    data_driven_grouping: bool
    pairing_field: Literal['pair_id','donor','biological_unit_id']='pair_id'
    batch_adjustment: bool=False
    bulk_model: Literal['shared_wald_v1'] | None=None
    covariates: list[QuantitativeCovariate]=Field(default_factory=list,max_length=16)
    condition_reference: Identifier | None=None
    minimum_sample_counts: int=Field(default=1,ge=1,le=1000000)
    excluded_samples: list[SampleExclusion]=Field(default_factory=list,max_length=10000)
    minimum_total_counts: int=Field(default=10,ge=1,le=1000000)
    size_factor_method: Literal['ratio','poscounts']='ratio'
    posthoc: Literal['none','all_pairs_holm']='none'
    missing_policy: Literal['complete_cases']='complete_cases'
    namespace: Identifier
    reference_version: Identifier
    species_taxon_id: int | None=Field(default=None,ge=1,le=2147483647)
    output_language: Literal['zh-CN','en']='zh-CN'

    @model_serializer(mode='wrap')
    def frozen_config(self, handler):
        data = handler(self)
        if self.bulk_model is None:
            for field in ('bulk_model','covariates','condition_reference','minimum_sample_counts'):
                data.pop(field, None)
        return data

    @model_validator(mode='after')
    def coherent(self):
        if len(self.model_dump_json().encode())>4*1024**2:raise ValueError('quantitative_config_limit')
        ids=[c.contrast_id for c in self.contrasts]
        if len(ids)!=len(set(ids)) or len(set(self.family_contrast_ids))!=len(self.family_contrast_ids) or set(ids)!=set(self.family_contrast_ids):raise ValueError('complete_family_required')
        covariate_fields=[covariate.field for covariate in self.covariates]
        if len(covariate_fields)!=len(set(covariate_fields)):raise ValueError('duplicate_covariate')
        reserved={'condition','sample_id','processed_version_id','biological_unit_id','pair_id','donor','batch','sample_role','retained','kept','source_row','exclusion_reason'}
        if reserved.intersection(covariate_fields):raise ValueError('reserved_covariate')
        if self.bulk_model is None and (self.covariates or self.condition_reference or self.minimum_sample_counts!=1):
            raise ValueError('structured_bulk_model_required')
        if self.mode=='bulk_counts':
            if self.method!='deseq2_wald' or self.analysis_layer!='raw_counts' or self.inference_unit!='biological':raise ValueError('counts_design_invalid')
            if self.bulk_model is None and (self.design=='multiple' or self.design=='paired' and self.batch_adjustment):
                raise ValueError('structured_bulk_model_required')
            if self.posthoc!='none':raise ValueError('counts_posthoc_unsupported')
        else:
            methods={'welch_t':'independent','mann_whitney_u':'independent','paired_t':'paired','wilcoxon':'paired','welch_anova':'multiple','kruskal_wallis':'multiple'}
            if methods.get(self.method)!=self.design or self.analysis_layer=='raw_counts' or self.batch_adjustment or self.bulk_model:raise ValueError('continuous_design_invalid')
        if self.posthoc!='none' and self.design!='multiple':raise ValueError('posthoc_requires_multiple')
        omnibus=self.mode=='continuous' and self.design=='multiple'
        for contrast in self.contrasts:
            if (omnibus and len(contrast.groups)<3) or (not omnibus and len(contrast.groups)!=2):raise ValueError('group_count_invalid')
            if len({g.label for g in contrast.groups})!=len(contrast.groups):raise ValueError('duplicate_group_label')
        return self


def quantitative_scope(config,assays):
    return 'sample_exploratory' if (config.inference_unit=='technical' or config.inference_goal=='exploratory'
        or config.data_driven_grouping or 'normalized_expression' in assays) else 'sample_inference'
