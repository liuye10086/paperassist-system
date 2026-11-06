"""Three optional single-cell methods on frozen processed data."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Id=Annotated[str,Field(min_length=1,max_length=200,pattern=r'^[^/\\\x00-\x1f]+$')]


class SingleCellTopicConfig(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',frozen=True,allow_inf_nan=False)
    kind: Literal['integration']='integration'
    schema_version: Literal[2]=2
    method: Literal['slingshot','genie3','cellchat']
    processed_source_id: Id
    annotation_source_id: Id|None=None
    label_ids: list[Id]=Field(default_factory=list,max_length=30)
    labels_confirmed: bool=False
    label_basis: str=Field(default='',max_length=4000)
    cluster_ids: list[Id]=Field(default_factory=list,max_length=50)
    condition_values: list[Id]=Field(default_factory=list,max_length=10)
    output_language: Literal['zh-CN','en']='zh-CN'
    seed: int=Field(default=0,ge=0,le=2147483646)
    purpose: str=Field(default='',max_length=4000)
    representation: Literal['pca','pca_unadjusted','pca_harmony']='pca'
    n_components: int=Field(default=10,ge=2,le=30)
    root_cluster: Id|None=None
    root_basis: str=Field(default='',max_length=4000)
    gene_ids: list[Id]=Field(default_factory=list,max_length=500)
    tf_ids: list[Id]=Field(default_factory=list,max_length=100)
    tf_basis: str=Field(default='',max_length=4000)
    n_trees: int=Field(default=100,ge=10,le=500)
    stability_seed: int=Field(default=1,ge=0,le=2147483646)
    communication_mode: Literal['per_donor','paired','unpaired']='per_donor'
    lr_resource_id: Literal['human-demo-literature-v1']='human-demo-literature-v1'
    lr_ids: list[Id]=Field(default_factory=list,max_length=100)
    n_boot: int=Field(default=100,ge=20,le=500)
    min_cells: int=Field(default=10,ge=2,le=1000)
    species_taxon_id: int|None=Field(default=None,gt=0,exclude_if=lambda value:value is None)
    species_basis: str=Field(default='',max_length=4000,exclude_if=lambda value:value=='')

    @model_validator(mode='after')
    def necessary_parameters(self):
        if self.species_taxon_id is not None or self.species_basis:
            if self.method!='cellchat':raise ValueError('topic_species_declaration_cellchat_only')
            if self.species_taxon_id is None or not self.species_basis.strip():raise ValueError('communication_species_and_basis_required')
        for key in ('label_ids','cluster_ids','condition_values','gene_ids','tf_ids','lr_ids'):
            values=getattr(self,key)
            if len(values)!=len(set(values)):raise ValueError('duplicate_topic_'+key)
        if self.label_ids and not self.annotation_source_id:raise ValueError('topic_annotation_required')
        if self.method=='slingshot' and (not self.root_cluster or not self.root_basis.strip()):raise ValueError('trajectory_root_and_basis_required')
        if self.method=='genie3':
            if len(self.gene_ids)<2 or not self.tf_ids or not self.tf_basis.strip():raise ValueError('regulation_genes_tfs_and_basis_required')
            if not set(self.tf_ids)<=set(self.gene_ids):raise ValueError('regulation_tf_outside_gene_axis')
            if self.seed==self.stability_seed:raise ValueError('regulation_two_distinct_seeds_required')
        if self.method=='cellchat':
            if not self.annotation_source_id or len(self.label_ids)<2:raise ValueError('communication_two_labels_required')
            if self.communication_mode!='per_donor' and len(self.condition_values)!=2:raise ValueError('communication_two_conditions_required')
        return self
