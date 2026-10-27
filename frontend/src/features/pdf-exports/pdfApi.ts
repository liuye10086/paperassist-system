import {onApiSessionChanged} from '../../shared/api/client'
import {taskRequest} from '../tasks/taskApi'
export type PdfSourceKind='report'|'collection_report'|'manuscript_export'|'layout_export'|'review_document_export'
export type PdfScope={projectId:string;sourceKind:PdfSourceKind;sourceId:string;sourceSha256?:string}
export type PdfExport={recovery_mode?:'local_candidate'|'blocked'|null;recovery_request_key?:string;id:string;project_id:string;source_kind:PdfSourceKind;source_id:string;source_sha256:string;status:'queued'|'running'|'succeeded'|'failed';task_id:string;created_at:string;filename:string|null;error_code:string|null;parent_export_id:string|null;renderer_manifest:Record<string,unknown>|null;sha256:string|null;size_bytes:number|null;download_url:string|null}
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
const text=(v:unknown):v is string=>typeof v==='string'
const id=(v:unknown):v is string=>text(v)&&/^[A-Za-z0-9_-]{1,128}$/.test(v)
const hash=(v:unknown)=>text(v)&&/^[a-f0-9]{64}$/.test(v)
export const pdfBase=(projectId:string)=>`/api/v1/projects/${encodeURIComponent(projectId)}/pdf-exports`
export function validPdfExport(v:unknown,scope:PdfScope):v is PdfExport{
 return object(v)&&id(v.id)&&v.project_id===scope.projectId&&v.source_kind===scope.sourceKind&&v.source_id===scope.sourceId&&hash(v.source_sha256)&&(scope.sourceSha256===undefined||v.source_sha256===scope.sourceSha256)&&['queued','running','succeeded','failed'].includes(String(v.status))&&id(v.task_id)&&text(v.created_at)&&Number.isFinite(Date.parse(v.created_at))&&(v.filename===null||text(v.filename))&&(v.error_code===null||text(v.error_code))&&(v.parent_export_id===null||id(v.parent_export_id)&&v.parent_export_id!==v.id)&&(v.renderer_manifest===null||object(v.renderer_manifest))&&(v.sha256===null||hash(v.sha256))&&(v.size_bytes===null||typeof v.size_bytes==='number'&&Number.isSafeInteger(v.size_bytes)&&v.size_bytes>0)&&(v.download_url===null||v.download_url===`${pdfBase(scope.projectId)}/${encodeURIComponent(v.id)}/download`)&&(v.status==='succeeded'?text(v.filename)&&v.filename.length>0&&hash(v.sha256)&&typeof v.size_bytes==='number'&&object(v.renderer_manifest)&&text(v.download_url):v.download_url===null)
}
export async function listPdfExports(scope:PdfScope,controller:AbortController){
 return taskRequest(`${pdfBase(scope.projectId)}?source_kind=${scope.sourceKind}&source_id=${encodeURIComponent(scope.sourceId)}`,controller,(v):v is {items:PdfExport[]}=>object(v)&&Array.isArray(v.items)&&v.items.every(item=>validPdfExport(item,scope))&&new Set(v.items.map(item=>item.id)).size===v.items.length,'PDF 状态读取失败，请刷新。')
}
export async function submitPdfExport(scope:PdfScope,controller:AbortController,parent?:string,original?:PdfExport){
 const url=parent?`${pdfBase(scope.projectId)}/${encodeURIComponent(parent)}/retry`:pdfBase(scope.projectId)
 const pendingKey=requestKey(scope,parent)
 const result=await taskRequest(url,controller,(v):v is PdfExport=>validPdfExport(v,scope)&&(parent&&v.recovery_mode==='local_candidate'?v.id===parent&&!!original&&v.source_sha256===original.source_sha256&&v.task_id===original.task_id&&v.parent_export_id===original.parent_export_id&&v.recovery_request_key===pendingKey:v.parent_export_id===(parent??null)&&v.id!==parent),'PDF 请求未确认，请刷新状态后重试。',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...(parent?{}:{source_kind:scope.sourceKind,source_id:scope.sourceId}),request_key:pendingKey})})
 const signature=keySignature(scope,parent)
 if(keys.get(signature)===pendingKey)keys.delete(signature)
 try{if(sessionStorage.getItem(signature)===pendingKey)sessionStorage.removeItem(signature)}catch{/* Memory still tracks uncertain requests if tab storage is unavailable. */}
 return result
}
const keys=new Map<string,string>(),prefix='paperassist-pdf-key:'
// Authentication restoration also emits a session change after a page reload.
// Keep tab-scoped random keys for immutable source IDs so an unconfirmed POST is
// replayed safely. These keys contain no credentials; the backend binds them to
// its authenticated owner as well as the project, source and parent.
onApiSessionChanged(()=>keys.clear())
export function hasUnconfirmedPdfRequest(scope:PdfScope,parent?:string){
 const signature=keySignature(scope,parent)
 let key=keys.get(signature)
 try{key??=sessionStorage.getItem(signature)??undefined}catch{/* The current page still retains its request identity. */}
 return !!key&&/^[!-~]{1,128}$/.test(key)
}
function requestKey(scope:PdfScope,parent?:string){
 const signature=keySignature(scope,parent)
 let key=keys.get(signature)
 try{key??=sessionStorage.getItem(signature)??undefined}catch{/* Fall back to this session's memory. */}
 if(!key||!/^[!-~]{1,128}$/.test(key))key=crypto.randomUUID()
 try{sessionStorage.setItem(signature,key)}catch{/* Preserve in memory when tab storage is unavailable. */}
 keys.set(signature,key);return key
}
function keySignature(scope:PdfScope,parent?:string){return prefix+JSON.stringify([scope.projectId,scope.sourceKind,scope.sourceId,parent??null])}
const retryable=new Set(['pdf_renderer_unavailable','pdf_conversion_timeout','pdf_renderer_busy','storage_unavailable','task_worker_interrupted','pdf_conversion_failed'])
export function canRetryPdf(item:PdfExport,items:PdfExport[]){
 if(item.status!=='failed'||item.recovery_mode==='blocked'||item.recovery_mode!=='local_candidate'&&!retryable.has(item.error_code??'')||items.some(row=>row.parent_export_id===item.id))return false
 let depth=0,current=item;const seen=new Set([item.id])
 while(current.parent_export_id){const parent=items.find(row=>row.id===current.parent_export_id);if(!parent||seen.has(parent.id))return false;seen.add(parent.id);depth++;current=parent}
 return item.recovery_mode==='local_candidate'||depth<3
}
