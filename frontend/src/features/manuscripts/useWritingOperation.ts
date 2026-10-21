import {useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError} from '../../shared/i18n'
import {taskRequest} from '../tasks/taskApi'
export function useWritingOperation(){
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[valid,setValid]=useState(true)
 const alive=useRef(true),session=useRef(true),controller=useRef<AbortController|null>(null),keys=useRef(new Map<string,string>())
 useEffect(()=>{alive.current=true;const off=onApiSessionChanged(()=>{session.current=false;const previous=controller.current;controller.current=null;previous?.abort();keys.current.clear();setValid(false);setBusy(false);setError('会话已失效，请重新登录。')});return()=>{off();alive.current=false;const previous=controller.current;controller.current=null;previous?.abort()}},[])
 async function run<T>(url:string,guard:(v:unknown)=>v is T,body?:unknown):Promise<T|null>{
  if(controller.current||!session.current||!alive.current)return null
  const request=new AbortController();controller.current=request;setBusy(true);setError('')
  const signature=`${url}:${body===undefined?'GET':JSON.stringify(body)}`
  if(body!==undefined&&!keys.current.has(signature))keys.current.set(signature,crypto.randomUUID())
  try{const result=await taskRequest(url,request,guard,'请求未确认；请刷新核对。不会自动重试或重新调用。',body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':keys.current.get(signature)!},body:JSON.stringify(body)});return controller.current===request&&alive.current&&session.current&&!request.signal.aborted?result:null}
  catch(cause){if(controller.current===request&&alive.current&&session.current)setError(safeError(cause,'请求未确认；请刷新核对。不会自动重试或重新调用。'));return null}
  finally{if(controller.current===request){controller.current=null;if(alive.current&&session.current)setBusy(false)}}
 }
 return {run,busy,error,valid,setError}
}
