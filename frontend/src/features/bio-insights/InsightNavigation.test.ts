import {describe,it,expect} from 'vitest'
import {parseNavigation,serializeNavigation} from '../projects/projectNavigation'
describe('fixed insight navigation',()=>{
 it.each(['bio-insights','bio-insight-plan','bio-insight-result','bio-resources','bio-candidates'])('round trips %s without borrowing Excel identity',view=>{
  const hash=`#project=p1&section=analysis&view=${view}&planId=plan1&planVersionId=v1&runId=run1&resultVersionId=result1&resourceVersionId=resource1&processed=processed1`
  const route=parseNavigation(hash);expect(route).not.toBeNull();expect(serializeNavigation(route!)).toBe(hash)
 })
 it('rejects invalid or duplicated fixed identities',()=>{expect(parseNavigation('#project=p1&section=analysis&view=bio-insights&planId=../bad')).toBeNull();expect(parseNavigation('#project=p1&section=analysis&view=bio-insights&runId=a&runId=b')).toBeNull()})
})
