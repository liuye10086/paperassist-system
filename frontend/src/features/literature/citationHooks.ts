import {useEffect,useRef,useState} from 'react'
import {TaskRequestError,taskRequest} from '../tasks/taskApi'
export function useCitationResource<T>(url:string|null,guard:(v:unknown)=>v is T,refresh:number,onDenied:()=>void,onLoaded?:(data:T)=>void){
 const key=JSON.stringify([url,refresh]),callbacks=useRef({guard,onDenied,onLoaded});useEffect(()=>{callbacks.current={guard,onDenied,onLoaded}})
 const [state,setState]=useState<{key:string;url:string|null;data:T|null;error:string}>({key:'',url:null,data:null,error:''})
 useEffect(()=>{if(!url)return;const controller=new AbortController();let alive=true
 void taskRequest(url,controller,v=>callbacks.current.guard(v),'引用资料读取失败，请刷新重试。').then(data=>{if(alive){setState({key,url,data,error:''});callbacks.current.onLoaded?.(data)}}).catch(cause=>{if(alive){if(cause instanceof TaskRequestError&&[403,404].includes(cause.status))callbacks.current.onDenied();setState({key,url,data:null,error:'引用资料读取失败，请刷新重试。'})}})
 return()=>{alive=false;controller.abort()}
 },[url,key,refresh])
 return state.key===key?{...state,loading:false}:{data:state.url===url?state.data:null,error:'',loading:!!url}
}
export function useCitationMutation(onDenied:()=>void){
 const [busy,setBusy]=useState(false),[error,setError]=useState('');const active=useRef<AbortController|null>(null),alive=useRef(true),keys=useRef(new Map<string,string>())
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;active.current?.abort()}},[])
 async function post<T>(url:string,body:unknown,guard:(v:unknown)=>v is T){if(active.current)return null;const signature=JSON.stringify([url,body]);if(!keys.current.has(signature))keys.current.set(signature,crypto.randomUUID());const controller=new AbortController();active.current=controller;setBusy(true);setError('')
 try{const result=await taskRequest(url,controller,guard,'保存未确认，请刷新记录后重试。',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':keys.current.get(signature)!},body:JSON.stringify(body)});return alive.current&&!controller.signal.aborted?result:null}
 catch(cause){if(alive.current){if(cause instanceof TaskRequestError&&[403,404].includes(cause.status))onDenied();setError(cause instanceof TaskRequestError&&cause.status===409?'来源或版本已变化，请刷新并重新核对后保存。':'保存未确认，请刷新记录后重试。')}return null}
 finally{if(active.current===controller)active.current=null;if(alive.current)setBusy(false)}
 }
 return {post,busy,error,setError}
}
