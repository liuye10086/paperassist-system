import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import useProjectFlow, { flowBlockReason } from './useProjectFlow'
import type { Project } from './projectTypes'

vi.mock('../research-results/api',()=>({useResearchRead:()=>({data:null,error:'',refresh:vi.fn()})}))
afterEach(cleanup)
const project:Project={id:'p1',name:'研究',research_topic:'分组',project_type:'research',file_count:1,created_at:'2026-11-03',updated_at:'2026-11-03'}
it('requires saved requirements and the working step before opening results',()=>{
  expect(flowBlockReason(3,{hasFiles:true,requirementSaved:false,reached:2,existingResults:false})).toContain('选择并保存需求')
  expect(flowBlockReason(4,{hasFiles:true,requirementSaved:true,reached:2,existingResults:false})).toContain('第 4 步')
  expect(flowBlockReason(4,{hasFiles:true,requirementSaved:true,reached:3,existingResults:false})).toBe('')
})
it('accepts a successfully saved writing-only selection before its continuation callback navigates',()=>{
  const {result}=renderHook(()=>useProjectFlow(project,'overview','requirements'))
  expect(result.current.reason('manuscripts')).not.toBe('')
  act(()=>{result.current.acceptServices(['sci_draft']);expect(result.current.reason('manuscripts')).toBe('')})
  expect(result.current.hasAnalysis).toBe(false)
  expect(result.current.reason('analysis')).toContain('未选择数据分析')
})
it('retains reached pages within a project and isolates that state when changing projects',()=>{
  const {result,rerender}=renderHook(({id,section}:{id:string;section:'artifacts'|'overview'})=>useProjectFlow({...project,id},section,'settings'),{initialProps:{id:'p1',section:'artifacts'}})
  rerender({id:'p1',section:'overview'});expect(result.current.reason('artifacts')).toBe('')
  rerender({id:'p2',section:'overview'});expect(result.current.reason('artifacts')).not.toBe('')
})
