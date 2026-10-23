import {useCallback,useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError} from '../../shared/i18n'
import {taskRequest,TaskRequestError} from '../tasks/taskApi'
export function useReviewRequest(){
 const [available,setAvailable]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const alive=useRef(true),controller=useRef(new AbortController()),lock=useRef(false),attempts=useRef(new Map<string,{body:string;key:string}>())
 useEffect(()=>{alive.current=true;controller.current=new AbortController();const current=controller.current;const stop=onApiSessionChanged(()=>{current.abort();setAvailable(false);setError('')});return()=>{alive.current=false;current.abort();stop()}},[])
 const request=useCallback(async<T,>(url:string,valid:(v:unknown)=>v is T,body?:unknown,signal?:AbortSignal):Promise<T>=>{
  const parent=controller.current;if(parent.signal.aborted)throw new DOMException('Aborted','AbortError')
  const c=new AbortController(),abort=()=>c.abort();parent.signal.addEventListener('abort',abort,{once:true});signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)c.abort()
  let init:RequestInit|undefined
  if(body!==undefined){const serialized=JSON.stringify(body);let a=attempts.current.get(url);if(a?.body!==serialized){a={body:serialized,key:crypto.randomUUID()};attempts.current.set(url,a)}init={method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':a.key},body:serialized}}
  try{const value=await taskRequest(url,c,valid,'修改成果请求失败，请刷新后重试。',init);if(!alive.current||c.signal.aborted)throw new DOMException('Aborted','AbortError');return value}catch(cause){if(cause instanceof TaskRequestError&&[401,403].includes(cause.status)){parent.abort();setAvailable(false)}throw cause}finally{parent.signal.removeEventListener('abort',abort);signal?.removeEventListener('abort',abort)}
 },[])
 const run=useCallback(async(work:()=>Promise<void>)=>{if(lock.current||controller.current.signal.aborted)return;lock.current=true;setBusy(true);setError('');try{await work()}catch(cause){if(alive.current&&!controller.current.signal.aborted)setError(safeError(cause,'修改成果请求失败，请刷新后重试。'))}finally{lock.current=false;if(alive.current)setBusy(false)}},[])
 return {request,run,available,busy,error,setError}
}
