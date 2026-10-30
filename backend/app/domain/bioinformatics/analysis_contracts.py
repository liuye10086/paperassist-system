"""Strict spatial-analysis identities, separate from legacy rectangular sources."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.domain.bioinformatics.contracts import BioDatasetSourceV1, digest, conflict

ENGINE_VERSION = 'visium_explore_v1.0.0'
WORKFLOW_VERSION = 'bio_analysis_v1'
FIGURE_WORKFLOW_VERSION = 'bio_figure_v1'
Hash = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r'^[^/\\\x00-\x1f]+$')]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)


class BioMappingValue(StrictModel):
    status: Literal['known','pending','not_applicable'] = 'pending'
    value: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode='after')
    def knowledge(self):
        if (self.status == 'known') != (self.value is not None):
            raise ValueError('Known values require evidence; unknown values must stay null')
        return self


class BioObservationRow(StrictModel):
    barcode: Identifier
    sample_id: BioMappingValue = Field(default_factory=BioMappingValue)
    section: BioMappingValue = Field(default_factory=BioMappingValue)
    donor: BioMappingValue = Field(default_factory=BioMappingValue)
    batch: BioMappingValue = Field(default_factory=BioMappingValue)
    group: BioMappingValue = Field(default_factory=BioMappingValue)


class BioMappingTableSource(StrictModel):
    file_id: str = Field(min_length=1,max_length=64)
    sha256: Hash
    sheet: int | str = 0
    mapping: dict[Literal['barcode','sample_id','section','donor','batch','group'],str]

    @model_validator(mode='after')
    def columns(self):
        if 'barcode' not in self.mapping or any(not value or len(value)>200 for value in self.mapping.values()):
            raise ValueError('An explicit barcode column is required')
        if isinstance(self.sheet,int) and self.sheet<0:
            raise ValueError('Invalid sheet')
        return self


class BioObservationMapRequest(StrictModel):
    name: str = Field(min_length=1,max_length=200)
    raw_source: BioDatasetSourceV1
    expected_revision: int = Field(ge=0,lt=2147483647)
    design_version_id: str | None = Field(default=None,min_length=1,max_length=64)
    rows: list[BioObservationRow] = Field(default_factory=list,max_length=20000)
    table_source: BioMappingTableSource | None = None

    @model_validator(mode='after')
    def unique_barcodes(self):
        if len({row.barcode for row in self.rows}) != len(self.rows):
            raise ValueError('Duplicate barcode')
        if self.table_source is not None and self.rows:
            raise ValueError('Table application and manually entered rows are exclusive')
        return self


class BioObservationMapPreviewRequest(StrictModel):
    raw_source: BioDatasetSourceV1
    file_id: str = Field(min_length=1,max_length=64)
    sheet: int | str = 0
    mapping: dict[Literal['barcode','sample_id','section','donor','batch','group'],str]
    design_version_id: str | None = Field(default=None,min_length=1,max_length=64)

    @model_validator(mode='after')
    def columns(self):
        if 'barcode' not in self.mapping or any(not value or len(value)>200 for value in self.mapping.values()):
            raise ValueError('An explicit barcode column is required')
        if isinstance(self.sheet,int) and self.sheet<0:
            raise ValueError('Invalid sheet')
        return self


class BioMitochondrialRule(StrictModel):
    kind: Literal['unknown','feature_ids','prefix'] = 'unknown'
    feature_ids: list[Identifier] = Field(default_factory=list,max_length=100000)
    prefix: str | None = Field(default=None,min_length=1,max_length=100)
    confirmed: bool = False

    @model_validator(mode='after')
    def explicit_rule(self):
        if len(set(self.feature_ids)) != len(self.feature_ids):
            raise ValueError('Duplicate mitochondrial feature ID')
        if self.kind=='unknown' and (self.feature_ids or self.prefix is not None or self.confirmed):
            raise ValueError('Unknown mitochondrial rule cannot imply a rule')
        if self.kind=='feature_ids' and (not self.feature_ids or self.prefix is not None):
            raise ValueError('Explicit feature IDs required')
        if self.kind=='prefix' and (self.prefix is None or self.feature_ids):
            raise ValueError('Explicit prefix required')
        return self


class BioRecipeParameters(StrictModel):
    in_tissue_only: bool = False
    min_counts: int = Field(default=1,ge=0,le=2147483647)
    min_genes: int = Field(default=1,ge=0,le=100000)
    min_spots: int = Field(default=3,ge=1,le=20000)
    max_counts: int | None = Field(default=None,ge=1,le=2147483647)
    max_mt_fraction: float | None = Field(default=None,ge=0,le=1)
    exclude_barcodes: list[Identifier] = Field(default_factory=list,max_length=20000)
    mt_rule: BioMitochondrialRule = Field(default_factory=BioMitochondrialRule)
    target_sum: float = Field(default=10000.0,ge=1,le=1000000)
    hvg_count: int = Field(default=2000,ge=3,le=10000)
    pca_components: int = Field(default=30,ge=2,le=100)
    neighbors: int = Field(default=15,ge=2,le=100)
    resolution: float = Field(default=0.5,gt=0,le=10)
    seed: int = Field(default=0,ge=0,le=2147483647)
    marker_top_n: int = Field(default=5,ge=1,le=100)
    output_language: Literal['zh-CN','en'] = 'en'

    @model_validator(mode='after')
    def consistent(self):
        if self.max_counts is not None and self.max_counts<self.min_counts:
            raise ValueError('Maximum counts cannot be lower than minimum counts')
        if self.max_mt_fraction is not None and (not self.mt_rule.confirmed or self.mt_rule.kind=='unknown'):
            raise ValueError('Mitochondrial filtering requires a confirmed rule')
        if len(set(self.exclude_barcodes)) != len(self.exclude_barcodes):
            raise ValueError('Duplicate excluded barcode')
        return self


class BioAnalysisSetupRequest(StrictModel):
    name: str = Field(min_length=1,max_length=200)
    raw_source: BioDatasetSourceV1
    expected_revision: int = Field(ge=0,lt=2147483647)
    observation_map_version_id: str | None = Field(default=None,min_length=1,max_length=64)
    design_version_id: str | None = Field(default=None,min_length=1,max_length=64)
    params: BioRecipeParameters = Field(default_factory=BioRecipeParameters)


class BioAnalysisRunRequest(StrictModel):
    raw_source: BioDatasetSourceV1
    recipe_version_id: str = Field(min_length=1,max_length=64)
    expected_setup_revision: int = Field(ge=1,lt=2147483647)


class BioAnalysisConfirmRequest(StrictModel):
    task_revision: int = Field(ge=1,lt=2147483647)
    checkpoint_id: str = Field(min_length=1,max_length=64)
    wait_id: str = Field(min_length=1,max_length=64)
    candidate_sha256: Hash
    expected_setup_revision: int = Field(ge=1,lt=2147483647)


class BioProcessedDatasetSourceV1(StrictModel):
    model_config = ConfigDict(strict=True,extra='forbid',frozen=True)
    kind: Literal['bio_processed_dataset_version'] = 'bio_processed_dataset_version'
    schema_version: Literal[1] = 1
    project_id: str
    processed_dataset_version_id: str
    analysis_run_id: str
    raw_source: BioDatasetSourceV1
    recipe_version_id: str
    manifest_sha256: Hash
    engine_version: Literal['visium_explore_v1.0.0'] = ENGINE_VERSION
    environment_digest: Hash

    @model_validator(mode='after')
    def scope(self):
        if self.raw_source.project_id != self.project_id:
            raise ValueError('Processed and raw project differ')
        return self


class BioFigureConfig(StrictModel):
    kind: Literal['qc','pca','umap','marker_dotplot','marker_heatmap','spatial_cluster','spatial_gene','annotation']
    panel: Literal['default','scores','variance','distribution','violin','scatter','mitochondrial','sample_id','section','batch'] = 'default'
    color_by: Literal['cluster','sample_id','section','batch'] = 'cluster'
    gene_ids: list[Identifier] = Field(default_factory=list,max_length=100)
    layer: Literal['counts','normalized','log1p'] = 'log1p'
    title: str = Field(default='',max_length=200)
    palette: Literal['viridis','magma','tab20'] = 'viridis'
    vmin: float | None = None
    vmax: float | None = None
    width: int = Field(default=1800,ge=100,le=4096)
    height: int = Field(default=1500,ge=100,le=4096)
    dpi: int = Field(default=300,ge=72,le=600)
    output_language: Literal['zh-CN','en'] = 'en'

    @model_validator(mode='after')
    def bounded(self):
        panels={'qc':{'default','distribution','violin','scatter','mitochondrial','sample_id','section','batch'},
            'pca':{'default','scores','variance'},'umap':{'default','scores'}}
        if self.panel not in panels.get(self.kind,{'default'}):raise ValueError('Panel does not belong to figure kind')
        if self.width*self.height>16000000:
            raise ValueError('Figure pixel budget exceeded')
        if self.vmin is not None and self.vmax is not None and self.vmin>=self.vmax:
            raise ValueError('Color range must increase')
        if len(set(self.gene_ids)) != len(self.gene_ids):
            raise ValueError('Duplicate feature ID')
        if self.kind=='spatial_gene' and not 1<=len(self.gene_ids)<=16:
            raise ValueError('Spatial panels require 1 to 16 stable feature IDs')
        if self.kind in ('marker_dotplot','marker_heatmap') and self.layer!='log1p':
            raise ValueError('Marker colors require mean log1p expression')
        return self


class BioFigureRequest(StrictModel):
    processed_source: BioProcessedDatasetSourceV1
    annotation_version_id: str | None = Field(default=None,min_length=1,max_length=64)
    expected_version: int = Field(default=0,ge=0,lt=2147483647)
    config: BioFigureConfig

    @model_validator(mode='after')
    def annotation(self):
        if self.config.kind=='annotation' and self.annotation_version_id is None:
            raise ValueError('An annotation version is required')
        return self


class BioAnnotationLabel(StrictModel):
    id: Identifier
    name: str = Field(min_length=1,max_length=200)
    status: Literal['proposed','confirmed','unknown'] = 'proposed'
    note: str = Field(default='',max_length=4000)
    cluster_ids: list[Identifier] = Field(default_factory=list,max_length=50)


class BioAnnotationRegion(StrictModel):
    id: Identifier
    label_id: Identifier
    section: str | None = Field(default=None,min_length=1,max_length=200)
    points: list[Annotated[list[float],Field(min_length=2,max_length=2)]] = Field(min_length=3,max_length=2000)
    priority: int | None = Field(default=None,ge=0,le=10000)

    @model_validator(mode='after')
    def polygon(self):
        if any(abs(v)>10000000 for point in self.points for v in point):
            raise ValueError('Coordinates exceed full-resolution bounds')
        if len({tuple(p) for p in self.points})<3:
            raise ValueError('Polygon needs three distinct vertices')
        return self


class BioAnnotationEvidence(StrictModel):
    label_id: Identifier
    kind: Literal['marker','file']
    analysis_artifact_id: str | None = Field(default=None,min_length=1,max_length=64)
    file_id: str | None = Field(default=None,min_length=1,max_length=64)
    note: str = Field(default='',max_length=4000)

    @model_validator(mode='after')
    def one_source(self):
        if (self.kind=='marker') != (self.analysis_artifact_id is not None) or (self.kind=='file') != (self.file_id is not None):
            raise ValueError('Evidence requires exactly one matching source')
        return self


class BioAnnotationRequest(StrictModel):
    name: str = Field(min_length=1,max_length=200)
    raw_source: BioDatasetSourceV1
    processed_dataset_version_id: str | None = Field(default=None,min_length=1,max_length=64)
    expected_revision: int = Field(ge=0,lt=2147483647)
    labels: list[BioAnnotationLabel] = Field(default_factory=list,max_length=100)
    regions: list[BioAnnotationRegion] = Field(default_factory=list,max_length=100)
    overlap_policy: Literal['ambiguity','priority'] = 'ambiguity'
    evidence: list[BioAnnotationEvidence] = Field(default_factory=list,max_length=200)

    @model_validator(mode='after')
    def references(self):
        labels={label.id for label in self.labels}
        if len(labels)!=len(self.labels) or len({r.id for r in self.regions})!=len(self.regions):
            raise ValueError('Duplicate label or region identity')
        if sum(len(r.points) for r in self.regions)>2000:
            raise ValueError('Vertex budget exceeded')
        if any(r.label_id not in labels for r in self.regions) or any(e.label_id not in labels for e in self.evidence):
            raise ValueError('Unknown label reference')
        if self.overlap_policy=='priority' and (any(r.priority is None for r in self.regions) or len({r.priority for r in self.regions})!=len(self.regions)):
            raise ValueError('Priority policy requires explicit distinct region priorities')
        if self.processed_dataset_version_id is None and (any(l.cluster_ids for l in self.labels) or any(e.kind=='marker' for e in self.evidence)):
            raise ValueError('Cluster and marker evidence requires a processed version')
        return self


class BioAnalysisInputVersion(StrictModel):
    model_config = ConfigDict(strict=True,extra='forbid',frozen=True)
    schema_version: Literal[1] = 1
    kind: Literal['bio_analysis'] = 'bio_analysis'
    run_id: str
    recipe_version_id: str
    raw_source: BioDatasetSourceV1
    workflow_version: Literal['bio_analysis_v1'] = WORKFLOW_VERSION
    engine_version: Literal['visium_explore_v1.0.0'] = ENGINE_VERSION
    environment_digest: Hash
    output_language: Literal['zh-CN','en']


class BioFigureInputVersion(StrictModel):
    model_config = ConfigDict(strict=True,extra='forbid',frozen=True)
    schema_version: Literal[1] = 1
    kind: Literal['bio_figure'] = 'bio_figure'
    figure_version_id: str
    processed_source: BioProcessedDatasetSourceV1
    workflow_version: Literal['bio_figure_v1'] = FIGURE_WORKFLOW_VERSION
    output_language: Literal['zh-CN','en']


def validate_snapshot(task):
    from app.domain.bioinformatics.analysis_settings import BioAnalysisLimits
    try:
        value=task['input_snapshot']
        common={'schema_version','kind','workflow_version','project_id','engine_version','environment_digest','code_digest','output_language','limits'}
        if task['task_type']=='bio_analysis':
            fields={'run_id','setup_id','recipe_version_id','expected_setup_revision','raw_source','params','observation_map_version_id','design_version_id'}
            BioRecipeParameters.model_validate(value['params'])
            source=BioDatasetSourceV1.model_validate(value['raw_source'])
            if type(value['expected_setup_revision']) is not int or value['expected_setup_revision']<1:raise ValueError('Invalid revision')
        elif task['task_type']=='bio_figure':
            fields={'figure_version_id','processed_source','annotation_version_id','config'}
            BioFigureConfig.model_validate(value['config'])
            source=BioProcessedDatasetSourceV1.model_validate(value['processed_source'])
        else:raise ValueError('Invalid task type')
        BioAnalysisLimits.model_validate(value['limits'])
        expected=WORKFLOW_VERSION if task['task_type']=='bio_analysis' else FIGURE_WORKFLOW_VERSION
        if (set(value)!=common|fields or type(value['schema_version']) is not int or value['schema_version']!=1
            or value['kind']!=task['task_type'] or value['workflow_version']!=expected or task['workflow_version']!=expected
            or value['project_id']!=task['project_id'] or source.project_id!=task['project_id']
            or value['engine_version']!=ENGINE_VERSION or task['input_digest']!=digest(value)):
            raise ValueError('Frozen analysis identity differs')
        import re
        if any(not isinstance(value[k],str) or not re.fullmatch('[0-9a-f]{64}',value[k]) for k in ('environment_digest','code_digest')):
            raise ValueError('Invalid environment identity')
        return value
    except (KeyError,TypeError,ValueError) as exc:
        raise conflict('bio_input_integrity_changed') from exc


def input_version(task):
    value=validate_snapshot(task)
    if task['task_type']=='bio_analysis':
        return BioAnalysisInputVersion(**{key:value[key] for key in ('run_id','recipe_version_id','raw_source','engine_version','environment_digest','output_language')}).model_dump(mode='json')
    return BioFigureInputVersion(**{key:value[key] for key in ('figure_version_id','processed_source','output_language')}).model_dump(mode='json')
