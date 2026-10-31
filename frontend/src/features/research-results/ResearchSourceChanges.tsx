import {RESEARCH_LOADING_MESSAGE} from './api'
import {useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import {jsonRequest,projectBase,researchRequest} from './api'
import {selectionOnly} from './state'
import type {Source} from './contracts'
import {Notices} from './ResearchShared'
export default function ResearchSourceChanges({projectId,sources}:{projectId:string;sources:Source[]}){
 const{t}=useI18n(),[items,setItems]=useState<unknown[]>([]),[busy,setBusy]=useState(false),[valid,setValid]=useState(true),[error,setError]=useState(''),request=useRef<AbortController|null>(null),signature=JSON.stringify(sources)
 useEffect(()=>()=>request.current?.abort(),[projectId,signature])
 useEffect(()=>onApiSessionChanged(()=>{request.current?.abort();setValid(false);setItems([]);setError('')}),[])
 async function check(){if(request.current||!valid||!sources.length)return;const c=new AbortController();request.current=c;setBusy(true);setError('');try{const result=await researchRequest<{items:unknown[]}>(`${projectBase(projectId)}/research-results/source-changes`,{...jsonRequest({sources:sources.map(selectionOnly)}),signal:c.signal});if(!c.signal.aborted)setItems(result.items)}catch(cause){if(!c.signal.aborted)setError(safeError(cause,'来源变化查询失败。'))}finally{if(request.current===c)request.current=null;if(!c.signal.aborted)setBusy(false)}}
 return <section><button type="button" disabled={!valid||busy||!sources.length} onClick={()=>void check()}>{t('检查固定来源更新与影响')}</button>{busy&&<p role="status">{t(RESEARCH_LOADING_MESSAGE)}</p>}{error&&<p role="alert">{t(error)}</p>}<Notices title="固定来源更新提示（不会自动替换）" items={items}/></section>
}
