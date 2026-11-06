import {describe,it,expect} from 'vitest'
import {cellSamplesBody,type CellSampleDraft} from './SingleCellSampleFields'
const row:CellSampleDraft={sample_id:' S1 ',library_id:'L1',donor:'',batch:'B1',group:'',file_ids:['a']}
describe('single-cell sample input',()=>{
 it('keeps legacy imports and unknown donor usable',()=>{
  expect(cellSamplesBody([],['a'])).toEqual([])
  expect(cellSamplesBody([row],['a'])).toEqual([{...row,sample_id:'S1',donor:null,group:null,species_taxon_id:null,reference_id:null,reference_version:null,library_chemistry:null,pair_id:null}])
 })
 it('requires every selected file exactly once and a unique library',()=>{
  expect(cellSamplesBody([row],['a','b'])).toBeNull()
  expect(cellSamplesBody([row,{...row}],['a'])).toBeNull()
  expect(cellSamplesBody([row,{...row,file_ids:['b']}],['a','b'])).toBeNull()
  expect(cellSamplesBody([row,{...row,library_id:'L2',file_ids:['b']}],['a','b'])).toHaveLength(2)
 })
 it('preserves declared source metadata and rejects conflicting or invalid declarations',()=>{
  const declared={...row,species_taxon_id:'9606',reference_id:' GRCh38 ',reference_version:'2024-A',library_chemistry:'3prime-v3',pair_id:'P1'}
  expect(cellSamplesBody([declared],['a'])?.[0]).toMatchObject({species_taxon_id:9606,reference_id:'GRCh38',reference_version:'2024-A',library_chemistry:'3prime-v3',pair_id:'P1'})
  expect(cellSamplesBody([{...declared,species_taxon_id:'0'}],['a'])).toBeNull()
  expect(cellSamplesBody([declared,{...declared,library_id:'L2',file_ids:['b'],species_taxon_id:'10090'}],['a','b'])).toBeNull()
  expect(cellSamplesBody([declared,{...row,library_id:'L2',file_ids:['b'],donor:'different'}],['a','b'])).toBeNull()
 })
})
