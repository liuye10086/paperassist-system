import {useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react'
import {getApiUserId,onApiSessionChanged} from '../../shared/api/client'
import {safeError} from '../../shared/i18n'
import {bioRequest,jsonRequest,IntakeError,projectBase} from './api'
import type {BioLookup} from './spatialContracts'
export default function useBioWrite<T>(project:string,kind:BioLookup['kind'],saved:(v:T)=>void,found:(v:BioLookup)=>void){
 const [storageKey]=useState(()=>{const owner=getApiUserId();return owner?`paperassist.bio-request.v1:${encodeURIComponent(owner)}:${encodeURIComponent(project)}:${kind}`:''})
 const [restored]=useState(()=>{try{const key=storageKey?sessionStorage.getItem(storageKey):null;return key&&/^[a-f0-9-]{36}$/.test(key)?{key}:null}catch{return null}})
 const [busy,setBusy]=useState(false),[unknown,setUnknown]=useState(!!restored),[error,setError]=useState(''),[valid,setValid]=useState(true)
 const [completion,setCompletion]=useState<{kind:'saved';value:T}|{kind:'found';value:BioLookup}|null>(null)
 const pending=useRef<{key:string}|null>(restored),request=useRef<AbortController|null>(null),live=useRef(true),callbacks=useRef({saved,found});useLayoutEffect(()=>{callbacks.current={saved,found}},[saved,found])
 const forget=useCallback(()=>{pending.current=null;try{if(storageKey)sessionStorage.removeItem(storageKey)}catch{/* Request identity remains guarded in memory if browser storage is unavailable. */}},[storageKey])
 useEffect(()=>{live.current=true;return()=>{live.current=false;request.current?.abort();pending.current=null}},[project])
 useEffect(()=>onApiSessionChanged(()=>{request.current?.abort();forget();setValid(false);setUnknown(false);setCompletion(null);setError('项目不存在或无权访问。')}),[forget])
 useEffect(()=>{if(!completion||!valid)return;if(completion.kind==='saved')callbacks.current.saved(completion.value);else callbacks.current.found(completion.value);queueMicrotask(()=>{if(live.current)setCompletion(null)})},[completion,valid])
 async function submit(url:string,body:unknown){if(request.current||pending.current||!valid)return;const c=new AbortController();request.current=c;pending.current={key:crypto.randomUUID()};try{if(storageKey)sessionStorage.setItem(storageKey,pending.current.key)}catch{}setBusy(true);setError('');try{const value=await bioRequest<T>(url,{...jsonRequest(body,pending.current.key),signal:c.signal});if(live.current&&!c.signal.aborted){forget();setUnknown(false);setCompletion({kind:'saved',value})}}catch(cause){if(live.current&&!c.signal.aborted){const definite=cause instanceof IntakeError&&cause.status<500;if(definite)forget();setUnknown(!definite);setError(cause instanceof IntakeError&&cause.status===409?'版本已更新；草稿已保留，请重新读取最新版本后核对。':safeError(cause,'提交结果待核对，请使用原请求身份查询。'))}}finally{if(request.current===c)request.current=null;if(live.current)setBusy(false)}}
 async function lookup(){if(!pending.current||request.current||!valid)return;const c=new AbortController();request.current=c;setBusy(true);setError('');try{const value=await bioRequest<BioLookup>(`${projectBase(project)}/bio-requests/${encodeURIComponent(pending.current.key)}?kind=${kind}`,{signal:c.signal});if(live.current&&!c.signal.aborted){if(value.kind!==kind||!value.id||!['run','confirmation'].includes(kind)&&!value.root_id)throw Error('format');forget();setUnknown(false);setCompletion({kind:'found',value})}}catch(cause){if(live.current&&!c.signal.aborted)setError(safeError(cause,'原请求结果尚未核实；请继续核对，不重新提交。'))}finally{if(request.current===c)request.current=null;if(live.current)setBusy(false)}}
 return {busy,unknown,error,valid,completed:!!completion,submit,lookup}
}
