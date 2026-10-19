import {it,expect,afterEach} from 'vitest'
import {apiError,setLocale,translate} from '../../shared/i18n'
afterEach(()=>setLocale('zh-CN'))
it.each(['zh-CN','en'] as const)('maps public NCBI errors to local guidance in %s',locale=>{
 setLocale(locale)
 expect(translate(apiError({code:'ncbi_not_configured'},'请求失败，请重试。'))).toContain('NCBI')
 expect(translate(apiError({code:'ncbi_response_invalid'},'请求失败，请重试。'))).toContain('NCBI')
})

it.each([['zh-CN','该论述已使用一轮补搜（最多20篇），请继续已有任务。'],['en','This claim already has one supplementary search (up to 20 candidates). Continue the existing task.']] as const)('explains the supplementary round limit in %s', (locale,expected)=>{
 setLocale(locale)
 expect(translate(apiError({code:'literature_supplement_limit'},'请求失败，请重试。'))).toBe(expected)
})
