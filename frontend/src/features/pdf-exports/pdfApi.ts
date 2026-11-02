import {STANDARD_REQUEST_TIMEOUT_MS,RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import {taskRequest} from '../tasks/taskApi'
export type PdfSourceKind='research_report'|'report'|'collection_report'|'manuscript_export'|'layout_export'|'review_document_export'
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
export const pdfRequestTimeoutMs=(scope:PdfScope)=>scope.sourceKind==='research_report'?RESEARCH_REQUEST_TIMEOUT_MS:STANDARD_REQUEST_TIMEOUT_MS
export async function listPdfExports(scope:PdfScope,controller:AbortController){
 return taskRequest(`${pdfBase(scope.projectId)}?source_kind=${scope.sourceKind}&source_id=${encodeURIComponent(scope.sourceId)}`,controller,(v):v is {items:PdfExport[]}=>object(v)&&Array.isArray(v.items)&&v.items.every(item=>validPdfExport(item,scope))&&new Set(v.items.map(item=>item.id)).size===v.items.length,'PDF 状态读取失败，请刷新。',undefined,pdfRequestTimeoutMs(scope))
}
