import {getApiUserId} from '../../shared/api/client'
import {useState} from 'react'
import {projectBase} from './api'

export function hasPendingResult(projectId:string,kind:'figure'|'report',scope:string){
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
