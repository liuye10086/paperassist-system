import {RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
export {IntakeError as ResearchError,jsonRequest,projectBase} from '../research-intake/api'
import {useEffect,useLayoutEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError} from '../../shared/i18n'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {intakeRequest} from '../research-intake/api'
export const RESEARCH_TIMEOUT_MS=RESEARCH_REQUEST_TIMEOUT_MS
export const RESEARCH_LOADING_MESSAGE='正在核验固定来源，大文件可能需要数分钟。'
/** Research provenance closures can verify large retained assets. Keep this bound
 * local to research operations; ordinary requests use the shared standard bound. */
export function researchRequest<T>(url:string,init?:RequestInit,timeoutMs=RESEARCH_TIMEOUT_MS){return intakeRequest<T>(url,init,timeoutMs)}
export function useResearchRead<T>(url:string,active:boolean,poll?: (value:T)=>boolean){
 const [data,setData]=useState<{url:string;value:T}|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false),[attempt,setAttempt]=useState(0),[valid,setValid]=useState(true);const visible=useDocumentVisible(),predicate=useRef(poll);useLayoutEffect(()=>{predicate.current=poll},[poll])
 useEffect(()=>onApiSessionChanged(()=>{setValid(false);setData(null);setError('')}),[])
 useEffect(()=>{if(!url||!active||!visible||!valid)return;let live=true,timer=0,pollAttempt=0;const c=new AbortController();async function load(first=false){if(first){pollAttempt=0;setLoading(true);setError('')}try{const value=await researchRequest<T>(url,{signal:c.signal});if(!live||c.signal.aborted)return;setData({url,value});setError('');if(predicate.current?.(value)){const delay=Math.min(3000*2**pollAttempt,30000);pollAttempt+=1;timer=window.setTimeout(()=>void load(),delay)}else pollAttempt=0}catch(cause){if(live&&!c.signal.aborted)setError(safeError(cause,'研究成果读取失败，请刷新。'))}finally{if(live)setLoading(false)}}void load(true);return()=>{live=false;c.abort();window.clearTimeout(timer)}},[url,active,visible,valid,attempt])
 return{data:data?.url===url?data.value:null,error,loading,loadingMessage:RESEARCH_LOADING_MESSAGE,valid,refresh:()=>setAttempt(v=>v+1)}
}
