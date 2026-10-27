import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import SavedUsageSummaries from './SavedUsageSummaries'
import {setApiSession,clearApiSession} from '../../shared/api/client'
import {setLocale} from '../../shared/i18n'
const summary={call_count:2,estimated_micro_usd:10,estimated_unknown_count:1,actual_micro_usd:null,actual_known_micro_usd:0,actual_unknown_count:2,reconciled_count:0,partial_count:0,pending_count:2,not_applicable_count:0,reserved_micro_usd:5,accounted_micro_usd:0,tool_call_count:2,tool_call_unknown_count:1,configured_tool_call_count:2,observed_actual_tool_uses:2,actual_tool_usage_known_calls:1,actual_tool_usage_unknown_calls:1,input_tokens:{known:1,unknown_count:1},output_tokens:{known:1,unknown_count:1},total_tokens:{known:2,unknown_count:1}}
const capture={id:'s1',created_at:'2026-10-25T00:00:00Z',asof:'2026-10-25T00:00:00Z',source_revision:'admin-usage-capture-v1',sha256:'a'.repeat(64),filters:{model:'exact',group_by:'model'},result:{summary,by_provenance:{},groups:[{key:'exact',summary,by_provenance:{}}],group_by:'model',coverage:{historical_missing_is_zero:false,immutable_recomputed:['tokens'],captured_mutable:['tool_evidence'],excludes:['budget_balances']}},items:[],total:12,page:1,page_size:10,group_total:1,group_page:1,group_page_size:10}
let mock:ReturnType<typeof vi.fn>,verified=true,denied=false
beforeEach(()=>{verified=true;denied=false;setApiSession('csrf','admin');mock=vi.fn(async(url:string,init?:RequestInit)=>{if(denied)return Response.json({detail:{code:'forbidden'}},{status:403});if(url.endsWith('/verify'))return Response.json({verified,errors:verified?[]:['usage_source_mismatch'],asof:capture.asof,source_revision:capture.source_revision,captured_mutable_fields:['tool_evidence']});if(init?.method==='POST')return Response.json(capture);if(url.includes('/s1?'))return Response.json(capture);return Response.json({items:[capture],page:1,page_size:10,total:12})});vi.stubGlobal('fetch',mock)})
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it('saves applied filters, displays cutoff and unknown costs, pages independently and verifies sources',async()=>{
 render(<SavedUsageSummaries filters={{model:'exact',from:'2026-10-01T00:00:00Z',group_by:'model',page:'9'}} onForbidden={()=>{}}/>)
 await screen.findByRole('button',{name:'查看保存汇总'});fireEvent.click(screen.getByRole('button',{name:'保存用量汇总'}));await screen.findByText('用量汇总已保存。')
 const saved=mock.mock.calls.find(([,init])=>init?.method==='POST')!;expect(JSON.parse(saved[1].body)).toEqual({model:'exact',from:'2026-10-01T00:00:00Z',group_by:'model'})
 fireEvent.click((await screen.findAllByRole('button',{name:'查看保存汇总'}))[0]);await screen.findByText('admin-usage-capture-v1');expect(screen.getAllByText('未知（尚未完整核对）').length).toBeGreaterThan(0)
 fireEvent.click(screen.getByRole('button',{name:'下一页保存调用'}));await waitFor(()=>expect(mock.mock.calls.some(([u])=>u.includes('/s1?')&&u.includes('page=2')&&u.includes('group_page=1'))).toBe(true))
 fireEvent.click(screen.getByRole('button',{name:'核对保存汇总'}));await screen.findByText('保存汇总核对一致。');expect(screen.getByText('汇总与原来源核对不代表费用已结算。')).toBeTruthy()
})
it('distinguishes a failed verification and clears privileged data on session change',async()=>{
 setLocale('en');render(<SavedUsageSummaries filters={{}} onForbidden={()=>{}}/>);fireEvent.click((await screen.findAllByRole('button',{name:'View saved summary'}))[0]);await screen.findByText('admin-usage-capture-v1');verified=false;fireEvent.click(screen.getByRole('button',{name:'Verify saved summary'}));await screen.findByText('Verification found a mismatch in the saved summary.');expect(screen.queryByText('usage_source_mismatch')).toBeNull();act(()=>clearApiSession());expect(screen.queryByText('admin-usage-capture-v1')).toBeNull()
})
it('removes the saved capture on a server denial',async()=>{const forbidden=vi.fn();render(<SavedUsageSummaries filters={{}} onForbidden={forbidden}/>);fireEvent.click((await screen.findAllByRole('button',{name:'查看保存汇总'}))[0]);await screen.findByText('admin-usage-capture-v1');denied=true;fireEvent.click(screen.getByRole('button',{name:'核对保存汇总'}));await waitFor(()=>expect(forbidden).toHaveBeenCalled());expect(screen.queryByText('admin-usage-capture-v1')).toBeNull()})
it('layers list, detail and generation while retaining a pending save across hidden views',async()=>{
 let finish!:(value:Response)=>void
 mock.mockImplementation(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST')return new Promise<Response>(resolve=>{finish=resolve})
  if(url.includes('/s1?'))return Response.json(capture)
  return Response.json({items:[capture],total:12})
 })
 const register=vi.fn((_guard:()=>boolean,_isDirty?:()=>boolean)=>()=>{})
 const view=render(<SavedUsageSummaries filters={{model:'exact'}} layered registerLeaveGuard={register} onForbidden={()=>{}} />)
 fireEvent.click((await screen.findAllByRole('button',{name:'查看保存汇总'}))[0])
 await screen.findByText('admin-usage-capture-v1')
 expect(screen.queryByRole('button',{name:'查看保存汇总'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'生成参数'}))
 expect(screen.getByText('将按当前已应用的用量筛选生成保存汇总。')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'保存用量汇总'}))
 await waitFor(()=>expect(finish).toBeTruthy())
 const save=mock.mock.calls.find(([,init])=>init?.method==='POST')!
 expect(register.mock.calls.at(-1)?.[1]?.()).toBe(true)
 view.rerender(<SavedUsageSummaries filters={{model:'exact'}} active={false} layered registerLeaveGuard={register} onForbidden={()=>{}} />)
 expect(save[1].signal.aborted).toBe(false)
 await act(async()=>finish(Response.json(capture)))
 expect(register.mock.calls.at(-1)?.[1]?.()).toBe(false)
})
it('aborts an unfinished detail GET when moving to another saved-summary view',async()=>{
 mock.mockImplementation(async(url:string)=>url.includes('/s1?')?new Promise<Response>(()=>{}):Response.json({items:[capture],total:12}))
 render(<SavedUsageSummaries filters={{}} layered onForbidden={()=>{}} />)
 fireEvent.click((await screen.findAllByRole('button',{name:'查看保存汇总'}))[0])
 const detail=mock.mock.calls.find(([url])=>url.includes('/s1?'))!
 expect(detail[1].signal.aborted).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'生成参数'}))
 expect(detail[1].signal.aborted).toBe(true)
 expect(screen.getByRole('button',{name:'保存用量汇总'}).hasAttribute('disabled')).toBe(false)
})
