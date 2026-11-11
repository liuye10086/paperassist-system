import type {AnalysisNavigation, BulkWorkflowView} from '../projects/analysisViews'
import {projectBase} from './api'
import type {BulkContrast,BulkSelection} from './bulk'

export const bulkWorkflowBase = (projectId:string) => `${projectBase(projectId)}/bulk-workflow`

export const bulkWorkflowLabels = {
  design:'研究设计', data:'数据与样本', qc:'质控', differential:'差异分析',
  functional:'功能分析', delivery:'报告与下载',
} satisfies Record<BulkWorkflowView,string>

export const bulkWorkflowStatuses:Record<string,string> = {
  queued:'待执行', running:'运行中', waiting_confirmation:'待确认', succeeded:'已完成',
  failed:'执行失败', cancelled:'已取消', skipped:'已跳过', not_applicable:'不适用',
  dependency_blocked:'依赖未就绪', ready:'可继续', no_significant_terms:'无显著条目', completed:'已完成',
}

export type BulkWorkflowRefs = Partial<Record<
  'design_version_id'|'dataset_id'|'dataset_version_id'|'observation_map_set_id'|'observation_map_version_id'|'import_id'|
  'setup_id'|'recipe_version_id'|'analysis_run_id'|'processed_version_id'|'plan_id'|
  'plan_version_id'|'insight_run_id'|'result_version_id'|'resource_version_id'|'task_id',string|null>>

type BulkVersionState = {
  status:string
  stale:boolean
  stale_reasons:{kind:string;version_id:string;current_version_id:string|null}[]
  refs:BulkWorkflowRefs
  reason?:string|null
  operation?:'save'|'confirm'
}

export type BulkWorkflowItem = BulkVersionState & {
  kind:string;created_at?:string|null;label?:string|null;error_code?:string|null;figure_type?:string|null;
  steps?:{key:string;status:string;reason?:string|null}[]
}
export type BulkWorkflowComparison = BulkWorkflowItem & {
  contrasts:Pick<BulkContrast,'contrast_id'|'numerator'|'denominator'>[]
  processed_version_ids?:string[]
}
export type BulkWorkflowDescendant = BulkWorkflowItem & {
  comparison_version_ids:string[]
  direct_comparison_version_ids:string[]
  processed_version_ids?:string[]
  direct_processed_version_ids?:string[]
  delivery_eligible:boolean
}

export type BulkWorkflowOverview = {
  project_id:string
  stages:(BulkVersionState & {key:BulkWorkflowView;depends_on:BulkWorkflowView[];items:BulkWorkflowItem[];
    reusable_processed_refs?:BulkWorkflowRefs|null})[]
  comparisons:BulkWorkflowComparison[]
  descendants:BulkWorkflowDescendant[]
}

export const bulkRoute = (bulkView:BulkWorkflowView,resultVersionId?:string):AnalysisNavigation => ({
  view:'bulk-workflow', fileId:'', bulkView, ...(resultVersionId?{resultVersionId}:{}),
})

export function continueBulkRoute(current:AnalysisNavigation,next:AnalysisNavigation):AnalysisNavigation {
  if(!current.bulkView||next.bulkView||!next.view.startsWith('bio-')) return next
  const bulkView = next.view==='bio-datasets'||next.view==='bio-import'||next.view==='bio-dataset'?'data'
    :next.view==='bio-analysis'||next.view==='bio-analysis-setup'||next.view==='bio-result'||next.view==='bio-figure'||next.bulkPanel?'qc'
    :next.view==='bio-resources'?'functional'
    :next.view==='bio-insights'||next.view==='bio-candidates'?'differential':current.bulkView
  return {...next,bulkView}
}

export function publishedBulkComparisons(items:BulkWorkflowComparison[]) {
  return items.filter(item=>item.status==='succeeded'&&item.refs.result_version_id&&item.contrasts.length>0)
}

export function compatibleBulkAttachments(comparison:BulkWorkflowComparison,items:BulkWorkflowDescendant[]) {
  const id = comparison.refs.result_version_id
  const qcIds = comparison.processed_version_ids??[comparison.refs.processed_version_id]
  return items.filter(item=>{
    if(!id||!item.refs.result_version_id||!['succeeded','not_applicable','no_significant_terms'].includes(item.status)) return false
    if(!item.delivery_eligible) return false
    if(item.comparison_version_ids.length) return item.comparison_version_ids.every(version=>version===id)
    const sources = item.direct_processed_version_ids??item.processed_version_ids??[item.refs.processed_version_id]
    return item.kind==='figure'&&sources.length===1&&!!sources[0]&&qcIds.includes(sources[0])
  })
}

export type BulkSensitivityRequest = {
  baseline_version_id:string
  scenario_version_id:string
  baseline_selection:BulkSelection
  scenario_selection:BulkSelection
  page?:number
  page_size?:number
}

type SensitivitySide = {
  version_id:string
  run_id:string
  plan_version_id:string
  processed_version_id?:string|null
  design_version_id?:string|null
  selection:BulkSelection
  numerator:string
  denominator:string
}

export type BulkSensitivityResult = {
  comparison_type:'threshold_only'|'alternate_run'
  baseline:SensitivitySide
  scenario:SensitivitySide
  sample_changes:{added:string[];removed:string[];shared:number;reassigned:string[];metadata_changed?:string[]}
  parameter_changes:string[]
  counts:Record<string,number>
  items:{feature_id:string;symbol:string|null;baseline_class:string;scenario_class:string;change:string;
    baseline_q:number|null;scenario_q:number|null;baseline_effect:number|null;scenario_effect:number|null}[]
  total:number
  page:number
  page_size:number
}

export const bulkEvidenceKinds = {independent_analysis:'独立分析',experimental_material:'实验材料'} as const
export type BulkEvidence = {kind:keyof typeof bulkEvidenceKinds;source_id:string;note?:string}
type BulkEvidenceFact = BulkEvidence & {filename?:string;verification_status?:string;
  independence_status?:string;shared_processed_source_ids?:string[]}

export type BulkDeliveryRequest = {
  comparison_version_id:string
  result_version_ids:string[]
  language:'zh'|'en'
  selections:BulkSelection[]
  sensitivity:BulkSensitivityRequest|null
  evidence:BulkEvidence[]
  facts_digest?:string
}

export type BulkDeliveryFacts = {
  project_id?:string
  language?:'zh'|'en'
  comparison_version_id:string
  processed_version_id:string
  processed_version_ids?:string[]
  design:{formula?:string;rank?:number;residual_df?:number;species_taxon_id?:number|null;
    namespace?:string;reference_version?:string;inference_scope?:string;confirmation?:{
      plan_version_id:string;plan_id:string;confirmed_at:string;confirmed_by:string;reviewed_design_sha256:string
    };[key:string]:unknown}
  qc:{summary:Record<string,unknown>;input_files?:{id:string;filename:string;sha256:string;size_bytes:number}[];[key:string]:unknown}
  contrasts:(Pick<BulkContrast,'contrast_id'|'numerator'|'denominator'> & {selection:BulkSelection;counts:Record<string,number>})[]
  figures:{version_id:string;title:string|null;source_version_id:string;figure_type:string;panel?:string|null}[]
  candidates:unknown[]
  enrichments:{version_id:string;kind:string;status:string;not_applicable_reason?:string|null;resource_version_ids:string[]}[]
  sensitivity:Pick<BulkSensitivityResult,'comparison_type'|'baseline'|'scenario'|'sample_changes'|'parameter_changes'|'counts'>|null
  evidence:BulkEvidenceFact[]
  references:unknown
  limitations:string[]
  resource_version_ids:string[]
  selected_result_version_ids:string[]
  result_version_ids:string[]
  facts_digest:string
}
