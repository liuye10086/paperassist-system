import {describe,it,expect} from 'vitest'
import {mergeSelection,selectionOnly,findingDiff,sourceOptionLabel} from './state'
import {parseNavigation,serializeNavigation} from '../projects/projectNavigation'
describe('fixed research selection',()=>{
 it('uses figure type, source name and version to identify a fixed source without exposing an internal ID',()=>{
  expect(sourceOptionLabel({source_kind:'bio_figure_version',source_id:'12345678-1234-5678-aaaa-bbbbbbbbbbbb',title:'UMAP clusters',kind:'umap',panel:'clusters',version:3,source_label:'GSE262082 NPC',status:'succeeded',created_at:'',sha256:null},s=>s)).toBe('UMAP clusters · umap / clusters · GSE262082 NPC · v3 · 已完成')
 })
 it('keeps existing draft choices while deduplicating incoming sources',()=>{
  expect(mergeSelection({finding_version_ids:['old'],figure_version_ids:['fig'],report_version_ids:[]},{finding_version_ids:['new','old'],figure_version_ids:[],report_version_ids:['report']})).toEqual({finding_version_ids:['old','new'],figure_version_ids:['fig'],report_version_ids:['report']})
 })
 it('never sends frozen source payloads as selection input',()=>{
  expect(selectionOnly({schema_version:1,source_kind:'original_file',source_id:'f',sha256:'hash',locator:{kind:'cell',sheet:'Sheet1',cell:'B2'},content:{facts:[]},project_id:'p'})).toEqual({schema_version:1,source_kind:'original_file',source_id:'f',sha256:'hash',locator:{kind:'cell',sheet:'Sheet1',cell:'B2'}})
 })
 it('compares fixed facts and claims including changes to an existing identity',()=>{
  expect(findingDiff({facts:[{id:'a',raw_value:1}],claims:[]},{facts:[{id:'a',raw_value:2},{id:'b',raw_value:3}],claims:[{id:'c'}]})).toEqual({facts:{added:['b'],removed:[],changed:['a']},claims:{added:['c'],removed:[],changed:[]}})
 })
 it.each(['#project=p&section=analysis&view=research-findings','#project=p&section=artifacts&view=research-figures&artifact=fig','#project=p&section=artifacts&view=research-reports&artifact=rep','#project=p&section=manuscripts&view=research-candidates&candidate=c'])('round trips research deep link %s',hash=>{const route=parseNavigation(hash);expect(route).not.toBeNull();expect(serializeNavigation(route!)).toBe(hash)})
})
