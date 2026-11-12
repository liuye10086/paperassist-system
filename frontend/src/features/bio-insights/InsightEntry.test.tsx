import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import BioAnalysisResult from '../bioinformatics/BioAnalysisResult'
import BioInsightsWorkspace from './BioInsightsWorkspace'
import {processedFixture} from '../bioinformatics/spatialFixtures'
import {setApiSession,clearApiSession} from '../../shared/api/client'
import type {Result} from './contracts'
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession();sessionStorage.clear()})
it('enters insights from an existing B02 result with its fixed processed identity and performs no reanalysis',async()=>{setApiSession('csrf','owner');const fetch=vi.fn().mockResolvedValue(Response.json(processedFixture));vi.stubGlobal('fetch',fetch);const navigate=vi.fn();render(<BioAnalysisResult projectId="p1" processedId="processed1" tab="methods" onNavigate={navigate}/>);fireEvent.click(await screen.findByRole('button',{name:'差异与功能分析'}));expect(navigate).toHaveBeenCalledWith({view:'bio-insights',fileId:'',processedId:'processed1'});expect(fetch.mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)})

it('starts scoped single-cell differential expression with the existing donor-based design',async()=>{
 setApiSession('csrf','owner')
 const hash='a'.repeat(64)
 const fetch=vi.fn(async(_url:RequestInfo|URL,_init?:RequestInit)=>Response.json({items:[
  {source_kind:'bio_processed_dataset_version',source_id:'cell',sha256:hash,title:'Cells',assay:'single_cell'},
  {source_kind:'bio_processed_dataset_version',source_id:'bulk',sha256:hash,title:'Bulk counts',assay:'bulk_rna_counts'},
 ],total:2,page:1,page_size:20}))
 vi.stubGlobal('fetch',fetch)
 const entry={requirementVersionId:'req1',scopeItemId:'customer.analysis.single_cell.differential'}
 render(<BioInsightsWorkspace projectId="p1" active navigation={{view:'bio-insights',fileId:'',intent:'single_cell_differential',entry}} onNavigate={vi.fn()}/>)
 await screen.findByRole('option',{name:'Cells'})
 expect(screen.queryByRole('option',{name:'Bulk counts'})).toBeNull()
 fireEvent.change(screen.getByLabelText('选择固定来源版本'),{target:{value:'cell'}})
 fireEvent.click(screen.getByRole('button',{name:'加入固定来源'}))
 fireEvent.click(screen.getByRole('button',{name:'配置分析'}))
 expect(screen.getByLabelText('比较数据类型')).toHaveProperty('value','single_cell_de')
 expect(screen.getByLabelText('固定人工注释版本')).toBeTruthy()
 expect(fetch.mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
})

const fixedHash='a'.repeat(64)
const fixedComparison:Result={
 id:'de1',run_id:'run1',plan_version_id:'plan1',kind:'comparison',provenance:'project',inference_scope:'donor_inference',
 summary:{tested_universe_complete:true,row_count:20,not_computable_rows:2},
 methods:{single_cell_selection:{processed_source_id:'cell'},family_contrast_ids:['case-control']},
 manifest:{},manifest_sha256:fixedHash,task_id:'task1',task:{id:'task1',status:'succeeded'},
 members:[{id:'table1',key:'comparison_results',role:'table',format:'tsv',sha256:fixedHash,size_bytes:20,download_url:'/table'}],
}
const enrichmentEntry={requirementVersionId:'req1',scopeItemId:'customer.analysis.single_cell.enrichment'}

it.each([
 {configured:true,methods:fixedComparison.methods,ready:true},
 {configured:false,methods:fixedComparison.methods,ready:false},
 {configured:true,methods:{},ready:false},
])('only offers local ORA from a compatible fixed single-cell comparison and verified runtime ($ready)',async({configured,methods,ready})=>{
 setApiSession('csrf','owner')
 const fetch=vi.fn(async(url:RequestInfo|URL,_init?:RequestInit)=>Response.json(
  String(url).endsWith('/bio-insights/capabilities')?{configured}:String(url).endsWith('/bio-insight-results/de1')?{...fixedComparison,methods}:{items:[],total:0,columns:[]}
 ))
 vi.stubGlobal('fetch',fetch)
 const navigate=vi.fn()
 render(<BioInsightsWorkspace projectId="p1" active
  navigation={{view:'bio-insight-result',fileId:'',intent:'single_cell_enrichment',entry:enrichmentEntry,resultVersionId:'de1'}} onNavigate={navigate}/>)
 if(ready){
  fireEvent.click(await screen.findByRole('button',{name:'配置本地 ORA 富集'}))
  expect(navigate).toHaveBeenCalledWith({view:'bio-resources',fileId:'',intent:'single_cell_enrichment',entry:enrichmentEntry,resultVersionId:'de1'})
 }else{
  await screen.findByText(configured?'请选择包含完整受检基因表的单细胞供者差异结果。':'当前环境未验证 ORA 运行能力。')
  expect(screen.queryByRole('button',{name:'配置本地 ORA 富集'})).toBeNull()
 }
 expect(fetch.mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
})

it('requires a published gene-set resource and explicit preflight for scoped ORA',async()=>{
 setApiSession('csrf','owner')
 const fetch=vi.fn(async(url:RequestInfo|URL,_init?:RequestInit)=>Response.json(
  String(url).endsWith('/bio-insights/capabilities')?{configured:true}:String(url).endsWith('/bio-insight-results/de1')?fixedComparison:
  String(url).endsWith('/bio-insight-plans/preview')?{executable:true,blocking_reasons:[]}:
  String(url).includes('/sources?source_kind=bio_resource_version')?{
   items:[{source_kind:'bio_resource_version',source_id:'set1',sha256:fixedHash,title:'Gene sets',kind:'gene_sets',release:'2026-01',version:1}],
   total:1,page:1,page_size:20,
  }:{items:[],total:0,columns:[]}
 ))
 vi.stubGlobal('fetch',fetch)
 render(<BioInsightsWorkspace projectId="p1" active
  navigation={{view:'bio-resources',fileId:'',intent:'single_cell_enrichment',entry:enrichmentEntry,resultVersionId:'de1'}} onNavigate={vi.fn()}/>)
 await screen.findByRole('heading',{name:'选择本地固定富集资源'})
 expect(screen.getByRole('button',{name:'检查与运行'})).toHaveProperty('disabled',true)
 await screen.findByRole('option',{name:/Gene sets/})
 fireEvent.change(screen.getByLabelText('选择固定来源版本'),{target:{value:'set1'}})
 fireEvent.click(screen.getByRole('button',{name:'加入固定来源'}))
 fireEvent.click(screen.getByRole('button',{name:'检查与运行'}))
 expect(screen.getByRole('button',{name:'开始分析'})).toHaveProperty('disabled',true)
 expect(fetch.mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'预检当前设计'}))
 await screen.findByRole('heading',{name:'设计预检可执行'})
 expect(screen.getByRole('button',{name:'开始分析'})).toHaveProperty('disabled',false)
 const preview=fetch.mock.calls.find(([url,init])=>String(url).endsWith('/bio-insight-plans/preview')&&init?.method==='POST')
 expect(JSON.parse(String(preview?.[1]?.body))).toMatchObject({kind:'ora',config:{result_source_ids:['de1'],resource_source_ids:['set1'],contrast_ids:['case-control']}})
})
