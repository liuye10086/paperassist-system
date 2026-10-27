import {useI18n} from '../../shared/i18n'
import {freshRuntimeStamp} from './runtimeTypes'
import useRuntimeStatus from './useRuntimeStatus'
import './runtime.css'

export default function RuntimeNotice({onProjects,loginTarget='#paperassist-login'}:{onProjects?:()=>void;loginTarget?:string}){
 const{t}=useI18n(),{data,error,receivedAt,now,clockCurrent}=useRuntimeStatus(false)
 const responseFresh=clockCurrent&&receivedAt!==null&&now-receivedAt<=45_000&&!error
 const observed=responseFresh&&data?.reason==='observed_available'&&freshRuntimeStamp(data.observed_at,now)
 const maintenance=responseFresh&&data?.status==='maintenance'&&data.reason==='operator_maintenance'
 const unavailable=responseFresh&&data?.status==='service_unavailable'&&data.reason==='service_observation_unavailable'&&freshRuntimeStamp(data.observed_at,now)
 const legacy=responseFresh&&data?.reason==='runtime_control_not_configured'
 const text=maintenance?'系统维护中，暂不接受新的修改或任务。':unavailable?'服务依赖不可用，部分操作暂时受限。':observed?'最近采样显示服务可用；实际操作仍以响应为准。':legacy?'运行观测尚未配置，不能据此确认服务健康。':'运行状态暂不可确认，请稍后重试。'
 return <aside className="runtime-notice" aria-label={t('服务运行提示')} data-runtime-state={maintenance?'maintenance':unavailable?'unavailable':observed?'observed':'unknown'}>
  <p role="status">{t(text)}</p>
  {!observed&&<p>{t('已保存成果的读取或下载取决于依赖可用性，当前可能受限。')}</p>}
  {!observed&&<p>{t('页面内的未提交内容保持原样；恢复后不会自动提交。')}</p>}
  {data?.observed_at&&<small>{t(maintenance?'维护设置时间：{time}':'最近状态时间：{time}',{time:data.observed_at})}</small>}
  {!observed&&(onProjects?<button type="button" onClick={onProjects}>{t('查看已有项目与成果')}</button>:<a href={loginTarget} onClick={event=>{
   event.preventDefault()
   const target=document.querySelector<HTMLElement>(loginTarget)
   target?.scrollIntoView?.({block:'start'})
   target?.querySelector<HTMLElement>('input:not(:disabled),button:not(:disabled)')?.focus({preventScroll:true})
  }}>{t('登录后查看已有项目与成果')}</a>)}
 </aside>
}
