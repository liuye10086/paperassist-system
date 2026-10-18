import { expect, test } from 'vitest'
import { isPlanReview, isConfirmedPlan } from './analysisPlanApi'
import { isTask } from '../tasks/taskTypes'
import { reviewFixture } from './analysisPlanFixtures'

import { correlationSelection,input,v3Review,v3Plan } from './batch02Fixtures'
import { sameSelection } from '../analysis/analysisSelection'

test('v3 correlation review preserves v1 and validates method and field limits', () => {
  expect(isPlanReview(v3Review, 'p1', 't1')).toBe(true)
  expect(isPlanReview(reviewFixture, 'p1', 't1')).toBe(true)
  for (const selection of [{ ...correlationSelection, method: 'regression' }, { ...correlationSelection, columns: ['C','C'] }, { ...correlationSelection, units: { C:'kg' } }, { ...correlationSelection, mode:'matrix', columns: Array.from({length:11},(_,i)=>String(i)) }]) expect(isPlanReview({...v3Review,selection},'p1','t1')).toBe(false)
  expect(isConfirmedPlan(v3Plan, 'p1', 'f1')).toBe(true)
  expect(isConfirmedPlan({ ...v3Plan, schema_version: 2 }, 'p1', 'f1')).toBe(false)
})
test('selection equality ignores object key order but keeps field order',()=>{
 expect(sameSelection(correlationSelection,Object.fromEntries(Object.entries(correlationSelection).reverse()))).toBe(true)
 expect(sameSelection(correlationSelection,{...correlationSelection,columns:['D','C']})).toBe(false)
})
test('keeps v2 research missing codes separate from v3 and fences recommendation references',()=>{
 expect(isPlanReview({...v3Review,recommendation_ref:undefined},'p1','t1')).toBe(false)
 expect(isPlanReview({...reviewFixture,input_version:{...input,workflow_version:'analysis_plan_v2'},task:{...reviewFixture.task,input_version:{...input,workflow_version:'analysis_plan_v2'}},research_request:v3Review.research_request,check:{...v3Review.check,rules_version:'analysis_plan_rules_v2',research_missing:['independent_observations']}},'p1','t1')).toBe(false)
})
test('confirmed v3 plans reject unconfirmed assumptions and blocked checks',()=>{
 expect(isConfirmedPlan({...v3Plan,selection:{...correlationSelection,assumptions:{...correlationSelection.assumptions,independent_observations:false}}},'p1','f1')).toBe(false)
 expect(isConfirmedPlan({...v3Plan,check:{...v3Plan.check,selection_check:{...v3Plan.check.selection_check,ready:false}}},'p1','f1')).toBe(false)
})
test('recommendation tasks and English analysis tasks use their exact frozen sources', () => {
  expect(isTask({ ...reviewFixture.task, task_type:'analysis_recommendation', input_version:{ ...input, kind:'analysis_recommendation', workflow_version:'analysis_recommendation_v1' } }, 'p1')).toBe(true)
  expect(isTask({ ...reviewFixture.task, task_type:'boxplot', input_version:{ kind:'dataset_analysis', source:reviewFixture.source, setup_revision:2, output_language:'en' } }, 'p1')).toBe(true)
})
