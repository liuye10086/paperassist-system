import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import useProjectFlow, { flowBlockReason } from './useProjectFlow'
import type { Project } from './projectTypes'

vi.mock('../research-results/api',()=>({useResearchRead:()=>({data:null,error:'',refresh:vi.fn()})}))
afterEach(cleanup)
const project:Project={id:'p1',name:'研究',research_topic:'分组',project_type:'research',file_count:1,created_at:'2026-11-03',updated_at:'2026-11-03'}
it('requires saved requirements for new analysis while leaving results viewable',()=>{
  expect(flowBlockReason(3,{hasFiles:true,requirementSaved:false,reached:2,existingResults:false})).toContain('选择并保存需求')
  expect(flowBlockReason(4,{hasFiles:true,requirementSaved:true,reached:2,existingResults:false})).toBe('')
  expect(flowBlockReason(4,{hasFiles:true,requirementSaved:true,reached:3,existingResults:false})).toBe('')
})
it('accepts a successfully saved writing-only selection before its continuation callback navigates',()=>{
  const {result}=renderHook(()=>useProjectFlow(project,'overview','requirements'))
  expect(result.current.reason('manuscripts')).toBe('')
  act(()=>{result.current.acceptServices(['sci_draft']);expect(result.current.reason('manuscripts')).toBe('')})
  expect(result.current.hasAnalysis).toBe(false)
  expect(result.current.reason('analysis')).toContain('未选择数据分析')
})
it('isolates accepted requirements between projects rather than deriving them from visited pages',()=>{
  const {result,rerender}=renderHook(({id})=>useProjectFlow({...project,id},'overview','settings'),{initialProps:{id:'p1'}})
  act(()=>result.current.acceptServices(['analysis']));expect(result.current.reason('analysis')).toBe('')
  rerender({id:'p2'});expect(result.current.reason('analysis')).toContain('选择并保存需求');expect(result.current.reason('artifacts')).toBe('')
})
it('does not use visited analysis pages to bypass upload or a saved requirement',()=>{
 expect(flowBlockReason(2,{hasFiles:false,requirementSaved:false,reached:4,existingResults:false})).toContain('文件上传/整理')
 expect(flowBlockReason(3,{hasFiles:true,requirementSaved:false,reached:4,existingResults:false})).toContain('选择并保存需求')
 expect(flowBlockReason(3,{hasFiles:true,requirementSaved:true,reached:1,existingResults:false})).toBe('')
})
