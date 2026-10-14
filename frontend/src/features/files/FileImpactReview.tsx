import {useCallback,useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import {statusNames,taskNames} from '../tasks/taskTypes'
import {isAssessment,isImpactTask,isPage,lifecycleBase,lifecycleCounts,lifecycleRequest,reasonLabels,type Assessment,type ImpactTask,type Page} from './fileLifecycleApi'
export const retentionText='本操作保留原件、历史版本和备份，不会物理删除或隐藏文件。历史成果的实际可用性需分别核验。'
const sourceLabels={frozen_source:'使用当时冻结的来源版本',newer_attempt_available:'有更新的尝试，尚不代表已发布成功版本',newer_published_version:'有更新的已发布版本',integrity_unknown:'来源完整性无法确认'}
export function AssessmentFacts({value}:{value:Assessment}){const {t,locale}=useI18n();return <><p className="file-retention">{t(retentionText)}</p><p>{t('影响范围：全文件保守评估，不预测所选 OCR 页的替换关系。')}</p><p>{t(value.original_available?'本次已核验原件可读取。':'本次原件不可用，保留策略不代表原件已恢复。')}</p><ul>{value.reasons.map(r=><li key={r.code}>{t(reasonLabels[r.code])}</li>)}</ul><dl className="file-reference-counts">{Object.entries(lifecycleCounts).map(([key,label])=><div key={key}><dt>{t(label)}</dt><dd>{value.counts[key as keyof typeof lifecycleCounts].toLocaleString(locale)}</dd></div>)}</dl></>}
function Review({projectId,fileId,action,operation,observedVersion,onUnavailable,onCancel,onConfirm,confirmDisabled=false}:{projectId:string;fileId:string;action:'delete'|'reparse';operation:string;observedVersion?:number;onUnavailable:()=>void;onCancel:()=>void;onConfirm:(value:Assessment)=>void;confirmDisabled?:boolean}){
 const {t,locale}=useI18n(),[assessment,setAssessment]=useState<Assessment|null>(null),[tasks,setTasks]=useState<Page<ImpactTask>|null>(null),[page,setPage]=useState(1),[refresh,setRefresh]=useState(0),[error,setError]=useState(''),[taskError,setTaskError]=useState(''),[loading,setLoading]=useState(true),[tasksLoading,setTasksLoading]=useState(true),[valid,setValid]=useState(true)
 const base=lifecycleBase(projectId,fileId),generation=useRef(0),unavailable=useRef(onUnavailable)
 useEffect(()=>{unavailable.current=onUnavailable},[onUnavailable])
 const lost=useCallback(()=>{generation.current++;setValid(false);setAssessment(null);setTasks(null);setError('');setTaskError('');unavailable.current()},[])
 useEffect(()=>onApiSessionChanged(()=>{generation.current++;setValid(false);setAssessment(null);setTasks(null);setError('');setTaskError('')}),[])
 useEffect(()=>{
  if(!valid)return
  const c=new AbortController(),captured=generation.current;let current=true
  // Invalidate a previous confirmation as the external assessment scope changes.
  // oxlint-disable-next-line react/set-state-in-effect
  setAssessment(null);setLoading(true);setError('')
  const timer=window.setTimeout(()=>c.abort(),15000)
  void lifecycleRequest(`${base}/assessment?action=${action}`,c.signal,lost,(v):v is Assessment=>isAssessment(v,fileId,action)).then(v=>{if(current&&captured===generation.current&&!c.signal.aborted)setAssessment(v)}).catch(cause=>{if(current&&captured===generation.current)setError(safeError(cause,'影响读取失败或超时，请重新读取。'))}).finally(()=>{window.clearTimeout(timer);if(current&&captured===generation.current)setLoading(false)})
  return()=>{current=false;c.abort();window.clearTimeout(timer)}
 },[base,fileId,action,refresh,observedVersion,valid,lost])
 useEffect(()=>{
  if(!valid)return
  const c=new AbortController(),captured=generation.current;let current=true
  // Keep visible task rows tied to the pending external page request.
  // oxlint-disable-next-line react/set-state-in-effect
  setTasks(null);setTaskError('');setTasksLoading(true);const timer=window.setTimeout(()=>c.abort(),15000)
  void lifecycleRequest(`${base}/tasks?page=${page}&page_size=10`,c.signal,lost,(v):v is Page<ImpactTask>=>isPage(v,page,isImpactTask,true)).then(v=>{if(current&&captured===generation.current&&!c.signal.aborted)setTasks(v)}).catch(cause=>{if(current&&captured===generation.current)setTaskError(safeError(cause,'受影响任务读取失败或超时，请重新读取。'))}).finally(()=>{window.clearTimeout(timer);if(current&&captured===generation.current)setTasksLoading(false)})
  return()=>{current=false;c.abort();window.clearTimeout(timer)}
 },[base,page,refresh,observedVersion,valid,lost])
 const canConfirm=valid&&!!assessment&&!loading&&!tasksLoading&&!!tasks&&!taskError&&!confirmDisabled&&(action==='delete'||assessment.can_reparse)
 return <section className="file-impact-review" role="dialog" aria-modal="false" aria-label={t(action==='delete'?'删除申请影响确认':'重解析影响确认')}><h4>{t(action==='delete'?'删除申请影响确认':'重解析影响确认')}</h4><p>{t('本次操作：{operation}',{operation})}</p>
  {(loading||tasksLoading)&&<p role="status">{t('正在读取文件影响……')}</p>}{!valid&&<p role="alert">{t('文件访问或会话已改变，请重新选择文件。')}</p>}{error&&<p role="alert" className="error-panel">{t(error)}</p>}{taskError&&<p role="alert" className="error-panel">{t(taskError)}</p>}
  {assessment&&<AssessmentFacts value={assessment}/>}{assessment?.reparse_reason&&action==='reparse'&&<p className="warning-panel">{t(reasonLabels[assessment.reparse_reason])}</p>}
  <h5>{t('受影响任务')}</h5>{tasks&&<><p>{t('可显示任务共 {total} 条；无法验证的来源身份不会公开。',{total:tasks.total})}</p>{!tasks.items.length&&<p>{t('此页没有可显示的受影响任务。')}</p>}<ul className="lifecycle-tasks">{tasks.items.map(task=><li key={task.id}><strong>{t(taskNames[task.task_type])}</strong> · {t(statusNames[task.status])} · <time dateTime={task.created_at}>{new Date(task.created_at).toLocaleString(locale)}</time><p>{t(sourceLabels[task.source_status])}</p>{task.sources.map((s,i)=><p key={i}>{t(lifecycleCounts[s.kind])}{s.version!==null&&` · ${t('版本 v{version}',{version:s.version})}`}{s.sheet_index!==undefined&&` · ${t('工作表 {number}',{number:s.sheet_index+1})}`}</p>)}</li>)}</ul><nav aria-label={t('受影响任务分页')}><button disabled={page===1||tasksLoading} onClick={()=>setPage(p=>p-1)}>{t('上一页受影响任务')}</button><span>{t('第 {page} 页',{page})}</span><button disabled={page*10>=tasks.total||tasksLoading} onClick={()=>setPage(p=>p+1)}>{t('下一页受影响任务')}</button></nav></>}
  <div className="file-actions"><button disabled={loading||tasksLoading||!valid} onClick={()=>setRefresh(n=>n+1)}>{t('重新读取影响')}</button><button onClick={onCancel}>{t('取消')}</button><button className="button-primary" disabled={!canConfirm} onClick={()=>{if(assessment&&canConfirm)onConfirm(assessment)}}>{t(action==='delete'?'确认提交删除申请':'确认并开始重解析')}</button></div>
 </section>
}
export default function FileImpactReview(props:Parameters<typeof Review>[0]){return <Review key={JSON.stringify([props.projectId,props.fileId,props.action])} {...props}/>}
