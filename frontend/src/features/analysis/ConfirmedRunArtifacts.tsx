import {useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import FigureWorkbench from '../figure-workbench/FigureWorkbench'
import {workbenchRequest} from '../figure-workbench/api'
import {identifier,object,text} from '../figure-workbench/contracts'
import ReportCollections from '../report-collections/ReportCollections'
import {WorkflowStage} from './AnalysisWorkflow'
import {useWorkflowNavigation} from './analysisWorkflowContext'
import {isDatasetSource} from './datasetSource'
import SourceSummary from './SourceSummary'
import QualityProvenance from '../datasetPreparation/QualityProvenance'
import {validStatisticsContext} from './statisticsContext'
import type {Result} from './StatisticsResults'

type Props={base:string;current?:Result|null;disabled:boolean;onHistoricalSelection:(selected:boolean)=>void}
function validHistoricalResult(value:unknown,base:string):value is Result{
 if(!object(value)||!identifier(value.id)||!text(value.filename)||!text(value.completed_at)||!Number.isFinite(Date.parse(value.completed_at))||!Number.isSafeInteger(value.setup_revision)||!isDatasetSource(value.source)||value.source.kind!=='prepared_dataset_version'||value.source_sha256!==value.source.source_sha256||!object(value.selection)||value.selection.sheet_name!==value.source.sheet_name||!object(value.analysis_context)||!object(value.analysis_context.plan))return false
 return validStatisticsContext(value as Result,base)
}
const methodLabels:Record<string,string>={correlation:'相关分析',group_comparison:'组间比较',regression:'回归分析',roc:'ROC 分析',survival:'生存分析'}

export default function ConfirmedRunArtifacts(props:Props){return <Artifacts key={props.base} {...props}/>}
function Artifacts({base,current,disabled,onHistoricalSelection}:Props){
 const {t,locale}=useI18n(),navigation=useWorkflowNavigation()
 const [items,setItems]=useState<Result[]|null>(null),[selectedId,setSelectedId]=useState<string|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),[session,setSession]=useState(true),[refresh,setRefresh]=useState(0)
 const active=useRef<AbortController|null>(null)
 const currentAvailable=current&&validHistoricalResult(current,base)?current:null
 const selected=selectedId===null?currentAvailable:items?.find(item=>item.id===selectedId)
 useEffect(()=>{const stop=onApiSessionChanged(()=>{active.current?.abort();setSession(false);setItems(null)});return()=>{active.current?.abort();stop()}},[])
 async function read(){
  if(active.current||!session)return
  const controller=new AbortController();active.current=controller;setLoading(true);setError('')
  try{
   const value=await workbenchRequest(`${base}/analysis-runs`,controller.signal,(v):v is {items:Result[]}=>object(v)&&Array.isArray(v.items)&&v.items.every(item=>validHistoricalResult(item,base))&&new Set(v.items.map(item=>item.id)).size===v.items.length)
   if(!controller.signal.aborted)setItems(value.items)
  }catch(cause){if(!controller.signal.aborted)setError(safeError(cause,'图表与报告请求失败，请重新读取后重试。'))}
  finally{if(active.current===controller)active.current=null;if(!controller.signal.aborted)setLoading(false)}
 }
 const options=items&&currentAvailable&&!items.some(item=>item.id===currentAvailable.id)?[currentAvailable,...items]:items
 return <div hidden={!!navigation&&!['figure','explanation','report'].includes(navigation.stage)}>
  <section className="statistics-results" aria-label={t('选择已确认结果')}>
   <button type="button" disabled={loading||disabled||!session} onClick={()=>void read()}>{t(items?'重新读取历史已确认结果':'查看历史已确认结果')}</button>
   <p className="muted">{t('仅列出已确认且来源完整的整理数据结果，可继续为历史结果补齐图表和解释。')}</p>
   {loading&&<p role="status">{t('正在读取历史已确认结果……')}</p>}
   {error&&<p role="alert" className="error-panel">{t(error)}</p>}
   {options&&session&&<label>{t('图表与报告所用结果')}<select disabled={loading||disabled} value={selectedId??currentAvailable?.id??''} onChange={event=>{const id=event.target.value;setSelectedId(id===currentAvailable?.id?null:id);onHistoricalSelection(!!id&&id!==currentAvailable?.id)}}>
    <option value="">{t('请选择已确认结果')}</option>
    {options.map(item=><option key={item.id} value={item.id}>{t(methodLabels[item.result_type??'']??'描述统计')} · {t('配置修订 {number}',{number:item.setup_revision})} · {item.source?.sheet_name} · {new Date(item.completed_at).toLocaleString(locale)} · {item.analysis_context?.plan.research_request?.output_language==='en'?'English':t('中文')}</option>)}
   </select></label>}
   {items?.length===0&&<p>{t('尚无来源完整的历史已确认结果。')}</p>}
   {selectedId&&!selected&&<p role="alert">{t('所选历史结果当前不可用，请重新读取；不会自动替换为最新结果。')}</p>}
   {selected&&session&&<><p>{t('所选结果的图表、解释与报告保持原来源和语言，不替换集合冻结引用。')}</p><SourceSummary source={selected.source} filename={selected.filename}/><QualityProvenance projectId={decodeURIComponent(base.split('/')[4])} source={selected.source}/></>}
  </section>
  {selected?.source&&session&&<>
   <div hidden={!!navigation&&!['figure','explanation'].includes(navigation.stage)}><FigureWorkbench base={base} runId={selected.id} source={selected.source} language={selected.analysis_context?.plan.research_request?.output_language??'zh-CN'} resultType={selected.result_type} mode={selected.result_type==='correlation'?selected.selection.mode:selected.result_type==='group_comparison'?selected.selection.design:undefined} disabled={disabled} onChanged={()=>setRefresh(n=>n+1)}/></div>
   <WorkflowStage stage="report"><ReportCollections currentRunId={selected.id} projectId={decodeURIComponent(base.split('/')[4])} fileId={selected.source.file_id} source={selected.source} language={selected.analysis_context?.plan.research_request?.output_language??'zh-CN'} refreshKey={refresh} disabled={disabled}/></WorkflowStage>
  </>}
 </div>
}
