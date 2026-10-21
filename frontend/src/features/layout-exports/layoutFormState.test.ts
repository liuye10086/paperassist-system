import {expect,it} from 'vitest'
import {layoutFormError} from './layoutFormState'
import {emptyLayout,type Catalog} from './layoutApi'
it('blocks heading overrides exceeding the strict server limit before POST',()=>{
 const hash='a'.repeat(64);const headings=Array.from({length:101},(_,i)=>({anchor_id:`${hash}:${i}`,level:1}));expect(layoutFormError({...emptyLayout(hash),headings},{anchors:[]} as unknown as Catalog)).not.toBe('')
})

const hash='a'.repeat(64),anchor=hash+':0',catalog={anchors:[{id:anchor,type:'heading',heading_level:1}]} as Catalog
it.each([2000,2001])('validates user equation boundary %i in code points',count=>{
 const result=layoutFormError({...emptyLayout(hash),formulas:[{id:'eq1',anchor_id:anchor,expression:'𝑥'+'x'.repeat(count-1),placement:'after'}]},catalog)
 expect(result==='').toBe(count<=2000)
})
it.each([100,101])('validates user reference prefix boundary %i in code points',count=>{
 const result=layoutFormError({...emptyLayout(hash),references:[{anchor_id:anchor,target_id:anchor,kind:'text',prefix:'𝑥'+'p'.repeat(count-1)}]},catalog)
 expect(result==='').toBe(count<=100)
})
