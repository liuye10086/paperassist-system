import {expect,it} from 'vitest'
import {buildPlan,planIssues} from './state'
import {defaultSingleCellComposition,defaultSingleCellDE,selectedSingleCellRows,compositionOverview} from './singleCellComparison'
const rows=[
 {processed_version_id:'p',barcode:'a',condition:'stim',donor:'d1',sample:'s1',label_id:'T',annotation_status:'assigned',retained:true},
 {processed_version_id:'p',barcode:'b',condition:'stim',donor:'d1',sample:'s2',label_id:'T',annotation_status:'assigned',retained:true},
 {processed_version_id:'p',barcode:'c',condition:'ctrl',donor:'d1',label_id:'B',annotation_status:'assigned',retained:true},
 {processed_version_id:'p',barcode:'u',condition:'ctrl',donor:null,annotation_status:'unknown',retained:true},
 {processed_version_id:'p',barcode:'x',condition:'ctrl',donor:'d2',label_id:'T',annotation_status:'uncertain',retained:true},
 {processed_version_id:'p2',barcode:'a',condition:'stim',donor:'d3',label_id:'T',annotation_status:'assigned',retained:true},
 {processed_version_id:'p',barcode:'gone',condition:'stim',donor:'d2',label_id:'T',annotation_status:'assigned',retained:false},
]
it('freezes only retained assigned labels on the exact processed and condition intersection',()=>{
 expect(selectedSingleCellRows(rows,{processed_source_id:'p',label_ids:['T']},'stim').map(r=>r.barcode)).toEqual(['a','b'])
 expect(selectedSingleCellRows(rows,{processed_source_id:'p',label_ids:['T']},'ctrl')).toEqual([])
 expect(defaultSingleCellDE().single_cell_selection).toMatchObject({labels_confirmed:false,label_ids:[]})
})
it('keeps unknown and uncertain in the denominator and merges technical samples for donor n',()=>{
 expect(compositionOverview(rows,'p',['stim','ctrl'],['T'])).toEqual({totalCells:5,donors:2,unknownDonorCells:1,categories:{label:2,other:1,unknown:1,uncertain:1,conflict:0,unlabeled:0}})
})
it('keeps composition schema free of DE-only family fields and permits descriptive unconfirmed labels',()=>{
 const config={...defaultSingleCellComposition(),processed_source_id:'p',annotation_source_id:'ann',label_ids:['T'],numerator:'stim',denominator:'ctrl'}
 expect(planIssues(config)).toEqual([])
 expect(buildPlan('Composition',config,[],0,'draft').config).not.toHaveProperty('family_contrast_ids')
 expect(planIssues({...config,numerator:'ctrl',mode:'donor_unpaired'})).toContain('请选择两个不同的条件。')
 expect(planIssues({...config,numerator:'ctrl',mode:'descriptive'})).toEqual([])
 expect(compositionOverview(rows,'p',['ctrl','ctrl'],['T']).totalCells).toBe(3)
})
