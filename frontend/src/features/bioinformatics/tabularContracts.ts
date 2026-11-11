import type {RawBioSource, BioRecipe, BioSetup, BioProcessed, BioFigure, SpatialMember} from './spatialContracts'
import {isRawBioSource} from './spatialContracts'

export const tabularAssays = ['bulk_rna_counts','normalized_expression','proteomics','metabolomics','microbiome'] as const
export type TabularAssay = typeof tabularAssays[number]
export const assayLabels:Record<TabularAssay,string> = {bulk_rna_counts:'bulk RNA 原始整数 counts',normalized_expression:'标准化表达矩阵',proteomics:'蛋白定量矩阵',metabolomics:'代谢定量矩阵',microbiome:'微生物组 counts／相对丰度'}
export type ScaleKind = 'raw_counts'|'tpm'|'fpkm'|'normalized'|'log2'|'ln'|'log10'|'intensity'|'relative_abundance'|'concentration'
export type InputOrigin = 'bulk_rna'|'single_cell_expression'|'tpm'|'fpkm'|'log'|'vst'|'rlog'|'z_score'|'unknown'
export type TabularScale = {kind:ScaleKind;unit:string;upstream_method:string;upstream_transforms:string[];namespace:string;reference_version:string;species_taxon_id:number|null;zero_meaning:'measured_zero'|'unknown'|'below_lod';input_origin?:InputOrigin}
export type TableRole = 'quantitative_matrix'|'sample_metadata'|'feature_metadata'
export type TabularTable = {file_id:string;role:TableRole;format:'csv'|'tsv'|'xlsx';sheet:string|null;header_row:number;encoding:'utf-8-sig';delimiter:','|'\t'|null}
export type TabularSampleMetadataMapping = {sample_id:string;condition:string|null;biological_unit_id:string|null;pair_id:string|null;batch:string|null;donor:string|null;sample_role:string|null}
export type TabularQualityReport = {file_id:string;source:string;report_type:string}
export type TabularImportRequest = {workflow_version:'bio_import_v3';file_ids:string[];assay:TabularAssay;name:string;dataset_id:string|null;expected_dataset_revision:number;tables:TabularTable[];feature_id_column:string;sample_columns:string[];scale:TabularScale;na_values:string[];sample_metadata_mapping?:TabularSampleMetadataMapping;quality_reports?:TabularQualityReport[]}
export type TabularParams = {normalization:'none'|'already_normalized'|'median'|'display_library_size'|'vst';transform:'none'|'log2'|'ln'|'log10'|'log1p';log1p_offset?:1;scaling:'none'|'unit_variance';exclude_samples:string[];exclude_features:string[];pca_components:number;seed:number;output_language:'en'|'zh-CN'}
export type TabularRecipe = Omit<BioRecipe,'recipe_code'|'params'> & {recipe_code:'tabular_quantitative_v1';params:TabularParams}
export type TabularSetup = Omit<BioSetup,'current_recipe'> & {current_recipe:TabularRecipe}
export type TabularCapabilities = {raw_source:RawBioSource;available:boolean;blockers:string[];limits:Record<string,unknown>;recipes:string[];design_gaps:string[];default_params:TabularParams;assay?:TabularAssay;scale?:TabularScale;sample_ids?:string[];sample_mapping?:Record<string,unknown>}
export type TabularSetupRequest = {recipe_code:'tabular_quantitative_v1';name:string;raw_source:RawBioSource;expected_revision:number;observation_map_version_id:null;design_version_id:string|null;params:TabularParams}
export type TabularProcessedSource = {kind:'bio_processed_dataset_version';schema_version:2;project_id:string;processed_dataset_version_id:string;analysis_run_id:string;raw_source:RawBioSource;recipe_version_id:string;setup_id?:string;manifest_sha256:string;engine_version:'tabular_quantitative_v1.0.0';environment_digest:string;assay:TabularAssay;observation_level:'sample'}
export type TabularProcessed = Omit<BioProcessed,'source'|'figures'> & {source:TabularProcessedSource;figures:{id:string;config:{kind:string;title:string};members:SpatialMember[]}[]}
export type TabularFigure = Omit<BioFigure,'processed_source'|'config'> & {processed_source:TabularProcessedSource;config:Record<string,unknown>&{kind:string;title:string;output_language:'en'|'zh-CN'}}
export const isTabularRaw = (source:RawBioSource)=>source.parser_version==='tabular_assay_import_v1'
export function isTabularProcessedSource(v:unknown,project:string):v is TabularProcessedSource {
 if(!v||typeof v!=='object'||Array.isArray(v))return false
 const value=v as Record<string,unknown>,id=(s:unknown)=>typeof s==='string'&&/^[A-Za-z0-9_-]{1,64}$/.test(s),hash=(s:unknown)=>typeof s==='string'&&/^[a-f0-9]{64}$/.test(s)
 return Object.keys(value).length>=12&&value.kind==='bio_processed_dataset_version'&&value.schema_version===2&&value.project_id===project&&id(value.processed_dataset_version_id)&&id(value.analysis_run_id)&&id(value.recipe_version_id)&&(!('setup_id' in value)||id(value.setup_id))&&isRawBioSource(value.raw_source,project)&&isTabularRaw(value.raw_source)&&hash(value.manifest_sha256)&&hash(value.environment_digest)&&value.engine_version==='tabular_quantitative_v1.0.0'&&tabularAssays.includes(value.assay as TabularAssay)&&value.observation_level==='sample'
}
