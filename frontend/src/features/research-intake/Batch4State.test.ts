import {expect,it} from 'vitest'
import {emptyRequirement,sameIntakeVersion} from './state'
import type {MaterialRef} from './contracts'
it('compares object semantics and reference multisets while preserving content array order',()=>{
 const content={...emptyRequirement(),contact:{name:'A',email:'a@b'}},refs:MaterialRef[]=[{purpose:'raw_data',availability:'provided',file_id:'f1'},{purpose:'sample_sheet',availability:'pending',note:'待补'}]
 const current={content:{...content,contact:{email:'a@b',name:'A'}},material_refs:[{...refs[1],locator:null},{...refs[0],note:''}]}
 expect(sameIntakeVersion(content,refs,current)).toBe(true)
 expect(sameIntakeVersion(content,[...refs,refs[0]],current)).toBe(false)
 expect(sameIntakeVersion({...content,services:['analysis','sci_draft']},refs,{...current,content:{...content,services:['sci_draft','analysis']}})).toBe(false)
 expect(sameIntakeVersion(content,refs,null)).toBe(false)
})
it.each(['purpose','availability','file_id','bio_dataset_version_id','delivery_id','locator','note'] as const)('does not discard changed material %s',key=>{
 const refs:MaterialRef[]=[{purpose:'raw_data',availability:'provided',file_id:'f1'}]
 expect(sameIntakeVersion(emptyRequirement(),refs,{content:emptyRequirement(),material_refs:[{...refs[0],[key]:'changed'}] as MaterialRef[]})).toBe(false)
})
