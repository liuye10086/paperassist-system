import type {BulkDeliveryRequest} from '../bio-insights/bulkWorkflow'
import type {FrozenReportRequest,Member,Page,ReportRequest,ResearchTask} from '../research-results/contracts'
import {projectBase} from '../research-results/api'

export type ReportLanguage=ReportRequest['language']
export type NativeSelection=
 | {kind:'processed';processed_version_id:string;annotation_version_id:string|null}
 | {kind:'insight';result_version_id:string}
export type BulkSelection={kind:'bulk';delivery:BulkDeliveryRequest&{facts_digest:string}}
export type BioReportSelection=(NativeSelection&{figure_version_ids:string[]})|BulkSelection
export type BioReportRequest={title:string;language:ReportLanguage;selection:BioReportSelection}
export type BioReportContext=BioReportRequest&{
 id:string
 workbook_limited?:boolean
 report:FrozenReportRequest
 source:{source_kind:'bio_report_context';source_id:string;sha256:string;selection:BioReportSelection;
  supporting_sources?:{kind:string;facts?:{enrichments?:{kind:string;version_id:string}[]}}[]}
}
export type BioReportExport={id:string;task_id:string;task:ResearchTask&{project_id:string;task_type:string};members:Member[]}
export type BioReportExportPage=Page<BioReportExport>&{export_state:'available'|'active'|'completed'}
export type FigureChoice={id:string;title:string}
export const bioReportsBase=(projectId:string)=>projectBase(projectId)+'/bio-reader-reports'
export const reportIdentityError='固定来源身份不匹配，请重新打开。'
const validId=(value:unknown):value is string=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,64}$/.test(value)
const digest=(value:unknown)=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value)

export function isBulkReportEnrichmentSource(context:BioReportContext,id:string){
 return context.selection.kind==='bulk'&&context.selection.delivery.result_version_ids[0]===id
  &&!!context.source.supporting_sources?.some(source=>source.kind==='bulk'&&
   source.facts?.enrichments?.some(result=>result.version_id===id&&['ora','gsea_prerank'].includes(result.kind)))
}

function validSelection(value:BioReportSelection|undefined):boolean {
 if(value?.kind==='bulk'){
  const delivery=value.delivery
  return validId(delivery?.comparison_version_id)&&Array.isArray(delivery.result_version_ids)&&delivery.result_version_ids.every(validId)
   &&digest(delivery.facts_digest)&&['zh','en'].includes(delivery.language)
 }
 if(value?.kind!=='processed'&&value?.kind!=='insight')return false
 return Array.isArray(value.figure_version_ids)&&value.figure_version_ids.every(validId)
  &&(value.kind==='processed'?validId(value.processed_version_id)&&(value.annotation_version_id===null||validId(value.annotation_version_id)):validId(value.result_version_id))
}

export function validContext(value:BioReportContext|null|undefined,id?:string):value is BioReportContext {
 if(!value||!validId(value.id)||id!==undefined&&value.id!==id||!validSelection(value.selection))return false
 const {source,selection,report,language,title}=value
 return source?.source_kind==='bio_report_context'&&source.source_id===value.id&&digest(source.sha256)
  &&JSON.stringify(source.selection)===JSON.stringify(selection)
  &&['zh-CN','en'].includes(language)&&typeof title==='string'&&!!title
  &&(selection.kind!=='bulk'||selection.delivery.language===(language==='en'?'en':'zh'))
  &&report?.schema_version===1&&report.title===title&&report.language===language&&validId(report.finding_version_id)
  &&Array.isArray(report.figure_version_ids)&&!report.figure_version_ids.length
  &&report.root_id===null&&report.expected_revision===0&&report.reader_narrative_id===null
}

function ordered(left:string[],right:string[]){
 return left.length===right.length&&left.every((id,index)=>id===right[index])
}

export function matchesRequest(context:BioReportContext,request:BioReportRequest){
 if(context.title!==request.title||context.language!==request.language)return false
 const got=context.selection,want=request.selection
 if(got.kind==='processed'&&want.kind==='processed')return got.processed_version_id===want.processed_version_id
  &&got.annotation_version_id===want.annotation_version_id&&ordered(got.figure_version_ids,want.figure_version_ids)
 if(got.kind==='insight'&&want.kind==='insight')return got.result_version_id===want.result_version_id&&ordered(got.figure_version_ids,want.figure_version_ids)
 if(got.kind==='bulk'&&want.kind==='insight'){
  const delivery=got.delivery
  if(delivery.comparison_version_id===want.result_version_id)return ordered(delivery.result_version_ids,want.figure_version_ids)
  return ordered(delivery.result_version_ids,[want.result_version_id,...want.figure_version_ids])
 }
 return got.kind==='bulk'&&want.kind==='bulk'&&got.delivery.comparison_version_id===want.delivery.comparison_version_id
  &&got.delivery.facts_digest===want.delivery.facts_digest&&ordered(got.delivery.result_version_ids,want.delivery.result_version_ids)
}
