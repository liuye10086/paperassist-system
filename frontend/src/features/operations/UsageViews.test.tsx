import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import UsagePanel from './UsagePanel'
import ProjectModelUsage from '../model-usage/ProjectModelUsage'
import TaskModelUsage from '../model-usage/TaskModelUsage'
import { usageFixture } from '../tasks/taskFixtures'
const reads=vi.hoisted(()=>vi.fn())
vi.mock('./operationsApi',async original=>{
 const api=await original<typeof import('./operationsApi')>()
 const summary={call_count:3,tool_call_count:2,tool_call_unknown_count:1}
 return {...api,useOperationsRead:(url:string,_forbidden:()=>void,active=true)=>{
  reads(url,active)
  return {loading:false,error:'',reload:vi.fn(),data:url.includes('/storage')?null:url.includes('/summaries')?{items:[],total:0}:url.includes('/metrics')?{coverage:{},requests:0,errors:0,model_calls:3}: {summary,by_provenance:{},quota:{configured:false},period:{},budgets:[],groups:[],items:[],total:21,group_total:101}}
 }}
})
afterEach(()=>{cleanup();reads.mockClear();vi.unstubAllGlobals()})
it('layers ordinary usage, preserves filter drafts, and gates inactive reads',()=>{
 const view=render(<UsagePanel admin={false} onForbidden={()=>{}} />)
 expect(screen.getByRole('navigation',{name:'用量工作视图'})).toBeTruthy()
 expect(screen.queryByRole('region',{name:'逐次调用'})).toBeNull()
 fireEvent.click(screen.getByText('筛选条件'));fireEvent.change(screen.getByLabelText('精确模型'),{target:{value:'exact-model'}})
 fireEvent.click(screen.getByRole('button',{name:'逐次调用'}))
 expect(screen.getByRole('region',{name:'逐次调用'})).toBeTruthy()
 expect(screen.getByLabelText('精确模型')).toHaveProperty('value','exact-model')
 expect(screen.queryByRole('button',{name:'已保存的用量汇总'})).toBeNull()
 view.rerender(<UsagePanel admin={false} active={false} onForbidden={()=>{}} />)
 expect(reads.mock.calls.at(-1)?.[1]).toBe(false)
})
it('admin saved summaries and request metrics load only when visited and stop when hidden',()=>{
 render(<UsagePanel admin onForbidden={()=>{}} />)
 expect(reads.mock.calls.some(([url])=>url.includes('/metrics')||url.includes('/summaries'))).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'已保存的用量汇总'}))
 expect(reads.mock.calls.some(([url,active])=>url.includes('/summaries')&&active)).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'运行指标'}))
 expect(reads.mock.calls.some(([url,active])=>url.includes('/metrics')&&active)).toBe(true)
 expect(reads.mock.calls.filter(([url])=>url.includes('/summaries')).at(-1)?.[1]).toBe(false)
})
it('layers project and task budgets and calls without changing call sources',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(usageFixture)))
 render(<TaskModelUsage taskId="t1" layered />)
 await screen.findByRole('navigation',{name:'任务用量工作视图'})
 await screen.findByText('任务内部估算')
 expect(screen.queryByRole('heading',{name:'任务预算'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'预算额度'}))
 expect(screen.getByText('任务预算')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'逐次调用'}))
 expect(await screen.findByText('test-model')).toBeTruthy()
 expect(within(screen.getByText('test-model').closest('tr')!).getByText('待核对')).toBeTruthy()
 cleanup()
 render(<ProjectModelUsage projectId="p1" layered />)
 await screen.findByRole('navigation',{name:'项目用量工作视图'})
 expect(screen.queryByRole('table')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'逐次调用'}))
 expect(await screen.findByRole('table')).toBeTruthy()
})

it('retains independent group and call pages and applies the exact model and UTC range together',()=>{
 render(<UsagePanel admin onForbidden={()=>{}} />)
 fireEvent.click(screen.getByText('筛选条件'))
 fireEvent.change(screen.getByLabelText('精确模型'),{target:{value:' exact-model '}})
 fireEvent.change(screen.getByLabelText('起始时间'),{target:{value:'2026-10-01T08:00'}})
 fireEvent.change(screen.getByLabelText('结束时间'),{target:{value:'2026-10-02T08:00'}})
 fireEvent.click(screen.getByRole('button',{name:'应用筛选'}))
 const getUsage=()=>new URL(reads.mock.calls.filter(([url])=>url.includes('/usage?')).at(-1)![0],'https://test')
 expect(getUsage().searchParams.get('model')).toBe('exact-model')
 expect(getUsage().searchParams.get('from')).toBe(new Date('2026-10-01T08:00').toISOString())
 expect(getUsage().searchParams.get('to')).toBe(new Date('2026-10-02T08:00').toISOString())
 fireEvent.click(screen.getByRole('button',{name:'聚合明细'}))
 fireEvent.click(screen.getByRole('button',{name:'下一页聚合'}))
 expect(getUsage().searchParams.get('group_page')).toBe('2')
 expect(getUsage().searchParams.get('page')).toBe('1')
 fireEvent.click(screen.getByRole('button',{name:'逐次调用'}))
 fireEvent.click(screen.getByRole('button',{name:'下一页调用'}))
 expect(getUsage().searchParams.get('group_page')).toBe('2')
 expect(getUsage().searchParams.get('page')).toBe('2')
 fireEvent.click(screen.getByRole('button',{name:'综合汇总'}))
 fireEvent.click(screen.getByRole('button',{name:'应用筛选'}))
 expect(getUsage().searchParams.get('page')).toBe('1')
 expect(getUsage().searchParams.get('group_page')).toBe('1')
})
it('keeps storage in its own visited view, retaining its draft and gating hidden reads',()=>{
 render(<UsagePanel admin={false} onForbidden={()=>{}} />)
 expect(screen.queryByRole('region',{name:'本人存储'})).toBeNull()
 expect(reads.mock.calls.some(([url,active])=>url.includes('/storage')&&active)).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'本人存储'}))
 fireEvent.change(screen.getByLabelText('本人项目标识（可选）'),{target:{value:'project-draft'}})
 expect(reads.mock.calls.some(([url,active])=>url.includes('/me/storage')&&active)).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'综合汇总'}))
 expect(reads.mock.calls.filter(([url])=>url.includes('/me/storage')).at(-1)?.[1]).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'本人存储'}))
 expect(screen.getByLabelText('本人项目标识（可选）')).toHaveProperty('value','project-draft')
})

it('starts with collapsed filters and keeps an unsubmitted draft through close and view changes',()=>{
 render(<UsagePanel admin onForbidden={()=>{}} />)
 const filters=screen.getByText('筛选条件').closest('details')!
 expect(filters.open).toBe(false)
 expect(screen.getByRole('region',{name:'综合汇总'})).toBeTruthy()
 fireEvent.click(screen.getByText('筛选条件'))
 fireEvent.change(screen.getByLabelText('精确模型'),{target:{value:'unapplied-model'}})
 fireEvent.click(screen.getByText('筛选条件'))
 expect(filters.open).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'来源口径'}))
 fireEvent.click(screen.getByRole('button',{name:'综合汇总'}))
 fireEvent.click(screen.getByText('筛选条件'))
 expect(screen.getByLabelText('精确模型')).toHaveProperty('value','unapplied-model')
 const latest=reads.mock.calls.filter(([url])=>url.includes('/usage?')).at(-1)![0]
 expect(new URL(latest,'https://test').searchParams.has('model')).toBe(false)
})
