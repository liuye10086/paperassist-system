"""Versioned nonspatial quantitative contracts; old Visium contracts stay strict."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer
from .contracts import BioDatasetSourceV1, BioImportInputVersion, digest, conflict
from .analysis_contracts import BioAnalysisInputVersion

ENGINE_VERSION='tabular_quantitative_v1.0.0'
PARSER_VERSION='tabular_assay_import_v1'
ASSAYS=('bulk_rna_counts','normalized_expression','proteomics','metabolomics','microbiome')
Assay=Literal['bulk_rna_counts','normalized_expression','proteomics','metabolomics','microbiome']


class BioImportInputVersionV3(BioImportInputVersion):
    workflow_version: Literal['bio_import_v3']
    engine_version: Literal['tabular_quantitative_v1.0.0']
    environment_digest: str = Field(pattern='^[0-9a-f]{64}$')
    code_digest: str = Field(pattern='^[0-9a-f]{64}$')
    assay: Assay


class BioAnalysisInputVersionV2(BioAnalysisInputVersion):
    workflow_version: Literal['bio_analysis_v2']='bio_analysis_v2'
    engine_version: Literal['tabular_quantitative_v1.0.0']=ENGINE_VERSION


class Strict(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',allow_inf_nan=False)


class TabularFileSpec(Strict):
    file_id: str = Field(min_length=1,max_length=64)
    role: Literal['quantitative_matrix','sample_metadata','feature_metadata']
    format: Literal['csv','tsv','xlsx']
    sheet: str | None = Field(default=None,max_length=200)
    header_row: int = Field(default=1,ge=1,le=1000)
    encoding: Literal['utf-8-sig','utf-8'] = 'utf-8-sig'
    delimiter: Literal[',','\t'] | None = None

    @model_validator(mode='after')
    def sheet_required(self):
        if self.format=='xlsx' and not self.sheet:raise ValueError('xlsx_explicit_sheet_required')
        return self


class QuantitativeScale(Strict):
    kind: Literal['raw_counts','tpm','fpkm','normalized','log2','ln','log10','intensity','relative_abundance','concentration']
    unit: str = Field(min_length=1,max_length=200)
    upstream_method: str = Field(min_length=1,max_length=4000)
    upstream_transforms: list[str] = Field(default_factory=list,max_length=20)
    namespace: str = Field(default='unknown',min_length=1,max_length=200)
    reference_version: str = Field(default='unknown',min_length=1,max_length=200)
    species_taxon_id: int | None = Field(default=None,ge=1)
    zero_meaning: Literal['measured_zero','unknown','below_lod'] = 'measured_zero'


class BioImportRequestV3(Strict):
    workflow_version: Literal['bio_import_v3']
    file_ids: list[str] = Field(min_length=2,max_length=3)
    assay: Assay
    name: str = Field(min_length=1,max_length=200)
    dataset_id: str | None = Field(default=None,min_length=1,max_length=64)
    expected_dataset_revision: int = Field(ge=0,le=2147483646)
    tables: list[TabularFileSpec] = Field(min_length=2,max_length=3)
    feature_id_column: str = Field(min_length=1,max_length=200)
    sample_columns: list[str] = Field(min_length=1,max_length=500)
    scale: QuantitativeScale
    na_values: list[str] = Field(default_factory=lambda:['','NA','N/A'],max_length=30)

    @property
    def roles(self):return {table.file_id:table.role for table in self.tables}

    @model_validator(mode='after')
    def valid(self):
        roles=[t.role for t in self.tables]
        if (len(self.file_ids)!=len(set(self.file_ids)) or {t.file_id for t in self.tables}!=set(self.file_ids)
            or len(roles)!=len(set(roles)) or not {'quantitative_matrix','sample_metadata'}<=set(roles)
            or len(self.sample_columns)!=len(set(self.sample_columns)) or self.feature_id_column in self.sample_columns
            or any(not s or len(s)>200 or any(ord(c)<32 for c in s) for s in self.sample_columns)
            or (self.dataset_id is None)!=(self.expected_dataset_revision==0)):
            raise ValueError('tabular_source_or_axis_invalid')
        if self.assay!='microbiome' and (self.assay=='bulk_rna_counts')!=(self.scale.kind=='raw_counts'):raise ValueError('counts_scale_mismatch')
        if self.assay=='normalized_expression' and self.scale.kind not in ('tpm','fpkm','normalized','log2','ln','log10'):
            raise ValueError('expression_scale_invalid')
        if self.assay=='microbiome':
            if ((self.scale.kind,self.scale.unit) not in (('raw_counts','counts'),('relative_abundance','fraction'),('relative_abundance','percent'))
                or len(self.tables)!=3):raise ValueError('microbiome_scale_and_taxonomy_required')
        elif len(self.sample_columns)>255:raise ValueError('tabular_sample_limit')
        return self


class TabularRecipeParameters(Strict):
    normalization: Literal['none','already_normalized','median','display_library_size'] = 'none'
    transform: Literal['none','log2','ln','log10','log1p'] = 'none'
    log1p_offset: Literal[1] = 1
    scaling: Literal['none','unit_variance'] = 'none'
    exclude_samples: list[str] = Field(default_factory=list,max_length=255)
    exclude_features: list[str] = Field(default_factory=list,max_length=100000)
    pca_components: int = Field(default=10,ge=2,le=100)
    seed: int = Field(default=0,ge=0,le=2147483647)
    output_language: Literal['zh-CN','en'] = 'en'

    @model_serializer(mode='wrap')
    def explicit_offset_only(self,handler):
        data=handler(self)
        if self.transform!='log1p':data.pop('log1p_offset',None)
        return data


def validate_recipe(params, manifest):
    params=TabularRecipeParameters.model_validate(params) if isinstance(params,dict) else params
    scale=manifest['scale']['kind']
    if manifest['assay']=='microbiome' and (params.normalization not in ('none','already_normalized') or params.transform!='none' or params.scaling!='none'):raise ValueError('microbiome_preserve_source_scale')
    if params.transform!='none' and scale in ('log2','ln','log10'):raise ValueError('already_logged_input')
    if params.transform=='log1p' and manifest['assay']!='bulk_rna_counts':raise ValueError('counts_only_explicit_log1p')
    if params.normalization=='display_library_size' and manifest['assay']!='bulk_rna_counts':raise ValueError('counts_only_normalization')
    if params.normalization=='median' and scale in ('log2','ln','log10'):raise ValueError('median_requires_positive_unlogged_scale')
    if len(set(params.exclude_samples))!=len(params.exclude_samples) or len(set(params.exclude_features))!=len(params.exclude_features):raise ValueError('duplicate_exclusion')
    return params


class TabularAnalysisSetupRequest(Strict):
    recipe_code: Literal['tabular_quantitative_v1']
    name: str = Field(min_length=1,max_length=200)
    raw_source: BioDatasetSourceV1
    expected_revision: int = Field(ge=0,lt=2147483647)
    observation_map_version_id: None = None
    design_version_id: str | None = Field(default=None,min_length=1,max_length=64)
    params: TabularRecipeParameters = Field(default_factory=TabularRecipeParameters)


class BioProcessedDatasetSourceV2(Strict):
    kind: Literal['bio_processed_dataset_version']='bio_processed_dataset_version'
    schema_version: Literal[2]=2
    project_id: str
    processed_dataset_version_id: str
    analysis_run_id: str
    raw_source: BioDatasetSourceV1
    recipe_version_id: str
    manifest_sha256: str = Field(pattern='^[0-9a-f]{64}$')
    engine_version: Literal['tabular_quantitative_v1.0.0']=ENGINE_VERSION
    environment_digest: str = Field(pattern='^[0-9a-f]{64}$')
    assay: Assay
    observation_level: Literal['sample']='sample'

    @model_validator(mode='after')
    def scoped(self):
        if self.project_id!=self.raw_source.project_id:raise ValueError('processed_project_mismatch')
        return self


def validate_import_snapshot(task):
    from .settings import BioLimits
    try:
        value=task['input_snapshot'];config=BioImportRequestV3.model_validate(value['tabular_config'])
        expected={'schema_version','kind','workflow_version','project_id','import_id','dataset_id','name','assay','parser_version',
                  'expected_dataset_revision','output_language','files','settings','tabular_config','engine_version','environment_digest','code_digest'}
        if (set(value)!=expected or value['schema_version']!=1 or value['workflow_version']!='bio_import_v3'
            or task['workflow_version']!=value['workflow_version'] or task['task_type']!='bio_import' or value['kind']!='bio_import'
            or value['project_id']!=task['project_id'] or digest(value)!=task['input_digest'] or value['parser_version']!=PARSER_VERSION
            or value['engine_version']!=ENGINE_VERSION or value['assay']!=config.assay or value['name']!=config.name
            or {f['id'] for f in value['files']}!=set(config.file_ids) or value['expected_dataset_revision']<1):raise ValueError()
        import re
        if any(not re.fullmatch('[a-f0-9]{64}',value[k]) for k in ('code_digest','environment_digest')):raise ValueError()
        BioLimits.model_validate(value['settings'])
        return value
    except (KeyError,TypeError,ValueError) as exc:raise conflict() from exc
