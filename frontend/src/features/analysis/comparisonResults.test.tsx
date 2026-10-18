import {afterEach,expect,test,vi} from 'vitest'
import {cleanup,render,screen} from '@testing-library/react'
import StatisticsResults from './StatisticsResults'
import {comparisonResult} from './comparisonFixtures'
import {setLocale} from '../../shared/i18n'
import ComparisonResults from './ComparisonResults'
import {resultForMethod} from './comparisonFixtures'
import type {ComparisonResult} from './comparisonResult'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
test('comparison results render local numeric facts and row exclusions without technical identities',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>String(input).endsWith('/analysis-result')?new Response(JSON.stringify({current_revision:2,is_current:true,result:comparisonResult})):new Response(JSON.stringify({current_revision:2,is_current:true,figure:null,job:null,configured:false,model:null}))))
 render(<StatisticsResults base="/api/v1/projects/p1/files/f1" savedRevision={2} savedSelection={comparisonResult.selection as never} savedSource={comparisonResult.source as never} fieldsMatch disabled={false} onBusyChange={()=>{}}/>)
 expect(await screen.findByText('比较结果')).toBeTruthy()
 expect(screen.getByText('纳入 6 条独立观察；排除 1 行。')).toBeTruthy()
 expect(screen.getByText('均值差')).toBeTruthy()
 expect(screen.getByText('普通 95% 置信区间')).toBeTruthy()
 expect(screen.getByText('来源行 8 · D8 · 未纳入该组')).toBeTruthy()
 expect(screen.queryByText(comparisonResult.analysis_plan.sha256)).toBeNull()
 expect(screen.queryByText(comparisonResult.id)).toBeNull()
})
test('paired rank result states complete-pair n, direction and unavailable rank interval in English',()=>{
 setLocale('en');render(<ComparisonResults result={resultForMethod('wilcoxon') as ComparisonResult}/>)
 expect(screen.getByText('Included 5 complete pairs; excluded 0 rows.')).toBeTruthy()
 expect(screen.getByText('Difference direction: Before − After.')).toBeTruthy()
 expect(screen.getAllByText('Confidence intervals for rank effects are not implemented in this batch.').length).toBeGreaterThan(0)
 expect(screen.getByText('Rank-biserial correlation')).toBeTruthy()
 expect(screen.getByText('Single comparison')).toBeTruthy()
 expect(document.body.textContent).not.toMatch(/配对|差值|未实现/)
})
test('multiple-group result displays every predeclared Holm pair and ordinary interval caveat',()=>{
 render(<ComparisonResults result={resultForMethod('welch_anova') as ComparisonResult}/>)
 expect(screen.getByText('比较族包含 3 个预先声明的组对；α = 0.05。')).toBeTruthy()
 expect(screen.getByText('Treatment − Control')).toBeTruthy()
 expect(screen.getByText('Treatment − Third')).toBeTruthy()
 expect(screen.getByText('Control − Third')).toBeTruthy()
 expect(screen.getAllByText('组对区间是普通区间，未经多重比较调整，不是同时置信区间。').length).toBeGreaterThan(0)
 expect(screen.getByText('总体检验没有单一效应量。')).toBeTruthy()
 expect(screen.getByText('总体检验没有单一区间。')).toBeTruthy()
})
