import { useEffect, useRef, useState } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { apiError, safeError, useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { useDocumentVisible } from '../tasks/useDocumentVisible'
import { isWorkspace, sameInputVersion, type TaskView, type TaskWorkspace } from '../tasks/taskTypes'
import { documentRequest } from './documentApi'
import { isReviewEdits, isReviewWorkspace, isReviewTask, reviewTaskBase, type ReviewWorkspace, type ReviewEdit } from './ocrReviewApi'
import OcrReviewDocument from './OcrReviewDocument'
import './documents.css'
import useDraftLeaveGuard, {type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'

type Props={projectId:string;fileId:string;parseId:string;taskId:string;filename:string;onUnavailable:()=>void;onPublished?:()=>void;active?:boolean;registerLeaveGuard?:RegisterLeaveGuard}
export default function OcrReviewWorkspace(props:Props){return <Workspace key={`${props.projectId}:${props.fileId}:${props.parseId}:${props.taskId}`} {...props}/>}
function Workspace({projectId,fileId,parseId,taskId,onUnavailable,onPublished,active=true,registerLeaveGuard}:Props) {
 const {t}=useI18n(),visible=useDocumentVisible()
 const [data,setData]=useState<ReviewWorkspace|null>(null),[edits,setEdits]=useState<ReviewEdit[]>([]),[dirty,setDirty]=useState(false)
 const [refresh,setRefresh]=useState(0),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[feedback,setFeedback]=useState(''),[sessionValid,setSessionValid]=useState(true)
 const [actionError,setActionError]=useState(''),[conflict,setConflict]=useState(false),[retryAllowed,setRetryAllowed]=useState(false)
 const dirtyRef=useRef(false),draftBase=useRef<ReviewWorkspace|null>(null),latest=useRef<ReviewWorkspace|null>(null),action=useRef<AbortController|null>(null),read=useRef<AbortController|null>(null)
 const alive=useRef(true),notified=useRef(''),replay=useRef<{body:string;key:string}|null>(null)
 const base=reviewTaskBase(taskId)
 useDraftLeaveGuard(registerLeaveGuard, dirty, busy || Boolean(actionError && !conflict))
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;action.current?.abort();read.current?.abort()}},[])
 useEffect(()=>onApiSessionChanged(()=>{alive.current=false;action.current?.abort();read.current?.abort();setSessionValid(false);setData(null);setEdits([]);draftBase.current=null;replay.current=null}),[])
 useEffect(()=>{
  if(!sessionValid||!visible||!active)return
  const controller=new AbortController();read.current=controller;let mounted=true,timer=0
  const load=async()=>{
   try {
    const value=await documentRequest(base,controller.signal,onUnavailable,(v):v is ReviewWorkspace=>isReviewWorkspace(v,projectId,fileId,parseId,taskId))
    if(!mounted||controller.signal.aborted)return
    if((latest.current?.task.revision??0)>(value.task.revision??0))return
    latest.current=value;setData(value);setError('')
    if(value.task.status==='failed') {
     const workspace=await documentRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/workspace`,controller.signal,onUnavailable,(v):v is TaskWorkspace=>isWorkspace(v,projectId,taskId)&&isReviewTask(v.task,projectId,fileId,parseId,taskId))
     if(!mounted||controller.signal.aborted)return
     setRetryAllowed(workspace.allowed_actions.includes('retry')&&workspace.task.revision===value.task.revision)
    } else setRetryAllowed(false)
    if(!dirtyRef.current){setEdits(value.edits);draftBase.current=value}
    if(value.result&&notified.current!==value.result.id){notified.current=value.result.id;onPublished?.()}
    if(['queued','running'].includes(value.task.status))timer=window.setTimeout(()=>void load(),2000)
   }catch(cause){if(mounted&&!controller.signal.aborted)setError(safeError(cause,'核对进度读取失败，请重试。'))}
   finally{if(mounted&&!controller.signal.aborted)setLoading(false)}
  }
  void load();return()=>{mounted=false;controller.abort();window.clearTimeout(timer)}
 },[base,projectId,fileId,parseId,taskId,sessionValid,visible,active,refresh,onUnavailable,onPublished])
 function change(block:string,edit:ReviewEdit|null) {
  if(!data||busy||data.task.status!=='waiting_confirmation'||data.wait?.status!=='open')return
  if(!dirtyRef.current)draftBase.current=data
  dirtyRef.current=true;setDirty(true);setFeedback('')
  setEdits(previous=>{const next=previous.filter(e=>e.block_id!==block);if(edit)next.push(edit);return next})
 }
 const waiting=data?.task.status==='waiting_confirmation'&&data.wait?.status==='open'&&!!data.checkpoint_id
 const validEdits=isReviewEdits(edits)
 const canApprove=waiting&&!dirty&&!loading&&!busy&&!error&&!conflict&&data?.summary?.unreviewed_blocks===0&&!!data.preview_download_url
 async function decide(operation:'revise'|'approve'|'retry') {
  if(!data||action.current||loading||error||conflict||(operation==='retry'?!retryAllowed:!waiting)||operation==='approve'&&!canApprove||operation==='revise'&&!validEdits)return
  const frozen=operation==='revise'&&dirtyRef.current?draftBase.current:data
  if(!frozen||operation!=='retry'&&(!frozen.wait||!frozen.checkpoint_id))return
  const body=JSON.stringify({operation,wait_id:operation==='retry'?null:frozen.wait?.id,...(operation!=='retry'?{checkpoint_id:frozen.checkpoint_id}:{}),expected_task_revision:frozen.task.revision,input_version:frozen.task.input_version,...(operation==='revise'?{edits}: {})})
  if(replay.current?.body!==body)replay.current={body,key:crypto.randomUUID()}
  read.current?.abort()
  const controller=new AbortController();action.current=controller;setBusy(true);setError('');setActionError('');setFeedback('')
  try {
   const task=await documentRequest(operation==='retry'?`/api/v1/tasks/${encodeURIComponent(taskId)}/resume`:`${base}/decision`,controller.signal,onUnavailable,(v):v is TaskView=>isReviewTask(v,projectId,fileId,parseId,taskId)&&sameInputVersion(v.input_version,frozen.task.input_version),{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':replay.current.key},body})
   if(!alive.current||controller.signal.aborted)return
   dirtyRef.current=false;setDirty(false);replay.current=null
   latest.current={...data,task,wait:null};setData(latest.current)
   setFeedback(operation==='revise'?'进度已保存。':operation==='retry'?'正在恢复核对任务……':'正在生成核对版本……');setRefresh(n=>n+1)
  }catch(cause){if(alive.current&&!controller.signal.aborted){const changed=!!cause&&typeof cause==='object'&&'status' in cause&&cause.status===409;setConflict(changed);setActionError(changed?'核对状态已变化，请重新读取已保存进度后核对。':'核对提交未确认，请刷新状态后重试。');setRefresh(n=>n+1)}}
  finally{if(action.current===controller)action.current=null;if(alive.current&&!controller.signal.aborted)setBusy(false)}
 }
 if(!sessionValid)return <p role="alert">{t('会话已失效，请重新登录。')}</p>
 return <section className="ocr-review-workspace" aria-label={t('人工核对工作区')} aria-busy={loading||busy}>
  <h4>{t('对照原图逐条核对')}</h4><p className="warning-panel">{t('人工核对仅确认原图转录，不代表研究事实、单位、数字或统计结论已验证。')}</p>
  <div className="file-actions"><button disabled={busy||loading} onClick={()=>{setLoading(true);setRefresh(n=>n+1)}}>{t('刷新核对状态')}</button>{(dirty||conflict)&&<button disabled={busy||loading} onClick={()=>{dirtyRef.current=false;setDirty(false);setConflict(false);setActionError('');replay.current=null;setEdits(data?.edits??[]);draftBase.current=data;setLoading(true);setRefresh(n=>n+1);setFeedback('')}}>{t('重新读取已保存进度')}</button>}</div>
  {loading&&!data&&<p role="status">{t('正在读取核对进度……')}</p>}{error&&<p role="alert" className="error-panel">{t(error)}</p>}{actionError&&<p role="alert" className="error-panel">{t(actionError)}</p>}{feedback&&<p role="status">{t(feedback)}</p>}
  {data&&<>
   {data.task.status==='failed'&&<><p role="alert" className="error-panel">{t(apiError({code:data.task.error_code},'核对任务失败，已保存进度保留。请重试原任务。'))}</p>{retryAllowed&&<button className="button-primary" disabled={loading||busy||!!error||conflict} onClick={()=>void decide('retry')}>{t('重试原任务')}</button>}</>}
   {['queued','running'].includes(data.task.status)&&<p role="status">{t('正在保存核对候选或生成版本，请稍候。')}</p>}
   {data.result?<><p role="status">{t('核对版本已生成，内容只读。')}</p><ProjectDownloadLink href={data.result.download_url} filename={`ocr-review.v${data.result.version}.json`}>{t('下载核对版本 JSON')}</ProjectDownloadLink></>:<>
    {data.summary&&<p className="ocr-review-progress">{t('未核对 {remaining} / {total} 条',{remaining:data.summary.total_blocks-edits.length,total:data.summary.total_blocks})}</p>}
    {dirty&&<p className="muted">{t('有未保存修改，请先保存进度。')}</p>}
    {!validEdits&&<p className="error-panel" role="alert">{t('请填写非空修正文字或选择无法辨认。每条最多 20000 字，修正文字合计最多 4 MiB。')}</p>}
    <div className="file-actions"><button disabled={!waiting||busy||loading||!!error||conflict||!validEdits} onClick={()=>void decide('revise')}>{t('保存核对进度')}</button><button className="button-primary" disabled={!canApprove} onClick={()=>void decide('approve')}>{t('确认生成核对版本')}</button></div>
    {!dirty&&data.summary&&data.preview_download_url&&<div className="ocr-review-candidate"><h5>{t('已保存核对候选')}</h5><p>{t('确认原文 {accepted} 条 · 修改 {corrected} 条 · 无法辨认 {unreadable} 条',{accepted:data.summary.accepted_blocks,corrected:data.summary.corrected_blocks,unreadable:data.summary.unreadable_blocks})}</p><ProjectDownloadLink href={data.preview_download_url} filename="ocr-review-preview.json">{t('下载核对预览 JSON')}</ProjectDownloadLink></div>}
   </>}
   {!!data.summary?.no_text_pages.length&&<p className="warning-panel">{t('物理页 {pages} 未识别到文字，可能漏识别；这些页面不算完整内容已核验。',{pages:data.summary.no_text_pages.join(', ')})}</p>}
   <OcrReviewDocument projectId={projectId} source={data.source} edits={data.result?data.edits:edits} readOnly={!!data.result} refreshKey={refresh} disabled={!waiting||busy||loading||!!error} onEdit={change} onUnavailable={onUnavailable}/>
  </>}
 </section>
}
