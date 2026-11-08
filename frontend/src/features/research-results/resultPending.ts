import {getApiUserId} from '../../shared/api/client'
import {useState} from 'react'
import {projectBase} from './api'

export function pendingNewReportScope(projectId:string):string|null{
 const prefix=`paperassist.research-request.v1:${getApiUserId()??'anonymous'}:${projectId}:report:`
 try{for(const key of Object.keys(sessionStorage)){if(!key.startsWith(prefix))continue;const scope=key.slice(prefix.length);if((scope==='new'||scope.startsWith('new:'))&&exactPending(projectId,'report',scope))return scope}}catch{}
 return null
}

export function hasPendingResult(projectId:string,kind:'figure'|'report',scope:string){
 return kind==='report'&&scope==='new'?!!pendingNewReportScope(projectId):exactPending(projectId,kind,scope)
}
function exactPending(projectId:string,kind:'figure'|'report',scope:string){
 try{
  const raw=sessionStorage.getItem(`paperassist.research-request.v1:${getApiUserId()??'anonymous'}:${projectId}:${kind}:${scope}`)
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
