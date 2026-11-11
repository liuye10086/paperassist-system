import type {Config, EnrichmentIdentity, Page, Result, Source} from './contracts'
import {isTabularProcessedSource, type TabularProcessed} from '../bioinformatics/tabularContracts'

export const bulkQColumns = {
  q_within_contrast:'比较内 BH q',
  q_global_family:'冻结比较族 BH q',
  original_method_adjustment:'模型原生调整值（独立过滤）',
} as const
export type BulkQColumn = keyof typeof bulkQColumns
export const BULK_ORA_ELIGIBLE_BACKGROUND = 'computable_selected_q_effect_intersected_with_collection'
export type BulkSubset = 'all' | 'deg' | 'up' | 'down'
export type BulkSelection = {
  contrast_id:string
  q_column:BulkQColumn
  q_threshold:number
  minimum_absolute_effect:number
  direction:'both' | 'up' | 'down'
}
export type BulkContrast = {
  contrast_id:string
  numerator:string
  denominator:string
  total:number
  tested:number
  excluded:number
  not_computable:number
  missing_metric:number
  deg:number
  up:number
  down:number
}
export type BulkComparisonPage = Page<Record<string, unknown>> & {
  contrast_id:string
  contrasts:BulkContrast[]
  columns:string[]
  matched_total:number
  sha256:string
  feature_matches:Record<string, unknown>[]
}
export const bulkFigureLabels = {
  bulk_volcano:'Bulk 火山图',
  bulk_ma:'Bulk MA 图',
  bulk_heatmap:'DEG 表达热图',
  bulk_variable_heatmap:'高变基因表达热图',
  bulk_expression:'单基因样本表达图',
  bulk_summary:'DEG 数量汇总图',
  bulk_qc:'Bulk 样本 QC 图',
  bulk_pca:'Bulk 样本 PCA 图',
} as const
export type BulkFigureType = keyof typeof bulkFigureLabels
export const bulkPanels = {
  qc_missing:'样本缺失比例',
  qc_expression:'样本表达分布',
  sample_clustering:'样本聚类',
  sample_correlation:'样本相关性',
  sample_distance:'样本距离',
  pca_scores:'样本 PCA 得分',
  pca_variance:'PCA 方差解释率',
} as const
export type BulkPanel = keyof typeof bulkPanels
export type BulkPlanSeed = {config:Config;source:Source}
export const isBulkFigureType = (v:unknown):v is BulkFigureType =>
  typeof v==='string'&&Object.hasOwn(bulkFigureLabels,v)
export const isBulkPanel = (v:unknown):v is BulkPanel =>
  typeof v==='string'&&Object.hasOwn(bulkPanels,v)
export const isBulkProcessedFigure = (v:unknown) => v==='bulk_qc'||v==='bulk_pca'
export const isBulkHeatmap = (v:unknown) => v==='bulk_heatmap'||v==='bulk_variable_heatmap'
export const bulkPanelFigureType = (panel:BulkPanel):BulkFigureType => panel.startsWith('pca_')?'bulk_pca':'bulk_qc'
export const bulkPanelTab = (panel:BulkPanel) => panel.startsWith('pca_')?'embedding':panel==='sample_clustering'?'clusters':'qc'

export function isReviewedBulkComparison(result:Result|null|undefined) {
  const config = result?.methods?.config as Record<string,unknown>|undefined
  return result?.kind==='comparison'&&result.task?.status==='succeeded'
    &&config?.mode==='bulk_counts'&&config.bulk_model==='shared_wald_v1'
}

export function isBulkEnrichmentResult(result:Result|null|undefined) {
  return (result?.kind==='ora'||result?.kind==='gsea_prerank')&&result.methods?.bulk_enrichment!=null
}

export function isBulkEnrichmentFigure(result:Result|null|undefined) {
  return result?.kind==='figure'&&(result.methods?.config as Config|undefined)?.bulk_enrichment_render===true
}

export function bulkEnrichmentContrast(config:Config) {
  const contrast = config.kind==='ora'&&Array.isArray(config.contrast_ids)?config.contrast_ids[0]:config.contrast_id
  return typeof contrast==='string'?contrast:''
}

export function fixedBulkEnrichmentIdentity(result:Result|null):EnrichmentIdentity {
  const methods = result?.methods
  const saved = methods?.config as Partial<EnrichmentIdentity>|undefined
  const taxon = methods?.species_taxon_id??saved?.species_taxon_id
  const namespace = methods?.namespace??saved?.namespace
  const reference = methods?.reference_version??saved?.reference_version
  return {species_taxon_id:typeof taxon==='number'?taxon:null,namespace:typeof namespace==='string'?namespace:null,
    reference_version:typeof reference==='string'?reference:null}
}

export function hasBulkPanel(result:TabularProcessed, panel:BulkPanel) {
  const tableKey = panel==='pca_variance'?'pca_variance_ratio':panel
  if (panel.startsWith('pca_')) return result.tables.some(table=>table.key===tableKey)
  const dataKey = panel==='qc_expression'?'expression_distribution':panel
  return result.figures.some(figure=>figure.config.kind===dataKey)
    ||result.members.some(member=>member.key===dataKey||member.key===dataKey+'_data')
    ||panel==='sample_clustering'&&result.tables.some(table=>table.key===tableKey)
}

export function bulkProcessedMatches(result:TabularProcessed, projectId:string, processedId:string, panel:BulkPanel) {
  return isTabularProcessedSource(result.source,projectId)&&result.source.assay==='bulk_rna_counts'
    &&result.source.processed_dataset_version_id===processedId&&result.id===processedId
    &&result.source.manifest_sha256===result.manifest_sha256&&hasBulkPanel(result,panel)
}

export function validBulkSelection(value:unknown):value is BulkSelection {
  if (!value||typeof value!=='object') return false
  const s = value as BulkSelection
  return typeof s.contrast_id==='string'&&s.contrast_id.length>0
    &&Object.hasOwn(bulkQColumns,s.q_column)&&['both','up','down'].includes(s.direction)
    &&Number.isFinite(s.q_threshold)&&s.q_threshold>=0&&s.q_threshold<=1
    &&Number.isFinite(s.minimum_absolute_effect)&&s.minimum_absolute_effect>=0&&s.minimum_absolute_effect<=1000000
}

export function bulkComparisonLabel(contrast:Pick<BulkContrast,'numerator'|'denominator'|'contrast_id'>) {
  return `${contrast.numerator} vs ${contrast.denominator} (${contrast.contrast_id})`
}

export function bulkPlanScope({config,source}:BulkPlanSeed) {
  const selection = config.bulk_selection as BulkSelection|undefined
  return JSON.stringify([
    source.source_id, source.sha256, config.figure_type ?? config.kind, config.bulk_panel,
    selection?.contrast_id, selection?.q_column, selection?.q_threshold, selection?.minimum_absolute_effect,
    selection?.direction, config.feature_ids,
    ...(config.bulk_enrichment!=null?[bulkEnrichmentContrast(config),config.q_column,config.q_threshold,
      config.minimum_absolute_effect,config.direction]:[]),
    ...(config.bulk_enrichment_render?[config.contrast_id,config.enrichment_style,config.term_row_key]:[]),
  ])
}
