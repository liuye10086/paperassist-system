import {STANDARD_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import {useEffect,useState} from 'react'
import {apiFetch,onApiSessionChanged} from '../../shared/api/client'
import {useI18n} from '../../shared/i18n'
export default function ManuscriptImage({url,title,timeoutMs=STANDARD_REQUEST_TIMEOUT_MS}:{url:string;title:string;timeoutMs?:number}){
 const {t}=useI18n();const [src,setSrc]=useState(''),[error,setError]=useState(false),[attempt,setAttempt]=useState(0),[valid,setValid]=useState(true)
 useEffect(()=>{if(!valid)return;const controller=new AbortController();let active=true,objectUrl=''
 const stop=onApiSessionChanged(()=>{controller.abort();setSrc('');setValid(false);if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl=''}})
 const timer=window.setTimeout(()=>{controller.abort();if(active)setError(true)},timeoutMs)
 void apiFetch(url,{signal:controller.signal}).then(async response=>{if(!response.ok)throw new Error('image');const blob=await response.blob();if(!active||controller.signal.aborted)return;if(!['image/png','image/jpeg'].includes(blob.type))throw new Error('image');objectUrl=URL.createObjectURL(blob);setSrc(objectUrl)}).catch(()=>{if(active&&!controller.signal.aborted)setError(true)}).finally(()=>window.clearTimeout(timer))
 return()=>{active=false;controller.abort();window.clearTimeout(timer);stop();if(objectUrl)URL.revokeObjectURL(objectUrl)}
 },[url,attempt,valid,timeoutMs])
 return <>{valid&&!src&&!error&&<p role="status">{t(timeoutMs>STANDARD_REQUEST_TIMEOUT_MS?'正在核验固定来源，大文件可能需要数分钟。':'正在读取图片，大文件可能需要数分钟。')}</p>}{src&&<img src={src} alt={title}/>} {error&&<div><p role="alert">{t('图片读取失败，请重新读取图片。')}</p><button type="button" onClick={()=>{setSrc('');setError(false);setAttempt(a=>a+1)}}>{t('重新读取图片')}</button></div>}</>
}
