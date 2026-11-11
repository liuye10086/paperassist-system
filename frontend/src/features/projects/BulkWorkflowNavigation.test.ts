import {expect,it} from 'vitest'
import {parseNavigation,serializeNavigation} from './projectNavigation'

const prefix = '#project=p1&section=analysis&view='

it.each(['design','data','qc','differential','functional','delivery'])('round trips the Bulk %s view',view=>{
  const hash = `${prefix}bulk-workflow&bulkView=${view}`
  const route = parseNavigation(hash)
  expect(route?.analysisNavigation).toEqual({view:'bulk-workflow',fileId:'',bulkView:view})
  expect(serializeNavigation(route!)).toBe(hash)
})

it('preserves a fixed nested result in the Bulk workflow',()=>{
  const hash = `${prefix}bio-insight-result&resultVersionId=de-v2&bulkView=differential`
  const route = parseNavigation(hash)
  expect(route?.analysisNavigation).toEqual({view:'bio-insight-result',fileId:'',resultVersionId:'de-v2',bulkView:'differential'})
  expect(serializeNavigation(route!)).toBe(hash)
})

it('links directly to a frozen primary comparison in delivery',()=>{
  const hash = `${prefix}bulk-workflow&resultVersionId=de-v2&bulkView=delivery`
  const route = parseNavigation(hash)
  expect(route?.analysisNavigation).toEqual({view:'bulk-workflow',fileId:'',resultVersionId:'de-v2',bulkView:'delivery'})
  expect(serializeNavigation(route!)).toBe(hash)
})

it('rejects unscoped or invalid Bulk workflow navigation',()=>{
  for(const route of ['bulk-workflow','bulk-workflow&bulkView=results','bulk-workflow&bulkView=delivery&file=x','setup&bulkView=qc']) {
    expect(parseNavigation(prefix+route)).toBeNull()
  }
  expect(parseNavigation('#project=p1&section=files&view=quality&quality=bio-datasets&bulkView=data')).toBeNull()
})
