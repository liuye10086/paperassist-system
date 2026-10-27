import type {ReactNode} from 'react'
import {useI18n} from '../../shared/i18n'
import {freshRuntimeStamp,type AdminRuntime,type RuntimeHealth} from './runtimeTypes'
import useRuntimeStatus from './useRuntimeStatus'
import './runtime.css'

export default function RuntimeStatus({onForbidden,active=true}:{onForbidden:()=>void;active?:boolean}){
 const{t}=useI18n(),result=useRuntimeStatus(true,active,onForbidden)
 const data=result.data as AdminRuntime|null,{now}=result
 const sampleTime=data?.coverage.observed_at??null
 const stale=sampleTime!==null&&!freshRuntimeStamp(sampleTime,now)
 const fresh=result.clockCurrent&&!!data&&data.coverage.status==='observed'&&freshRuntimeStamp(sampleTime,now)&&!result.error&&result.valid
 const responseFresh=result.clockCurrent&&result.receivedAt!==null&&now-result.receivedAt<=45_000&&!result.error&&result.valid
 const unknown=t('未知')
 const value=(n:number|null|undefined)=>n==null?unknown:n
 const fact=(label:string,content:ReactNode)=><div><dt>{t(label)}</dt><dd>{content}</dd></div>
 const state=(health:RuntimeHealth|undefined)=>fresh&&health&&freshRuntimeStamp(health.observed_at,now)?t(({healthy:'健康',unavailable:'不可用',unknown:'未知'} as const)[health.status]):unknown
 const healthTime=(health:RuntimeHealth|undefined)=>health?.observed_at??unknown
 const q=fresh?data?.queue:null,f=fresh?data?.failures:null,b=fresh?data?.budgets:null,d=fresh?data?.disk:null
 const e=fresh&&data?.external_limits&&freshRuntimeStamp(data.external_limits.observed_at,now)?data.external_limits:null
 const n=responseFresh?data?.concurrency:null
 const workerProven=fresh&&data?.services.worker.status==='healthy'&&freshRuntimeStamp(data.services.worker.observed_at,now)
 const effective=workerProven?n?.effective:null
 const message=result.forbidden?'运行状态需要有效管理员权限。':!result.valid?'会话已变化，运行状态已清除。':stale?'采样已陈旧，运行事实未知。':result.error?'运行状态读取失败，运行事实未知。':!fresh?'尚无有效采样，运行事实未知。':'当前展示最近一次运行采样。'
 return <section className="runtime-panel" aria-label={t('运行状态')}>
  <h2>{t('运行状态')}</h2><p role="status">{t(message)}</p>
  <p>{t('只读观测，每 15 秒刷新；超过 45 秒显示未知。')}</p>
  <p>{t('运行采样时间：{time}',{time:sampleTime??unknown})}</p>
  <p>{t('缺失或陈旧采样不能视为零或健康；状态不保证当前操作成功。')}</p>
  {result.valid&&!result.forbidden&&<>
   <section aria-label={t('依赖健康')}><h3>{t('依赖健康')}</h3><dl className="runtime-facts">
    {(['worker','dispatcher','broker'] as const).map(name=><div key={name}><dt>{t(({worker:'Worker',dispatcher:'调度器',broker:'消息代理'} as const)[name])}</dt><dd>{state(data?.services[name])}</dd><dd>{t('最近探测时间：{time}',{time:healthTime(data?.services[name])})}</dd></div>)}
    <div><dt>{t('数据库')}</dt><dd>{state(data?.database)}</dd><dd>{t('最近探测时间：{time}',{time:healthTime(data?.database)})}</dd></div>
   </dl></section>
   <div className="runtime-grid">
    <section aria-label={t('任务队列')}><h3>{t('任务队列')}</h3><dl className="runtime-facts">{fact('排队任务数',value(q?.queued_count))}{fact('最老等待时长（秒）',q?.queued_count===0?t('无排队任务'):value(q?.oldest_pending_age_seconds))}</dl></section>
    <section aria-label={t('任务失败覆盖')}><h3>{t('任务失败覆盖')}</h3><dl className="runtime-facts">{fact('失败数 / 终态任务数',f?`${f.failed} / ${f.denominator}`:unknown)}{fact('失败比例',f?.ratio==null?unknown:`${(f.ratio*100).toFixed(2)}%`)}{fact('窗口（秒）',value(f?.window_seconds))}{fact('窗口开始',f?.window_start??unknown)}{fact('窗口结束',f?.window_end??unknown)}</dl><p>{t('仅统计窗口内最后更新的终态任务；历史缺失不代表零。')}</p></section>
    <section aria-label={t('外部限流观测')}><h3>{t('外部限流观测')}</h3><dl className="runtime-facts">{fact('已记录 429 / 响应数',e?`${e.observed_429} / ${e.observed_calls}`:unknown)}{fact('观测窗口（秒）',value(e?.window_seconds))}{fact('外部响应采样时间',e?.observed_at??unknown)}</dl><p>{t('仅已记录的供应商响应；不是供应商公布的限流上限。')}</p></section>
    <section aria-label={t('用户预算观测')}><h3>{t('用户预算观测')}</h3><dl className="runtime-facts">{fact('已登记用户预算数',value(b?.registered_user_budgets))}{fact('预算上限（微美元）',b?.status==='known'?value(b.limit_micro_usd):unknown)}{fact('当前预留（微美元）',b?.status==='known'?value(b.reserved_micro_usd):unknown)}{fact('已记账（微美元）',b?.status==='known'?value(b.accounted_micro_usd):unknown)}</dl><p>{t('仅登记的用户预算；不是全局余额或供应商账单。')}</p></section>
    <section aria-label={t('磁盘观测')}><h3>{t('磁盘观测')}</h3><dl className="runtime-facts">{fact('可用字节',value(d?.free_bytes))}{fact('总字节',value(d?.total_bytes))}</dl><p>{t('仅数据所在文件系统。')}</p></section>
   </div>
   <section aria-label={t('Worker 并发与配置')}><h3>{t('Worker 并发与配置')}</h3><dl className="runtime-facts">
    {fact('期望并发数',value(n?.desired))}{fact('已证实实际并发数',value(effective))}{fact('部署并发上限',value(n?.deployment_ceiling))}
    {fact('重启状态',effective==null||n?.pending_restart==null?unknown:t(n.pending_restart?'等待显式重启':'与启动配置一致'))}
    {fact('期望配置标识',n?.desired_configuration_id??unknown)}{fact('期望配置 SHA256',n?.desired_configuration_sha256??unknown)}
    {fact('实际启动配置标识',effective!=null?n?.effective_configuration_id??t('默认启动配置'):unknown)}{fact('实际启动配置 SHA256',effective!=null?n?.effective_configuration_sha256??t('默认启动配置'):unknown)}
   </dl>{n&&n.desired>n.deployment_ceiling&&<p>{t('期望值超过部署许可上限；仅重启不能提高并发。')}</p>}<p>{t('保存或启用仅改变期望配置；实际并发须在维护窗口显式重启后核对运行状态。')}</p><p>{t('启动配置标识不改变既有任务的冻结配置与授权。')}</p></section>
  </>}
 </section>
}
