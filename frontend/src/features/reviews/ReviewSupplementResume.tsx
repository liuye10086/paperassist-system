import {useEffect,useState} from 'react'
import {safeError,useI18n} from '../../shared/i18n'
import TaskPendingAction from '../tasks/TaskPendingAction'
import {isWorkspace,type TaskWorkspace} from '../tasks/taskTypes'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {useReviewRequest} from './useReviewRequest'
import type {Round} from './reviewTypes'
type Props={projectId:string;round:Round;active:boolean;disabled:boolean;onChanged:()=>void}
export default function ReviewSupplementResume({projectId,round,active,disabled,onChanged}:Props){
 const {t}=useI18n(),visible=useDocumentVisible(),{request,available,error,setError}=useReviewRequest(),[open,setOpen]=useState(false),[workspace,setWorkspace]=useState<TaskWorkspace|null>(null),[refresh,setRefresh]=useState(0)
 useEffect(()=>{if(!open||disabled||!active||!visible||!available)return;const c=new AbortController();void request(`/api/v1/tasks/${encodeURIComponent(round.task.id)}/workspace`,(v):v is TaskWorkspace=>isWorkspace(v,projectId,round.task.id)&&v.task.input_version.kind==='review_round_plan'&&v.task.input_version.round_id===round.id,undefined,c.signal).then(v=>{if(!c.signal.aborted)setWorkspace(v)}).catch(cause=>{if(!c.signal.aborted)setError(safeError(cause,'本轮等待信息读取失败。'))});return()=>c.abort()},[open,disabled,active,visible,available,projectId,round.id,round.revision,round.task.id,request,setError,refresh])
 if(!['waiting_input','waiting_confirmation'].includes(round.task.status))return null
 return <section className="manuscript-panel" aria-label={t('同轮补料继续')}><button type="button" onClick={()=>setOpen(v=>!v)} aria-expanded={open}>{t('核对补料与继续本轮')}</button>{open&&<><p>{t('新增材料需显式保存为新计划版本；补料到达不表示实验完成。仅受影响的重要处理内容需要重新确认。')}</p>{disabled?<p className="warning-panel">{t('请先保存补充材料和计划，再继续本轮。')}</p>:workspace&&available?<TaskPendingAction key={`${workspace.task.id}:${workspace.task.revision}:${workspace.wait?.id}`} workspace={workspace} blocked={!active} onChanged={()=>{setRefresh(v=>v+1);onChanged()}}/>:null}{error&&<p role="alert">{t(error)}</p>}</>}</section>
}
