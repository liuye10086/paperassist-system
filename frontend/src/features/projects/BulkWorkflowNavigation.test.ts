import {expect,it} from 'vitest'
import {bulkRoute,continueBulkRoute} from '../bio-insights/bulkWorkflow'
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

it('round trips and preserves a confirmed scope through Bulk stages and nested results',()=>{
  const entry={requirementVersionId:'req-1',scopeItemId:'customer.analysis.bulk.differential'}
  const hash=`${prefix}bulk-workflow&requirement=req-1&scope=customer.analysis.bulk.differential&bulkView=differential`
  const route=parseNavigation(hash)
  expect(route?.analysisNavigation).toEqual({...bulkRoute('differential'),entry})
  expect(serializeNavigation(route!)).toBe(hash)
  const nested=continueBulkRoute(route!.analysisNavigation,{view:'bio-insight-result',fileId:'',resultVersionId:'de-v2'})
  expect(nested).toEqual({view:'bio-insight-result',fileId:'',resultVersionId:'de-v2',bulkView:'differential',entry})
  expect(continueBulkRoute(nested,bulkRoute('delivery','de-v2'))).toEqual({...bulkRoute('delivery','de-v2'),entry})
  expect(continueBulkRoute(nested,{view:'overview',fileId:''})).toEqual({view:'overview',fileId:''})
})

it('retains an explicit single-cell scope when leaving a Bulk workflow',()=>{
  const entry={requirementVersionId:'req-1',scopeItemId:'customer.type.bulk'}
  const singleCell={view:'bio-datasets' as const,fileId:'',intent:'single_cell_import' as const,entry:{...entry,scopeItemId:'customer.type.single_cell'}}
  expect(continueBulkRoute({...bulkRoute('data'),entry},singleCell)).toEqual(singleCell)
})

it('round trips a linked single-cell original, topic intent and fixed insight history',()=>{
  for(const suffix of [
    'bio-datasets&file=matrix&requirement=req-1&scope=customer.type.single_cell&intent=single_cell_import',
    'bio-insights&requirement=req-1&scope=customer.analysis.single_cell.pseudotime&intent=single_cell_topic&processed=processed1',
    'bio-insight-runs&requirement=req-1&scope=customer.analysis.single_cell.enrichment&intent=single_cell_enrichment',
    'bio-insight-runs',
  ]){
    const route=parseNavigation(prefix+suffix)
    expect(route).not.toBeNull()
    expect(serializeNavigation(route!)).toBe(prefix+suffix)
  }
})
