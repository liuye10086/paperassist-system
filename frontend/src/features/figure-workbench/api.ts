import {apiFetch} from '../../shared/api/client'
import {apiError} from '../../shared/i18n'
export async function workbenchRequest<T>(url:string,signal:AbortSignal,validate:(v:unknown)=>v is T,body?:unknown,key?:string):Promise<T>{
 const c=new AbortController(),abort=()=>c.abort();signal.addEventListener('abort',abort,{once:true});if(signal.aborted)c.abort()
 let rejectAbort:()=>void=()=>{};const timer=window.setTimeout(abort,30000)
 const cancelled=new Promise<never>((_,reject)=>{rejectAbort=()=>reject(new DOMException('Request aborted','AbortError'));c.signal.addEventListener('abort',rejectAbort,{once:true});if(c.signal.aborted)rejectAbort()})
 try{return await Promise.race([cancelled,(async()=>{
  const response=await apiFetch(url,{signal:c.signal,...(body!==undefined?{method:'POST',headers:{'Content-Type':'application/json',...(key?{'Idempotency-Key':key}:{})},body:JSON.stringify(body)}:{})})
  const value:unknown=await response.json().catch(()=>null)
  if(c.signal.aborted)throw new DOMException('Request aborted','AbortError')
  if(!response.ok)throw new Error(apiError(value,'图表与报告请求失败，请重新读取后重试。'))
  if(!validate(value))throw new Error('数据来源或版本不一致，请重新载入配置。')
  return value
 })()])}finally{window.clearTimeout(timer);signal.removeEventListener('abort',abort);c.signal.removeEventListener('abort',rejectAbort)}
}
