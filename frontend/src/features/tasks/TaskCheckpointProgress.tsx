import {useEffect,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import {validId} from '../projects/projectNavigation'
import {deliveryHref,deliveryStageLabels} from '../research-intake/deliveryPackageContracts'
import {taskRequest} from './taskApi'
import {useDocumentVisible} from './useDocumentVisible'
type Stage={stage:string;started_at:string;ended_at:string|null;elapsed_seconds:number}
type Progress={stage:string;completed_members?:number;total_members?:number;table_count?:number;figure_count?:number;stage_started_at:string;stage_ended_at:string|null;stage_elapsed_seconds:number;observed_at:string;stages:Stage[]}
type View={project_id:string;task_id:string;task_type:string;status:string;delivery_id?:string;snapshot_id?:string;progress:Progress|null}
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
const date=(v:unknown)=>typeof v==='string'&&Number.isFinite(Date.parse(v))
const elapsed=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)&&v>=0
function validView(v:unknown,project:string,task:string,type:string):v is View{
 if(!object(v)||v.project_id!==project||v.task_id!==task||v.task_type!==type||!['queued','running','failed','succeeded'].includes(String(v.status)))return false
 if(v.delivery_id!=null&&(typeof v.delivery_id!=='string'||!validId(v.delivery_id)))return false
 if(v.snapshot_id!=null&&(typeof v.snapshot_id!=='string'||!validId(v.snapshot_id)||!v.delivery_id))return false
 const p=v.progress;if(p===null)return true
 return object(p)&&typeof p.stage==='string'&&date(p.stage_started_at)&&(p.stage_ended_at===null||date(p.stage_ended_at))&&elapsed(p.stage_elapsed_seconds)&&date(p.observed_at)&&Array.isArray(p.stages)&&p.stages.every(s=>object(s)&&typeof s.stage==='string'&&date(s.started_at)&&(s.ended_at===null||date(s.ended_at))&&elapsed(s.elapsed_seconds))&&['completed_members','total_members','table_count','figure_count'].every(k=>p[k]===undefined||typeof p[k]==='number'&&Number.isSafeInteger(p[k])&&p[k]>=0)
}
export default function TaskCheckpointProgress({projectId,taskId,taskType,active}:{projectId:string;taskId:string;taskType:'research_report'|'delivery_package';active:boolean}){
 const{t}=useI18n(),visible=useDocumentVisible(),[data,setData]=useState<View|null>(null),[error,setError]=useState(''),[valid,setValid]=useState(true),[attempt,setAttempt]=useState(0)
 useEffect(()=>onApiSessionChanged(()=>{setValid(false);setData(null)}),[])
 useEffect(()=>{if(!active||!visible||!valid)return;const c=new AbortController();let live=true,timer=0;async function read(){try{const result=await taskRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/progress`,c,(v):v is View=>validView(v,projectId,taskId,taskType),'任务阶段读取失败，请重试。');if(live&&!c.signal.aborted){setData(result);setError('');if(['queued','running'].includes(result.status))timer=window.setTimeout(()=>void read(),3000)}}catch(e){if(live&&!c.signal.aborted)setError(safeError(e,'任务阶段读取失败，请重试。'))}}void read();return()=>{live=false;c.abort();window.clearTimeout(timer)}},[projectId,taskId,taskType,active,visible,valid,attempt])
 if(!active||!valid)return null
 const current=data?.project_id===projectId&&data.task_id===taskId&&data.task_type===taskType?data:null
 const p=current?.progress
 return <section aria-label={t('真实处理阶段')}><h4>{t('真实处理阶段')}</h4>{error&&<p role="alert">{t(error)}</p>}{error&&<button type="button" onClick={()=>setAttempt(v=>v+1)}>{t('重新读取阶段')}</button>}
  {p?<><p role="status"><strong>{t(deliveryStageLabels[p.stage]??p.stage)}</strong> · {t('此阶段已记录耗时')} {p.stage_elapsed_seconds.toFixed(1)} s</p>{p.stage==='source_verification'&&p.total_members!==undefined&&<p>{p.completed_members??'—'} / {p.total_members} {t('所选成员')}</p>}{taskType==='research_report'&&(p.table_count!==undefined||p.figure_count!==undefined)&&<p>{t('来源统计：{tables} 表 / {figures} 图',{tables:p.table_count??'—',figures:p.figure_count??'—'})}</p>}<section className="research-detail-block"><h5>{t('已记录阶段与耗时')}</h5><ol>{p.stages.map((s,i)=><li key={`${s.stage}:${i}`}>{t(deliveryStageLabels[s.stage]??s.stage)} · {s.started_at} → {s.ended_at??t('尚未结束')} · {s.elapsed_seconds.toFixed(1)} s</li>)}</ol><p>{t('观测时间')} {p.observed_at}</p></section></>:!error&&<p>{t('尚无阶段记录')}</p>}
  {current?.delivery_id&&current.snapshot_id&&<p><a href={deliveryHref(projectId,current.delivery_id,current.snapshot_id)}>{t('返回此固定交付快照')}</a></p>}
 </section>
}
