"""Nonspatial cell counts intake with explicit H5AD source and annotation evidence."""
from typing import Literal
from pydantic import Field, model_validator
from .contracts import BioImportRequest, BioImportInputVersion, digest, conflict
from .analysis_contracts import StrictModel, BioRecipeParameters, BioAnalysisSetupRequest, BioAnalysisInputVersion

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


class SingleCellImportRequest(BioImportRequest):
    workflow_version: Literal['bio_import_v4']
    assay: Literal['single_cell']
    matrix_representation: Literal['mtx','10x_h5','h5ad']
    h5ad: H5adSelection | None = None
    two_column_feature_type: Literal['Gene Expression'] | None = None

    @model_validator(mode='after')
    def explicit_source(self):
        if (self.matrix_representation=='h5ad')!=(self.h5ad is not None):raise ValueError('h5ad_selection_required_only_for_h5ad')
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


class SingleCellParameters(BioRecipeParameters):
    in_tissue_only: Literal[False] = False
    cell_labels: list[CellLabel] = Field(default_factory=list,max_length=1000)
    donor_design_confirmed: bool = False
    independence_basis: str = Field(default='',max_length=4000)

    @model_validator(mode='after')
    def unique_labels(self):
        if len({v.cluster for v in self.cell_labels})!=len(self.cell_labels):raise ValueError('duplicate_cluster_label')
        if self.donor_design_confirmed and not self.independence_basis.strip():raise ValueError('donor_independence_basis_required')
        return self


class SingleCellSetupRequest(BioAnalysisSetupRequest):
    recipe_code: Literal['single_cell_explore_v1']
    params: SingleCellParameters = Field(default_factory=SingleCellParameters)


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
