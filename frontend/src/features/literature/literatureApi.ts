import { taskRequest } from '../tasks/taskApi'
import { isTask, type TaskView } from '../tasks/taskTypes'
export const publicationTypes = ['Clinical Trial','Randomized Controlled Trial','Review','Systematic Review','Meta-Analysis','Observational Study','Case Reports'] as const
export type SearchInput = {research_topic:string;source_context:{kind:'project_topic'|'section'|'feedback';label:string;text:string};query:string;year_from:number|null;year_to:number|null;publication_types:string[];sort:'relevance'|'pub_date';limit:20|50|100;output_language:'zh-CN'|'en'}
export type Configuration = {available:boolean;reason:string|null;candidate_limits:number[];default_limit:number;page_size:number;publication_types:string[];full_text_acquisition:false;claim_verification:false}
export type Search = {id:string;project_id:string;task:TaskView;input:SearchInput;effective_query:string;query_translation:string|null;matched_count:number|null;retrieved_count:number;missing_pmids:string[];warnings:string[];created_at:string;updated_at:string;source_url:string}
export type Source = {search_id:string;receipt_id:string;query:string;source_context?:SearchInput['source_context']|null;effective_query:string;retrieved_at:string;source_kind:'ncbi_eutilities'|'synthetic_fixture';cached:boolean;ordinal:number;source_download_url:string}
export type Selection = {status:'candidate'|'shortlisted'|'excluded';note:string;revision:number}
export type Reference = {id:string;reference_id:string;project_id:string;pmid:string;record:{pmid:string;title:string|null;authors:string[];year:number|null;journal:string|null;doi:string|null;abstract:{label:string|null;text:string}[];abstract_status:'available'|'not_returned'|'empty';full_text_status:'not_acquired';verification_status:'not_verified';doi_resolution_status:'not_checked';keywords:string[];mesh_terms:string[];full_text_links:{url:string;source:string}[]};selection:Selection;source:Source;created_at:string;updated_at:string}
export type Page<T> = {project_id:string;items:T[];total:number;page:number;page_size:number}
export type ReferenceDetail = Reference & {sources:{items:Source[];total:number;page:number;page_size:number};decisions:unknown[]}
const obj=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
const str=(v:unknown):v is string=>typeof v==='string'
const id=(v:unknown):v is string=>str(v)&&/^[A-Za-z0-9_-]{1,64}$/.test(v)
const nat=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0
const date=(v:unknown)=>str(v)&&Number.isFinite(Date.parse(v))
const nullable=(v:unknown)=>v===null||str(v)
const texts=(v:unknown):v is string[]=>Array.isArray(v)&&v.every(str)
const validSearchContext=(v:unknown):v is SearchInput['source_context']=>obj(v)&&str(v.kind)&&['project_topic','section','feedback'].includes(v.kind)&&str(v.label)&&v.label.length<=200&&str(v.text)&&v.text.length<=6000
export function validSearchInput(v:unknown):v is SearchInput {
 if(!obj(v)||!str(v.research_topic)||!v.research_topic.trim()||v.research_topic.length>2000||v.research_topic.includes('\0')||!str(v.query)||!v.query.trim()||v.query.length>4000||v.query.includes('\0')||!validSearchContext(v.source_context))return false
 const year=(x:unknown)=>x===null||nat(x)&&x>=1800&&x<=3000
 return year(v.year_from)&&year(v.year_to)&&!(typeof v.year_from==='number'&&typeof v.year_to==='number'&&v.year_from>v.year_to)&&texts(v.publication_types)&&new Set(v.publication_types).size===v.publication_types.length&&v.publication_types.every(p=>(publicationTypes as readonly string[]).includes(p))&&['relevance','pub_date'].includes(String(v.sort))&&typeof v.limit==='number'&&[20,50,100].includes(v.limit)&&['zh-CN','en'].includes(String(v.output_language))
}
export const basePath=(project:string)=>`/api/v1/projects/${encodeURIComponent(project)}/literature`
export const validConfig=(v:unknown):v is Configuration=>obj(v)&&typeof v.available==='boolean'&&nullable(v.reason)&&Array.isArray(v.candidate_limits)&&v.candidate_limits.join(',')==='20,50,100'&&v.default_limit===20&&v.page_size===10&&texts(v.publication_types)&&v.full_text_acquisition===false&&v.claim_verification===false
export function validSource(v:unknown,project:string):v is Source {return obj(v)&&id(v.search_id)&&id(v.receipt_id)&&str(v.query)&&(v.source_context===undefined||v.source_context===null||validSearchContext(v.source_context))&&str(v.effective_query)&&date(v.retrieved_at)&&['ncbi_eutilities','synthetic_fixture'].includes(String(v.source_kind))&&typeof v.cached==='boolean'&&nat(v.ordinal)&&v.ordinal>=1&&v.source_download_url===`${basePath(project)}/receipts/${encodeURIComponent(v.receipt_id)}/source`}
export function validSearch(v:unknown,project:string):v is Search {return obj(v)&&id(v.id)&&v.project_id===project&&isTask(v.task,project,v.id)&&v.task.task_type==='literature_search'&&validSearchInput(v.input)&&str(v.effective_query)&&nullable(v.query_translation)&&(v.matched_count===null||nat(v.matched_count))&&nat(v.retrieved_count)&&v.retrieved_count<=100&&texts(v.missing_pmids)&&v.missing_pmids.every(p=>/^[1-9][0-9]*$/.test(p))&&texts(v.warnings)&&date(v.created_at)&&date(v.updated_at)&&str(v.source_url)}
export function validReference(v:unknown,project:string):v is Reference {
 if(!obj(v)||!id(v.id)||!id(v.reference_id)||v.project_id!==project||!str(v.pmid)||!/^[1-9][0-9]*$/.test(v.pmid)||!obj(v.record)||!obj(v.selection)||!validSource(v.source,project)||!date(v.created_at)||!date(v.updated_at))return false
 const r=v.record,s=v.selection
 return r.pmid===v.pmid&&nullable(r.title)&&texts(r.authors)&&(r.year===null||nat(r.year))&&nullable(r.journal)&&nullable(r.doi)&&Array.isArray(r.abstract)&&r.abstract.every(x=>obj(x)&&nullable(x.label)&&str(x.text))&&['available','not_returned','empty'].includes(String(r.abstract_status))&&r.full_text_status==='not_acquired'&&r.verification_status==='not_verified'&&r.doi_resolution_status==='not_checked'&&texts(r.keywords)&&texts(r.mesh_terms)&&Array.isArray(r.full_text_links)&&r.full_text_links.every(l=>obj(l)&&str(l.url)&&str(l.source))&&['candidate','shortlisted','excluded'].includes(String(s.status))&&str(s.note)&&s.note.length<=2000&&nat(s.revision)&&s.revision>=1
}
export function validPage<T>(v:unknown,project:string,page:number,valid:(x:unknown)=>x is T):v is Page<T>{return obj(v)&&v.project_id===project&&v.page===page&&v.page_size===10&&nat(v.total)&&Array.isArray(v.items)&&v.items.length<=10&&v.items.length<=v.total&&v.items.every(valid)}
export function validDetail(v:unknown,project:string,referenceId:string,page:number):v is ReferenceDetail{return validReference(v,project)&&v.id===referenceId&&'sources' in v&&obj(v.sources)&&v.sources.page===page&&v.sources.page_size===10&&nat(v.sources.total)&&Array.isArray(v.sources.items)&&v.sources.items.length<=10&&v.sources.items.length<=v.sources.total&&v.sources.items.every(s=>validSource(s,project))&&'decisions' in v&&Array.isArray(v.decisions)}
export function literatureRequest<T>(path:string,controller:AbortController,validate:(v:unknown)=>v is T,init?:RequestInit){return taskRequest(path,controller,validate,'文献资料读取失败，请重试。',init)}
