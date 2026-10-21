import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import {validContext,validReview} from './reviewTypes'
import {reviewContext,reviewVersion,savedReview} from './reviewFixtures'
import {setLocale} from '../../shared/i18n'
import ManuscriptPreview from './ManuscriptPreview'
afterEach(()=>{cleanup();setLocale('zh-CN')})
it('accepts owned frozen review and rejects invalid supplemental source selections',()=>{
 expect(validReview(savedReview,'p1','m1')).toBe(true)
 expect(validReview({...savedReview,input:{...savedReview.input,selected_sources:[{id:'foreign'}]}},'p1','m1')).toBe(false)
 expect(validReview({...savedReview,project_id:'p2'},'p1','m1')).toBe(false)
})
it('rejects foreign fact hashes and unrelated context relationships',()=>{
 expect(validContext(reviewContext,'p1',reviewVersion)).toBe(true)
 expect(validContext({...reviewContext,facts:[{...reviewContext.facts[0],source_sha256:'c'.repeat(64)}]},'p1',reviewVersion)).toBe(false)
 expect(validContext({...reviewContext,relationships:{...reviewContext.relationships,methods:[]}},'p1',reviewVersion)).toBe(false)
})
it('exposes frozen confirmation and pending source addendum in ordinary preview, with historical reports clearly labeled',()=>{
 setLocale('en');const review={...savedReview.candidate.review!,decisions:[{target_id:'missing:ethics',status:'supplied' as const,value:'Explicit approval',reason:'Checked record',evidence:'Signed protocol',scientifically_verified:false as const,created_by:'u1',created_at:'2026-10-20T00:00:00Z',base_revision:1,source_versions:[]}],addendum:[{id:'new-material:doc1',text:'Selected new protocol; impact pending',origin:'user_provided' as const,source_ids:['doc1'],citations:[],numeric_bindings:[],pending_impact:true}]}
 render(<ManuscriptPreview snapshot={{...reviewVersion.snapshot,review,review_history:[{review,provenance:{},applies_to_current_text:false,status:'historical_requires_recheck'}]}}/>);expect(screen.getByText('Frozen confirmations and checks')).toBeTruthy();expect(screen.getByText('Historical checks (do not apply to current text)')).toBeTruthy();expect(screen.getAllByText(/Signed protocol/)).toHaveLength(2);expect(screen.getAllByText(/Selected new protocol; impact pending/)).toHaveLength(2)
})
