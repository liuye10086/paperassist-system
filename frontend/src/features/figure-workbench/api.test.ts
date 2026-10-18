import {afterEach,expect,test,vi} from 'vitest'
import {apiError,translate,setLocale} from '../../shared/i18n'
import {workbenchRequest} from './api'
afterEach(()=>{vi.unstubAllGlobals();setLocale('zh-CN')})
test('projection failure maps only public reasons to specific bilingual guidance',()=>{
 setLocale('en')
 expect(translate(apiError({detail:{code:'figure_projection_invalid',params:{reason:'missing_group'}}},'请求失败，请重试。'))).toBe('Grouping values are missing. Complete the data or explicitly confirm their exclusion.')
 expect(translate(apiError({detail:{code:'figure_projection_invalid',params:{reason:'private-server-secret'}}},'请求失败，请重试。'))).not.toContain('private-server-secret')
})
test('abort releases a request even when a transport ignores its signal',async()=>{
 vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(()=>{})))
 const c=new AbortController();let settled=false
 const request=workbenchRequest('/api/v1/projects/p1/report-collections',c.signal,(v):v is object=>typeof v==='object').catch(()=>{settled=true})
 c.abort();await Promise.race([request,new Promise(resolve=>setTimeout(resolve,20))])
 expect(settled).toBe(true)
})
