import {useEffect, useState} from 'react'
import {act, cleanup, fireEvent, render, screen, within} from '@testing-library/react'
import {afterEach, beforeEach, expect, it, vi} from 'vitest'
import RuntimeStatus from './RuntimeStatus'
import RuntimeNotice from './RuntimeNotice'
import OperationsWorkspace from './OperationsWorkspace'
import {AuthIdentityContext} from '../auth/AuthIdentityContext'
import AuthBoundary from '../auth/AuthBoundary'
import useProjectSelection from '../projects/useProjectSelection'
import {clearApiSession, setApiSession} from '../../shared/api/client'
import {setLocale} from '../../shared/i18n'
import {apiError,translate} from '../../shared/i18n'

const now = new Date('2026-10-27T05:00:00Z')
const healthy = {status:'healthy', observed_at:now.toISOString()}
const sample = () => ({status:'normal',reason:'observed_available',observed_at:now.toISOString(),
 coverage:{status:'observed',observed_at:now.toISOString(),sample_seconds:15,stale_after_seconds:45,historical_missing_is_zero:false},
 services:{worker:healthy,dispatcher:healthy,broker:healthy},database:healthy,
 queue:{queued_count:0,oldest_pending_age_seconds:null},
 failures:{failed:0,denominator:0,ratio:null,window_seconds:3600,window_start:'2026-10-27T04:00:00Z',window_end:now.toISOString(),coverage:'terminal_tasks_updated_in_window'},
 budgets:{status:'unknown',registered_user_budgets:0,limit_micro_usd:null,reserved_micro_usd:null,accounted_micro_usd:null,coverage:'registered_user_budgets_only_not_global_balance'},
 disk:{free_bytes:0,total_bytes:100,coverage:'data_filesystem_only'},external_limits:null,
 concurrency:{desired:2,effective:1,deployment_ceiling:2,pending_restart:true,desired_configuration_id:'desired-config',desired_configuration_sha256:'a'.repeat(64),effective_configuration_id:'startup-config',effective_configuration_sha256:'b'.repeat(64)}})
let mock:ReturnType<typeof vi.fn>
beforeEach(()=>{vi.useFakeTimers();vi.setSystemTime(now);setApiSession('csrf','admin');mock=vi.fn(async()=>Response.json(sample()));vi.stubGlobal('fetch',mock)})
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals();setLocale('zh-CN')})
async function flush(){await act(async()=>{await Promise.resolve();await Promise.resolve()})}
const forbidden=vi.fn()
it('preserves the exact artifact deep link through the anonymous notice click and login',async()=>{
 const original=window.location.href
 const hash='#project=retained-project&section=artifacts&view=detail&artifact=saved-report&kind=report&page=2'
 function ExistingRoute(){const route=useProjectSelection(()=>{},()=>{});return <output aria-label="Existing route">{JSON.stringify({project:route.instance?.id,section:route.section,artifact:route.artifactNavigation})}</output>}
 try{
  clearApiSession()
  window.history.replaceState(null,'',hash)
  mock.mockImplementation(async(url:string)=>{
   if(url==='/api/v1/auth/me')return Response.json({},{status:401})
   if(url==='/api/v1/auth/login')return Response.json({csrf_token:'login-csrf',user:{id:'user',email:'user@example.test',role:'user'}})
   if(url==='/api/v1/projects/retained-project')return Response.json({id:'retained-project',name:'Saved project',research_topic:'topic',project_type:'sci',file_count:1,created_at:now.toISOString(),updated_at:now.toISOString()})
   return Response.json({status:'maintenance',reason:'operator_maintenance',observed_at:now.toISOString()})
  })
  render(<AuthBoundary><ExistingRoute/></AuthBoundary>);await flush()
  const scroll=vi.fn(),target=document.getElementById('paperassist-login')!
  target.scrollIntoView=scroll
  screen.getByRole('button',{name:'登录'}).focus()
  fireEvent.click(screen.getByRole('link',{name:'登录后查看已有项目与成果'}))
  await act(async()=>vi.advanceTimersByTime(0))
  expect(window.location.hash).toBe(hash)
  expect(document.activeElement).toBe(screen.getByLabelText('邮箱'));expect(scroll).toHaveBeenCalledOnce()
  fireEvent.change(screen.getByLabelText('邮箱'),{target:{value:'user@example.test'}})
  fireEvent.change(screen.getByLabelText('密码'),{target:{value:'test-password'}})
  fireEvent.click(screen.getByRole('button',{name:'登录'}));await flush()
  expect(window.location.hash).toBe(hash)
  expect(JSON.parse(screen.getByLabelText('Existing route').textContent!)).toEqual({project:'retained-project',section:'artifacts',artifact:{view:'detail',artifactId:'saved-report',kind:'report',page:2}})
  expect(mock.mock.calls.filter(([url])=>url==='/api/v1/auth/login')).toHaveLength(1)
 }finally{window.history.replaceState(null,'',original)}
})
it('expires old health immediately when resuming active or visible after the clock was paused',async()=>{
 const visibility=vi.spyOn(document,'visibilityState','get')
 try{
  for(const paused of ['active','visible']){
   vi.setSystemTime(now);visibility.mockReturnValue('visible');mock.mockImplementation(async()=>Response.json(sample()))
   const view=render(<RuntimeStatus onForbidden={forbidden}/>);await flush()
   expect(screen.getAllByText('健康')).toHaveLength(4)
   mock.mockImplementation(()=>new Promise(()=>{}))
   if(paused==='active')view.rerender(<RuntimeStatus onForbidden={forbidden} active={false}/>)
   else{visibility.mockReturnValue('hidden');fireEvent(document,new Event('visibilitychange'))}
   vi.setSystemTime(new Date(now.getTime()+60_000))
   if(paused==='active')view.rerender(<RuntimeStatus onForbidden={forbidden}/>)
   else{visibility.mockReturnValue('visible');fireEvent(document,new Event('visibilitychange'))}
   expect(screen.getByText('尚无有效采样，运行事实未知。')).toBeTruthy()
   expect(screen.queryByText('健康')).toBeNull();expect(screen.queryByText('startup-config')).toBeNull()
   expect(within(screen.getByRole('region',{name:'任务队列'})).queryByText('0')).toBeNull()
   expect(screen.getByText(`运行采样时间：${now.toISOString()}`)).toBeTruthy()
   await act(async()=>vi.advanceTimersByTime(1_000))
   expect(screen.getByText('采样已陈旧，运行事实未知。')).toBeTruthy();expect(screen.queryByText('健康')).toBeNull()
   view.unmount()
  }
 }finally{visibility.mockRestore()}
})
it('integrates the admin runtime tab with active polling and immediate role revocation',async()=>{
 let role='admin',denied=false
 mock.mockImplementation(async(url:string)=>{
  if(url==='/api/v1/runtime/status')return Response.json({status:'maintenance',reason:'operator_maintenance',observed_at:now.toISOString()})
  if(url==='/api/v1/admin/runtime/status')return denied?Response.json({detail:{code:'forbidden'}},{status:403}):Response.json(sample())
  if(url==='/api/v1/auth/me')return Response.json({user:{id:'admin',email:'admin@example.test',role}})
  return Response.json({items:[],total:0,page:1,page_size:10})
 })
 render(<AuthIdentityContext.Provider value={{id:'admin',email:'admin@example.test',role:'admin'}}><OperationsWorkspace layered><input aria-label="Retained project draft" defaultValue="text"/></OperationsWorkspace></AuthIdentityContext.Provider>)
 expect(mock.mock.calls.some(([url])=>url==='/api/v1/admin/runtime/status')).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'管理员'}));fireEvent.click(screen.getByRole('button',{name:'运行状态'}));await flush()
 expect(screen.getByText('desired-config')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'查看已有项目与成果'}));const count=mock.mock.calls.filter(([url])=>url==='/api/v1/admin/runtime/status').length
 await act(async()=>vi.advanceTimersByTime(16_000));expect(mock.mock.calls.filter(([url])=>url==='/api/v1/admin/runtime/status')).toHaveLength(count)
 expect(screen.getByLabelText('Retained project draft')).toHaveProperty('value','text')
 denied=true;role='user';fireEvent.click(screen.getByRole('button',{name:'管理员'}));await flush()
 expect(screen.queryByRole('button',{name:'管理员'})).toBeNull();expect(screen.queryByText('desired-config')).toBeNull()
})
it('translates maintenance admission errors from fixed codes without trusting server prose',()=>{
 for(const locale of ['zh-CN','en'] as const){
  setLocale(locale)
  expect(translate(apiError({detail:{code:'service_maintenance',message:'SECRET'}},'fallback'))).toBe(locale==='en'?'The system is under maintenance and is not accepting new changes or tasks. Please try again later.':'系统维护中，暂不接受新的修改或任务，请稍后重试。')
  expect(translate(apiError({detail:{code:'service_unavailable',message:'SECRET'}},'fallback'))).toBe(locale==='en'?'Runtime status is unconfirmed. Please try again later.':'运行状态暂不可确认，请稍后重试。')
 }
})
it('shows observed zero separately from unknown, coverage, identities and desired versus effective concurrency',async()=>{
 render(<RuntimeStatus onForbidden={forbidden}/>);await flush()
 expect(within(screen.getByRole('region',{name:'任务队列'})).getByText('0')).toBeTruthy()
 expect(within(screen.getByRole('region',{name:'任务失败覆盖'})).getByText('0 / 0')).toBeTruthy()
 expect(screen.getByText('仅统计窗口内最后更新的终态任务；历史缺失不代表零。')).toBeTruthy()
 expect(screen.getByText('仅登记的用户预算；不是全局余额或供应商账单。')).toBeTruthy()
 expect(screen.getByText('仅数据所在文件系统。')).toBeTruthy()
 expect(screen.getByText('desired-config')).toBeTruthy();expect(screen.getByText('startup-config')).toBeTruthy()
 expect(screen.getByText('等待显式重启')).toBeTruthy();expect(screen.queryByRole('button',{name:/重启/})).toBeNull()
 expect(mock.mock.calls[0][0]).toBe('/api/v1/admin/runtime/status')
})
it('expires an old green sample independently while the next request hangs and aborts on inactive',async()=>{
 const view=render(<RuntimeStatus onForbidden={forbidden}/>);await flush()
 let signal:AbortSignal|undefined
 mock.mockImplementation((_url:string,init:RequestInit)=>{signal=init.signal as AbortSignal;return new Promise(()=>{})})
 await act(async()=>{vi.advanceTimersByTime(46_000)})
 expect(screen.getByText('采样已陈旧，运行事实未知。')).toBeTruthy()
 expect(screen.queryByText('健康')).toBeNull();expect(screen.queryByText('startup-config')).toBeNull()
 view.rerender(<RuntimeStatus onForbidden={forbidden} active={false}/>);expect(signal?.aborted).toBe(true)
 const calls=mock.mock.calls.length;await act(async()=>vi.advanceTimersByTime(60_000));expect(mock).toHaveBeenCalledTimes(calls)
})
it('does not display malformed counters, missing observations or unproved effective concurrency as healthy',async()=>{
 mock.mockResolvedValue(Response.json({...sample(),coverage:{...sample().coverage,status:'unknown',observed_at:null},queue:null,failures:null,budgets:null,disk:null,concurrency:{...sample().concurrency,effective:null,pending_restart:null,effective_configuration_id:null,effective_configuration_sha256:null}}))
 render(<RuntimeStatus onForbidden={forbidden}/>);await flush()
 expect(screen.getByText('尚无有效采样，运行事实未知。')).toBeTruthy();expect(screen.queryByText('健康')).toBeNull();expect(screen.queryByText('startup-config')).toBeNull()
})
it('revokes private data on forbidden and session change and ignores delayed old responses',async()=>{
 forbidden.mockClear();mock.mockResolvedValue(Response.json({detail:{code:'forbidden'}},{status:403}))
 const view=render(<RuntimeStatus onForbidden={forbidden}/>);await flush();expect(forbidden).toHaveBeenCalledOnce()
 expect(screen.getByText('运行状态需要有效管理员权限。')).toBeTruthy();view.unmount()
 let finish!:(r:Response)=>void;let signal:AbortSignal|undefined
 mock.mockImplementation((_url:string,init:RequestInit)=>new Promise<Response>(resolve=>{finish=resolve;signal=init.signal as AbortSignal}))
 render(<RuntimeStatus onForbidden={forbidden}/>);act(()=>clearApiSession());expect(signal?.aborted).toBe(true)
 await act(async()=>finish(Response.json(sample())));expect(screen.queryByText('desired-config')).toBeNull()
})
it.each(['maintenance','service_unavailable'] as const)('public %s preserves mounted draft and existing workspace navigation without promising downloads',async status=>{
 let mounts=0
 function Draft(){const[value,setValue]=useState('');useEffect(()=>{mounts++},[]);return <input aria-label="Existing draft" value={value} onChange={e=>setValue(e.target.value)}/>}
 mock.mockImplementation(async(url:string)=>Response.json(url==='/api/v1/runtime/status'?{status,reason:status==='maintenance'?'operator_maintenance':'service_observation_unavailable',observed_at:now.toISOString()}:{user:{id:'admin',email:'admin@example.test',role:'admin'}}))
 render(<AuthIdentityContext.Provider value={{id:'admin',email:'admin@example.test',role:'admin'}}><OperationsWorkspace layered><Draft/></OperationsWorkspace></AuthIdentityContext.Provider>);await flush()
 fireEvent.change(screen.getByLabelText('Existing draft'),{target:{value:'Keep research text'}})
 expect(screen.getByText('已保存成果的读取或下载取决于依赖可用性，当前可能受限。')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'本人用量'}));fireEvent.click(screen.getByRole('button',{name:'查看已有项目与成果'}))
 expect(screen.getByLabelText('Existing draft')).toHaveProperty('value','Keep research text');expect(mounts).toBe(1)
 mock.mockImplementation(async()=>Response.json({status:'normal',reason:'observed_available',observed_at:new Date().toISOString()}))
 await act(async()=>vi.advanceTimersByTime(15_000));expect(mounts).toBe(1);expect(screen.getByLabelText('Existing draft')).toHaveProperty('value','Keep research text')
})
it('public reads are session independent, legacy normal is unverified, and anonymous maintenance retains the actual login path',async()=>{
 mock.mockResolvedValue(Response.json({status:'normal',reason:'runtime_control_not_configured',observed_at:null}))
 const view=render(<RuntimeNotice/>);act(()=>clearApiSession());await flush()
 expect(screen.getByText('运行观测尚未配置，不能据此确认服务健康。')).toBeTruthy();expect(mock.mock.calls[0][1]).toMatchObject({cache:'no-store'})
 view.unmount();mock.mockImplementation(async(url:string)=>url==='/api/v1/auth/me'?Response.json({},{status:401}):Response.json({status:'maintenance',reason:'operator_maintenance',observed_at:'2026-10-26T00:00:00Z'}))
 render(<AuthBoundary><p>Authenticated workspace</p></AuthBoundary>);await flush()
 expect(screen.getByText('系统维护中，暂不接受新的修改或任务。')).toBeTruthy()
 const link=screen.getByRole('link',{name:'登录后查看已有项目与成果'});expect(document.querySelector(link.getAttribute('href')!)).toBeTruthy()
 expect(screen.getByRole('button',{name:'登录'})).toBeTruthy()
})
it('renders unknown, stale, failures and restart metadata in English without exposing server error prose',async()=>{
 setLocale('en');mock.mockResolvedValue(Response.json({...sample(),failures:{...sample().failures,failed:1,denominator:2,ratio:0.5}}))
 render(<RuntimeStatus onForbidden={forbidden}/>);await flush()
 expect(screen.getByText('Awaiting explicit restart')).toBeTruthy();expect(screen.getByText('50.00%')).toBeTruthy()
 expect(screen.getByText('Recorded provider responses only; this is not a provider rate ceiling.')).toBeTruthy()
 mock.mockResolvedValue(Response.json({secret:'SECRET'},{status:500}));await act(async()=>vi.advanceTimersByTime(15_000))
 expect(screen.getByText('Runtime status could not be read; observations are unknown.')).toBeTruthy();expect(screen.queryByText('SECRET')).toBeNull()
})
