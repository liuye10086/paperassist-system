import {useEffect,useRef,useState} from 'react'
import {safeError,useI18n} from '../../shared/i18n'
import {taskRequest} from '../tasks/taskApi'
import {isTask,sameInputVersion,type TaskView,type TaskWorkspace} from '../tasks/taskTypes'

export default function StatisticsTaskRecovery({workspace,blocked,onChanged}:{workspace:TaskWorkspace;blocked:boolean;onChanged:()=>void}){
 const {t}=useI18n(),{task}=workspace
 const [busy,setBusy]=useState(false),[error,setError]=useState('')
 const active=useRef(true),request=useRef<AbortController|null>(null),identity=useRef<{body:string;key:string}|null>(null)
 useEffect(()=>()=>{active.current=false;request.current?.abort()},[])
 async function retry(){
  if(blocked||request.current||task.origin==='legacy'||!workspace.allowed_actions.includes('retry'))return
  const body=JSON.stringify({operation:'retry',wait_id:null,expected_task_revision:task.revision,input_version:task.input_version})
  if(identity.current?.body!==body)identity.current={body,key:crypto.randomUUID()}
  const controller=new AbortController();request.current=controller;setBusy(true);setError('')
  try{
   await taskRequest(`/api/v1/tasks/${encodeURIComponent(task.id)}/resume`,controller,(value):value is TaskView=>isTask(value,task.project_id,task.id)&&sameInputVersion(value.input_version,task.input_version),'统计重试尚未确认，请重新读取任务。',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':identity.current.key},body})
   if(active.current)onChanged()
  }catch(cause){if(active.current){setError(safeError(cause,'统计重试尚未确认，请重新读取任务。'));onChanged()}}
  finally{if(request.current===controller)request.current=null;if(active.current)setBusy(false)}
 }
 return <section aria-label={t('统计任务处理')}><p>{t('此统计任务在本地执行，不调用付费模型。')}</p>
  {workspace.allowed_actions.includes('retry')&&<button type="button" disabled={blocked||busy} onClick={()=>void retry()}>{t('重试原任务')}</button>}
  {error&&<p role="alert">{t(error)}</p>}
 </section>
}
