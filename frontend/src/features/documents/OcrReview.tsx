import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { safeError, useI18n } from '../../shared/i18n'
import { useDocumentVisible } from '../tasks/useDocumentVisible'
import type { TaskView } from '../tasks/taskTypes'
import { documentRequest, type DocumentVersion } from './documentApi'
import { reviewBase, isReviewTask } from './ocrReviewApi'
import OcrReviewWorkspace from './OcrReviewWorkspace'
import OcrReviewHistory from './OcrReviewHistory'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'

type Props={projectId:string;fileId:string;filename:string;parent:DocumentVersion;onUnavailable:()=>void;children?:ReactNode;active?:boolean;registerLeaveGuard?:RegisterLeaveGuard}
export default function OcrReview(props:Props){return <Review key={`${props.projectId}:${props.fileId}:${props.parent.id}`} {...props}/>}
function Review({projectId,fileId,filename,parent,onUnavailable,children,active=true,registerLeaveGuard}:Props) {
 const {t}=useI18n(),visible=useDocumentVisible()
 const [tasks,setTasks]=useState<TaskView[]|null>(null),[taskId,setTaskId]=useState(''),[refresh,setRefresh]=useState(0),[busy,setBusy]=useState(false),[error,setError]=useState(''),[sessionValid,setSessionValid]=useState(true)
 const action=useRef<AbortController|null>(null),key=useRef<string|null>(null)
 const [visited,setVisited]=useState<string[]>([])
 if(taskId&&!visited.includes(taskId))setVisited(current=>[...current,taskId])
 const base=reviewBase(projectId,fileId)
 useEffect(()=>onApiSessionChanged(()=>{action.current?.abort();setSessionValid(false);setTasks(null);setTaskId('');key.current=null}),[])
 useEffect(()=>()=>action.current?.abort(),[])
 useEffect(()=>{
  if(!sessionValid||!visible||!active)return
  const controller=new AbortController()
  void documentRequest(`${base}?parse_id=${encodeURIComponent(parent.id)}`,controller.signal,onUnavailable,(v):v is {items:TaskView[]}=>!!v&&typeof v==='object'&&'items' in v&&Array.isArray(v.items)&&v.items.every(item=>isReviewTask(item,projectId,fileId,parent.id))).then(value=>{if(!controller.signal.aborted){setTasks(value.items);setError('')}}).catch(cause=>{if(!controller.signal.aborted)setError(safeError(cause,'核对任务读取失败，请重试。'))})
  return()=>controller.abort()
 },[base,parent.id,projectId,fileId,refresh,sessionValid,visible,active,onUnavailable])
 const published=useCallback(()=>setRefresh(n=>n+1),[])
 const recover=tasks?.find(task=>task.status!=='succeeded')
 async function open() {
  if(action.current||!sessionValid)return
  if(recover){setTaskId(recover.id);return}
  const controller=new AbortController();action.current=controller;setBusy(true);setError('');key.current??=crypto.randomUUID()
  try {
   const task=await documentRequest(base,controller.signal,onUnavailable,(v):v is TaskView=>isReviewTask(v,projectId,fileId,parent.id),{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key.current},body:JSON.stringify({parse_id:parent.id})})
   if(!controller.signal.aborted){key.current=null;setTaskId(task.id);setRefresh(n=>n+1)}
  }catch(cause){if(!controller.signal.aborted){const conflict=!!cause&&typeof cause==='object'&&'status' in cause&&cause.status===409;if(conflict){key.current=null;setRefresh(n=>n+1)}setError(conflict?'已有核对进度，请继续人工核对。':safeError(cause,'开始核对未确认，请刷新状态后重试。'))}}
  finally{if(action.current===controller)action.current=null;if(!controller.signal.aborted)setBusy(false)}
 }
 if(!sessionValid)return <p role="alert">{t('会话已失效，请重新登录。')}</p>
 return <section className="ocr-review" aria-label={t('文字人工核对')}>
  <h4>{t('文字人工核对')}</h4>
  <p className="muted">{t('核对当前识别版本的全部已有文字块，保存进度后可继续。原始识别结果保留。')}</p>
  {parent.summary?.counts.text_blocks===0&&<p>{t('此版本没有已有文字块，无法创建核对任务。请核对原图是否漏识别。')}</p>}
  <div className="file-actions"><button className="button-primary" disabled={busy||!tasks||parent.summary?.counts.text_blocks===0} onClick={()=>void open()}>{t(recover?'继续人工核对':'开始人工核对')}</button><button disabled={busy} onClick={()=>setRefresh(n=>n+1)}>{t('刷新核对任务')}</button>{taskId&&<button disabled={busy} onClick={()=>setTaskId('')}>{t('返回识别预览')}</button>}</div>
  {error&&<p className="error-panel" role="alert">{t(error)}</p>}
  {visited.map(id=><div key={id} hidden={taskId!==id}><OcrReviewWorkspace projectId={projectId} fileId={fileId} parseId={parent.id} taskId={id} filename={filename} active={active&&taskId===id} registerLeaveGuard={registerLeaveGuard} onUnavailable={onUnavailable} onPublished={published}/></div>)}
  <div hidden={Boolean(taskId)}>{children}</div>
  <OcrReviewHistory projectId={projectId} fileId={fileId} parseId={parent.id} filename={filename} refreshKey={refresh} active={active} onUnavailable={onUnavailable}/>
 </section>
}
