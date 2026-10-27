import {expect,it} from 'vitest'
import {parseNavigation,serializeNavigation} from './projectNavigation'

it('restores old fixed manuscript and adaptation links to their detail tasks',()=>{
 expect(parseNavigation('#project=p1&section=manuscripts&manuscript=m1&revision=2')?.manuscriptView).toBe('body')
 expect(parseNavigation('#project=p1&section=journals&adaptation=a1')?.journalView).toBe('adaptation')
})
it.each([
 '#project=p1&section=manuscripts&view=writing&manuscript=m1&revision=2',
 '#project=p1&section=manuscripts&view=materials',
 '#project=p1&section=journals&view=guidelines',
 '#project=p1&section=school-templates&view=confirm&template=t1',
 '#project=p1&section=school-templates&view=profile',
])('round-trips layered tasks: %s',hash=>{
 const route=parseNavigation(hash);expect(route).not.toBeNull();expect(serializeNavigation(route!)).toBe(hash)
})
it.each([
 '#project=p1&section=school-templates&view=confirm',
 '#project=p1&section=school-templates&view=list&template=t1',
 '#project=p1&section=manuscripts&view=other',
 '#project=p1&section=journals&view=body',
 '#project=p1&section=manuscripts&view=body&revision=1',
])('rejects malformed task destinations: %s',hash=>expect(parseNavigation(hash)).toBeNull())
