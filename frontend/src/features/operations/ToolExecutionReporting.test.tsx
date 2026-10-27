import {cleanup,render,screen,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {setLocale} from '../../shared/i18n'
import UsagePanel from './UsagePanel'
import LogsPanel from './LogsPanel'
vi.mock('./operationsApi',async(importOriginal)=>{
 const original=await importOriginal<typeof import('./operationsApi')>()
 const summary={call_count:3,tool_call_count:2,tool_call_unknown_count:1,configured_tool_call_count:3,observed_actual_tool_uses:2,actual_tool_usage_known_calls:2,actual_tool_usage_unknown_calls:1}
 return {...original,useOperationsRead:(url:string)=>({loading:false,error:null,reload:vi.fn(),data:url.includes('/storage')?null:url.includes('/usage')?{summary,by_provenance:{},quota:{configured:false},period:{},budgets:[],groups:[],items:[],total:0,group_total:0}:url.includes('/metrics')?{coverage:{},requests:0,errors:0,rate_limited:0,retry_requests:0,resume_requests:0,model_calls:3,tool_calls:2,tool_calls_unknown_count:1}: {coverage:{},items:[],total:0}})}
})
it('separates configured tool calls, observed uses and unknown calls in admin usage',()=>{
 render(<UsagePanel admin onForbidden={()=>{}} />)
 const combined=screen.getByRole('region',{name:'综合汇总'})
 for(const [label,value] of [['配置允许工具的模型调用数','3'],['已观测实际工具使用','2'],['实际工具使用未知的调用数','1']])expect(within(combined).getByText(label).nextElementSibling?.textContent).toBe(value)
 expect(screen.getByText('全站请求指标使用独立时间筛选，不随模型用量筛选变化。')).toBeTruthy()
})
it('does not offer saved summaries or site-wide request metrics to ordinary usage readers',()=>{
 render(<UsagePanel admin={false} onForbidden={()=>{}} />)
 expect(screen.queryByRole('button',{name:'保存用量汇总'})).toBeNull();expect(screen.queryByText('全站请求指标使用独立时间筛选，不随模型用量筛选变化。')).toBeNull()
})
afterEach(()=>{cleanup();setLocale('zh-CN')})
it.each(['zh-CN','en'] as const)('shows known tool executions and unknown calls in usage and metrics (%s)',locale=>{
 setLocale(locale)
 const expected=locale==='en'?'Known executions 2; unknown for 1 calls':'已知执行 2 次；1 次调用的执行次数未知'
 render(<UsagePanel admin onForbidden={()=>{}} />)
 expect(within(screen.getByRole('region',{name:locale==='en'?'Combined summary':'综合汇总'})).getByText(expected)).toBeTruthy()
 cleanup()
 render(<LogsPanel onForbidden={()=>{}} auditTarget="" taskId="" />)
 expect(screen.getByText(expected)).toBeTruthy()
})
