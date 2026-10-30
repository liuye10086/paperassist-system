import { describe, expect, it } from 'vitest'
import { parseNavigation, serializeNavigation } from './projectNavigation'
import { isProject } from './projectTypes'
describe('research intake navigation',()=>{
 it('round trips immutable bio identity and overview views',()=>{
  for(const hash of ['#project=p1&section=overview&view=requirements','#project=p1&section=overview&view=design','#project=p1&section=overview&view=deliveries','#project=p1&section=analysis&view=bio-import&import=i1','#project=p1&section=analysis&view=bio-dataset&dataset=d1&version=v1']){
   const route=parseNavigation(hash);expect(route).not.toBeNull();expect(parseNavigation(serializeNavigation(route!))).toEqual(route)
  }
 })
 it('rejects duplicate, unrelated and incomplete bio identities',()=>{
  for(const hash of ['#project=p1&section=analysis&view=bio-import','#project=p1&section=analysis&view=bio-import&import=i1&dataset=d1','#project=p1&section=analysis&view=bio-dataset&dataset=d1','#project=p1&section=analysis&view=bio-dataset&dataset=d1&version=v1&file=f1','#project=p1&section=analysis&view=bio-datasets&import=i1','#project=p1&section=analysis&view=bio-import&import=i1&import=i2'])expect(parseNavigation(hash)).toBeNull()
 })
 it('accepts research without broadening writing models',()=>expect(isProject({id:'p',name:'n',research_topic:'r',project_type:'research',file_count:0,created_at:'x',updated_at:'x'})).toBe(true))
})
