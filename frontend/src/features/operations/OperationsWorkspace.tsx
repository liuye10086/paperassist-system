import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import StoragePanel from './StoragePanel'
import RuntimeStatus from './RuntimeStatus'
import RuntimeNotice from './RuntimeNotice'
import { useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { AuthIdentityContext } from '../auth/AuthIdentityContext'
import { onApiSessionChanged } from '../../shared/api/client'
import { safeError, useI18n } from '../../shared/i18n'
import AccountsPanel from './AccountsPanel'
import TasksPanel from './TasksPanel'
import UsagePanel from './UsagePanel'
import LogsPanel from './LogsPanel'
import ConfigurationsPanel from './ConfigurationsPanel'
import { operationsRequest } from './operationsApi'
import './operations.css'
type Identity={id:string;email:string;role:string}
type Tab='accounts'|'tasks'|'usage'|'logs'|'configurations'|'storage'|'runtime'
export default function OperationsWorkspace({children,layered=false}:{children:ReactNode;layered?:boolean}){
 const confirmedIdentity=useContext(AuthIdentityContext)
 const{t}=useI18n();const[user,setUser]=useState<Identity|null>(confirmedIdentity),[view,setView]=useState<'projects'|'own'|'admin'>('projects'),[tab,setTab]=useState<Tab>('accounts'),[error,setError]=useState(''),[valid,setValid]=useState(true),[auditTarget,setAuditTarget]=useState(''),[logTask,setLogTask]=useState(''),[configurationOpened,setConfigurationOpened]=useState(false),[storageOpened,setStorageOpened]=useState(false),[ownOpened,setOwnOpened]=useState(false)
 const [visited,setVisited]=useState<Tab[]>([]),[logLinkIntent,setLogLinkIntent]=useState(0)
 const guards=useRef(new Map<() => boolean, () => boolean>())
 const registerLeaveGuard=useCallback<RegisterLeaveGuard>((guard,isDirty=()=>true)=>{guards.current.set(guard,isDirty);return()=>{guards.current.delete(guard)}},[])
 useEffect(()=>{const warn=(event:BeforeUnloadEvent)=>{if(Array.from(guards.current.values()).some(dirty=>dirty())){event.preventDefault();event.returnValue=''}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn)},[])
 const identityRequest=useRef<AbortController|null>(null),validRef=useRef(true)
 const readIdentity=useCallback(async()=>{identityRequest.current?.abort();const controller=new AbortController();identityRequest.current=controller
  try{const response=await operationsRequest<{user:Identity}>('/api/v1/auth/me',controller.signal);if(!controller.signal.aborted&&validRef.current&&response.user&&typeof response.user.id==='string'){setUser(response.user);setError('')}}catch(cause){if(!controller.signal.aborted&&validRef.current){setUser(null);setView('projects');setError(safeError(cause,'运营信息读取失败，请重试。'))}}
 },[])
 // Identity restoration is an asynchronous server read, not derived local state.
 // eslint-disable-next-line react/set-state-in-effect
 useEffect(()=>{if(!confirmedIdentity)void readIdentity();const unsubscribe=onApiSessionChanged(()=>{validRef.current=false;identityRequest.current?.abort();setValid(false);setConfigurationOpened(false);setStorageOpened(false);setOwnOpened(false);setUser(null);setView('projects');setAuditTarget('');setLogTask('');setError('')});return()=>{unsubscribe();identityRequest.current?.abort()}},[readIdentity,confirmedIdentity])
 const forbidden=useCallback(()=>{setConfigurationOpened(false);setStorageOpened(false);setOwnOpened(false);setUser(null);setView('projects');setAuditTarget('');setLogTask('');setError('管理员权限已变化，请核对账号权限。');void readIdentity()},[readIdentity])
 function enter(next:'projects'|'own'|'admin'){setView(next);if(next==='admin')setVisited(values=>values.includes(tab)?values:[...values,tab]);if(next==='own')setOwnOpened(true);setError('');if(next!=='projects')void readIdentity()}
 // Server-confirmed context changes must also revoke retained privileged panels.
 // eslint-disable-next-line react/set-state-in-effect
 useEffect(()=>{if(confirmedIdentity)setUser(confirmedIdentity)},[confirmedIdentity])
 function selectTab(next:Tab){setTab(next);setVisited(values=>values.includes(next)?values:[...values,next]);if(next==='configurations')setConfigurationOpened(true);if(next==='storage')setStorageOpened(true)}
 const shown=(name:Tab)=>view==='admin'&&tab===name
 const retained=(name:Tab)=>shown(name)||(layered&&visited.includes(name))
 const isAdmin=user?.role==='admin'&&valid
 return <><RuntimeNotice onProjects={()=>enter('projects')}/><nav className="operations-nav" aria-label={t('工作区入口')}><button aria-pressed={view==='projects'} onClick={()=>enter('projects')}>{t('项目工作区')}</button>{user&&valid&&<button aria-pressed={view==='own'} onClick={()=>enter('own')}>{t('本人用量')}</button>}{isAdmin&&<button aria-pressed={view==='admin'} onClick={()=>enter('admin')}>{t('管理员')}</button>}</nav>{error&&<p role="alert">{t(error)}</p>}<div hidden={view!=='projects'}>{children}</div>{ownOpened&&user&&valid&&<main hidden={view!=='own'} className="operations-workspace"><h1>{t('本人用量')}</h1><UsagePanel admin={false} onForbidden={forbidden} active={view==='own'} layered={layered} registerLeaveGuard={registerLeaveGuard}/></main>}{isAdmin&&(view==='admin'||configurationOpened||storageOpened||layered&&visited.length>0)&&<main hidden={view!=='admin'} className="operations-workspace"><header><p className="step-label">PaperAssist</p><h1>{t('运营管理')}</h1><p>{t('跨账号仅提供运营元数据；研究内容遵循原有所有权。')}</p></header><nav className="operations-tabs" aria-label={t('管理员页面')}>{([['accounts','账号管理'],['tasks','系统任务'],['usage','用量统计'],['logs','运行日志'],['configurations','配置治理'],['storage','存储治理'],['runtime','运行状态']] as const).map(([value,label])=><button key={value} aria-pressed={tab===value} onClick={()=>selectTab(value)}>{t(label)}</button>)}</nav>{retained('accounts')&&<div hidden={!shown('accounts')}><AccountsPanel userId={user.id} onForbidden={forbidden} active={shown('accounts')} layered={layered} registerLeaveGuard={registerLeaveGuard} onAudit={id=>{selectTab('logs');setLogTask('');setAuditTarget(id);setLogLinkIntent(value=>value+1)}}/></div>}
 {retained('runtime')&&<div hidden={!shown('runtime')}><RuntimeStatus onForbidden={forbidden} active={shown('runtime')}/></div>}
 {retained('tasks')&&<div hidden={!shown('tasks')}><TasksPanel userId={user.id} onForbidden={forbidden} active={shown('tasks')} layered={layered} registerLeaveGuard={registerLeaveGuard} onProject={()=>enter('projects')} onLogs={id=>{selectTab('logs');setAuditTarget('');setLogTask(id);setLogLinkIntent(value=>value+1)}}/></div>}
 {storageOpened&&<StoragePanel admin onForbidden={forbidden} active={shown('storage')} layered={layered} registerLeaveGuard={registerLeaveGuard}/>}
 {configurationOpened&&<div hidden={!shown('configurations')}><ConfigurationsPanel onForbidden={forbidden} active={shown('configurations')} layered={layered} registerLeaveGuard={registerLeaveGuard}/></div>}
 {retained('usage')&&<div hidden={!shown('usage')}><UsagePanel admin onForbidden={forbidden} active={shown('usage')} layered={layered} registerLeaveGuard={registerLeaveGuard}/></div>}
 {retained('logs')&&<div hidden={!shown('logs')}><LogsPanel onForbidden={forbidden} active={shown('logs')} layered={layered} auditTarget={auditTarget} taskId={logTask} linkIntent={logLinkIntent}/></div>}</main>}</>
}
