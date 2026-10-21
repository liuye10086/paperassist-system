import {act,cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import {apiError,setLocale,translate} from './index'
import {ReviewReport} from '../../features/manuscripts/ReviewSnapshot'
import {savedReview} from '../../features/manuscripts/reviewFixtures'
import {validReview} from '../../features/manuscripts/reviewTypes'
afterEach(()=>{cleanup();setLocale('zh-CN')})
it('reads the v2 workflow block and translates its safe API error and read-only report without changing publication gates',()=>{
 const zh='该版本已完成 v2 科学与语言审核。此处仅可重新检查；修改或发布请返回受控的 v2 科学与语言审核工作区。'
 const en='This version has completed v2 scientific and language review. Only rechecking is available here; to edit or publish, return to the controlled v2 scientific and language review workspace.'
 const error=apiError({detail:{code:'manuscript_review_v2_workflow_required',message:'PRIVATE TRACE'}},'请求失败，请重试。')
 expect(translate(error)).toBe(zh)
 const review=structuredClone(savedReview);const issue={id:'workflow:v2_scientific_language_review',category:'workflow',severity:'error' as const,location:'v2_scientific_language_review',message:zh,actual:null,expected:'v2 scientific and language review workspace',source_evidence:[],rules_version:review.rules_version}
 review.report={...review.report,issues:[issue],can_publish:false};review.candidate.review!.report=review.report
 expect(validReview(review,'p1','m1')).toBe(true)
 const unknown=structuredClone(review);unknown.report.issues[0].id='workflow:unknown';unknown.candidate.review!.report=unknown.report;expect(validReview(unknown,'p1','m1')).toBe(false)
 render(<ReviewReport report={review.report}/>);expect(screen.getAllByText(zh,{exact:false})).toHaveLength(2);expect(screen.queryByText('存在不可豁免的数值、来源或引用错误，禁止发布。')).toBeNull()
 act(()=>setLocale('en'));expect(translate(error)).toBe(en);expect(screen.getAllByText(en,{exact:false})).toHaveLength(2);expect(screen.queryByText(zh)).toBeNull();expect(review.report.can_publish).toBe(false)
})
