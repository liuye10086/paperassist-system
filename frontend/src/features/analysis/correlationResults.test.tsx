import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import StatisticsResults from './StatisticsResults'
import { validStatisticsContext } from './statisticsContext'
import { correlationResult } from './correlationFixtures'
import CorrelationResults from './CorrelationResults'
import {setLocale} from '../../shared/i18n'
import type {CorrelationResult} from './correlationResult'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
test('validates frozen correlation statistics and rejects a downgraded method or crossed plan',()=>{
 expect(validStatisticsContext(correlationResult,'/api/v1/projects/p1/files/f1',correlationResult.analysis_plan)).toBe(true)
 expect(validStatisticsContext({...correlationResult,schema_version:2},'/api/v1/projects/p1/files/f1')).toBe(false)
 expect(validStatisticsContext({...correlationResult,statistics:{...correlationResult.statistics,coefficient:2}},'/api/v1/projects/p1/files/f1')).toBe(false)
})
test('a configured correlation plan has an accurate empty statistics state',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({current_revision:2,is_current:true,result:null})))
 render(<StatisticsResults base="/api/v1/projects/p1/files/f1" savedRevision={2} savedSelection={correlationResult.selection} savedSource={correlationResult.source} savedPlan={correlationResult.analysis_plan} fieldsMatch={true} disabled={false} onBusyChange={()=>{}}/>)
 expect(await screen.findByText('尚未执行当前配置的相关分析。')).toBeTruthy()
})
test.each(['zh-CN','en'] as const)('matrix presents common n and coefficients without significance markers in %s',locale=>{
 setLocale(locale)
 const selection={...correlationResult.selection,mode:'matrix' as const}
 const result={...correlationResult,selection,analysis_context:{...correlationResult.analysis_context,plan:{...correlationResult.analysis_context.plan,selection},method:{...correlationResult.analysis_context.method,parameters:selection}},statistics:{...correlationResult.statistics,mode:'matrix',coefficient:null,matrix:[[1,0.8],[0.8,1]],p_value:{value:null,method:null,reason:'exploratory_matrix'},confidence_interval:{low:null,high:null,level:0.95,method:null,reason:'exploratory_matrix'}}} as CorrelationResult
 expect(validStatisticsContext(result,'/api/v1/projects/p1/files/f1')).toBe(true)
 expect(validStatisticsContext({...result,statistics:{...result.statistics,matrix:[[1,0.8],[0.7,1]]}},'/api/v1/projects/p1/files/f1')).toBe(false)
 render(<CorrelationResults result={result}/>)
 expect(screen.getByRole('table',{name:locale==='en'?'Correlation coefficient matrix':'相关系数矩阵'})).toBeTruthy()
 expect(screen.queryByText(locale==='en'?'Two-sided P value':'双侧 P 值')).toBeNull()
 expect(document.body.textContent).not.toContain('*')
})
test('displays actual coefficient, n, two-sided P and Fisher interval',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/analysis-result')?{current_revision:2,is_current:true,result:correlationResult}:url.endsWith('/openai/config')?{configured:false,message:'',model:null}:{current_revision:2,is_current:true,figure:null,job:null,task:null})))
 render(<StatisticsResults base="/api/v1/projects/p1/files/f1" savedRevision={2} savedSource={correlationResult.source} savedPlan={correlationResult.analysis_plan} fieldsMatch={true} disabled={false} onBusyChange={()=>{}}/>)
 expect(await screen.findByText('相关系数')).toBeTruthy()
 expect(screen.getByText('双侧 P 值')).toBeTruthy()
 expect(screen.getByText('95% Fisher 区间')).toBeTruthy()
 expect(screen.getByRole('heading',{name:'散点图'})).toBeTruthy()
})
