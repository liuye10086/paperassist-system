import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {setLocale} from '../../shared/i18n'
import RequestMetrics from './RequestMetrics'

vi.mock('./operationsApi',async(importOriginal)=>({
 ...await importOriginal<typeof import('./operationsApi')>(),
 useOperationsRead:()=>({loading:false,error:'',reload:vi.fn(),data:{coverage:{started_at:'2026-10-28T00:00:00Z'},requests:8,errors:2,rate_limited:1,retry_requests:3,resume_requests:1,recovery_operation_unknown_requests:2,model_calls:0,tool_calls:0}}),
}))
afterEach(()=>{cleanup();setLocale('zh-CN')})
it.each(['zh-CN','en'] as const)('explains HTTP intent and historical unknown recovery (%s)',locale=>{
 setLocale(locale)
 render(<RequestMetrics onForbidden={()=>{}} />)
 const label=locale==='en'?'Recovery requests with unknown operation':'恢复操作未知的请求'
 expect(screen.getByText(label).nextElementSibling?.textContent).toBe('2')
 expect(screen.getByText(locale==='en'?
  'HTTP requests include rejected requests and idempotent replays; retry and resume counts describe validated intent, not task failures or execution attempts.':
  'HTTP 请求包含被拒绝请求和幂等重放；重试、继续按已验证操作统计，不代表任务失败数或执行尝试数。')).toBeTruthy()
 expect(screen.getByText(locale==='en'?
  'Historical or unvalidated recovery operations remain unknown; missing evidence is not zero.':
  '历史未记录或未通过校验的恢复操作保留未知，缺失不按零。')).toBeTruthy()
})
