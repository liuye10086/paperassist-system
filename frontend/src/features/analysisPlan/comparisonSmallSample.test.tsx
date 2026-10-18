import {afterEach,expect,test,vi} from 'vitest'
import {cleanup,render,screen} from '@testing-library/react'
import AnalysisPlanReview from './AnalysisPlanReview'
import {v3Review} from './batch02Fixtures'
import {resultForMethod} from '../analysis/comparisonFixtures'
import {setLocale,translate} from '../../shared/i18n'
import {issueDescription} from './diagnostics'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
test.each(['zh-CN','en'] as const)('comparison small sample explanation describes instability without false fewer-than-two claim (%s)',async language=>{
 setLocale(language);const result=resultForMethod('welch_t')
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...v3Review,selection:result.selection,research_request:result.analysis_context.plan.research_request,check:{...result.analysis_context.plan.check,issues:[{id:'small_sample:all',code:'small_sample',severity:'warning',field:null,count:10,coordinates:[],message:'untrusted raw message',allowed_resolutions:['accept_partial_metrics']}]}})))
 render(<AnalysisPlanReview projectId="p1" taskId="t1"/>)
 expect(await screen.findByText(language==='en'?'At least one group has fewer than 10 complete observations; small-sample inference may be unstable.':'至少一组不足 10 条完整观察，小样本推断可能不稳定。')).toBeTruthy()
 expect(screen.getByRole('option',{name:language==='en'?'Acknowledge that small-sample inference may be unstable':'知悉小样本推断可能不稳定'}).getAttribute('value')).toBe('accept_partial_metrics')
 expect(document.body.textContent).not.toMatch(/不足2条|fewer than 2|partial metrics|untrusted raw message/)
})
test('legacy descriptive small-sample diagnosis retains its original meaning',()=>{
 expect(issueDescription('small_sample','ignored')).toBe('部分分组或全部数据不足2条完整记录，部分指标无法计算。')
})
test.each(['zh-CN','en'] as const)('paired comparison small sample diagnosis counts complete pairs (%s)',language=>{
 setLocale(language)
 const result=resultForMethod('paired_t')
 expect(translate(issueDescription('small_sample','ignored',result.selection as never))).toBe(language==='en'?'There are fewer than 10 complete pairs; small-sample inference may be unstable.':'不足 10 个完整对，小样本推断可能不稳定。')
})
