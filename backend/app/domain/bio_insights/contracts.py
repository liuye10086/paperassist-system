"""Bounded HTTP/domain contracts. No scientific runtime is imported here."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r'^[^/\\\x00-\x1f]+$')]
Hash = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
Text = Annotated[str, Field(max_length=4000)]
Language = Literal['zh-CN', 'en']
SourceKind = Literal['bio_processed_dataset_version','bio_observation_map_version','bio_annotation_version',
                     'research_design_version','bio_resource_version','bio_insight_result_version','original_file']
InsightKind = Literal['comparison','result_import','ora','gsea_prerank','candidate','figure']
QColumn = Literal['q_within_contrast','q_global_family','original_q','system_recomputed_q']


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True, allow_inf_nan=False)

    @model_validator(mode='after')
    def bounded_document(self):
        if len(self.model_dump_json().encode('utf-8')) > 4 * 1024 * 1024:
            raise ValueError('Insight contract exceeds 4 MiB; large tables belong in storage members')
        return self


class ConfigModel(StrictModel):
    output_language: Language = 'zh-CN'


class SourceLocator(StrictModel):
    kind: Literal['object','table','row','field'] = 'object'
    member_key: Identifier | None = None
    table: Identifier | None = None
    row_key: dict[Identifier, Identifier] | None = Field(default=None, min_length=1, max_length=8)
    field: Identifier | None = None
    parse_version_id: Identifier | None = None

    @model_validator(mode='after')
    def location(self):
        if self.kind == 'table' and not (self.table or self.member_key):
            raise ValueError('Table locator requires a table or member key')
        if self.kind == 'row' and not self.row_key:
            raise ValueError('Row locator requires exact stable row keys')
        if self.kind == 'field' and not self.field:
            raise ValueError('Field locator requires a field')
        if self.kind in ('object','table') and (self.row_key is not None or self.field is not None):
            raise ValueError('Locator fields do not match kind')
        return self


class InsightSourceSelection(StrictModel):
    source_kind: SourceKind
    source_id: Identifier
    role: Literal['source','processed','observation_map','annotation','design','resource','result','table',
                  'background','foreground','ranking','id_mapping','gene_sets','feature_annotation'] = 'source'
    sha256: Hash
    locator: SourceLocator = Field(default_factory=SourceLocator)


class FrozenInsightSource(InsightSourceSelection):
    project_id: Identifier


class ObservationKey(StrictModel):
    processed_version_id: Identifier
    barcode: Identifier


class GroupSelection(StrictModel):
    label: Identifier
    observation_keys: list[ObservationKey] = Field(default_factory=list, max_length=100000)


class Contrast(StrictModel):
    contrast_id: Identifier
    name: str = Field(min_length=1,max_length=500)
    numerator: GroupSelection
    denominator: GroupSelection


class ObservationExclusion(ObservationKey):
    reason: str = Field(min_length=1,max_length=1000)


class DonorExclusion(StrictModel):
    donor: Identifier
    reason: str = Field(min_length=1,max_length=1000)


class ComparisonConfig(ConfigModel):
    kind: Literal['comparison'] = 'comparison'
    mode: Literal['spot_exploratory','donor_unpaired','donor_paired']
    contrasts: list[Contrast] = Field(min_length=1,max_length=10)
    family_contrast_ids: list[Identifier] = Field(min_length=1,max_length=10)
    species_taxon_id: int = Field(ge=1,le=2147483647)
    namespace: Identifier
    reference_version: Identifier
    mapping_confirmed: bool = False
    independence_confirmed: bool = False
    independence_basis: Text = ''
    batch_adjustment: bool = False
    data_driven_grouping: bool = True
    excluded_observations: list[ObservationExclusion] = Field(default_factory=list,max_length=100000)
    excluded_donors: list[DonorExclusion] = Field(default_factory=list,max_length=10000)
    minimum_total_counts: int = Field(default=10,ge=1,le=1000000)
    purpose: Text = ''

    @model_validator(mode='after')
    def comparison_family(self):
        ids=[c.contrast_id for c in self.contrasts]
        if len(ids)!=len(set(ids)) or len(self.family_contrast_ids)!=len(set(self.family_contrast_ids)):
            raise ValueError('Duplicate contrast or correction-family identity')
        if set(ids)!=set(self.family_contrast_ids):
            raise ValueError('Correction family must freeze exactly all planned contrasts')
        if self.mode=='donor_paired' and self.batch_adjustment:
            raise ValueError('Paired model supports donor + condition only')
        return self


class ImportColumns(StrictModel):
    feature_id: Identifier
    symbol: Identifier | None = None
    effect: Identifier | None = None
    p_value: Identifier | None = None
    q_value: Identifier | None = None
    direction: Identifier | None = None
    status: Identifier | None = None
    contrast_id: Identifier | None = None


class ResultImportConfig(ConfigModel):
    kind: Literal['result_import'] = 'result_import'
    file_source_id: Identifier
    parse_version_id: Identifier
    species_taxon_id: int = Field(ge=1,le=2147483647)
    namespace: Identifier
    reference_version: Identifier
    sheet: Identifier | None = None
    columns: ImportColumns
    contrast_id: Identifier
    numerator: Identifier
    denominator: Identifier
    effect_name: Identifier = 'external_effect'
    effect_unit: str = Field(default='',max_length=200)
    observation_level: Literal['spot','donor','sample','unknown'] = 'unknown'
    inference_scope: Literal['spot_exploratory','donor_inference','external_result'] = 'external_result'
    original_method: Text
    original_correction_scope: Text
    complete_tested_universe: bool = False
    recompute_q: bool = False
    duplicate_policy: Literal['error','exclude_all'] = 'error'
    na_values: list[Annotated[str,Field(max_length=100)]] = Field(default_factory=lambda:['','NA','N/A','null'],max_length=30)

    @model_validator(mode='after')
    def recomputation(self):
        if self.recompute_q and (not self.complete_tested_universe or not self.columns.p_value):
            raise ValueError('Recomputed q requires a confirmed full tested universe and P column')
        return self


class OraConfig(ConfigModel):
    kind: Literal['ora'] = 'ora'
    result_source_ids: list[Identifier] = Field(min_length=1,max_length=10)
    resource_source_ids: list[Identifier] = Field(min_length=1,max_length=10)
    mapping_source_ids: list[Identifier] = Field(default_factory=list,max_length=10)
    foreground_member_key: Identifier | None = None
    background_source_id: Identifier | None = None
    background_member_key: Identifier | None = None
    contrast_ids: list[Identifier] = Field(min_length=1,max_length=30)
    direction: Literal['up','down','both'] = 'both'
    q_column: QColumn = 'q_within_contrast'
    q_threshold: float = Field(default=0.05,ge=0,le=1)
    minimum_absolute_effect: float = Field(default=1.0,ge=0,le=1000000)
    min_size: int = Field(default=15,ge=1,le=1000000)
    max_size: int = Field(default=500,ge=1,le=1000000)
    merge_collections: bool = False

    @model_validator(mode='after')
    def sizes(self):
        if self.min_size>self.max_size:raise ValueError('min_size exceeds max_size')
        if (self.background_source_id is None)!=(self.background_member_key is None):
            raise ValueError('Explicit background requires source and member')
        return self


class GseaPrerankConfig(ConfigModel):
    kind: Literal['gsea_prerank'] = 'gsea_prerank'
    result_source_id: Identifier
    resource_source_ids: list[Identifier] = Field(min_length=1,max_length=10)
    mapping_source_ids: list[Identifier] = Field(default_factory=list,max_length=10)
    contrast_id: Identifier
    ranking_column: Identifier
    complete_ranking: Literal[True] = True
    signed_ranking: Literal[True] = True
    min_size: int = Field(default=15,ge=1,le=1000000)
    max_size: int = Field(default=500,ge=1,le=1000000)
    permutation_num: int = Field(default=1000,ge=100,le=10000)
    weight: float = Field(default=1.0,ge=0,le=10)
    seed: int = Field(default=0,ge=0,le=2147483647)

    @model_validator(mode='after')
    def sizes(self):
        if self.min_size>self.max_size:raise ValueError('min_size exceeds max_size')
        return self


class CandidateStep(StrictModel):
    operation: Literal['threshold','union','intersection','at_least_k','same_direction','include','exclude','annotation']
    source_ids: list[Identifier] = Field(default_factory=list,max_length=10)
    q_column: QColumn | None = None
    q_threshold: float | None = Field(default=None,ge=0,le=1)
    minimum_absolute_effect: float | None = Field(default=None,ge=0,le=1000000)
    k: int | None = Field(default=None,ge=1,le=10)
    feature_ids: list[Identifier] = Field(default_factory=list,max_length=10000)
    annotation_field: Identifier | None = None
    annotation_operator: Literal['eq','ne','gt','ge','lt','le','known','unknown'] | None = None
    annotation_value: str | float | bool | None = None

    @model_validator(mode='after')
    def step(self):
        if self.operation=='at_least_k' and self.k is None:raise ValueError('at_least_k requires k')
        if self.operation=='threshold' and (not self.source_ids or not self.q_column or self.q_threshold is None):
            raise ValueError('Threshold requires sources and explicit q scope')
        if self.operation=='annotation' and (not self.annotation_field or not self.annotation_operator):
            raise ValueError('Annotation step requires field and operator')
        return self


class EvidenceWeight(StrictModel):
    item: Literal['support_fraction','direction_agreement','primary_significance','primary_absolute_effect']
    weight: float = Field(gt=0,le=1)
    required: bool = True


class CandidateConfig(ConfigModel):
    kind: Literal['candidate'] = 'candidate'
    result_source_ids: list[Identifier] = Field(min_length=1,max_length=10)
    source_contrasts: dict[Identifier,Identifier] = Field(min_length=1,max_length=10)
    mapping_source_ids: list[Identifier] = Field(default_factory=list,max_length=10)
    annotation_source_ids: list[Identifier] = Field(default_factory=list,max_length=10)
    primary_result_source_id: Identifier
    steps: list[CandidateStep] = Field(min_length=1,max_length=20)
    ranking_mode: Literal['lexicographic','weighted'] = 'lexicographic'
    weights: list[EvidenceWeight] = Field(default_factory=list,max_length=20)

    @model_validator(mode='after')
    def recipe(self):
        if set(self.source_contrasts)!=set(self.result_source_ids):raise ValueError('Exactly one contrast must be frozen for each selected result source')
        if self.primary_result_source_id not in self.result_source_ids:raise ValueError('Primary result must be a selected source')
        if len(set(self.result_source_ids))!=len(self.result_source_ids):raise ValueError('Duplicate candidate sources')
        if any(set(s.source_ids)-set(self.result_source_ids) for s in self.steps):raise ValueError('Step uses unselected source')
        if (self.ranking_mode=='weighted') != bool(self.weights):raise ValueError('Weights require weighted ranking')
        if len({w.item for w in self.weights})!=len(self.weights):raise ValueError('Duplicate evidence weight')
        return self


class FigureSetSelection(StrictModel):
    result_source_id: Identifier
    contrast_id: Identifier
    label: Identifier
    direction: Literal['up','down','both'] = 'both'
    q_column: QColumn = 'q_within_contrast'
    q_threshold: float = Field(default=0.05,ge=0,le=1)
    minimum_absolute_effect: float = Field(default=1.0,ge=0,le=1000000)


class FigureConfig(ConfigModel):
    kind: Literal['figure'] = 'figure'
    result_source_id: Identifier
    result_source_ids: list[Identifier] = Field(default_factory=list,max_length=8)
    processed_source_id: Identifier | None = None
    expression_groups: list[GroupSelection] = Field(default_factory=list,max_length=30)
    selected_sets: list[FigureSetSelection] = Field(default_factory=list,max_length=8)
    intersection_mode: Literal['all','exclusive','at_least_k'] | None = None
    intersection_k: int | None = Field(default=None,ge=1,le=8)
    figure_type: Literal['volcano','heatmap','enrichment','gsea','venn','upset','candidate_evidence']
    contrast_id: Identifier | None = None
    member_key: Identifier | None = None
    term_row_key: Identifier | None = None
    enrichment_style: Literal['dot','bar'] = 'dot'
    title: str = Field(default='',max_length=1000)
    x_column: Identifier | None = None
    y_column: Identifier | None = None
    q_column: QColumn | None = None
    top_n: int = Field(default=30,ge=1,le=500)
    width_inches: float = Field(default=7.0,ge=2,le=20)
    height_inches: float = Field(default=5.0,ge=2,le=20)
    dpi: int = Field(default=300,ge=72,le=600)
    formats: list[Literal['png','tiff','svg','pdf']] = Field(default_factory=lambda:['png','tiff','svg','pdf'],min_length=1,max_length=4)
    palette: list[Annotated[str,Field(pattern=r'^#[0-9a-fA-F]{6}$')]] = Field(default_factory=lambda:['#2563eb','#dc2626'],min_length=1,max_length=20)

    @model_validator(mode='after')
    def figure_inputs(self):
        if len(set(self.formats))!=len(self.formats):raise ValueError('Duplicate figure formats')
        width=round(self.width_inches*self.dpi);height=round(self.height_inches*self.dpi)
        if max(width,height)>4096 or width*height>16000000:raise ValueError('Figure exceeds 4096 pixels per side or 16 million total pixels')
        if self.figure_type=='gsea' and not self.term_row_key:raise ValueError('GSEA curve requires an explicitly selected term row')
        if self.figure_type=='heatmap':
            if self.top_n>100:raise ValueError('Heatmap supports at most 100 selected features')
            if not self.processed_source_id or not self.expression_groups:
                raise ValueError('Heatmap requires real processed expression and explicit observation groups')
            if any(not group.observation_keys for group in self.expression_groups):raise ValueError('Heatmap groups must resolve exact observations')
            if any(key.processed_version_id!=self.processed_source_id for group in self.expression_groups for key in group.observation_keys):
                raise ValueError('Heatmap observation is outside selected processed source')
        if self.figure_type in ('venn','upset'):
            if not 2<=len(self.result_source_ids)<=8 or len(set(self.result_source_ids))!=len(self.result_source_ids):
                raise ValueError('Set figures require 2-8 distinct result sources')
            if not self.intersection_mode or len(self.selected_sets)<2:
                raise ValueError('Set figures require explicit selected sets and intersection definition')
            if {s.result_source_id for s in self.selected_sets}!=set(self.result_source_ids):
                raise ValueError('Selected sets must cover exactly selected result sources')
            if self.result_source_id not in self.result_source_ids:raise ValueError('Primary figure result is outside selected sources')
            if self.intersection_mode=='at_least_k' and (self.intersection_k is None or self.intersection_k>len(self.selected_sets)):
                raise ValueError('Invalid intersection k')
        return self


InsightConfig = Annotated[ComparisonConfig | ResultImportConfig | OraConfig | GseaPrerankConfig | CandidateConfig | FigureConfig,
                          Field(discriminator='kind')]


class InsightPlanRequest(StrictModel):
    name: str = Field(min_length=1,max_length=200)
    kind: InsightKind
    decision: Literal['draft','confirmed'] = 'draft'
    expected_revision: int = Field(ge=0,le=2147483646)
    sources: list[InsightSourceSelection] = Field(min_length=1,max_length=100)
    config: InsightConfig

    @model_validator(mode='after')
    def coherent_plan(self):
        if self.kind!=self.config.kind:raise ValueError('Plan kind and configuration differ')
        identities=[(s.source_kind,s.source_id,s.role,s.locator.model_dump_json()) for s in self.sources]
        if len(identities)!=len(set(identities)):raise ValueError('Duplicate frozen source selection')
        config=self.config
        def require(source_id,kinds,roles):
            if not any(s.source_id==source_id and s.source_kind in kinds and s.role in roles for s in self.sources):
                raise ValueError('Configuration reference lacks selected source with matching kind and role: '+source_id)
        def require_many(ids,kinds,roles):
            if len(ids)!=len(set(ids)):raise ValueError('Duplicate configuration source identity')
            for source_id in ids:require(source_id,kinds,roles)
        result_kinds={'bio_insight_result_version'}
        resource_kinds={'bio_resource_version'}
        if isinstance(config,ComparisonConfig):
            ids={key.processed_version_id for c in config.contrasts for g in (c.numerator,c.denominator) for key in g.observation_keys}
            for source_id in ids:require(source_id,{'bio_processed_dataset_version'},{'processed','source'})
        elif isinstance(config,ResultImportConfig):
            require(config.file_source_id,{'original_file'},{'source','table'})
            source=next(s for s in self.sources if s.source_id==config.file_source_id and s.source_kind=='original_file')
            if source.locator.parse_version_id and source.locator.parse_version_id!=config.parse_version_id:
                raise ValueError('External result parse version differs from frozen file locator')
        elif isinstance(config,(OraConfig,GseaPrerankConfig)):
            ids=config.result_source_ids if isinstance(config,OraConfig) else [config.result_source_id]
            require_many(ids,result_kinds,{'result'})
            require_many(config.resource_source_ids,resource_kinds,{'gene_sets','resource'})
            require_many(config.mapping_source_ids,resource_kinds,{'id_mapping'})
            if isinstance(config,OraConfig) and config.background_source_id:
                require(config.background_source_id,{'original_file','bio_insight_result_version'},{'background','result'})
        elif isinstance(config,CandidateConfig):
            require_many(config.result_source_ids,result_kinds,{'result'})
            require_many(config.mapping_source_ids,resource_kinds,{'id_mapping'})
            require_many(config.annotation_source_ids,resource_kinds,{'feature_annotation','annotation'})
        elif isinstance(config,FigureConfig):
            require(config.result_source_id,result_kinds,{'result'})
            require_many(config.result_source_ids,result_kinds,{'result'})
            if config.processed_source_id:require(config.processed_source_id,{'bio_processed_dataset_version'},{'processed'})
        return self


class InsightRunRequest(StrictModel):
    plan_version_id: Identifier
    expected_plan_revision: int = Field(ge=1,le=2147483646)
    source_digest: Hash


class ResourceSource(StrictModel):
    institution: str = Field(min_length=1,max_length=500)
    name: str = Field(min_length=1,max_length=500)
    description: str = Field(min_length=1,max_length=4000)
    url: str | None = Field(default=None,min_length=1,max_length=2000,pattern=r'^https?://[^\s]+$')
    release_date: str | None = Field(default=None,pattern=r'^\d{4}-\d{2}-\d{2}$')


class ResourceUsage(StrictModel):
    basis: str = Field(min_length=1,max_length=4000)
    redistribution_allowed: bool
    scope: Literal['project','internal','redistributable']


class ResourceColumns(StrictModel):
    term_id: Identifier | None = None
    term_name: Identifier | None = None
    feature_id: Identifier | None = None
    source_id: Identifier | None = None
    target_id: Identifier | None = None
    field: Identifier | None = None
    value: Identifier | None = None
    value_type: Identifier | None = None
    unit: Identifier | None = None
    source: Identifier | None = None
    evidence_status: Identifier | None = None


class ResourceFile(StrictModel):
    file_id: Identifier
    sha256: Hash
    role: Literal['obo','gaf','gmt','term_gene','id_mapping','feature_annotation']
    format: Literal['obo','gaf','gmt','tsv','csv','xlsx','obo.gz','gaf.gz','gmt.gz','tsv.gz']
    parse_version_id: Identifier | None = None
    sheet: Identifier | None = None
    columns: ResourceColumns = Field(default_factory=ResourceColumns)
    max_uncompressed_bytes: int = Field(default=536870912,ge=1,le=2147483648)
    expected_uncompressed_size_bytes: int | None = Field(default=None,ge=1,le=2147483648)

    @model_validator(mode='after')
    def format_columns(self):
        fmt=self.format.removesuffix('.gz')
        columns={key for key,value in self.columns.model_dump().items() if value is not None}
        if self.role in ('obo','gaf','gmt'):
            if fmt!=self.role or columns:raise ValueError('Raw ontology/GAF/GMT format must match role and has fixed columns')
        else:
            if fmt not in ('tsv','csv','xlsx'):raise ValueError('Tabular resource requires TSV/CSV/XLSX')
            required={'term_gene':{'term_id','feature_id'},'id_mapping':{'source_id','target_id'},
                      'feature_annotation':{'feature_id','field','value','value_type','unit','source','evidence_status'}}[self.role]
            allowed=required|({'term_name'} if self.role=='term_gene' else set())
            if not required<=columns or columns-allowed:raise ValueError('Tabular columns do not match resource role')
            if fmt=='xlsx' and not self.sheet:raise ValueError('XLSX resource requires an explicit sheet')
        if self.expected_uncompressed_size_bytes and self.expected_uncompressed_size_bytes>self.max_uncompressed_bytes:
            raise ValueError('Declared expanded size exceeds streaming expansion budget')
        return self


class ResourceImportRequest(ConfigModel):
    kind: Literal['gene_sets','id_mapping','feature_annotation']
    title: str = Field(min_length=1,max_length=200)
    species_taxon_id: int = Field(ge=1,le=2147483647)
    namespace: Identifier
    mapping_source_namespace: Identifier | None = None
    mapping_target_namespace: Identifier | None = None
    release: Identifier
    source: ResourceSource
    usage: ResourceUsage
    files: list[ResourceFile] = Field(min_length=1,max_length=20)
    propagation_relations: list[Literal['is_a','part_of']] = Field(default_factory=lambda:['is_a','part_of'],max_length=2)
    exclude_not: Literal[True] = True
    exclude_obsolete: Literal[True] = True
    exclude_root_terms: Literal[True] = True
    evidence_codes: list[Identifier] = Field(default_factory=list,max_length=50)
    strip_ensembl_version: bool = False
    expected_revision: int = Field(default=0,ge=0,le=2147483646)

    @model_validator(mode='after')
    def resource_files(self):
        if self.kind=='id_mapping':
            if not self.mapping_source_namespace or not self.mapping_target_namespace:
                raise ValueError('ID mapping requires explicit source and target namespaces')
        elif self.mapping_source_namespace is not None or self.mapping_target_namespace is not None:
            raise ValueError('Mapping namespaces only apply to ID mapping resources')
        ids=[f.file_id for f in self.files]
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate resource file identity')
        roles={f.role for f in self.files}
        if self.kind=='id_mapping' and roles!={'id_mapping'}:raise ValueError('Mapping resource needs mapping files')
        if self.kind=='feature_annotation' and roles!={'feature_annotation'}:raise ValueError('Annotation resource needs annotation files')
        if self.kind=='gene_sets' and roles-{'obo','gaf','gmt','term_gene'}:raise ValueError('Gene sets require set/ontology files')
        if ('obo' in roles)!=('gaf' in roles):raise ValueError('GO import requires matched OBO and GAF files')
        return self
