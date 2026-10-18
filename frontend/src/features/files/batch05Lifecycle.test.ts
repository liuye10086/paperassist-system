import {expect,test} from 'vitest'
import {isCounts,lifecycleCounts,reasonLabels} from './fileLifecycleApi'
test('new lifecycle counts coexist with unchanged historical receipts',()=>{
 const previous=Object.fromEntries(Object.keys(lifecycleCounts).map(k=>[k,0]))
 expect(isCounts({...previous,figure_configurations:2,figure_config_versions:3,figure_projection_decisions:2,figure_projection_results:2,report_collections:1,report_collection_versions:1,report_collection_items:2,report_build_requests:1,collection_reports:0})).toBe(true)
 expect(isCounts(previous)).toBe(true)
 expect(Object.hasOwn(reasonLabels,'report_build_pending')).toBe(true)
})
