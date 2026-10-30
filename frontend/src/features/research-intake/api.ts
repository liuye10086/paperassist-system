import { apiFetch } from '../../shared/api/client'
import { apiError } from '../../shared/i18n'
export class IntakeError extends Error {status:number;code:string;constructor(status:number,code:string,message:string){super(message);this.status=status;this.code=code}}
export const projectBase=(p:string)=>`/api/v1/projects/${encodeURIComponent(p)}`
export async function intakeRequest<T>(url:string,init?:RequestInit,timeoutMs=15000):Promise<T>{
 const controller=new AbortController();const aborted=()=>controller.abort();if(init?.signal?.aborted)aborted();else init?.signal?.addEventListener('abort',aborted,{once:true});let timer=0
 try{return await Promise.race([apiFetch(url,{...init,signal:controller.signal}).then(async response=>{const data=await response.json().catch(()=>null);if(controller.signal.aborted)throw new DOMException('Request aborted','AbortError');if(!response.ok)throw new IntakeError(response.status,data?.detail?.code??'',apiError(data,'研究资料请求失败，请重试。'));return data as T}),new Promise<never>((_,reject)=>{timer=window.setTimeout(()=>{controller.abort();reject(new Error('研究资料请求超时，请重试。'))},timeoutMs)})])}finally{window.clearTimeout(timer);init?.signal?.removeEventListener('abort',aborted)}
}
export function jsonRequest(body:unknown,key?:string):RequestInit{return {method:'POST',headers:{'Content-Type':'application/json',...(key?{'Idempotency-Key':key}:{})},body:JSON.stringify(body)}}
