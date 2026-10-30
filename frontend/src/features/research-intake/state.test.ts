import { describe, expect, it } from 'vitest'
import { declared, updateServices } from './state'
describe('intake draft semantics',()=>{
 it('stores unknown values explicitly without inventing facts',()=>{expect(declared('pending','old')).toEqual({state:'pending',value:null});expect(declared('known','abc')).toEqual({state:'known',value:'abc'})})
 it('preserves hidden service requirements',()=>{const content={services:['sci_draft'],sci_request:{journal:{state:'known',value:'Nature'}}};expect(updateServices(content,['analysis']).sci_request).toEqual(content.sci_request)})
})
