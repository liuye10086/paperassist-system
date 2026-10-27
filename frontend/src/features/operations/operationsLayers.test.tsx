import {AuthIdentityContext} from '../auth/AuthIdentityContext'
import {clearApiSession} from '../../shared/api/client'
import {workspaceFixture,taskFixture} from '../tasks/taskFixtures'
import {act,cleanup,fireEvent,render,renderHook,screen,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import OperationsWorkspace from './OperationsWorkspace'
import {useOperationsRead} from './operationsApi'
import {setApiSession} from '../../shared/api/client'

const account={id:'other',email:'other@example.test',role:'user',active:true,admin_revision:3,updated_at:1792700000,allowed_actions:['edit']}
let role='admin'
const baseFetch=async(url:string)=>Response.json(url==='/api/v1/auth/me'?{user:{id:'self',email:'self@example.test',role}}:url.includes('/users?')?{items:[account],total:1,page:1,page_size:10}:{items:[],total:0,page:1,page_size:10,coverage:{started_at:'2026-10-23',historical_missing_is_zero:false,policy:'retain_no_auto_delete'}})
const fetch=vi.fn(baseFetch)
beforeEach(()=>{role='admin';setApiSession('csrf','self');fetch.mockReset();fetch.mockImplementation(baseFetch);vi.stubGlobal('fetch',fetch)})
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();window.history.replaceState(null,'','/')})
async function start(){render(<OperationsWorkspace layered><p>Project remains</p></OperationsWorkspace>);fireEvent.click(await screen.findByRole('button',{name:'管理员'}));await screen.findByText('other@example.test')}
it.each([['账号管理','账号搜索','unapplied-account'],['系统任务','任务状态','failed'],['运行日志','请求标识','unapplied-request']])('starts %s filters collapsed and preserves unapplied input when reopening',async(tab,label,value)=>{
 await start();if(tab!=='账号管理')fireEvent.click(screen.getByRole('button',{name:tab}))
 const input=screen.getByLabelText(label),disclosure=input.closest('details')!;expect(disclosure).not.toBeNull();expect(disclosure.open).toBe(false)
 const summary=disclosure.querySelector('summary')!;expect(summary.textContent).toBe('筛选条件');fireEvent.click(summary);expect(disclosure.open).toBe(true)
 fireEvent.change(input,{target:{value}});const reads=fetch.mock.calls.length;fireEvent.click(summary);expect(disclosure.open).toBe(false);fireEvent.click(summary);expect(disclosure.open).toBe(true)
 expect(screen.getByLabelText(label)).toBe(input);expect(input).toHaveProperty('value',value);expect(fetch).toHaveBeenCalledTimes(reads)
})
it('pauses hidden operational reads and ignores an aborted response',async()=>{
 const deny=vi.fn();let resolve!:(value:Response)=>void
 fetch.mockImplementationOnce(()=>new Promise<Response>(r=>{resolve=r}))
 const {result,rerender}=renderHook(({active})=>useOperationsRead<{items:string[]}>('/api/v1/admin/users',deny,active),{initialProps:{active:false}})
 expect(fetch).not.toHaveBeenCalled();rerender({active:true});expect(fetch).toHaveBeenCalledTimes(1)
 rerender({active:false});await act(async()=>resolve(Response.json({items:['obsolete']})))
 expect(result.current.data).toBeNull()
})
it('separates account list and editor and retains drafts through admin tabs',async()=>{
 await start();fireEvent.click(screen.getByRole('button',{name:'编辑账号'}))
 expect(screen.getByLabelText('账号搜索').closest('[hidden]')).toBeTruthy()
 fireEvent.change(screen.getByLabelText('账号角色'),{target:{value:'admin'}})
 fireEvent.change(screen.getByLabelText('变更理由'),{target:{value:'Keep this reviewed role change'}})
 fireEvent.click(screen.getByRole('button',{name:'运行日志'}));fireEvent.click(screen.getByRole('button',{name:'账号管理'}))
 expect(screen.getByLabelText('账号角色')).toHaveProperty('value','admin')
 expect(screen.getByLabelText('变更理由')).toHaveProperty('value','Keep this reviewed role change')
 fireEvent.click(screen.getByRole('button',{name:'返回账号列表'}));expect(screen.getByLabelText('账号搜索')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'编辑账号'}));expect(screen.getByLabelText('变更理由')).toHaveProperty('value','Keep this reviewed role change')
})
it('removes retained privileged content after server role revocation',async()=>{
 await start();fireEvent.click(screen.getByRole('button',{name:'编辑账号'}))
 fireEvent.change(screen.getByLabelText('变更理由'),{target:{value:'Privileged draft'}})
 fireEvent.click(screen.getByRole('button',{name:'项目工作区'}));role='user'
 fireEvent.click(screen.getByRole('button',{name:'管理员'}))
 await waitFor(()=>expect(screen.queryByRole('button',{name:'管理员'})).toBeNull())
 expect(document.querySelector('textarea')).toBeNull()
 expect(document.body.textContent).not.toContain('other@example.test')
})
it('keeps an in-flight account operation mounted while switching views',async()=>{
 let resolve!:(value:Response)=>void;let signal:AbortSignal|undefined
 const normal=fetch.getMockImplementation()!
 fetch.mockImplementation((url:string,init?:RequestInit)=>init?.method==='PATCH'?new Promise<Response>(r=>{resolve=r;signal=init.signal??undefined}):normal(url))
 await start();fireEvent.click(screen.getByRole('button',{name:'编辑账号'}))
 fireEvent.change(screen.getByLabelText('账号角色'),{target:{value:'admin'}})
 fireEvent.change(screen.getByLabelText('变更理由'),{target:{value:'Approved role adjustment'}})
 fireEvent.click(screen.getByRole('button',{name:'保存账号变更'}));fireEvent.click(screen.getByRole('button',{name:'运行日志'}))
 expect(signal?.aborted).toBe(false)
 await act(async()=>resolve(Response.json({...account,admin_revision:4,role:'admin'})))
 expect(screen.getByRole('button',{name:'运行日志'}).getAttribute('aria-pressed')).toBe('true')
 fireEvent.click(screen.getByRole('button',{name:'账号管理'}));expect(screen.getByText('账号已更新，目标会话已撤销。')).toBeTruthy()
})

it('clears hidden account drafts and leave guards after session invalidation',async()=>{
 await start();fireEvent.click(screen.getByRole('button',{name:'编辑账号'}));fireEvent.change(screen.getByLabelText('变更理由'),{target:{value:'Unsaved private reason'}})
 fireEvent.click(screen.getByRole('button',{name:'项目工作区'}))
 const dirtyEvent=new Event('beforeunload',{cancelable:true});window.dispatchEvent(dirtyEvent);expect(dirtyEvent.defaultPrevented).toBe(true)
 act(()=>clearApiSession());expect(document.querySelector('textarea')).toBeNull()
 const cleanEvent=new Event('beforeunload',{cancelable:true});window.dispatchEvent(cleanEvent);expect(cleanEvent.defaultPrevented).toBe(false)
})
it('revokes cached administrator content on confirmed identity context changes',async()=>{
 const identity={id:'self',email:'self@example.test',role:'admin'}
 const {rerender}=render(<AuthIdentityContext.Provider value={identity}><OperationsWorkspace layered><p>Project</p></OperationsWorkspace></AuthIdentityContext.Provider>)
 fireEvent.click(screen.getByRole('button',{name:'管理员'}));await screen.findByText('other@example.test')
 fireEvent.click(screen.getByRole('button',{name:'项目工作区'}))
 rerender(<AuthIdentityContext.Provider value={{...identity,role:'user'}}><OperationsWorkspace layered><p>Project</p></OperationsWorkspace></AuthIdentityContext.Provider>)
 expect(document.body.textContent).not.toContain('other@example.test')
})
it('retains independent log filter drafts and applies explicit task links',async()=>{
 const safe={id:'t1',user_id:'other',project_id:'p1',task_type:'boxplot',phase:'compute',status:'failed',revision:1,allowed_actions:[],can_open_workspace:false,attempt_count:1}
 fetch.mockImplementation(async(url:string)=>url.includes('/admin/tasks')?Response.json(url.includes('/tasks?')?{items:[safe],total:1,page:1,page_size:10}:safe):baseFetch(url))
 await start();fireEvent.click(screen.getByRole('button',{name:'运行日志'}))
 fireEvent.change(screen.getByLabelText('请求标识'),{target:{value:'request-draft'}})
 fireEvent.click(screen.getByRole('button',{name:'操作审计'}));fireEvent.change(screen.getByLabelText('目标账号标识'),{target:{value:'audit-draft'}})
 fireEvent.click(screen.getByRole('button',{name:'请求日志'}));expect(screen.getByLabelText('请求标识')).toHaveProperty('value','request-draft')
 fireEvent.click(screen.getByRole('button',{name:'系统任务'}));fireEvent.click(await screen.findByRole('button',{name:'查看安全详情'}))
 expect(await screen.findByText('此任务属于其他账号，仅可查看运营信息。')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'应用筛选'})).toBeNull()
 expect(fetch.mock.calls.some(([url])=>url.endsWith('/workspace'))).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'查看关联日志'}));expect(screen.getByLabelText('任务标识')).toHaveProperty('value','t1')
 await waitFor(()=>expect(fetch.mock.calls.some(([url])=>url.includes('/logs?task_id=t1'))).toBe(true))
 fireEvent.change(screen.getByLabelText('请求标识'),{target:{value:'linked-task-draft'}})
 fireEvent.click(screen.getByRole('button',{name:'账号管理'}));fireEvent.click(screen.getByRole('button',{name:'运行日志'}))
 expect(screen.getByLabelText('请求标识')).toHaveProperty('value','linked-task-draft')
 expect(screen.getByLabelText('任务标识')).toHaveProperty('value','t1')
 fireEvent.click(screen.getByRole('button',{name:'操作审计'}));fireEvent.change(screen.getByLabelText('目标账号标识'),{target:{value:'retained-audit-draft'}})
 fireEvent.click(screen.getByRole('button',{name:'系统任务'}));fireEvent.click(screen.getByRole('button',{name:'查看关联日志'}))
 expect(screen.getByRole('button',{name:'请求日志'}).getAttribute('aria-pressed')).toBe('true')
 expect(screen.getByLabelText('请求标识')).toHaveProperty('value','linked-task-draft')
 expect(screen.getByLabelText('任务标识')).toHaveProperty('value','t1')
 fireEvent.click(screen.getByRole('button',{name:'操作审计'}));expect(screen.getByLabelText('目标账号标识')).toHaveProperty('value','retained-audit-draft')
})
it('keeps the own task layer and exact project deep link after returning through the list',async()=>{
 const safe={id:'t1',user_id:'self',project_id:'p1',task_type:'boxplot',phase:'compute',status:'failed',revision:1,allowed_actions:['retry'],can_open_workspace:true,attempt_count:1}
 fetch.mockImplementation(async(url:string)=>url.includes('/admin/tasks')?Response.json(url.includes('/tasks?')?{items:[safe],total:1,page:1,page_size:10}:safe):url.endsWith('/workspace')?Response.json({...workspaceFixture,task:{...taskFixture,status:'failed',display_status:'failed'},wait:null,allowed_actions:['retry']}):baseFetch(url))
 await start();fireEvent.click(screen.getByRole('button',{name:'系统任务'}));fireEvent.click(await screen.findByRole('button',{name:'查看安全详情'}))
 expect((await screen.findByRole('link',{name:'在项目中打开'})).getAttribute('href')).toBe('#project=p1&section=tasks&task=t1')
 fireEvent.click(screen.getByRole('button',{name:'打开本人的任务详情'}));await screen.findByRole('heading',{name:'任务详情'})
 fireEvent.click(screen.getByRole('button',{name:'待处理'}));fireEvent.click(screen.getByRole('button',{name:'返回任务安全详情'}));fireEvent.click(screen.getByRole('button',{name:'返回任务列表'}))
 fireEvent.click(await screen.findByRole('button',{name:'查看安全详情'}));fireEvent.click(await screen.findByRole('button',{name:'打开本人的任务详情'}))
 expect(screen.getByRole('button',{name:'待处理'}).getAttribute('aria-current')).toBe('page')
})
it('reopens the same explicit account audit without resetting either log filter draft',async()=>{
 fetch.mockImplementation(async(url:string,init?:RequestInit)=>init?.method==='PATCH'?Response.json({...account,role:'admin',admin_revision:4}):baseFetch(url))
 await start();fireEvent.click(screen.getByRole('button',{name:'编辑账号'}));fireEvent.change(screen.getByLabelText('账号角色'),{target:{value:'admin'}});fireEvent.change(screen.getByLabelText('变更理由'),{target:{value:'Reviewed account adjustment'}});fireEvent.click(screen.getByRole('button',{name:'保存账号变更'}));fireEvent.click(await screen.findByRole('button',{name:'查看操作审计'}))
 expect(screen.getByRole('button',{name:'操作审计'}).getAttribute('aria-pressed')).toBe('true');expect(screen.getByLabelText('目标账号标识')).toHaveProperty('value','other');fireEvent.change(screen.getByLabelText('操作者账号标识'),{target:{value:'actor-draft'}})
 fireEvent.click(screen.getByRole('button',{name:'请求日志'}));fireEvent.change(screen.getByLabelText('请求标识'),{target:{value:'retained-request-draft'}});fireEvent.click(screen.getByRole('button',{name:'账号管理'}));fireEvent.click(screen.getByRole('button',{name:'查看操作审计'}))
 expect(screen.getByRole('button',{name:'操作审计'}).getAttribute('aria-pressed')).toBe('true');expect(screen.getByLabelText('操作者账号标识')).toHaveProperty('value','actor-draft');expect(screen.getByLabelText('目标账号标识')).toHaveProperty('value','other')
 fireEvent.click(screen.getByRole('button',{name:'请求日志'}));expect(screen.getByLabelText('请求标识')).toHaveProperty('value','retained-request-draft')
})
