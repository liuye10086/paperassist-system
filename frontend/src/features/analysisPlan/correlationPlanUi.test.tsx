import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisPlanReview from './AnalysisPlanReview'
import { v3Review } from './batch02Fixtures'
import ResearchRequestSummary from './ResearchRequestSummary'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
test('shows correlation choices and requires a separate plan approval after edits',async()=>{
 const fetch=vi.fn(async()=>Response.json(v3Review));vi.stubGlobal('fetch',fetch)
 render(<AnalysisPlanReview projectId="p1" taskId="t1" />)
 expect(await screen.findByText('Pearson')).toBeTruthy()
 await userEvent.click(screen.getByRole('button',{name:'修改研究需求与字段'}))
 expect(screen.getByLabelText('相关路径')).toBeTruthy()
 expect(screen.getByLabelText('每行代表一个独立观察单位')).toBeTruthy()
 await userEvent.selectOptions(screen.getByLabelText('计划方法'),'descriptive')
 expect(screen.getByLabelText('数值列')).toBeTruthy()
 expect(document.body.textContent).not.toContain('private-id')
})
test('empty requirements follow the correlation method while explicit historical wording remains unchanged',()=>{
 const view=render(<ResearchRequestSummary value={v3Review.research_request} selection={v3Review.selection}/>)
 expect(screen.getByText('Pearson 单对相关与散点图')).toBeTruthy()
 view.rerender(<ResearchRequestSummary value={{...v3Review.research_request,output_requirements:'总体及分组描述统计'}} selection={v3Review.selection}/>)
 expect(screen.getByText('总体及分组描述统计')).toBeTruthy()
})
test('waiting input exposes missing correlation assumptions and cannot approve',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...v3Review,task:{...v3Review.task,status:'waiting_input',display_status:'waiting_input'},check:{...v3Review.check,research_missing:['independent_observations']}})))
 render(<AnalysisPlanReview projectId="p1" taskId="t1"/>)
 expect(await screen.findByLabelText('每行代表一个独立观察单位')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'确认并发布分析计划'})).toBeNull()
})
