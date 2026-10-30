import {useEffect,useLayoutEffect,useRef,useState} from 'react'
import {apiFetch,onApiSessionChanged} from '../../shared/api/client'
import {safeError} from '../../shared/i18n'
import {bioRequest} from './api'
export function useBioRead<T>(url:string,poll?:(v:T)=>boolean){
 const [state,setState]=useState<{url:string;revision:number;value:T|null;error:string}>({url:'',revision:0,value:null,error:''}),[revision,setRevision]=useState(0),[valid,setValid]=useState(true),pollRef=useRef(poll)
 useLayoutEffect(()=>{pollRef.current=poll},[poll])
 useEffect(()=>onApiSessionChanged(()=>{setValid(false);setState({url:'',revision:0,value:null,error:'项目不存在或无权访问。'})}),[])
 useEffect(()=>{if(!url||!valid)return;const c=new AbortController();let live=true,timer=0;async function load(){try{const value=await bioRequest<T>(url,{signal:c.signal});if(live&&!c.signal.aborted){setState({url,revision,value,error:''});if(pollRef.current?.(value))timer=window.setTimeout(()=>void load(),3000)}}catch(cause){if(live&&!c.signal.aborted)setState(previous=>({url,revision,value:previous.url===url?previous.value:null,error:safeError(cause,'空间分析读取失败，请重试。')}))}}void load();return()=>{live=false;c.abort();window.clearTimeout(timer)}},[url,revision,valid])
 const current=state.url===url&&state.revision===revision
 return {value:valid&&state.url===url?state.value:null,error:!valid?'项目不存在或无权访问。':current?state.error:'',valid,reload:()=>setRevision(v=>v+1)}
}
export function useBioImage(url:string){const [state,setState]=useState({url:'',image:''});useEffect(()=>{if(!url)return;const c=new AbortController();let objectUrl='',live=true;void apiFetch(url,{signal:c.signal}).then(async r=>{if(!r.ok)throw Error('image');const blob=await r.blob();if(live&&!c.signal.aborted){objectUrl=URL.createObjectURL(blob);setState({url,image:objectUrl})}}).catch(()=>{});const stop=onApiSessionChanged(()=>{c.abort();setState({url:'',image:''});if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl=''}});return()=>{live=false;c.abort();stop();if(objectUrl)URL.revokeObjectURL(objectUrl)}},[url]);return state.url===url?state.image:''}
export function useBioText(url:string){const [state,setState]=useState({url:'',text:'',error:''});useEffect(()=>{if(!url)return;const c=new AbortController();let live=true;void apiFetch(url,{signal:c.signal}).then(async r=>{if(!r.ok)throw Error('text');const text=await r.text();if(live&&!c.signal.aborted)setState({url,text,error:''})}).catch(()=>{if(live&&!c.signal.aborted)setState({url,text:'',error:'方法预览读取失败，可通过下载清单重试。'})});const stop=onApiSessionChanged(()=>{c.abort();setState({url:'',text:'',error:''})});return()=>{live=false;c.abort();stop()}},[url]);return state.url===url?state:{url,text:'',error:''}}
