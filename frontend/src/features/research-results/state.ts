import {sourceLabels,type Source,type SourceItem,type Selection} from './contracts'
import {figureConfigName,resultFileName} from '../bioinformatics/bioPresentation'
import type {SourceKind} from './contracts'
const readerLabels:Record<SourceKind,string>={analysis_run:'统计分析结果',bio_insight_result_version:'差异、富集与候选结果',
 bio_insight_result_member:'差异与富集成果文件',bio_processed_dataset_version:'生信分析结果',bio_analysis_artifact:'生信分析结果表',
 bio_figure_version:'生信图件',original_file:'原始文件',external_evidence_version:'外部结果',
 research_finding_version:'研究发现',research_figure_version:'研究图件',research_report_version:'研究报告'}
export const readerSourceLabel=(kind:SourceKind)=>readerLabels[kind]
export function readerSourceTitle(s:Pick<SourceItem,'source_id'|'source_kind'|'title'>,t:(v:string)=>string){
 const tail=[' / ',' · ',' '].find(sep=>s.title?.endsWith(sep+s.source_id))
 const title=tail?s.title.slice(0,-(tail.length+s.source_id.length)):s.title===s.source_id?'':s.title
 if(s.source_kind==='bio_insight_result_version'){
  const result:Record<string,string>={comparison:'差异比较结果',ora:'功能富集结果',gsea_prerank:'基因集富集结果',candidate:'候选基因结果',figure:'分析图件',integration:'联合分析结果'}
  return t(result[title]??readerLabels[s.source_kind])
 }
 if(s.source_kind==='bio_insight_result_member'||s.source_kind==='bio_analysis_artifact')return t(readerLabels[s.source_kind])
 return title||t(readerLabels[s.source_kind])
}
export function readerSourceOption(s:SourceItem,t:(v:string)=>string,locale:string){
 const title=s.format&&s.key?resultFileName({key:s.key,format:s.format},t)
  :s.source_kind==='bio_figure_version'&&s.kind&&s.title===s.kind?figureConfigName({kind:s.kind,panel:s.panel},t)
  :readerSourceTitle(s,t)
 const time=s.created_at&&new Date(s.created_at).toLocaleString(locale)
 return [title,s.dataset_name===title?null:s.dataset_name,s.source_label,time].filter(Boolean).join(' · ')
}
export function sourceOptionLabel(s:SourceItem,t:(value:string)=>string){const title=s.title&&s.title!==s.source_id?s.title:t(sourceLabels[s.source_kind]);const context=s.source_label??s.dataset_name??s.sample_id;const status=({succeeded:'已完成',available:'可用',queued:'待执行',running:'运行中',failed:'执行失败',parsed:'已解析',stored:'已保存'} as Record<string,string>)[s.status]??s.status;return[title,[s.kind,s.panel].filter(Boolean).join(' / '),context,s.raw_version!==undefined?`${t('原始版本')} v${s.raw_version}`:'',s.recipe_version!==undefined?`${t('分析方案版本')} ${s.recipe_version}`:'',(s.version??s.revision)!==undefined?`v${s.version??s.revision}`:'',t(status)].filter(Boolean).join(' · ')}
export function selectionOnly(value:Source&Record<string,unknown>):Source
export function selectionOnly(value:Source):Source
export function selectionOnly(value:Source):Source{return{schema_version:1,source_kind:value.source_kind,source_id:value.source_id,locator:value.locator,...(value.sha256?{sha256:value.sha256}:{})}}
export function mergeSelection(current:Selection,incoming:Selection):Selection{return{finding_version_ids:[...new Set([...current.finding_version_ids,...incoming.finding_version_ids])],figure_version_ids:[...new Set([...current.figure_version_ids,...incoming.figure_version_ids])],report_version_ids:[...new Set([...current.report_version_ids,...incoming.report_version_ids])]}}
type Compared={facts:{id:string;[key:string]:unknown}[];claims:{id:string;[key:string]:unknown}[]}
export function findingDiff(a:Compared,b:Compared){function diff(k:'facts'|'claims'){return{added:b[k].filter(v=>!a[k].some(p=>p.id===v.id)).map(v=>v.id),removed:a[k].filter(v=>!b[k].some(p=>p.id===v.id)).map(v=>v.id),changed:b[k].filter(v=>{const p=a[k].find(p=>p.id===v.id);return p&&JSON.stringify(p)!==JSON.stringify(v)}).map(v=>v.id)}}return{facts:diff('facts'),claims:diff('claims')}}
export const sourceKey=(s:Source)=>JSON.stringify(selectionOnly(s))
export const emptySelection=():Selection=>({finding_version_ids:[],figure_version_ids:[],report_version_ids:[]})
