import {useEffect,useRef,useState} from 'react'
import {useI18n,safeError} from '../../shared/i18n'
import {onApiSessionChanged} from '../../shared/api/client'
import {taskRequest} from '../tasks/taskApi'
import {useAnalysisWritingTransfer} from './analysisWritingTransfer'
import {manuscriptBase,validAnalysisSelection,type AnalysisSelection} from './manuscriptTypes'

type Options={figures:{id:string;title:string}[];reports:{id:string;figure_id:string;filename:string}[]}
const validOptions=(v:unknown):v is Options=>!!v&&typeof v==='object'&&'figures'in v&&Array.isArray(v.figures)&&v.figures.every(f=>f&&typeof f.id==='string'&&typeof f.title==='string')&&'reports'in v&&Array.isArray(v.reports)&&v.reports.every(r=>r&&typeof r.id==='string'&&typeof r.figure_id==='string'&&typeof r.filename==='string')
export default function SendAnalysisToWriting({fileId,runId,figureId,reportId,disabled=false}:{fileId:string;runId:string;figureId?:string;reportId?:string;disabled?:boolean}){
 const transfer=useAnalysisWritingTransfer(),{t}=useI18n()
 const [options,setOptions]=useState<Options|null>(null),[figure,setFigure]=useState(figureId??''),[report,setReport]=useState(reportId??''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[session,setSession]=useState(true)
 const active=useRef<AbortController|null>(null)
 useEffect(()=>{const stop=onApiSessionChanged(()=>{active.current?.abort();setSession(false);setOptions(null)});return()=>{active.current?.abort();stop()}},[])
 if(!transfer)return null
 const base=manuscriptBase(transfer.projectId)
 async function perform(send:boolean){
  if(active.current||!transfer||!session)return
  const controller=new AbortController();active.current=controller;setBusy(true);setError('')
  try{
   if(!send){const value=await taskRequest(`${base}/analysis-options?file_id=${encodeURIComponent(fileId)}&analysis_run_id=${encodeURIComponent(runId)}`,controller,validOptions,'图表与报告请求失败，请重新读取后重试。');if(!controller.signal.aborted)setOptions(value)}
   else{const payload={file_id:fileId,analysis_run_id:runId,...(figure?{figure_id:figure}:{}),...(report?{report_id:report}:{})};const value=await taskRequest(`${base}/analysis-selection`,controller,(v):v is AnalysisSelection=>validAnalysisSelection(v,transfer.projectId)&&v.analysis_run_id===runId&&v.file_id===fileId,'图表与报告请求失败，请重新读取后重试。',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!controller.signal.aborted)transfer.send(value)}
  }catch(cause){if(!controller.signal.aborted)setError(safeError(cause,'图表与报告请求失败，请重新读取后重试。'))}
  finally{if(active.current===controller)active.current=null;if(!controller.signal.aborted)setBusy(false)}
 }
 return <section aria-label={t('送入写作资料')}><p>{t('固定分析版本')} · {runId}</p>
 <button type="button" disabled={disabled||busy||!session} onClick={()=>void perform(false)}>{t('选择写作资料')}</button>
 {options&&<><label>{t('附带已保存图表')}<select value={figure} disabled={busy||!!figureId} onChange={e=>{setFigure(e.target.value);setReport('')}}><option value="">{t('不附带图表')}</option>{options.figures.map(f=><option key={f.id} value={f.id}>{f.title} · {f.id}</option>)}</select></label><label>{t('附带已保存分析报告')}<select value={report} disabled={busy||!!reportId} onChange={e=>{setReport(e.target.value);const saved=options.reports.find(r=>r.id===e.target.value);if(saved)setFigure(saved.figure_id)}}><option value="">{t('不附带报告')}</option>{options.reports.filter(r=>!figureId||r.figure_id===figureId).map(r=><option key={r.id} value={r.id}>{r.filename}</option>)}</select></label>
 <p>{t('接收只合并资料；保留原草稿，预览和保存由你操作。')}</p><button type="button" disabled={disabled||busy||!session} onClick={()=>void perform(true)}>{t(transfer.projectType==='thesis'?'送入毕业论文写作':'送入SCI写作')}</button></>}
 {error&&<p role="alert">{t(error)}</p>}</section>
}
