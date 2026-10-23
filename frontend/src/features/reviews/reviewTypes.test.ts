import {expect,it} from 'vitest'
import {validSegments} from './reviewTypes'
it('uses Unicode character positions when preserving pasted scientific comments',()=>{expect(validSegments('补充🧪证据',[{start:0,end:5,original_number:'1'}])).toBe(true);expect(validSegments('补充🧪证据',[{start:0,end:2,original_number:'1'},{start:3,end:5,original_number:'2'}])).toBe(false)})
