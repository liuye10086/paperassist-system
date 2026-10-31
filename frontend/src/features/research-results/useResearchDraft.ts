import {useEffect,useLayoutEffect,useRef,useState} from 'react'
import {getApiUserId,onApiSessionChanged} from '../../shared/api/client'
// Research drafts and frozen pending intents are scoped by owner, but are also
// removed on a session transition so a later restoration cannot expose old content.
onApiSessionChanged(()=>{try{for(const key of Object.keys(sessionStorage))if(/^paperassist\.research-(draft|request|publish)\.v1:/.test(key))sessionStorage.removeItem(key)}catch{}})
export default function useResearchDraft<T>(project:string,scope:string,initial:()=>T){
 const key=`paperassist.research-draft.v1:${getApiUserId()??'anonymous'}:${project}:${scope}`
 const [value,setValue]=useState<T>(()=>{try{const raw=sessionStorage.getItem(key);if(raw)return JSON.parse(raw) as T}catch{}return initial()});const enabled=useRef(true),initializer=useRef(initial);useLayoutEffect(()=>{initializer.current=initial},[initial])
 useEffect(()=>onApiSessionChanged(()=>{enabled.current=false;try{sessionStorage.removeItem(key)}catch{}setValue(initializer.current())}),[key])
 function update(next:T|((old:T)=>T)){if(!enabled.current)return;setValue(old=>{const result=typeof next==='function'?(next as (old:T)=>T)(old):next;try{sessionStorage.setItem(key,JSON.stringify(result))}catch{}return result})}
 return[value,update] as const
}
