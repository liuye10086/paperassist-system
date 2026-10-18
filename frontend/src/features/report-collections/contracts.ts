import {sameSource,type DatasetAnalysisSource} from '../analysis/datasetSource'
import {object,isConfiguredFigure,isBoundExplanation,identifier,text,hash,type ConfiguredFigure,type BoundExplanation} from '../figure-workbench/contracts'
export type Bundle={result:{id:string;file_id:string;source:DatasetAnalysisSource;setup_revision:number;source_sha256:string};figure:ConfiguredFigure|null;explanation:BoundExplanation|null;configuration:{id:string;configuration_id?:string;revision?:number;source:DatasetAnalysisSource;config:{language:'zh-CN'|'en';figure_kind:string;style:{title:string;caption:string}}};projection:unknown;figure_number?:number;caption?:string;user_caption?:string|null;planned_title?:string;planned_caption?:string;dependency_engine?:string}
export const bundleId=(item:Bundle)=>item.figure?.id??item.configuration.id
export const bundleTitle=(item:Bundle)=>item.figure?.title||item.planned_title||item.configuration.config.style.title
export const bundleCaption=(item:Bundle)=>item.caption??item.figure?.caption??item.planned_caption??item.configuration.config.style.caption
export const bundleLanguage=(item:Bundle)=>item.figure?.language??item.configuration.config.language
export type ExportRequest={id:string;version_id:string;export_revision:number;status:'waiting'|'queued'|'succeeded'|'failed'|'blocked';missing:{figure_id?:string;figure_config_version_id?:string;kind:string}[];report:{id:string;filename:string;collection_id:string;collection_version_id:string;build_request_id:string;language:'zh-CN'|'en'}|null}
export type CollectionVersion={id:string;revision:number;language:'zh-CN'|'en';automatic:boolean;title:string;items:Bundle[];requests:ExportRequest[]}
export type Collection={id:string;title:string;current_version_id:string;versions:CollectionVersion[]}
export function sameCollectionScope(a:{source:DatasetAnalysisSource;language:string},b:{source:DatasetAnalysisSource;language:string;setup_revision?:number}){return a.source.kind==='prepared_dataset_version'&&sameSource(a.source,b.source)&&a.language===b.language}
export function reorderItems<T>(items:T[],index:number,direction:-1|1){const next=index+direction;if(index<0||next<0||next>=items.length)return items;const result=[...items];[result[index],result[next]]=[result[next],result[index]];return result}
const privateKey=/(^id$|^key$|required_references|rules_version|profile_version|dataset_size_bytes|recommendation_ref|resolutions|transform_version|_id$|_ids$|sha256|digest|hash|engine|parser_version|tool_version|schema_version|created_by|approved_by|response|container|workflow|renderer|provider|model|request_key|input_json|config_json|plan_id)/i
function publicValue(value:unknown):unknown{return object(value)?Object.fromEntries(publicEntries(value)):Array.isArray(value)?value.map(publicValue):typeof value==='string'&&/^[a-f0-9]{64}$/.test(value)?undefined:value}
export function publicEntries(value:Record<string,unknown>):[string,unknown][]{return Object.entries(value).filter(([k])=>!privateKey.test(k)).map(([k,v])=>[k,publicValue(v)])}
export function isBundle(value:unknown):value is Bundle{
 if(!object(value)||!object(value.result)||!object(value.result.source)||!object(value.configuration)||!identifier(value.configuration.id)||!object(value.configuration.config)||!object(value.configuration.config.style)||!text(value.configuration.config.style.title)||!text(value.configuration.config.style.caption)||!['zh-CN','en'].includes(String(value.configuration.config.language)))return false
 const r=value.result,source=r.source as DatasetAnalysisSource
 if(!identifier(r.id)||r.file_id!==source.file_id||!sameSource(value.configuration.source as DatasetAnalysisSource,source)||source.kind!=='prepared_dataset_version')return false
 if(value.figure===null)return value.explanation===null&&object(value.projection)&&identifier(value.projection.id)
 return isConfiguredFigure(value.figure,source,value.configuration.config.language as 'zh-CN'|'en',r.id,value.configuration.id)&&value.figure.setup_revision===r.setup_revision&&r.source_sha256===value.figure.source_sha256&&(value.explanation===null||isBoundExplanation(value.explanation,value.figure))
}
export const isExport=(v:unknown):v is ExportRequest=>object(v)&&identifier(v.id)&&identifier(v.version_id)&&Number.isSafeInteger(v.export_revision)&&['waiting','queued','succeeded','failed','blocked'].includes(String(v.status))&&Array.isArray(v.missing)&&v.missing.every(m=>object(m)&&(identifier(m.figure_id)||identifier(m.figure_config_version_id))&&text(m.kind))&&(v.report===null||object(v.report)&&identifier(v.report.id)&&text(v.report.filename)&&v.report.schema_version===1&&identifier(v.report.collection_id)&&v.report.collection_version_id===v.version_id&&v.report.build_request_id===v.id&&v.report.export_revision===v.export_revision&&['zh-CN','en'].includes(String(v.report.language))&&hash(v.report.sha256)&&hash(v.report.input_sha256)&&Number.isSafeInteger(v.report.size_bytes)&&object(v.report.engine)&&v.report.engine.id==='collection_word_v1')
export function isCollection(v:unknown):v is Collection{
 return object(v)&&identifier(v.id)&&text(v.title)&&identifier(v.current_version_id)&&Array.isArray(v.versions)&&v.versions.length>0&&v.versions.some(x=>object(x)&&x.id===v.current_version_id)&&v.versions.every(x=>{
  if(!object(x)||!identifier(x.id)||!Number.isSafeInteger(x.revision)||!['zh-CN','en'].includes(String(x.language))||typeof x.automatic!=='boolean'||!text(x.title)||!Array.isArray(x.items)||!x.items.length||!x.items.every(isBundle))return false
  const items=x.items
  return items.every(item=>bundleLanguage(item)===x.language&&sameSource(item.result.source,items[0].result.source))&&new Set(items.map(bundleId)).size===items.length&&Array.isArray(x.requests)&&x.requests.every(r=>isExport(r)&&r.version_id===x.id&&(!r.report||r.report.collection_id===v.id&&r.report.language===x.language))
 })
}
