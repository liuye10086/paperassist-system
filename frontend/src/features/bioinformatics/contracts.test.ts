import { describe, expect, it } from 'vitest'
import { canConfirmCandidate } from './contracts'
describe('bio candidate confirmation',()=>{
 it('requires ready identity and no structural blocker',()=>{
  const ready={task:{status:'waiting_confirmation',revision:3},candidate:{sha256:'a'.repeat(64),checks:[]},checkpoint_id:'c',wait_id:'w'}
  expect(canConfirmCandidate(ready)).toBe(true);expect(canConfirmCandidate({...ready,candidate:null})).toBe(false);expect(canConfirmCandidate({...ready,wait_id:null})).toBe(false)
  expect(canConfirmCandidate({...ready,candidate:{...ready.candidate,checks:[{blocking:true,status:'failed'}]}})).toBe(false)
  expect(canConfirmCandidate({...ready,candidate:{...ready.candidate,checks:[{code:'representation_equivalence',status:'passed',value:{status:'mismatch'}}]}})).toBe(false)
 })
})
