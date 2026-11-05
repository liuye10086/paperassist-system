import useManuscriptPendingRequest,{type ManuscriptRequestScope} from './useManuscriptPendingRequest'
import {useManuscriptDraft} from './useManuscriptDraft'
import {useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError} from '../../shared/i18n'
import {taskRequest,TaskRequestError} from '../tasks/taskApi'
export function useWritingOperation(scope?:ManuscriptRequestScope){
 const pending=useManuscriptPendingRequest(scope)
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[valid,setValid]=useState(true)
 const [mutating,setMutating]=useState(false),[uncertain,setUncertain]=useState(false)
 useManuscriptDraft(uncertain||!!pending.pending,mutating)
 const alive=useRef(true),session=useRef(true),controller=useRef<AbortController|null>(null),keys=useRef(new Map<string,string>())
 useEffect(()=>{alive.current=true;const off=onApiSessionChanged(()=>{session.current=false;const previous=controller.current;controller.current=null;previous?.abort();keys.current.clear();setValid(false);setBusy(false);setMutating(false);setUncertain(false);setError('会话已失效，请重新登录。')});return()=>{off();alive.current=false;const previous=controller.current;controller.current=null;previous?.abort()}},[])
 async function run<T>(url:string,guard:(v:unknown)=>v is T,body?:unknown,timing?:{timeoutMs:110000}):Promise<T|null>{
  if(controller.current||!session.current||!alive.current)return null
  const signature=`${url}:${body===undefined?'GET':JSON.stringify(body)}`
  if(body!==undefined&&!keys.current.has(signature))keys.current.set(signature,crypto.randomUUID())
  const ticket=body!==undefined&&scope?pending.begin(url,body,keys.current.get(signature)):null
  if(ticket)keys.current.set(signature,ticket.key)
  if(body!==undefined&&scope&&!ticket){setError('提交结果待核对，原请求与当前输入不一致。');return null}
  const request=new AbortController();controller.current=request;setBusy(true);setMutating(body!==undefined);setError('')
  try{const result=await taskRequest(url,request,guard,'请求未确认；请刷新核对。不会自动重试或重新调用。',body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':ticket?.key??keys.current.get(signature)!},body:ticket?.body??JSON.stringify(body)},timing?.timeoutMs);if(body!==undefined&&controller.current===request){setUncertain(false);if(scope)pending.complete()};return controller.current===request&&alive.current&&session.current&&!request.signal.aborted?result:null}
  catch(cause){if(body!==undefined&&controller.current===request){const rejected=cause instanceof TaskRequestError&&cause.status>=400&&cause.status<500&&cause.status!==408&&cause.status!==409;setUncertain(!rejected);if(scope){if(rejected)pending.complete();else pending.unknown()}};if(controller.current===request&&alive.current&&session.current)setError(safeError(cause,'请求未确认；请刷新核对。不会自动重试或重新调用。'));return null}
  finally{if(controller.current===request){controller.current=null;if(alive.current&&session.current){setBusy(false);setMutating(false)}}}
 }
 return {run,busy,error,valid,setError,pending:pending.pending,resolvePending:()=>{pending.complete();setUncertain(false)}}
}
