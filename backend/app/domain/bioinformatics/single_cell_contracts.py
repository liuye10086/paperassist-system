"""Nonspatial cell counts intake with explicit H5AD source and annotation evidence."""
from typing import Literal
from pydantic import ConfigDict, Field, field_validator, model_validator
from .contracts import BioImportRequest, BioImportInputVersion, BioDatasetSourceV1, digest, conflict
from .analysis_contracts import StrictModel, BioRecipeParameters, BioAnalysisSetupRequest, BioAnalysisInputVersion, BioProcessedDatasetSourceV1, Identifier

PARSER_VERSION='single_cell_import_v1'
WORKFLOW_VERSION='bio_import_v4'


class SingleCellAnalysisInputVersion(BioAnalysisInputVersion):
    workflow_version: Literal['bio_analysis_v3']='bio_analysis_v3'


class H5adSelection(StrictModel):
    matrix: str = Field(min_length=1,max_length=200)
    obs_index: str = Field(min_length=1,max_length=200)
    var_index: str = Field(min_length=1,max_length=200)
    symbol_column: str | None = Field(default=None,min_length=1,max_length=200)

    @model_validator(mode='after')
    def selected(self):
        if self.matrix not in ('X','raw.X') and not (self.matrix.startswith('layers/') and len(self.matrix.split('/'))==2 and self.matrix[7:]):raise ValueError('explicit_h5ad_matrix_required')
        if any('/' in s or s in ('.','..') for s in [self.obs_index,self.var_index]+([self.symbol_column] if self.symbol_column else [])):raise ValueError('h5ad_axis_column_invalid')
        return self


class SingleCellSample(StrictModel):
    sample_id: str = Field(min_length=1,max_length=100)
    library_id: str = Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_.-]+$')
    donor: str | None = Field(default=None,min_length=1,max_length=100)
    batch: str | None = Field(default=None,min_length=1,max_length=100)
    group: str | None = Field(default=None,min_length=1,max_length=100)
    species_taxon_id: int | None = Field(default=None,gt=0)
    reference_id: str | None = Field(default=None,min_length=1,max_length=200)
    reference_version: str | None = Field(default=None,min_length=1,max_length=200)
    library_chemistry: str | None = Field(default=None,min_length=1,max_length=200)
    pair_id: str | None = Field(default=None,min_length=1,max_length=100)
    file_ids: list[str] = Field(min_length=1,max_length=10)

    @model_validator(mode='after')
    def identifiers(self):
        if any(v is not None and not v.strip() for v in (self.sample_id,self.donor,self.batch,self.group,self.reference_id,self.reference_version,self.library_chemistry,self.pair_id)):
            raise ValueError('sample_identifier_empty')
        return self


class SingleCellImportRequest(BioImportRequest):
    workflow_version: Literal['bio_import_v4']
    assay: Literal['single_cell']
    matrix_representation: Literal['mtx','10x_h5','h5ad']
    h5ad: H5adSelection | None = None
    two_column_feature_type: Literal['Gene Expression'] | None = None
    samples: list[SingleCellSample] = Field(default_factory=list,max_length=10)

    @model_validator(mode='after')
    def explicit_source(self):
        if (self.matrix_representation=='h5ad')!=(self.h5ad is not None):raise ValueError('h5ad_selection_required_only_for_h5ad')
        if self.samples:
            files=[file_id for sample in self.samples for file_id in sample.file_ids]
            if len(files)!=len(set(files)) or set(files)!=set(self.file_ids):raise ValueError('sample_files_must_partition_inputs')
            if len({sample.library_id for sample in self.samples})!=len(self.samples):raise ValueError('sample_library_id_duplicate')
            for field in ('species_taxon_id','reference_id','reference_version'):
                if len({getattr(sample,field) for sample in self.samples if getattr(sample,field) is not None})>1:
                    raise ValueError('sample_'+field+'_conflict')
            assignments={}
            for sample in self.samples:
                assignment=(sample.donor,sample.group)
                if sample.sample_id in assignments and assignments[sample.sample_id]!=assignment:raise ValueError('sample_donor_assignment_conflict')
                assignments[sample.sample_id]=assignment
        return self


class SingleCellImportInputVersion(BioImportInputVersion):
    workflow_version: Literal['bio_import_v4']
    engine_version: Literal['visium_explore_v1.0.0']
    environment_digest: str = Field(pattern='^[0-9a-f]{64}$')
    code_digest: str = Field(pattern='^[0-9a-f]{64}$')
    assay: Literal['single_cell']
    matrix_representation: Literal['mtx','10x_h5','h5ad']


class CellLabel(StrictModel):
    cluster: str = Field(min_length=1,max_length=100)
    label: str = Field(default='unknown',min_length=1,max_length=200)
    marker_ids: list[str] = Field(default_factory=list,max_length=100)
    evidence_file_ids: list[str] = Field(default_factory=list,max_length=10)
    evidence_file_sha256: dict[str,str] = Field(default_factory=dict,max_length=10)
    basis: str = Field(default='',max_length=4000)
    decided_by: str = Field(default='',max_length=200)

    @model_validator(mode='after')
    def evidence(self):
        if self.label!='unknown' and (not self.decided_by.strip() or not self.basis.strip() or not (self.marker_ids or self.evidence_file_ids)):raise ValueError('cell_label_evidence_required')
        return self


class LibraryQcOverride(StrictModel):
    library_id: str = Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_.-]+$')
    min_counts: int | None = Field(default=None,ge=0,le=2147483647)
    min_genes: int | None = Field(default=None,ge=0,le=100000)
    max_counts: int | None = Field(default=None,ge=1,le=2147483647)
    max_mt_fraction: float | None = Field(default=None,ge=0,le=1)


class DoubletParameters(StrictModel):
    enabled: bool = False
    exclude_predicted: bool = False
    expected_rate: float | None = Field(default=None,gt=0,lt=1)

    @model_validator(mode='after')
    def exclusion(self):
        if self.exclude_predicted and not self.enabled:raise ValueError('doublet_exclusion_requires_enabled')
        return self


class DecontxParameters(StrictModel):
    enabled: bool = False


class HarmonyParameters(StrictModel):
    model_config = ConfigDict(extra='forbid',serialize_by_alias=True)
    enabled: bool = False
    batch_key: Literal['batch','library_id'] = 'batch'
    theta: float = Field(default=2,ge=0,le=20,allow_inf_nan=False)
    lambda_: float = Field(default=1,alias='lambda',gt=0,le=100,allow_inf_nan=False)
    max_iter: int = Field(default=10,ge=1,le=100)


class SingleCellParameters(BioRecipeParameters):
    in_tissue_only: Literal[False] = False
    cell_labels: list[CellLabel] = Field(default_factory=list,max_length=1000)
    donor_design_confirmed: bool = False
    independence_basis: str = Field(default='',max_length=4000)
    library_qc_overrides: list[LibraryQcOverride] = Field(default_factory=list,max_length=100)
    doublet: DoubletParameters = Field(default_factory=DoubletParameters)
    decontx: DecontxParameters = Field(default_factory=DecontxParameters)
    hvg_batch_key: Literal['batch','library_id'] | None = None
    technical_covariates: list[Literal['log1p_total_counts','mt_fraction']] = Field(default_factory=list,max_length=2)
    harmony: HarmonyParameters = Field(default_factory=HarmonyParameters)

    @model_validator(mode='after')
    def unique_labels(self):
        if len(set(self.technical_covariates))!=len(self.technical_covariates):raise ValueError('duplicate_technical_covariate')
        if len({v.cluster for v in self.cell_labels})!=len(self.cell_labels):raise ValueError('duplicate_cluster_label')
        if self.donor_design_confirmed and not self.independence_basis.strip():raise ValueError('donor_independence_basis_required')
        if len({v.library_id for v in self.library_qc_overrides})!=len(self.library_qc_overrides):raise ValueError('duplicate_library_qc')
        for override in self.library_qc_overrides:
            minimum=self.min_counts if override.min_counts is None else override.min_counts
            maximum=self.max_counts if override.max_counts is None else override.max_counts
            if maximum is not None and maximum<minimum:raise ValueError('library_qc_threshold_conflict:'+override.library_id)
            if override.max_mt_fraction is not None and (not self.mt_rule.confirmed or self.mt_rule.kind=='unknown'):raise ValueError('library_qc_mitochondrial_rule')
        return self


def new_single_cell_parameters():
    return SingleCellParameters(hvg_batch_key='batch',technical_covariates=['log1p_total_counts'],harmony=HarmonyParameters(enabled=True))


def new_parameter_defaults(value):
    if not isinstance(value,dict):return value
    defaults=new_single_cell_parameters().model_dump()
    return {**{key:defaults[key] for key in ('hvg_batch_key','technical_covariates','harmony')},**value}


class SingleCellSetupRequest(BioAnalysisSetupRequest):
    recipe_code: Literal['single_cell_explore_v1']
    params: SingleCellParameters = Field(default_factory=new_single_cell_parameters)
    @model_validator(mode='before')
    @classmethod
    def setup_defaults(cls,value):
        if isinstance(value,dict):
            value=dict(value)
            value['params']=new_parameter_defaults(value.get('params',{})) if value.get('expected_revision')==0 else value.get('params',{})
        return value


def validate_library_qc_libraries(params,samples):
    if {v.library_id for v in params.library_qc_overrides}-{v.get('library_id') for v in samples}:
        raise ValueError('unknown_library_qc_override')


class SingleCellAnalysisStartRequest(StrictModel):
    name: str = Field(min_length=1,max_length=200)
    raw_source: BioDatasetSourceV1
    observation_map_version_id: str | None = Field(default=None,min_length=1,max_length=64)
    design_version_id: str | None = Field(default=None,min_length=1,max_length=64)
    params: SingleCellParameters = Field(default_factory=new_single_cell_parameters)
    _new_defaults=field_validator('params',mode='before')(new_parameter_defaults)


class SingleCellSubsetRequest(StrictModel):
    name: str = Field(min_length=1,max_length=200)
    parent_processed_source: BioProcessedDatasetSourceV1
    cluster_ids: list[Identifier] = Field(default_factory=list,max_length=50)
    cell_ids: list[Identifier] = Field(default_factory=list,max_length=20000)
    observation_map_version_id: str | None = Field(default=None,min_length=1,max_length=64)
    design_version_id: str | None = Field(default=None,min_length=1,max_length=64)
    params: SingleCellParameters = Field(default_factory=new_single_cell_parameters)
    _new_defaults=field_validator('params',mode='before')(new_parameter_defaults)

    @model_validator(mode='after')
    def explicit_selection(self):
        if not self.cluster_ids and not self.cell_ids:raise ValueError('Explicit parent cell selection is required')
        if len(set(self.cluster_ids))!=len(self.cluster_ids) or len(set(self.cell_ids))!=len(self.cell_ids):raise ValueError('Duplicate subset selection')
        return self


class SingleCellSubsetSelection(StrictModel):
    parent_processed_source: BioProcessedDatasetSourceV1
    cluster_ids: list[Identifier] = Field(default_factory=list,max_length=50)
    cell_ids: list[Identifier] = Field(default_factory=list,max_length=20000)
    resolved_cell_ids: list[Identifier] = Field(min_length=1,max_length=20000)

    @model_validator(mode='after')
    def explicit_selection(self):
        if not self.cluster_ids and not self.cell_ids:raise ValueError('Explicit parent cell selection is required')
        if any(len(set(values))!=len(values) for values in (self.cluster_ids,self.cell_ids,self.resolved_cell_ids)):raise ValueError('Duplicate subset selection')
        return self


def validate_import_snapshot(task):
    from .settings import BioLimits
    from .analysis_settings import BioAnalysisLimits
    try:
        value=task['input_snapshot'];request=SingleCellImportRequest.model_validate(value['single_cell_config'])
        required={'schema_version','kind','workflow_version','project_id','import_id','dataset_id','name','assay','parser_version','expected_dataset_revision','output_language','files','settings','single_cell_config','analysis_limits','engine_version','environment_digest','code_digest'}
        if (set(value)!=required or value['workflow_version']!=WORKFLOW_VERSION or task['workflow_version']!=WORKFLOW_VERSION or value['kind']!='bio_import' or task['task_type']!='bio_import' or value['project_id']!=task['project_id'] or value['assay']!='single_cell' or value['parser_version']!=PARSER_VERSION or value['name']!=request.name or task['input_digest']!=digest(value) or {f['id'] for f in value['files']}!=set(request.file_ids)):raise ValueError('single_cell_snapshot_invalid')
        BioLimits.model_validate(value['settings']);BioAnalysisLimits.model_validate(value['analysis_limits'])
        SingleCellImportInputVersion(kind='bio_import',import_id=value['import_id'],dataset_id=value['dataset_id'],workflow_version=WORKFLOW_VERSION,source_file_ids=request.file_ids,parser_version=PARSER_VERSION,output_language=value['output_language'],assay='single_cell',matrix_representation=request.matrix_representation,**{k:value[k] for k in ('engine_version','environment_digest','code_digest')})
        return value
    except (KeyError,TypeError,ValueError) as exc:raise conflict() from exc
