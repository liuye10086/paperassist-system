import {expect,it} from 'vitest'
import {locationText,type RevisionLocation} from './revisionTypes'
it('labels removed objects as parent locations rather than current manuscript locations',()=>{
 const location={kind:'figure',id:'old',section_title:'Results',figure_number:1,removed_from_output:true} as RevisionLocation
 const label=locationText(location,(key,params)=>key.replace('{number}',String(params?.number)))
 expect(label).toContain('父稿位置（本稿已移出）')
 expect(label).toContain('图 1')
})
