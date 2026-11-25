import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import InsightPlanEditor from './InsightPlanEditor'
import BioInsightsWorkspace from './BioInsightsWorkspace'
import {apiFetch} from '../../shared/api/client'
import {defaultBulkConfig} from './quantitative'
import type {Plan,PlanBody,Design,Source} from './contracts'

vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',onApiSessionChanged:()=>()=>{}}))
const source:Source={source_kind:'bio_processed_dataset_version',source_id:'fixed',sha256:'a'.repeat(64),
 role:'processed',locator:{kind:'object'},title:'Fixed Bulk source',assay:'bulk_rna_counts'}
const config={...defaultBulkConfig(),namespace:'Ensembl',reference_version:'fixed',design_basis:'Prespecified',
 contrasts:[{contrast_id:'contrast_1',name:'B/A',groups:['B','A'].map(label=>({
  label,sample_keys:[0,1].map(i=>({processed_version_id:'fixed',sample_id:label+i})),
 }))}]}
const review:Design={executable:true,blocking_reasons:[],reviewed_design_sha256:'e'.repeat(64),
 bulk_model:{formula:'~ condition',condition_reference:'A',condition_levels:['A','B'],
  terms:[{term:'condition',field:'condition',kind:'categorical',reference_level:'A'}],
  contrasts:[{contrast_id:'contrast_1',numerator:'B',denominator:'A'}],size_factor_method:'ratio',
  filter:{minimum_total_counts:10,minimum_sample_counts:1,minimum_expressing_samples:2,eligible_feature_count:8},
  samples:[{processed_version_id:'fixed',sample_id:'A0',condition:'A',donor:'',batch:'',biological_unit_id:'A0',covariates:{}}]}}
const draft:Plan={id:'v1',plan_id:'plan',version:1,revision:1,current_revision:1,parent_id:null,
 kind:'comparison',name:'Bulk',decision:'draft',config,config_sha256:'b'.repeat(64),sources:[source],
 source_digest:'c'.repeat(64),design:review}
const posts=()=>vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')
afterEach(()=>{cleanup();sessionStorage.clear();vi.clearAllMocks()})

it('adopts raw counts when opening a new plan from a fixed Bulk result',async()=>{
 vi.mocked(apiFetch).mockImplementation(async()=>Response.json({items:[source],total:1}))
 render(<InsightPlanEditor projectId="p" kind="comparison" active initialProcessedId="fixed" onSaved={vi.fn()} onRun={vi.fn()}/>)
 const adopt=screen.getByRole('button',{name:'采用入口的固定处理版本'})
 await waitFor(()=>expect(adopt).toHaveProperty('disabled',false))
 fireEvent.click(adopt)
 fireEvent.click(screen.getByRole('button',{name:'配置分析'}))
 expect(screen.getByLabelText('定量统计路径')).toHaveProperty('value','bulk_counts')
 expect(screen.getByLabelText('比较数值层')).toHaveProperty('value','raw_counts')
})

it('shows only the practical analyst Bulk inputs and submits an exact paired design for review',async()=>{
 const observations=[
  {sample_id:'T1',condition:'treated',retained:true},
  {sample_id:'T2',condition:'treated',retained:false},
  {sample_id:'C1',condition:'control',retained:true},
 ]
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method==='POST')return Response.json(review)
  if(String(url).includes('/observations?'))return Response.json({items:observations,total:observations.length,observation_level:'sample',
   scale:{namespace:'unknown',reference_version:'unknown',species_taxon_id:9606}})
  return Response.json({items:[source],total:1})
 })
 render(<BioInsightsWorkspace projectId="p" analysisOnly active navigation={{view:'bio-insights',fileId:'',processedId:'fixed'}} onNavigate={vi.fn()}/>)
 const adopt=screen.getByRole('button',{name:'采用入口的固定处理版本'})
 await waitFor(()=>expect(adopt).toHaveProperty('disabled',false))
 fireEvent.click(adopt)
 fireEvent.click(screen.getByRole('button',{name:'配置分析'}))

 for(const name of ['新计划类型','比较数据类型','定量统计路径','统计方法','比较数值层','重复单位']){
  expect(screen.queryByRole('combobox',{name})).toBeNull()
 }
 expect(screen.queryByRole('spinbutton',{name:'总 counts 预过滤门槛'})).toBeNull()
 fireEvent.change(screen.getByRole('combobox',{name:'样本比较设计'}),{target:{value:'paired'}})
 expect(screen.getByRole('combobox',{name:'固定配对字段'})).toHaveProperty('value','pair_id')
 fireEvent.click(screen.getByRole('button',{name:'读取固定样本'}))
 fireEvent.change(await screen.findByRole('combobox',{name:'分子组（比较组）'}),{target:{value:'treated'}})
 fireEvent.change(screen.getByRole('combobox',{name:'分母组（参照组）'}),{target:{value:'control'}})
 fireEvent.change(screen.getByRole('textbox',{name:'样本设计与重复依据'}),{target:{value:'Same donors, paired by pair_id'}})
 fireEvent.click(screen.getByRole('checkbox',{name:'已核对分组和生物学重复依据'}))
 fireEvent.click(screen.getByRole('button',{name:'补充设置'}))
 expect(screen.getByRole('spinbutton',{name:'总 counts 预过滤门槛'})).toHaveProperty('value','10')
 fireEvent.click(screen.getByRole('button',{name:'分析参数'}))
 expect(screen.getByRole('combobox',{name:'分子组（比较组）'})).toHaveProperty('value','treated')
 fireEvent.click(screen.getByRole('button',{name:'检查与运行'}))
 fireEvent.click(screen.getByRole('button',{name:'预检当前设计'}))
 await screen.findByRole('region',{name:'Bulk 模型确认摘要'})
 expect(posts()).toHaveLength(1)
 expect(JSON.parse(String(posts()[0][1]?.body))).toMatchObject({
  sources:[{source_id:'fixed',role:'processed'}],
  config:{
   design:'paired',pairing_field:'pair_id',mode:'bulk_counts',method:'deseq2_wald',analysis_layer:'raw_counts',
   namespace:'unknown',reference_version:'unknown',species_taxon_id:9606,
   independence_confirmed:true,independence_basis:'Same donors, paired by pair_id',design_basis:'Same donors, paired by pair_id',
   contrasts:[{groups:[
    {label:'treated',sample_keys:[{processed_version_id:'fixed',sample_id:'T1'}]},
    {label:'control',sample_keys:[{processed_version_id:'fixed',sample_id:'C1'}]},
   ]}],
  },
 })
})

it('requires preview and confirmation separately, then invalidates confirmation when the direction changes',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method!=='POST')return Response.json({items:[],total:0})
  if(String(url).endsWith('/preview'))return Response.json(review)
  if(String(url).endsWith('/bio-insight-runs'))return Response.json({id:'run1',task:{id:'task1',status:'queued'}})
  const body=JSON.parse(String(init.body)) as PlanBody
  return Response.json({...draft,id:'v2',version:2,revision:2,current_revision:2,decision:body.decision,config:body.config})
 })
 const onRun=vi.fn()
 render(<InsightPlanEditor projectId="p" kind="comparison" active initial={draft} onSaved={vi.fn()} onRun={onRun}/>)
 fireEvent.click(screen.getByRole('button',{name:'检查与运行'}))
 expect(screen.getByRole('button',{name:'开始分析'})).toHaveProperty('disabled',true)
 fireEvent.click(screen.getByRole('button',{name:'预检当前设计'}))
 const model=await screen.findByRole('region',{name:'Bulk 模型确认摘要'})
 expect(model.textContent).toContain('~ condition')
 expect(model.textContent).toContain('B vs A')
 expect(model.querySelector('details, summary')).toBeNull()
 expect(within(model).getByRole('table',{name:'最终纳入样本'})).toBeTruthy()
 expect(posts()).toHaveLength(1)
 fireEvent.click(screen.getByRole('button',{name:'确认并保存 Bulk 模型'}))
 await waitFor(()=>expect(screen.getByRole('button',{name:'开始分析'})).toHaveProperty('disabled',false))
 expect(posts()).toHaveLength(2)
 expect(JSON.parse(String(posts()[1][1]?.body))).toMatchObject({decision:'confirmed',reviewed_design_sha256:'e'.repeat(64)})
 fireEvent.click(screen.getByRole('button',{name:'开始分析'}))
 await waitFor(()=>expect(onRun).toHaveBeenCalledOnce())
 expect(JSON.parse(String(posts()[2][1]?.body))).toMatchObject({plan_version_id:'v2',expected_plan_revision:2})
 fireEvent.click(screen.getByRole('button',{name:'配置分析'}))
 fireEvent.click(screen.getByRole('button',{name:'交换比较方向（保存后产生新版）'}))
 fireEvent.click(screen.getByRole('button',{name:'检查与运行'}))
 expect(screen.getByRole('button',{name:'开始分析'})).toHaveProperty('disabled',true)
 expect(screen.getByRole('button',{name:'确认并保存 Bulk 模型'})).toHaveProperty('disabled',true)
 expect(posts()).toHaveLength(3)
})
