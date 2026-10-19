import {useCallback,useEffect,useRef,useState} from 'react'
import {safeError} from '../../shared/i18n'
import {TaskRequestError} from '../tasks/taskApi'
import {literatureRequest} from './literatureApi'
export function useEvidenceResource<T>(url:string|null,guard:(value:unknown)=>value is T,revision:number,onDenied:()=>void){
 const key=JSON.stringify([url,revision]);const callbacks=useRef({guard,onDenied});useEffect(()=>{callbacks.current={guard,onDenied}})
 const [state,setState]=useState<{key:string;data:T|null;error:string}>({key:'',data:null,error:''})
 useEffect(()=>{if(!url)return;let active=true;const controller=new AbortController()
 void literatureRequest(url,controller,v=>callbacks.current.guard(v)).then(data=>{if(active)setState({key,data,error:''})}).catch(cause=>{if(active){if(cause instanceof TaskRequestError&&cause.status===403)callbacks.current.onDenied();setState({key,data:null,error:safeError(cause,'证据资料读取失败，请重试。')})}})
 return()=>{active=false;controller.abort()}
 },[url,key,revision])
 return state.key===key?{...state,loading:false}:{data:null,error:'',loading:!!url}
}
export function useEvidenceMutation(onDenied:()=>void){
 const [busy,setBusy]=useState(false),[error,setError]=useState('');const controller=useRef<AbortController|null>(null);const alive=useRef(true);const keys=useRef(new Map<string,string>())
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;controller.current?.abort()}},[])
 const post=useCallback(async<T,>(url:string,body:unknown,guard:(value:unknown)=>value is T):Promise<T|null>=>{
 if(controller.current)return null
 const signature=JSON.stringify([url,body]);let key=keys.current.get(signature);if(!key){key=crypto.randomUUID();keys.current.set(signature,key)}
 const request=new AbortController();controller.current=request;setBusy(true);setError('')
 try{const result=await literatureRequest(url,request,guard,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)});return alive.current&&!request.signal.aborted?result:null}
 catch(cause){if(alive.current){if(cause instanceof TaskRequestError&&cause.status===403)onDenied();setError(cause instanceof TaskRequestError&&cause.status===409?'记录已变化或本轮补搜已使用，请刷新并核对。':'保存结果未确认，请刷新记录；相同输入重试沿用请求标识。')}return null}
 finally{controller.current=null;if(alive.current)setBusy(false)}
 },[onDenied])
 return {post,busy,error,setError}
}
