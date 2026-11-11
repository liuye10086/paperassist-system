import {useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react'
import {getApiUserId,onApiSessionChanged} from '../../shared/api/client'
import {safeError} from '../../shared/i18n'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {insightRequest,IntakeError,jsonRequest,projectBase} from './api'
type Pending={key:string;url:string;body:unknown}
const prefix='paperassist.bio-insight.'
let sessionEstablished=getApiUserId()!==null
onApiSessionChanged(()=>{
 const restoredOwner=!sessionEstablished?getApiUserId():null
 sessionEstablished=true
 try{for(const key of Object.keys(sessionStorage)){
  const owner=/^paperassist\.bio-insight\.(?:draft|request):([^:]+):/.exec(key)?.[1]
  if(key.startsWith(prefix)&&owner!==restoredOwner)sessionStorage.removeItem(key)
 }}catch{}
})
export function useInsightDraft<T>(project:string,scope:string,initial:()=>T){
 const key=`${prefix}draft:${getApiUserId()??'anonymous'}:${project}:${scope}`
 const read=()=>{try{const raw=sessionStorage.getItem(key);if(raw)return JSON.parse(raw) as T}catch{}return initial()}
 const [state,setState]=useState(()=>({key,value:read()})),enabled=useRef(true),current=useRef(state)
 useLayoutEffect(()=>{current.current=state},[state])
 if(state.key!==key)setState({key,value:read()})
 useEffect(()=>onApiSessionChanged(()=>{enabled.current=false;setState({key,value:initial()})}),[key,initial])
 function update(value:T|((old:T)=>T)){if(!enabled.current)return;const previous=current.current.key===key?current.current.value:read(),next=typeof value==='function'?(value as (v:T)=>T)(previous):value;current.current={key,value:next};try{sessionStorage.setItem(key,JSON.stringify(next))}catch{}setState(current.current)}
 return[state.key===key?state.value:read(),update] as const
}
export function useInsightRead<T>(url:string,active=true,fullSource=false,poll?:(data:T)=>boolean){
 const[data,setData]=useState<{url:string;value:T}|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false),[attempt,setAttempt]=useState(0),[valid,setValid]=useState(true),visible=useDocumentVisible(),predicate=useRef(poll)
 useLayoutEffect(()=>{predicate.current=poll},[poll])
 useEffect(()=>onApiSessionChanged(()=>{setValid(false);setData(null);setError('')}),[])
 useEffect(()=>{if(!url||!active||!visible||!valid)return;const c=new AbortController();let live=true,timer=0,pollAttempt=0
  async function read(first=false){if(first){pollAttempt=0;setLoading(true);setError('')}try{const value=await insightRequest<T>(url,{signal:c.signal},fullSource);if(live&&!c.signal.aborted){setData({url,value});setError('');if(predicate.current?.(value)){const delay=Math.min(3000*2**pollAttempt,30000);pollAttempt+=1;timer=window.setTimeout(()=>void read(),delay)}else pollAttempt=0}}catch(cause){if(live&&!c.signal.aborted)setError(safeError(cause,'读取失败，请刷新固定版本。'))}finally{if(live)setLoading(false)}}void read(true)
  return()=>{live=false;c.abort();window.clearTimeout(timer)}
 },[url,active,visible,valid,attempt,fullSource])
 return{data:valid&&data?.url===url?data.value:null,error,loading,valid,refresh:()=>setAttempt(v=>v+1)}
}
export function useInsightIntent<T>(project:string,kind:'plan'|'run'|'resource'|'evidence',scope:string){
 const storage=`${prefix}request:${getApiUserId()??'anonymous'}:${project}:${kind}:${scope}`
 const[busy,setBusy]=useState(false),[unknown,setUnknown]=useState(false),[retryable,setRetryable]=useState(false),[error,setError]=useState(''),[value,setValue]=useState<T|null>(null),[valid,setValid]=useState(true)
 const pending=useRef<Pending|null>(null),request=useRef<AbortController|null>(null),live=useRef(true),allowed=useRef(true)
 const forget=useCallback(()=>{pending.current=null;try{sessionStorage.removeItem(storage)}catch{}},[storage])
 useEffect(()=>{live.current=true;queueMicrotask(()=>{if(live.current){setValue(null);setUnknown(false);setError('')}});try{const raw=sessionStorage.getItem(storage);if(raw){const p=JSON.parse(raw) as Pending;if(p.key&&p.url.startsWith(projectBase(project)+'/')){pending.current=p;queueMicrotask(()=>{if(live.current&&pending.current===p)setUnknown(true)})}}}catch{}return()=>{live.current=false;request.current?.abort();request.current=null;pending.current=null}},[storage,project])
 useEffect(()=>onApiSessionChanged(()=>{allowed.current=false;request.current?.abort();forget();setValid(false);setValue(null);setUnknown(false);setBusy(false);setError('会话已改变，请重新打开项目。')}),[forget])
 async function send(p:Pending,options?:{silent?:boolean}):Promise<T|undefined>{if(!live.current||!allowed.current||request.current)return;const c=new AbortController();request.current=c;setBusy(true);setError('');try{const result=await insightRequest<T>(p.url,{...jsonRequest(p.body,p.key),signal:c.signal},true);if(live.current&&allowed.current&&request.current===c&&!c.signal.aborted){forget();if(!options?.silent)setValue(result);setUnknown(false);setRetryable(false);return result}}catch(cause){if(live.current&&allowed.current&&request.current===c){const definite=!c.signal.aborted&&cause instanceof IntakeError&&cause.status>=400&&cause.status<500;if(definite)forget();setUnknown(!definite);setRetryable(false);setError(cause instanceof IntakeError&&cause.status===409?'版本已更新，草稿已保留；刷新并比较后另存新版。':safeError(cause,'请求状态需回查，请查询原请求。'))}}finally{if(request.current===c){request.current=null;if(live.current)setBusy(false)}}}
 async function submit(url:string,body:unknown,options?:{silent?:boolean}):Promise<T|undefined>{if(!live.current||request.current||pending.current||!allowed.current)return;const p={key:crypto.randomUUID(),url,body:structuredClone(body)};pending.current=p;try{sessionStorage.setItem(storage,JSON.stringify(p))}catch{}return await send(p,options)}
 async function lookup(){if(!live.current||request.current||!pending.current||!allowed.current)return;const c=new AbortController();request.current=c;setBusy(true);setError('');try{const result=await insightRequest<T>(kind==='evidence'?`${projectBase(project)}/external-evidence/requests/${encodeURIComponent(pending.current.key)}`:`${projectBase(project)}/bio-insight-requests/${encodeURIComponent(pending.current.key)}?kind=${kind}`,{signal:c.signal},true);if(live.current&&!c.signal.aborted&&allowed.current&&request.current===c){forget();setValue(result);setUnknown(false);setRetryable(false)}}catch(cause){if(live.current&&!c.signal.aborted&&allowed.current&&request.current===c){setRetryable(cause instanceof IntakeError&&cause.status===404);setError(cause instanceof IntakeError&&cause.status===404?'尚未找到原请求，可显式重试同一请求；不重新计算新任务。':safeError(cause,'原请求尚未核实，请继续回查。'))}}finally{if(request.current===c){request.current=null;if(live.current)setBusy(false)}}}
 return{busy,unknown,retryable,error,value,valid,submit,lookup,retry:async()=>{if(live.current&&!request.current&&retryable&&pending.current&&allowed.current)await send(pending.current)},cancel:()=>{request.current?.abort();if(pending.current){setUnknown(true);setRetryable(false)}},clear:()=>{setValue(null);setError('')}}
}
