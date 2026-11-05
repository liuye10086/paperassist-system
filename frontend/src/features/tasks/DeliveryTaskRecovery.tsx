import {useEffect,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import {deliveryMemberContainsPdf} from '../../shared/pdfDelivery'
import {validId} from '../projects/projectNavigation'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {deliveryBase,deliveryHref,type DeliveryMember} from '../research-intake/deliveryPackageContracts'
import {taskRequest} from './taskApi'
import TaskPendingAction from './TaskPendingAction'
import type {TaskWorkspace} from './taskTypes'

type Props={workspace:TaskWorkspace;active:boolean;blocked:boolean;registerLeaveGuard?:RegisterLeaveGuard;onChanged:()=>void}
type Location={project_id:string;task_id:string;task_type:'delivery_package';delivery_id:string;snapshot_id:string}
type Snapshot={id:string;members:DeliveryMember[]}
const object=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value)
export default function DeliveryTaskRecovery({workspace,active,blocked,registerLeaveGuard,onChanged}:Props){
 const {t}=useI18n(),{task}=workspace,[data,setData]=useState<{location:Location;snapshot:Snapshot}|null>(null),[error,setError]=useState(''),[valid,setValid]=useState(true),[attempt,setAttempt]=useState(0)
 useEffect(()=>onApiSessionChanged(()=>{setValid(false);setData(null)}),[])
 useEffect(()=>{
  setData(null);setError('');if(!active||!valid)return
  const c=new AbortController();let live=true
  void (async()=>{
   try{
    const location=await taskRequest(`/api/v1/tasks/${encodeURIComponent(task.id)}/progress`,c,(v):v is Location=>object(v)&&v.project_id===task.project_id&&v.task_id===task.id&&v.task_type==='delivery_package'&&typeof v.delivery_id==='string'&&validId(v.delivery_id)&&typeof v.snapshot_id==='string'&&validId(v.snapshot_id),'固定交付快照读取失败，请重试。')
    const snapshot=await taskRequest(deliveryBase(task.project_id,location.delivery_id)+'/snapshots/'+encodeURIComponent(location.snapshot_id),c,(v):v is Snapshot=>object(v)&&v.id===location.snapshot_id&&Array.isArray(v.members)&&v.members.every(m=>object(m)&&typeof m.format==='string'&&object(m.selection)&&typeof m.selection.kind==='string'),'固定交付快照读取失败，请重试。')
    if(live&&!c.signal.aborted)setData({location,snapshot})
   }catch(cause){if(live&&!c.signal.aborted)setError(safeError(cause,'固定交付快照读取失败，请重试。'))}
  })()
  return()=>{live=false;c.abort()}
 },[task.project_id,task.id,task.revision,active,valid,attempt])
 if(!active||!valid)return null
 if(error)return <p role="alert">{t(error)} <button type="button" onClick={()=>setAttempt(value=>value+1)}>{t('重新读取')}</button></p>
 if(!data)return <p role="status">{t('正在核对固定交付成员……')}</p>
 if(data.snapshot.members.some(deliveryMemberContainsPdf))return <p>{t('此历史交付包含 PDF，仅保留状态与原请求查询。')} <a href={deliveryHref(task.project_id,data.location.delivery_id,data.location.snapshot_id)}>{t('返回此固定交付快照')}</a></p>
 return <TaskPendingAction workspace={workspace} active={active} blocked={blocked} registerLeaveGuard={registerLeaveGuard} onChanged={onChanged}/>
}
