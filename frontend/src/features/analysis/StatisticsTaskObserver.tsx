import {useEffect, useRef, useState} from 'react'
import {safeError, useI18n} from '../../shared/i18n'
import {isTask, type TaskView} from '../tasks/taskTypes'
import {taskRequest} from '../tasks/taskApi'
import TaskDetail from '../tasks/TaskDetail'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {taskMatchesStatisticsContext, validStatisticsTaskResult, type StatisticsTaskContext} from './statisticsTaskContracts'
import type {Result} from './StatisticsResults'

type Props={task:TaskView;context:StatisticsTaskContext;onTask:(task:TaskView)=>void;onResult:(result:Result)=>void;onError:(message:string)=>void}
export default function StatisticsTaskObserver({task,context,onTask,onResult,onError}:Props){
 const {t}=useI18n(),visible=useDocumentVisible()
 const [details,setDetails]=useState(false),[attempt,setAttempt]=useState(0),[error,setError]=useState('')
 const callbacks=useRef({onTask,onResult,onError}),taskRef=useRef(task)
 useEffect(()=>{callbacks.current={onTask,onResult,onError}},[onTask,onResult,onError])
 useEffect(()=>{taskRef.current=task},[task])
 const completed=useRef<string|null>(null)
 const taskId=task.id
 const projectId=decodeURIComponent(context.base.split('/')[4])
 useEffect(()=>{
  const initialTask=taskRef.current
  const explicitRefresh=attempt>0
  if(!visible||!explicitRefresh&&(initialTask.status==='failed'||completed.current!==null&&completed.current===initialTask.result_analysis_run_id))return
  const controller=new AbortController();let timer=0;let mounted=true
  async function observe(){
   try{
    const current=!explicitRefresh&&initialTask.status==='succeeded'?initialTask:await taskRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}`,controller,
     (value):value is TaskView=>isTask(value,projectId,taskId)&&taskMatchesStatisticsContext(value,context)&&value.revision!==null&&initialTask.revision!==null&&value.revision>=initialTask.revision,'统计任务读取失败，请重新读取。')
    if(!mounted||controller.signal.aborted)return
    setError('')
    if(current.status==='succeeded'){
     const runId=current.result_analysis_run_id
     if(!runId)throw new Error('统计结果读取失败，请重新读取。')
     const result=await taskRequest(`${context.base}/analysis-runs/${encodeURIComponent(runId)}`,controller,
      (value):value is Result=>validStatisticsTaskResult(value,context,runId),'统计结果读取失败，请重新读取。')
     if(!mounted||controller.signal.aborted)return
     completed.current=runId;callbacks.current.onTask(current);callbacks.current.onResult(result)
    }else{callbacks.current.onTask(current);if(current.status!=='failed')timer=window.setTimeout(()=>void observe(),2000)}
   }catch(cause){if(mounted){const message=safeError(cause,'统计任务读取失败，请重新读取。');setError(message);callbacks.current.onError(message)}}
  }
  void observe()
  return()=>{mounted=false;controller.abort();window.clearTimeout(timer)}
 },[taskId,context,projectId,visible,attempt])
 return <section className="statistics-task" aria-label={t('统计任务')}>
  {task.status==='queued'&&<p role="status">{t('统计任务已排队；离开页面不会取消任务。')}</p>}
  {task.status==='running'&&<p role="status">{t('统计任务正在计算；离开页面不会取消任务。')}</p>}
  {task.status==='failed'&&<p className="warning-panel">{t('统计任务未完成，请查看任务详情处理失败原因。')}</p>}
  <p className="muted">{t('此统计任务在本地执行，不调用付费模型。')}</p>
  {error&&<><p role="alert">{t(error)}</p><button type="button" onClick={()=>setAttempt(n=>n+1)}>{t('重新读取统计任务')}</button></>}
  <button type="button" onClick={()=>setDetails(value=>!value)}>{t(details?'收起统计任务详情':'查看统计任务详情')}</button>
  {details&&<TaskDetail projectId={projectId} taskId={task.id} onChanged={()=>setAttempt(n=>n+1)}/>}
 </section>
}
