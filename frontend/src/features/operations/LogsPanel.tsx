import { useState } from 'react'
import RequestMetrics from './RequestMetrics'
import { useI18n } from '../../shared/i18n'
import { CoverageNote, DateValue, Filters, Pagination, ReadState, Table } from './OperationsCommon'
import { timeFields, queryUrl, useOperationsRead, type Audit, type Coverage, type Log, type Page } from './operationsApi'
type Props={onForbidden:()=>void;auditTarget:string;taskId:string;active?:boolean;layered?:boolean;linkIntent?:number}
export default function LogsPanel(props:Props){
 const {t}=useI18n(),{onForbidden,auditTarget,taskId,active=true,layered=false,linkIntent=0}=props
 const [tab,setTab]=useState<'logs'|'audit'|'metrics'>(auditTarget?'audit':'logs')
 const [visited,setVisited]=useState<string[]>([auditTarget?'audit':'logs'])
 const [target,setTarget]=useState({auditTarget,taskId,linkIntent})
 // Explicit links from account/task details select the corresponding filtered view.
 if(target.auditTarget!==auditTarget||target.taskId!==taskId||target.linkIntent!==linkIntent){setTarget({auditTarget,taskId,linkIntent});if(auditTarget||taskId){const next=auditTarget?'audit':'logs';setTab(next);setVisited(values=>values.includes(next)?values:[...values,next])}}
 function choose(next:'logs'|'audit'|'metrics'){setTab(next);setVisited(values=>values.includes(next)?values:[...values,next])}
 return <section aria-label={t('运行日志')}><h2>{t('运行日志')}</h2><nav className="operations-tabs" aria-label={t('日志视图')}><button aria-pressed={tab==='logs'} onClick={()=>choose('logs')}>{t('请求日志')}</button><button aria-pressed={tab==='audit'} onClick={()=>choose('audit')}>{t('操作审计')}</button>{layered&&<button aria-pressed={tab==='metrics'} onClick={()=>choose('metrics')}>{t('请求指标')}</button>}</nav>
 {(!layered||visited.includes('metrics'))&&<div hidden={layered&&tab!=='metrics'}><RequestMetrics onForbidden={onForbidden} active={active&&(!layered||tab==='metrics')}/></div>}
 {(['logs','audit'] as const).map(name=>(visited.includes(name))&&<div key={name} hidden={tab!==name}><LogRecords layered={layered} key={name==='audit'?auditTarget:taskId} tab={name} onForbidden={onForbidden} active={active&&tab===name} initial={name==='audit'?(auditTarget?{target_user_id:auditTarget}:{}):(taskId?{task_id:taskId}:{})}/></div>)}</section>
}
function LogRecords({tab,onForbidden,active,initial,layered}:{tab:'logs'|'audit';onForbidden:()=>void;active:boolean;initial:Record<string,string>;layered:boolean}){
 const{t}=useI18n();const[filters,setFilters]=useState(initial),[page,setPage]=useState(1)
 const read=useOperationsRead<Page<Log|Audit>&{coverage:Coverage}>(queryUrl(`/api/v1/admin/${tab}`,filters,page),onForbidden,active)
 function auditState(role: string | null, active: boolean | null) {
  const roleName = role === 'admin' ? '管理员' : role === 'user' ? '普通用户' : '未知'
  const activeName = active === true ? '启用' : active === false ? '停用' : '未知'
  return `${t(roleName)} / ${t(activeName)}`
 }
 return <section aria-label={t(tab==='logs'?'请求日志':'操作审计')}><h3>{t(tab==='logs'?'请求日志':'操作审计')}</h3><button disabled={read.loading} onClick={()=>read.reload()}>{t('刷新')}</button><Filters collapsible={layered} key={tab} initial={filters} fields={tab==='logs'?[{key:'request_id',label:'请求标识'},{key:'task_id',label:'任务标识'},{key:'user_id',label:'用户标识'},{key:'status',label:'HTTP 状态',type:'number'},...timeFields]:[{key:'target_user_id',label:'目标账号标识'},{key:'actor_user_id',label:'操作者账号标识'},...timeFields]} onApply={value=>{setFilters(value);setPage(1)}}/><ReadState {...read} empty={read.data?.items.length===0}/>{read.data&&<><CoverageNote coverage={read.data.coverage}/>{tab==='logs'?<Table headers={['时间','路由模板','方法 / 状态','耗时','用户标识','任务标识','请求标识','安全错误码']}>{(read.data.items as Log[]).map((item,index)=><tr key={`${item.request_id}:${index}`}><td><DateValue value={item.created_at}/></td><td>{item.route_template??t('未匹配路由')}</td><td>{item.method} / {item.status}</td><td>{item.elapsed_ms} ms</td><td>{item.user_id??t('未知')}</td><td>{item.task_id??t('未知')}</td><td><code>{item.request_id}</code></td><td>{item.error_code??'—'}</td></tr>)}</Table>:<Table headers={['生效时间','来源 / 操作人','目标账号标识','变更前','变更后','变更理由','请求标识']}>{(read.data.items as Audit[]).map(item=><tr key={item.id}><td><DateValue value={item.effective_at}/></td><td>{item.source}<small>{item.operator??t('未记录操作人')}</small><small>{item.actor_user_id??t('无 HTTP 账号身份')}</small></td><td>{item.target_user_id}</td><td>{item.before_role===null&&item.before_active===null?t('创建前不存在'):auditState(item.before_role,item.before_active)}</td><td>{auditState(item.after_role,item.after_active)}</td><td className="operations-reason">{item.reason}</td><td>{item.request_id??t('未知')}</td></tr>)}</Table>}<Pagination page={page} total={read.data.total} onChange={setPage}/></>}</section>
}
