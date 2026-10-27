import {useEffect,useRef,useState} from 'react'
import {apiFetch,onApiSessionChanged} from '../../shared/api/client'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {isAdminRuntime,isPublicRuntime,type AdminRuntime,type PublicRuntime} from './runtimeTypes'

const noop=()=>{}
// Public observations deliberately do not depend on or revoke an API session.
export default function useRuntimeStatus(admin:boolean,active=true,onForbidden:()=>void=noop){
 const visible=useDocumentVisible()
 const [data,setData]=useState<AdminRuntime|PublicRuntime|null>(null),[error,setError]=useState(false),[forbidden,setForbidden]=useState(false),[valid,setValid]=useState(true),[receivedAt,setReceivedAt]=useState<number|null>(null)
 const [now,setNow]=useState(()=>Date.now()),[clockCurrent,setClockCurrent]=useState(true)
 const current=useRef<{controller:AbortController;deadline:number}|null>(null)
 useEffect(()=>{
  if(!admin)return
  return onApiSessionChanged(()=>{current.current?.controller.abort();setValid(false);setData(null);setReceivedAt(null)})
 },[admin])
 useEffect(()=>{
  if(!active||!visible||!valid||forbidden)return
  let disposed=false
  function finish(request:NonNullable<typeof current.current>){window.clearTimeout(request.deadline);if(current.current===request)current.current=null}
  async function read(){
   if(current.current||disposed)return
   const request={controller:new AbortController(),deadline:0};current.current=request
   request.deadline=window.setTimeout(()=>{
    if(current.current!==request)return
    request.controller.abort();finish(request);setError(true)
   },10_000)
   try{
    const path=admin?'/api/v1/admin/runtime/status':'/api/v1/runtime/status'
    const init={signal:request.controller.signal,cache:'no-store' as const,credentials:'same-origin' as const}
    const response=await (admin?apiFetch(path,init):fetch(path,init))
    if(disposed||request.controller.signal.aborted||current.current!==request)return
    if(admin&&response.status===403){setData(null);setReceivedAt(null);setForbidden(true);onForbidden();return}
    if(!response.ok)throw new Error('runtime_read')
    const text=await response.text()
    if(disposed||request.controller.signal.aborted||current.current!==request)return
    if(text.length>65536)throw new Error('runtime_shape')
    const value:unknown=JSON.parse(text)
    if(!(admin?isAdminRuntime(value):isPublicRuntime(value)))throw new Error('runtime_shape')
    const sampledNow=Date.now()
    setData(value as AdminRuntime|PublicRuntime);setReceivedAt(sampledNow);setNow(sampledNow);setClockCurrent(true);setError(false)
   }catch{
    if(!disposed&&!request.controller.signal.aborted&&current.current===request)setError(true)
   }finally{finish(request)}
  }
  void read()
  const polling=window.setInterval(()=>void read(),15_000)
  // Freshness changes even when a network/body read never finishes.
  const clock=window.setInterval(()=>{setNow(Date.now());setClockCurrent(true)},1_000)
  // Retain the last sample, but do not reuse a paused clock on resume.
  return()=>{disposed=true;setClockCurrent(false);window.clearInterval(polling);window.clearInterval(clock);const request=current.current;if(request){request.controller.abort();finish(request)}}
 },[active,admin,visible,valid,forbidden,onForbidden])
 return {data,error,forbidden,valid,receivedAt,now,clockCurrent}
}
