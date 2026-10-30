import {useEffect,useRef,useState} from 'react'
import {useI18n,safeError} from '../../shared/i18n'
import {onApiSessionChanged} from '../../shared/api/client'
import {taskRequest} from '../tasks/taskApi'
import {useAnalysisWritingTransfer} from './analysisWritingTransfer'
import {manuscriptBase,validAnalysisSelection,type AnalysisSelection} from './manuscriptTypes'

export default function SendCollectionReportToWriting({collectionId,versionId,reportId,disabled}:{collectionId:string;versionId:string;reportId:string;disabled:boolean}){
 const transfer=useAnalysisWritingTransfer(),{t}=useI18n(),[busy,setBusy]=useState(false),[error,setError]=useState(''),[session,setSession]=useState(true)
 const active=useRef<AbortController|null>(null)
 useEffect(()=>{const stop=onApiSessionChanged(()=>{active.current?.abort();setSession(false)});return()=>{active.current?.abort();stop()}},[])
 if(!transfer)return null
 async function send(){if(!transfer||active.current||!session)return;const c=new AbortController();active.current=c;setBusy(true);setError('')
  try{const value=await taskRequest(`${manuscriptBase(transfer.projectId)}/collection-report-selection`,c,(v):v is AnalysisSelection=>validAnalysisSelection(v,transfer.projectId)&&v.selection_kind==='collection_report'&&v.collection_id===collectionId&&v.collection_version_id===versionId&&v.report_id===reportId,'图表与报告请求失败，请重新读取后重试。',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({collection_id:collectionId,collection_version_id:versionId,report_id:reportId})});if(!c.signal.aborted)transfer.send(value)}
  catch(cause){if(!c.signal.aborted)setError(safeError(cause,'图表与报告请求失败，请重新读取后重试。'))}
  finally{if(active.current===c)active.current=null;if(!c.signal.aborted)setBusy(false)}
 }
 return <div><p>{t('固定汇总报告及全部分析与图注')} · {versionId}</p><button type="button" disabled={disabled||busy||!session} onClick={()=>void send()}>{t(transfer.projectType==='thesis'?'送入毕业论文写作':'送入SCI写作')}</button>{error&&<p role="alert">{t(error)}</p>}</div>
}
