import {captureApiSession,getApiUserId} from '../../shared/api/client'
import {bioRequest,jsonRequest,IntakeError,projectBase} from '../bioinformatics/api'
export const PART_SIZE=16*1024*1024
export type Upload={id:string;filename:string;size_bytes:number;part_size:number;status:string;error_code?:string}
export type Profile={id:string;name?:string;species:string;chemistries:string[];account_verified:boolean;engine?:string;reference_id?:string;max_input_bytes?:number;estimated_run_cost_usd?:number|null}
export type Capabilities={enabled:boolean;provider:string;region?:string;profiles:Profile[];blockers:string[];part_size:number;evidence:{documentation_supported:boolean;code_integrated:boolean;real_data_verified:boolean}}
export type Output={role:string;file_id:string;filename?:string;size_bytes?:number;sha256?:string}
export type CloudRun={id:string;status:string;sample_id:string;library_id:string;engine:string;error_code?:string;cancel_requested?:boolean;provider_run_id?:string;provider_state?:string;outputs:Output[];task?:{id:string;revision:number;status:string};verification?:unknown}
export type RunDraft={profile_id:string;sample_id:string;library_id:string;donor_id:string;group:string;chemistry:string;r1:string;r2:string;budget_limit_usd:string}
export const newRunDraft=():RunDraft=>({profile_id:'',sample_id:'',library_id:'',donor_id:'',group:'',chemistry:'',r1:'',r2:'',budget_limit_usd:''})
export const cloudStorageKey=(owner:string,project:string)=>`paperassist.bio-cloud.v1:${encodeURIComponent(owner)}:${encodeURIComponent(project)}`
export const cloudBase=(project:string)=>`${projectBase(project)}/bio-cloud`
type Pending={key:string;kind:'upload'|'run'}
function requireReceipt(value:unknown,kind:Pending['kind']){
 if(!value||typeof value!=='object'||!('id' in value)||typeof value.id!=='string'||!value.id||!('status' in value)||typeof value.status!=='string'||(kind==='upload'&&!('filename' in value))||(kind==='run'&&(!('outputs' in value)||!Array.isArray(value.outputs))))throw Error('回执格式待核对，请查回原请求。')
}
export class CloudClient {
 readonly base:string
 readonly storageKey:string
 pending:Pending|null=null
 private checkSession=captureApiSession()
 constructor(project:string){this.base=cloudBase(project);const owner=getApiUserId();this.storageKey=owner?cloudStorageKey(owner,project):'';try{const stored=this.storageKey&&sessionStorage.getItem(this.storageKey);if(stored){const parsed=JSON.parse(stored);if(/^[a-f0-9-]{36}$/.test(parsed.key)&&['run','upload'].includes(parsed.kind))this.pending=parsed}}catch{/* Keep unknown identities only when readable. */}}
 request=<T,>(path:string,init?:RequestInit):Promise<T>=>{this.checkSession();return bioRequest<T>(`${this.base}${path}`,init)}
 private save(value:Pending|null){if(this.storageKey){if(value)sessionStorage.setItem(this.storageKey,JSON.stringify(value));else sessionStorage.removeItem(this.storageKey)}this.pending=value}
 async create<T>(kind:Pending['kind'],body:unknown,signal?:AbortSignal):Promise<T>{
  this.checkSession();if(this.pending)throw Error('原请求结果待确认，请先查回。')
  // Fail closed if durable identity cannot be saved before a potentially paid POST.
  if(!this.storageKey)throw Error('请重新登录后提交。')
  this.save({key:crypto.randomUUID(),kind})
  try{const value=await this.request<T>(kind==='upload'?'/uploads':'/runs',{...jsonRequest(body,this.pending!.key),signal});this.checkSession();requireReceipt(value,kind);this.save(null);return value}
  catch(cause){if(cause instanceof IntakeError&&cause.status>=400&&cause.status<500)this.save(null);throw cause}
 }
 async lookup<T>(signal?:AbortSignal):Promise<T>{if(!this.pending)throw Error('没有待查请求。');const {key,kind}=this.pending;const value=await this.request<T>(`/requests/${encodeURIComponent(key)}?kind=${kind}`,{signal});this.checkSession();requireReceipt(value,kind);this.save(null);return value}
}
export function runBody(draft:RunDraft,profile:Profile){
 if(!profile.account_verified||!draft.sample_id.trim()||!draft.library_id.trim()||!draft.r1||!draft.r2||draft.r1===draft.r2||!profile.chemistries.includes(draft.chemistry)||!/^\d+(\.\d{1,2})?$/.test(draft.budget_limit_usd)||Number(draft.budget_limit_usd)<=0)throw Error('请核对文库、FASTQ配对、流程和正数预算。')
 return {profile_id:profile.id,sample_id:draft.sample_id.trim(),library_id:draft.library_id.trim(),species:profile.species,chemistry:draft.chemistry,donor_id:draft.donor_id.trim(),group:draft.group.trim(),fastqs:[{upload_id:draft.r1,read:'R1',lane:'L001',chunk:1},{upload_id:draft.r2,read:'R2',lane:'L001',chunk:1}],external_processing_confirmed:true,budget_approved:true,budget_limit_usd:draft.budget_limit_usd}
}
export function matrixOutputs(outputs:Output[]){const roles=['matrix','features','barcodes'] as const;const selected=Object.fromEntries(roles.map(role=>[role,outputs.find(o=>o.role===role)?.file_id]));return roles.every(role=>selected[role])?selected as Record<typeof roles[number],string>:null}
type Request=<T>(path:string,init?:RequestInit)=>Promise<T>
export async function resumeUpload(file:File,upload:Upload,request:Request,signal:AbortSignal,put:typeof fetch=fetch,progress?:(part:number,total:number)=>void){
 if(file.name!==upload.filename||file.size!==upload.size_bytes||upload.part_size!==PART_SIZE)throw Error('本地文件身份或分片大小不匹配。')
 const check=()=>{if(signal.aborted)throw new DOMException('上传已停止','AbortError')};check()
 // The cloud may already have consumed the multipart session; let the backend verify the final object.
 if(upload.status==='completing')return request<Upload>(`/uploads/${encodeURIComponent(upload.id)}/complete`,{...jsonRequest({}),signal})
 const {items}=await request<{items:{part_number:number;checksum_sha256:string;size_bytes:number}[]}>(`/uploads/${encodeURIComponent(upload.id)}/parts`,{signal})
 const count=Math.ceil(file.size/PART_SIZE)
 // Verify every retained part before writing missing parts, preventing mixed-file multipart sessions.
 const numbers=Array.from({length:count},(_,index)=>index+1),existing=new Set(items.map(item=>item.part_number))
 const order=[...numbers.filter(number=>existing.has(number)),...numbers.filter(number=>!existing.has(number))]
 let verified=0
 for(const number of order){
  check();const start=(number-1)*PART_SIZE,end=Math.min(file.size,start+PART_SIZE),part=file.slice(start,end)
  const digest=new Uint8Array(await crypto.subtle.digest('SHA-256',await part.arrayBuffer()));check()
  const checksum=btoa(String.fromCharCode(...digest));const previous=items.find(item=>item.part_number===number)
  if(previous){if(previous.size_bytes!==end-start||previous.checksum_sha256!==checksum)throw Error(`第 ${number} 分片校验不一致，请选择原始文件；未继续上传。`)}
  else{const signed=await request<{url:string;headers:Record<string,string>}>(`/uploads/${encodeURIComponent(upload.id)}/parts/${number}/sign`,{...jsonRequest({checksum_sha256:checksum}),signal});check();const response=await put(signed.url,{method:'PUT',headers:signed.headers,body:part,credentials:'omit',signal});check();if(!response.ok)throw Error('分片上传失败，请重新选择原文件续传。')}
  progress?.(++verified,count)
 }
 check();return request<Upload>(`/uploads/${encodeURIComponent(upload.id)}/complete`,{...jsonRequest({}),signal})
}
