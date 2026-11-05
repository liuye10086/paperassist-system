import {useEffect,useLayoutEffect,useRef,useState} from 'react'
import {getApiUserId,onApiSessionChanged} from '../../shared/api/client'
// A page reload first restores the authenticated owner before mounting drafts.
// Preserve that owner's saved work; subsequent logout/account transitions clear it.
let sessionEstablished=getApiUserId()!==null
onApiSessionChanged(()=>{
 const restoredOwner=!sessionEstablished?getApiUserId():null
 sessionEstablished=true
 try{for(const key of Object.keys(sessionStorage)){
  const match=/^paperassist\.research-(?:draft|request|publish)\.v1:([^:]+):/.exec(key)
  if(match&&match[1]!==restoredOwner)sessionStorage.removeItem(key)
 }}catch{}
})
export default function useResearchDraft<T>(project:string,scope:string,initial:()=>T){
 const key=`paperassist.research-draft.v1:${getApiUserId()??'anonymous'}:${project}:${scope}`
 const [value,setValue]=useState<T>(()=>{try{const raw=sessionStorage.getItem(key);if(raw)return JSON.parse(raw) as T}catch{}return initial()});const current=useRef(value),enabled=useRef(true),initializer=useRef(initial);useLayoutEffect(()=>{initializer.current=initial},[initial])
 useEffect(()=>onApiSessionChanged(()=>{enabled.current=false;try{sessionStorage.removeItem(key)}catch{}current.current=initializer.current();setValue(current.current)}),[key])
 // Persist before a caller can send a request; React may defer state updaters.
 function update(next:T|((old:T)=>T)){if(!enabled.current)return;const result=typeof next==='function'?(next as (old:T)=>T)(current.current):next;current.current=result;try{sessionStorage.setItem(key,JSON.stringify(result))}catch{}setValue(result)}
 return[value,update] as const
}
