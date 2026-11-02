"""Frozen microbiome recipe, scale and exchangeability declarations."""
from typing import Literal
from pydantic import Field, model_validator
from .quantitative_contracts import QuantitativeModel, Identifier
from .qpcr_contracts import QpcrContrast

class MicrobiomeConfig(QuantitativeModel):
    kind: Literal['comparison']='comparison'
    schema_version: Literal[4]=4
    mode: Literal['microbiome']='microbiome'
    recipe: Literal['microbiome_diversity_v1']='microbiome_diversity_v1'
    output_language: Literal['zh-CN','en']='zh-CN'
    processed_source_id: Identifier
    abundance_scale: Literal['counts','fraction','percent']
    rounding_tolerance: float = Field(default=0.0002,ge=0,le=0.05)
    closure_confirmed: bool=False
    closure_basis: str = Field(default='',max_length=4000)
    measurement_pipeline: str = Field(min_length=1,max_length=4000)
    classification_database: Identifier
    classification_version: Identifier
    host_identity: str = Field(min_length=1,max_length=1000)
    feature_identity: str = Field(min_length=1,max_length=4000)
    taxonomy_columns: list[Identifier] = Field(min_length=1,max_length=12)
    aggregate_rank: Identifier
    taxonomy_na_values: list[str] = Field(default_factory=lambda:['','NA','N/A',r'\N'],max_length=30)
    group_column: Identifier | None=None
    unit_column: Identifier | None=None
    pair_column: Identifier | None=None
    design: Literal['descriptive','independent','paired','repeated','stratified','multifactor']='descriptive'
    independence_confirmed: bool=False
    independence_basis: str = Field(default='',max_length=4000)
    alpha_metrics: list[Literal['shannon','simpson','observed_features']] = Field(default_factory=lambda:['shannon','simpson','observed_features'],min_length=1,max_length=3)
    alpha_method: Literal['welch_t','mann_whitney_u','paired_t','wilcoxon']='welch_t'
    contrasts: list[QpcrContrast] = Field(default_factory=list,max_length=10)
    family_contrast_ids: list[Identifier] = Field(default_factory=list,max_length=10)
    beta_inference: bool=False
    permutations: int = Field(default=999,ge=0,le=9999)
    seed: int = Field(default=0,ge=0,le=2147483647)
    pcoa_method: Literal['eigh']='eigh'
    permdisp_center: Literal['median']='median'
    permdisp_method: Literal['eigh']='eigh'
    permdisp_dimensions: Literal[0]=0
    top_n: int = Field(default=10,ge=1,le=30)

    @model_validator(mode='after')
    def coherent(self):
        if len(self.model_dump_json().encode())>4*1024**2:raise ValueError('microbiome_config_limit')
        if len(set(self.taxonomy_columns))!=len(self.taxonomy_columns) or self.aggregate_rank not in self.taxonomy_columns:raise ValueError('microbiome_taxonomy_path_invalid')
        if len(set(self.alpha_metrics))!=len(self.alpha_metrics):raise ValueError('microbiome_duplicate_metric')
        ids=[c.contrast_id for c in self.contrasts]
        if len(set(ids))!=len(ids) or len(set(self.family_contrast_ids))!=len(self.family_contrast_ids) or set(ids)!=set(self.family_contrast_ids):raise ValueError('microbiome_complete_alpha_family_required')
        if any(c.numerator==c.denominator for c in self.contrasts):raise ValueError('microbiome_identical_groups')
        if self.closure_confirmed and not self.closure_basis.strip():raise ValueError('microbiome_closure_basis_required')
        if self.contrasts and self.design not in ('independent','paired'):raise ValueError('microbiome_alpha_design_unsupported')
        if self.contrasts and (not self.group_column or not self.unit_column or not self.independence_confirmed or not self.independence_basis.strip()):raise ValueError('microbiome_alpha_units_required')
        if self.contrasts and ((self.alpha_method in ('paired_t','wilcoxon'))!=(self.design=='paired')):raise ValueError('microbiome_alpha_method_design_mismatch')
        if self.design=='paired' and self.contrasts and not self.pair_column:raise ValueError('microbiome_pair_column_required')
        if self.beta_inference and (self.design!='independent' or not self.group_column or not self.unit_column or not self.independence_confirmed or not self.independence_basis.strip()):raise ValueError('microbiome_beta_requires_independent_exchangeable_single_factor')
        return self
