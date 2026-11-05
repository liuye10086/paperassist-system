import {expect,it} from 'vitest'
import {parseNavigation,serializeNavigation} from './projectNavigation'

it('restores old fixed manuscript and adaptation links to their detail tasks',()=>{
 expect(parseNavigation('#project=p1&section=manuscripts&manuscript=m1&revision=2')?.manuscriptView).toBe('body')
 expect(parseNavigation('#project=p1&section=journals&adaptation=a1')?.journalView).toBe('adaptation')
})
it.each([
 '#project=p1&section=manuscripts&view=writing&manuscript=m1&revision=2',
 '#project=p1&section=manuscripts&view=materials',
 '#project=p1&section=manuscripts&view=research-selection&sourceKind=research_report_version&sourceId=rep1',
 '#project=p1&section=journals&view=guidelines',
 '#project=p1&section=school-templates&view=confirm&template=t1',
 '#project=p1&section=school-templates&view=profile',
])('round-trips layered tasks: %s',hash=>{
 const route=parseNavigation(hash);expect(route).not.toBeNull();expect(serializeNavigation(route!)).toBe(hash)
})
it('retains a fixed research source when entering writing materials',()=>{
 const route=parseNavigation('#project=p1&section=manuscripts&view=research-selection&sourceKind=research_figure_version&sourceId=fig1')
 expect(route?.writingSource).toEqual({kind:'research_figure_version',id:'fig1'})
 expect(serializeNavigation(route!)).toBe('#project=p1&section=manuscripts&view=research-selection&sourceKind=research_figure_version&sourceId=fig1')
})
it.each([
 '#project=p1&section=school-templates&view=confirm',
 '#project=p1&section=school-templates&view=list&template=t1',
 '#project=p1&section=manuscripts&view=other',
 '#project=p1&section=journals&view=body',
 '#project=p1&section=manuscripts&view=body&revision=1',
])('rejects malformed task destinations: %s',hash=>expect(parseNavigation(hash)).toBeNull())

it('round trips a fixed finding origin and writing delivery independently of delivery registry',()=>{
 const hash='#project=p1&section=manuscripts&view=research-selection&sourceKind=research_finding_version&sourceId=fv1&sourceSet=fs1&writingDelivery=d1'
 const route=parseNavigation(hash)
 expect(route?.writingSource).toEqual({kind:'research_finding_version',id:'fv1',setId:'fs1'})
 expect(route?.writingDeliveryId).toBe('d1')
 expect(serializeNavigation(route!)).toBe(hash)
})
it('round trips a fixed finding detail destination',()=>{
 const hash='#project=p1&section=analysis&view=research-findings&findingSet=fs1&findingVersion=fv1'
 expect(serializeNavigation(parseNavigation(hash)!)).toBe(hash)
})

it('recognizes only writing entry and its exact fixed source as historical reads',async()=>{
 const {isFixedWritingNavigation}=await import('./projectNavigation')
 const entry=parseNavigation('#project=p1&section=manuscripts&view=research-selection&sourceKind=research_finding_version&sourceId=fv1&sourceSet=fs1')!
 expect(isFixedWritingNavigation(entry)).toBe(true)
 expect(isFixedWritingNavigation({...entry,section:'analysis',analysisNavigation:{view:'research-findings',fileId:'',findingSetId:'fs1',findingVersionId:'fv1'}})).toBe(true)
 expect(isFixedWritingNavigation({...entry,section:'analysis',analysisNavigation:{view:'research-findings',fileId:'',findingSetId:'fs1',findingVersionId:'fv2'}})).toBe(false)
})
