import {getApiUserId} from '../../shared/api/client'
import {useState} from 'react'
import {projectBase} from './api'

export function pendingNewReportScope(projectId:string):string|null{
 try{for(const kind of ['report','report_narrative'] as const){const prefix=requestKey(projectId,kind,'');for(const key of Object.keys(sessionStorage)){if(!key.startsWith(prefix))continue;const scope=key.slice(prefix.length);if((scope==='new'||scope.startsWith('new:'))&&exactPending(projectId,kind,scope))return scope}}}catch{}
 return null
}

export function savedNewReportScope(projectId:string):string|null{
 const prefix=`paperassist.research-draft.v1:${getApiUserId()??'anonymous'}:${projectId}:report:`
 try{for(const key of Object.keys(sessionStorage)){if(!key.startsWith(prefix))continue;const scope=key.slice(prefix.length);if((scope==='new'||scope.startsWith('new:'))&&JSON.parse(sessionStorage.getItem(key)??'null')?.reader?.id)return scope}}catch{}
 return null
}

export function hasPendingResult(projectId:string,kind:'figure'|'report',scope:string){
 if(kind==='report'&&scope==='new')return !!pendingNewReportScope(projectId)
 return exactPending(projectId,kind,scope)||kind==='report'&&hasPendingReportNarrative(projectId,scope)
}
export function hasPendingReportNarrative(projectId:string,scope:string){return exactPending(projectId,'report_narrative',scope)}
function requestKey(projectId:string,kind:'figure'|'report'|'report_narrative',scope:string){
 return `paperassist.research-request.v1:${getApiUserId()??'anonymous'}:${projectId}:${kind}:${scope}`
}
function exactPending(projectId:string,kind:'figure'|'report'|'report_narrative',scope:string){
 try{
  const raw=sessionStorage.getItem(requestKey(projectId,kind,scope))
  const pending=raw?JSON.parse(raw):null
  return !!pending?.key&&typeof pending.url==='string'&&pending.url.startsWith(projectBase(projectId)+'/')
 }catch{return false}
}

// Switching modules must not replace the editor that owns an unresolved request.
export function useResultSelection(projectId:string,kind:'figure'|'report',incoming:string,active:boolean){
 const [selected,setSelected]=useState(incoming)
 if(active&&incoming!==selected&&!hasPendingResult(projectId,kind,selected||'new'))setSelected(incoming)
 return selected
}
