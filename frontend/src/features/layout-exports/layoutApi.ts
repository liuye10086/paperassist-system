import {codePointLength} from './unicodeText'
import {apiFetch,captureApiSession,getApiUserId,onApiSessionChanged} from '../../shared/api/client'
import {apiError,message} from '../../shared/i18n'
export type LayoutSourceKind='report'|'collection_report'|'manuscript_export'
export type LayoutScope={projectId:string;sourceKind:LayoutSourceKind;sourceId:string;sourceSha256?:string}
export type Anchor={id:string;position:number;type:'paragraph'|'heading'|'figure'|'table';text:string;heading_level:number|null;bookmark:string|null;is_caption:boolean}
export type Formula={id:string;anchor_id:string;expression:string;placement:'after'|'inline'}
export type Reference={anchor_id:string;target_id:string;kind:'text'|'page'|'number';prefix:string}
export type Layout={source_sha256:string;formulas:Formula[];references:Reference[];headings:{anchor_id:string;level:number}[];toc:{depth:number}|null;pagination:{mode:'continuous'|'roman_front';body_anchor_id?:string|null}|null;landscape_anchor_ids:string[]}
export type Catalog={source_kind:LayoutSourceKind;source_id:string;source_sha256:string;source_size:number;filename:string;version:Record<string,unknown>;output_language:'zh-CN'|'en';anchors:Anchor[];limits:Record<string,unknown>}
export type LayoutExport={id:string;project_id:string;source_kind:LayoutSourceKind;source_id:string;source_sha256:string;status:'queued'|'running'|'succeeded'|'failed';task_id:string;created_at:string;layout:Layout;layout_version:'document_layout_v1';output_language:'zh-CN'|'en';request_key:string;can_retry:boolean;parent_export_id:string|null;filename:string|null;error_code:string|null;renderer_manifest:Record<string,unknown>|null;sha256:string|null;size_bytes:number|null;download_url:string|null}
export const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
const text=(v:unknown):v is string=>typeof v==='string'
const id=(v:unknown):v is string=>text(v)&&/^[A-Za-z0-9_-]{1,128}$/.test(v)
const hash=(v:unknown):v is string=>text(v)&&/^[a-f0-9]{64}$/.test(v)
const integer=(v:unknown,min=0):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=min
const keys=(v:Record<string,unknown>,allowed:string[])=>Object.keys(v).every(k=>allowed.includes(k))
const sourceKinds=['report','collection_report','manuscript_export']
export const layoutBase=(projectId:string)=>`/api/v1/projects/${encodeURIComponent(projectId)}/layout-exports`
export function emptyLayout(sha:string):Layout{return {source_sha256:sha,formulas:[],references:[],headings:[],toc:null,pagination:null,landscape_anchor_ids:[]}}
export function validCatalog(v:unknown,s:LayoutScope):v is Catalog{
 if(!object(v)||v.source_kind!==s.sourceKind||v.source_id!==s.sourceId||!hash(v.source_sha256)||s.sourceSha256!==undefined&&v.source_sha256!==s.sourceSha256||!integer(v.source_size,1)||!text(v.filename)||!object(v.version)||!['zh-CN','en'].includes(String(v.output_language))||!object(v.limits)||!Array.isArray(v.anchors))return false
 if(!id(v.version.id)||!integer(v.version.revision,1)||s.sourceKind==='report'&&!text(v.version.renderer_version)||s.sourceKind==='collection_report'&&!integer(v.version.export_revision,1))return false
 return v.anchors.every(a=>object(a)&&integer(a.position)&&a.id===`${v.source_sha256}:${a.position}`&&['paragraph','heading','figure','table'].includes(String(a.type))&&text(a.text)&&codePointLength(a.text)<=160&&(a.heading_level===null||integer(a.heading_level,1)&&a.heading_level<=9)&&(a.bookmark===null||text(a.bookmark))&&typeof a.is_caption==='boolean')&&new Set(v.anchors.map(a=>a.id)).size===v.anchors.length
}
export function validLayout(v:unknown,sha:string):v is Layout{
 if(!object(v)||v.source_sha256!==sha||Object.keys(v).some(k=>!['source_sha256','formulas','references','headings','toc','pagination','landscape_anchor_ids'].includes(k)))return false
 const anchor=(a:unknown)=>text(a)&&new RegExp(`^${sha}:[0-9]+$`).test(a)
 return Array.isArray(v.formulas)&&v.formulas.length<=40&&v.formulas.every(f=>object(f)&&keys(f,['id','anchor_id','expression','placement'])&&text(f.id)&&/^[A-Za-z][A-Za-z0-9_]{0,31}$/.test(f.id)&&anchor(f.anchor_id)&&text(f.expression)&&codePointLength(f.expression)>=1&&codePointLength(f.expression)<=2000&&['after','inline'].includes(String(f.placement)))&&new Set(v.formulas.map(f=>f.id)).size===v.formulas.length
 &&Array.isArray(v.references)&&v.references.length<=60&&v.references.every(r=>object(r)&&keys(r,['anchor_id','target_id','kind','prefix'])&&anchor(r.anchor_id)&&(anchor(r.target_id)||text(r.target_id)&&r.target_id.startsWith('formula:'))&&['text','page','number'].includes(String(r.kind))&&text(r.prefix)&&codePointLength(r.prefix)<=100)
 &&Array.isArray(v.headings)&&v.headings.length<=100&&v.headings.every(h=>object(h)&&keys(h,['anchor_id','level'])&&anchor(h.anchor_id)&&integer(h.level,1)&&h.level<=3)&&new Set(v.headings.map(h=>h.anchor_id)).size===v.headings.length
 &&(v.toc===null||object(v.toc)&&keys(v.toc,['depth'])&&integer(v.toc.depth,1)&&v.toc.depth<=3)
 &&(v.pagination===null||object(v.pagination)&&keys(v.pagination,['mode','body_anchor_id'])&&(v.pagination.mode==='continuous'&&v.pagination.body_anchor_id==null||v.pagination.mode==='roman_front'&&anchor(v.pagination.body_anchor_id)))
 &&Array.isArray(v.landscape_anchor_ids)&&v.landscape_anchor_ids.length<=16&&v.landscape_anchor_ids.every(anchor)&&new Set(v.landscape_anchor_ids).size===v.landscape_anchor_ids.length
}
export function validLayoutExport(v:unknown,s:LayoutScope):v is LayoutExport{
 if(!object(v)||!id(v.id)||v.project_id!==s.projectId||!sourceKinds.includes(String(v.source_kind))||v.source_kind!==s.sourceKind||v.source_id!==s.sourceId||!hash(v.source_sha256)||s.sourceSha256!==undefined&&v.source_sha256!==s.sourceSha256||!validLayout(v.layout,v.source_sha256)||v.layout_version!=='document_layout_v1'||!['zh-CN','en'].includes(String(v.output_language))||!text(v.request_key)||!/^[!-~]{1,128}$/.test(v.request_key)||typeof v.can_retry!=='boolean'||!id(v.task_id)||!text(v.created_at)||!Number.isFinite(Date.parse(v.created_at))||!['queued','running','succeeded','failed'].includes(String(v.status))||!(v.parent_export_id===null||id(v.parent_export_id)&&v.parent_export_id!==v.id)||!(v.error_code===null||text(v.error_code)))return false
 if(v.status==='succeeded')return v.can_retry===false&&v.error_code===null&&text(v.filename)&&v.filename.length>0&&hash(v.sha256)&&integer(v.size_bytes,1)&&object(v.renderer_manifest)&&v.download_url===`${layoutBase(s.projectId)}/${encodeURIComponent(v.id)}/download`
 return [v.filename,v.sha256,v.size_bytes,v.renderer_manifest,v.download_url].every(x=>x===null)&&(v.status==='failed'||v.can_retry===false)
}
async function request<T>(url:string,controller:AbortController,valid:(v:unknown)=>v is T,init?:RequestInit){
 let timer=0
 try{return await Promise.race([apiFetch(url,{...init,signal:controller.signal}).then(async response=>{
 const value:unknown=await response.json().catch(()=>null)
 if(!response.ok){let error=apiError(value,'排版请求失败，请核对设置后重试。');if(object(value)&&object(value.detail)&&object(value.detail.params)){const p=value.detail.params;if(text(p.formula_id)&&/^[A-Za-z][A-Za-z0-9_]{0,31}$/.test(p.formula_id))error=message('公式 {id} 无效，请检查语法或缩短单行表达式。',{id:p.formula_id});else if(text(p.path)&&/^(?:formulas\.(?:[0-9]|[1-3][0-9])\.(?:anchor_id|expression)|references\.(?:[0-9]|[1-5][0-9])\.(?:anchor_id|target_id|kind)|headings\.(?:[0-9]|[1-9][0-9])\.anchor_id|landscape_anchor_ids\.(?:[0-9]|1[0-5])|pagination\.body_anchor_id|toc\.depth)$/.test(p.path))error=message('排版设置位置 {path} 无效，请核对对应条目。',{path:p.path})}throw new LayoutRequestError(error,response.status)}
 if(!valid(value))throw new Error('排版数据读取失败，请刷新。');return value}),new Promise<never>((_,reject)=>{timer=window.setTimeout(()=>{controller.abort();reject(new Error('排版请求未确认，请确认上次请求。'))},15000)})])}finally{window.clearTimeout(timer)}
}
export class LayoutRequestError extends Error{status:number;constructor(message:string,status:number){super(message);this.status=status}}
export function getCatalog(s:LayoutScope,c:AbortController){return request(`${layoutBase(s.projectId)}/sources/${s.sourceKind}/${encodeURIComponent(s.sourceId)}/catalog`,c,(v):v is Catalog=>validCatalog(v,s))}
export function listLayoutExports(s:LayoutScope,c:AbortController){return request(`${layoutBase(s.projectId)}?source_kind=${s.sourceKind}&source_id=${encodeURIComponent(s.sourceId)}`,c,(v):v is {items:LayoutExport[]}=>object(v)&&Array.isArray(v.items)&&v.items.every(x=>validLayoutExport(x,s))&&new Set(v.items.map(x=>x.id)).size===v.items.length)}
type Pending={body:string;parent:string|null}
const pending=new Map<string,Pending>()
const signature=(s:LayoutScope,parent?:string)=>'paperassist-layout-request:'+JSON.stringify([getApiUserId(),s.projectId,s.sourceKind,s.sourceId,s.sourceSha256??null,parent??null])
onApiSessionChanged(()=>pending.clear())
export function pendingLayout(s:LayoutScope,parent?:string):Pending|null{
 const key=signature(s,parent);let value=pending.get(key)
 if(!value)try{const raw=sessionStorage.getItem(key);if(raw)value=JSON.parse(raw)}catch{/* Memory retains pending requests when storage is unavailable. */}
 if(!value||!object(value)||typeof value.body!=='string'||value.parent!==(parent??null))return null
 try{const b:unknown=JSON.parse(value.body);if(!object(b)||!text(b.request_key)||!/^[!-~]{1,128}$/.test(b.request_key)||(!parent&&(b.source_kind!==s.sourceKind||b.source_id!==s.sourceId||!object(b.layout)||!hash(b.layout.source_sha256)||s.sourceSha256!==undefined&&b.layout.source_sha256!==s.sourceSha256||!validLayout(b.layout,b.layout.source_sha256))))return null}catch{return null}
 return value
}
export async function submitLayout(s:LayoutScope,layout:Layout|undefined,c:AbortController,parent?:string){
 const key=signature(s,parent),check=captureApiSession();let saved=pendingLayout(s,parent)
 if(!saved){if(!parent&&!layout)throw new Error('排版设置尚未就绪。');saved={parent:parent??null,body:JSON.stringify(parent?{request_key:crypto.randomUUID()}:{source_kind:s.sourceKind,source_id:s.sourceId,layout,request_key:crypto.randomUUID()})};pending.set(key,saved);try{sessionStorage.setItem(key,JSON.stringify(saved))}catch{/* The current page still retains the exact request. */}}
 const body=JSON.parse(saved.body) as {request_key:string}
 const clear=()=>{pending.delete(key);try{sessionStorage.removeItem(key)}catch{/* No stored request remains in memory. */}}
 try{const result=await request(parent?`${layoutBase(s.projectId)}/${encodeURIComponent(parent)}/retry`:layoutBase(s.projectId),c,(v):v is LayoutExport=>validLayoutExport(v,s)&&v.parent_export_id===(parent??null)&&v.request_key===body.request_key,{method:'POST',headers:{'Content-Type':'application/json'},body:saved.body});check();clear();return result}
 catch(cause){check();if(cause instanceof LayoutRequestError&&cause.status>=400&&cause.status<500&&cause.status!==408)clear();throw cause}
}
