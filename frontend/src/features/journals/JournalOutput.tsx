import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {useEffect,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import {taskRequest,TaskRequestError} from '../tasks/taskApi'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import ManuscriptPreview from '../manuscripts/ManuscriptPreview'
import ManuscriptExports from '../manuscripts/ManuscriptExports'
import {manuscriptBase,validManuscriptVersion,type ManuscriptVersion} from '../manuscripts/manuscriptTypes'
import type {Adaptation} from './adaptationContracts'
export default function JournalOutput({projectId,adaptationId,output,active,onOpenTask,onUnavailable,registerLeaveGuard}:{projectId:string;adaptationId:string;output:NonNullable<Adaptation['result']>['output'];active:boolean;onOpenTask?:(id:string)=>void;onUnavailable:()=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const {t}=useI18n();const visible=useDocumentVisible(),[version,setVersion]=useState<ManuscriptVersion|null>(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0),[validSession,setValidSession]=useState(true)
 useEffect(()=>onApiSessionChanged(()=>{setValidSession(false);setVersion(null);setError('')}),[])
 useEffect(()=>{if(!active||!visible||!validSession)return;let current=true,timer=0;const controller=new AbortController()
 void taskRequest(`${manuscriptBase(projectId)}/${encodeURIComponent(output.manuscript_id)}/versions/${output.revision}`,controller,(v):v is ManuscriptVersion=>validManuscriptVersion(v,projectId,output.manuscript_id)&&v.id===output.version_id&&v.revision===output.revision&&v.task_id===output.task_id&&v.parent_version_id===output.parent_version_id&&v.snapshot.journal_adaptation_provenance?.adaptation_id===adaptationId,'固定新稿读取失败，请刷新。').then(v=>{if(current&&!controller.signal.aborted){setVersion(v);setError('');if(v.status==='pending')timer=window.setTimeout(()=>setAttempt(a=>a+1),3000)}}).catch(cause=>{if(current){if(cause instanceof TaskRequestError&&[401,403].includes(cause.status)){setVersion(null);setValidSession(false);onUnavailable()}else setError(safeError(cause,'固定新稿读取失败，请刷新。'))}})
 return()=>{current=false;controller.abort();window.clearTimeout(timer)}
 },[projectId,adaptationId,output.manuscript_id,output.version_id,output.revision,output.parent_version_id,output.task_id,active,visible,validSession,attempt,onUnavailable])
 return <section id={`journal-output-${adaptationId}`} aria-label={t("固定公共新稿与导出")}><h5>{t("固定公共新稿与导出")}</h5><p>{output.manuscript_id} {t("\u00b7 revision")} {output.revision} · {output.version_id}</p>{error&&<p role="alert">{t(error)}</p>}<button type="button" disabled={!validSession} onClick={()=>setAttempt(a=>a+1)}>{t("刷新固定新稿")}</button>{version?.status==='pending'&&<p role="status">{t("公共新稿待发布；DOCX/PDF 尚未生成。")}</p>}{version?.status==='failed'&&<><p role="alert">{t("公共新稿发布失败；格式适配结果已保留。请在公共发布任务中重试固定新稿。")}</p>{onOpenTask?<button type="button" onClick={()=>onOpenTask(output.task_id)}>{t("查看公共新稿发布任务")}</button>:<a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(output.task_id)}`}>{t("查看公共新稿发布任务")}</a>}</>}{version&&<><ManuscriptPreview snapshot={version.snapshot}/>{version.status==='published'&&<ManuscriptExports projectId={projectId} manuscriptId={output.manuscript_id} version={version} active={active&&validSession} onOpenTask={onOpenTask} registerLeaveGuard={registerLeaveGuard}/>}</>}</section>
}
