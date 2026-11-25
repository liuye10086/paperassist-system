import {RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
export {IntakeError as ResearchError,jsonRequest,projectBase} from '../research-intake/api'
import {useEffect,useLayoutEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError} from '../../shared/i18n'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {IntakeError, intakeRequest} from '../research-intake/api'
export const RESEARCH_TIMEOUT_MS=RESEARCH_REQUEST_TIMEOUT_MS
export const RESEARCH_LOADING_MESSAGE='正在核验固定来源，大文件可能需要数分钟。'
/** Research provenance closures can verify large retained assets. Keep this bound
 * local to research operations; ordinary requests use the shared standard bound. */
export function researchRequest<T>(url:string,init?:RequestInit,timeoutMs=RESEARCH_TIMEOUT_MS){return intakeRequest<T>(url,init,timeoutMs)}
type PollingOptions<T> = {maxDelayMs?: number; retryTemporaryErrors?: boolean; maxDelayFor?: (value:T)=>number|undefined}

export function useResearchRead<T>(url:string,active:boolean,poll?: (value:T)=>boolean, refreshKey=0, polling?: PollingOptions<T>){
 const {maxDelayMs=30000,retryTemporaryErrors=false,maxDelayFor}=polling??{}
 const [data,setData]=useState<{url:string;value:T}|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false),[attempt,setAttempt]=useState(0),[valid,setValid]=useState(true);const visible=useDocumentVisible(),predicate=useRef(poll);useLayoutEffect(()=>{predicate.current=poll},[poll])
 const currentRead=useRef<AbortController|null>(null)
 useEffect(()=>onApiSessionChanged(()=>{setValid(false);setData(null);setError('')}),[])
 useEffect(()=>{
  if(!url||!active||!visible||!valid)return
  let live=true,timer=0,pollAttempt=0,retryAttempt=0
  const c=new AbortController()
  currentRead.current=c
  async function load(first=false){
   if(first){setLoading(true);setError('')}
   try {
    const value=await researchRequest<T>(url,{signal:c.signal,cache:retryTemporaryErrors?'no-store':undefined})
    if(!live||c.signal.aborted)return
    retryAttempt=0
    setData({url,value});setError('')
    if(predicate.current?.(value))schedule(pollAttempt++,maxDelayFor?.(value)??maxDelayMs)
   } catch(cause) {
    if(!live||c.signal.aborted)return
    const temporary = !(cause instanceof IntakeError) || cause.status >= 500 || cause.status === 408 || cause.status === 429
    if(retryTemporaryErrors && temporary) schedule(retryAttempt++,30000)
    else setError(safeError(cause,'研究成果读取失败，请刷新。'))
   } finally {if(live)setLoading(false)}
  }
  function schedule(attempt:number,cap:number){
   timer=window.setTimeout(()=>void load(),Math.min(3000*2**attempt,cap))
  }
  void load(true)
  return()=>{live=false;currentRead.current=null;c.abort();window.clearTimeout(timer)}
 },[url,active,visible,valid,attempt,refreshKey,maxDelayMs,retryTemporaryErrors,maxDelayFor])
 function refresh(): void
 function refresh(mode: 'invalidate'): void
 function refresh(mode?: 'invalidate') {
  if(mode==='invalidate'){
   currentRead.current?.abort()
   setData(null)
   setError('')
  }
  setAttempt(v=>v+1)
 }
 return{data:data?.url===url?data.value:null,error,loading,loadingMessage:RESEARCH_LOADING_MESSAGE,valid,refresh}
}
