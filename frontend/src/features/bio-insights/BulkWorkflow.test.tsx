import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {apiFetch} from '../../shared/api/client'
import type {ProjectFile} from '../files/fileLibraryApi'
import {bulkWorkflowViews,type BulkWorkflowView} from '../projects/analysisViews'
import BulkWorkflowWorkspace,{BulkWorkflowNav} from './BulkWorkflowWorkspace'
import {sensitivityCompatible} from './BulkSensitivity'
import {bulkRoute,type BulkWorkflowComparison,type BulkWorkflowDescendant,type BulkWorkflowOverview} from './bulkWorkflow'

vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',onApiSessionChanged:()=>()=>{},captureApiSession:()=>()=>{}}))

const hash='a'.repeat(64)
const comparison=(id:string,contrast_id='treated-control'):BulkWorkflowComparison=>({
  kind:'comparison',label:`Comparison ${id}`,refs:{result_version_id:id,processed_version_id:'qc-v2'},
  contrasts:[{contrast_id,numerator:'treated',denominator:'control'}],status:'succeeded',stale:false,stale_reasons:[],
  sensitivity_lineage:[['dataset','raw']],sensitivity_samples:[['sample-hash','treated']],sensitivity_identity:[9606,'ensembl','v1'],
})
const baseline=comparison('de-v2')
it('filters sensitivity alternatives by raw lineage, identity and shared samples',()=>{
  const fixed={...baseline,sensitivity_lineage:[['dataset','raw']],sensitivity_samples:[['s1','treated'],['s2','other']],
    sensitivity_identity:[9606,'ensembl','v1']} as BulkWorkflowComparison
  const compatible={...fixed,refs:{result_version_id:'other'},sensitivity_samples:[['s1','control'],['s2','other']]}
  const contrast=fixed.contrasts[0]
  expect(sensitivityCompatible(fixed,compatible,contrast)).toBe(true)
  expect(sensitivityCompatible(fixed,{...compatible,sensitivity_lineage:[['dataset','different']]},contrast)).toBe(false)
  expect(sensitivityCompatible(fixed,{...compatible,sensitivity_samples:[['s2','other']]},contrast)).toBe(false)
  expect(sensitivityCompatible(fixed,{...compatible,sensitivity_identity:[10090,'ensembl','v1']},contrast)).toBe(false)
})
const alternate={...comparison('de-v1','variant-treated-control'),stale:true,
  stale_reasons:[{kind:'dataset_version',version_id:'raw-v1',current_version_id:'raw-v2'}]}
const descendant=(id:string,parent:string,kind='ora'):BulkWorkflowDescendant=>({
  kind,label:`Published ${id}`,refs:{result_version_id:id},comparison_version_ids:[parent],direct_comparison_version_ids:[parent],
  stale:false,stale_reasons:[],status:'succeeded',delivery_eligible:true,
})
const empty={refs:{},stale:false,stale_reasons:[],depends_on:[],items:[],status:'ready'}
const overview:BulkWorkflowOverview={project_id:'p1',comparisons:[baseline,alternate],descendants:[descendant('ora-v2','de-v2'),descendant('wrong-lineage','de-v1'),
  {...descendant('unsupported-candidate','de-v2','candidate'),delivery_eligible:false}],
  stages:bulkWorkflowViews.map(key=>key==='differential'?{...empty,key,refs:{...baseline.refs,task_id:'de-task'},status:'succeeded',items:[baseline,alternate]}:{...empty,key})}
const files=[{id:'experiment-1',filename:'qpcr-confirmation.pdf'}] as ProjectFile[]
const selection={contrast_id:'treated-control',q_column:'q_within_contrast',q_threshold:0.05,minimum_absolute_effect:1,direction:'both'}
const mockFetch=vi.mocked(apiFetch)
const downloadNames:string[]=[]
const originalCreate=Object.getOwnPropertyDescriptor(URL,'createObjectURL')
const originalRevoke=Object.getOwnPropertyDescriptor(URL,'revokeObjectURL')

beforeEach(()=>{
  downloadNames.length=0
  Object.defineProperty(URL,'createObjectURL',{configurable:true,value:vi.fn(()=> 'blob:bulk-report')})
  Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()})
  vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(function(this:HTMLAnchorElement){downloadNames.push(this.download)})
  mockFetch.mockImplementation(async (url,init)=>{
    const path=String(url)
    if(path.includes('/sources?'))return Response.json({items:[{source_id:'de-v2',sha256:hash,kind:'comparison',title:'Primary'},
      {source_id:'qpcr-v3',sha256:hash,kind:'comparison',title:'qPCR fixed comparison'}],total:2})
    if(path.endsWith('/bulk-workflow'))return Response.json(overview)
    if(path.endsWith('/delivery/preview')) {
      const input=JSON.parse(String(init?.body))
      return Response.json({comparison_version_id:input.comparison_version_id,processed_version_id:'qc-v2',
        facts_digest:hash,design:{formula:'~ condition',rank:2,residual_df:4},qc:{summary:{raw_observations:6,retained_observations:5,
          analysis_object:{format:'h5ad',round_trip:{status:'verified'}}}},
        contrasts:[{...baseline.contrasts[0],selection,counts:{total:50,tested:48,deg:2}}],figures:[],candidates:[],enrichments:[],
        sensitivity:null,evidence:input.evidence,references:{},resource_version_ids:[],selected_result_version_ids:input.result_version_ids,
        result_version_ids:input.result_version_ids,limitations:['Local fixture only']})
    }
    if(path.endsWith('/sensitivity')) {
      const input=JSON.parse(String(init?.body))
      const independent=input.baseline_version_id!==input.scenario_version_id
      const side=(id:string,value:unknown)=>({version_id:id,run_id:`run-${id}`,plan_version_id:`plan-${id}`,numerator:'treated',denominator:'control',selection:value})
      return Response.json({comparison_type:independent?'alternate_run':'threshold_only',baseline:side(input.baseline_version_id,input.baseline_selection),
        scenario:side(input.scenario_version_id,input.scenario_selection),sample_changes:{added:[],removed:independent?['S6']:[],shared:independent?5:6,reassigned:[]},
        parameter_changes:independent?['minimum_total_counts']:[],counts:{stable_up:1,lost:0},items:[{feature_id:'ENSG0001',symbol:'GENE1',
          baseline_class:'up',scenario_class:'up',change:'stable_up',baseline_q:0.01,scenario_q:0.01,baseline_effect:2,scenario_effect:2}],total:1,page:1,page_size:50})
    }
    if(path.includes('/delivery/prepare/'))return Response.json({download_url:path.replace('/prepare/','/prepared/')+'/'+hash,artifact_id:hash,facts_digest:hash})
    if(path.endsWith('/analyst-workspace/delivery-artifacts'))return Response.json({file_id:'bulk-doc',filename:'bulk-report.docx',format:'docx',sha256:hash,size_bytes:200},{status:201})
    throw new Error(path)
  })
})
afterEach(()=>{
  cleanup();sessionStorage.clear();vi.restoreAllMocks();mockFetch.mockReset()
  if(originalCreate)Object.defineProperty(URL,'createObjectURL',originalCreate);else Reflect.deleteProperty(URL,'createObjectURL')
  if(originalRevoke)Object.defineProperty(URL,'revokeObjectURL',originalRevoke);else Reflect.deleteProperty(URL,'revokeObjectURL')
})

function workspace(view:BulkWorkflowView,initialId?:string,onNavigate=vi.fn()) {
  return <BulkWorkflowWorkspace projectId="p1" navigation={bulkRoute(view,initialId)} active allowNewAnalysis files={files}
    onNavigate={onNavigate} onUpload={vi.fn()}/>
}
const bodyFor=(suffix:string)=>mockFetch.mock.calls.filter(([url,init])=>String(url).endsWith(suffix)&&init?.method==='POST')
  .map(([,init])=>JSON.parse(String(init?.body)))

it('prepares and adds the reviewed Bulk Word without downloading or publishing it',async()=>{
  render(<BulkWorkflowWorkspace projectId="p1" navigation={bulkRoute('delivery','de-v2')} active allowNewAnalysis files={files}
    onNavigate={vi.fn()} onUpload={vi.fn()} deliveryTarget={{assignmentRevision:4}}/>)
  const preview=await screen.findByRole('button',{name:'预览报告事实'})
  expect(screen.queryByRole('button',{name:'加入交付候选 · Bulk Word'})).toBeNull()
  fireEvent.click(preview)
  const add=await screen.findByRole('button',{name:'加入交付候选 · Bulk Word'})
  expect(bodyFor('/delivery/prepare/word')).toHaveLength(0)
  fireEvent.click(add)
  await screen.findByText('已加入交付候选 · bulk-report.docx')
  expect(bodyFor('/delivery/prepare/word')).toEqual([expect.objectContaining({comparison_version_id:'de-v2',facts_digest:hash})])
  expect(bodyFor('/analyst-workspace/delivery-artifacts')).toEqual([{assignment_revision:4,kind:'bulk_word',artifact_id:hash,facts_digest:hash}])
  expect(bodyFor('/analyst-workspace/publish')).toHaveLength(0)
  expect(downloadNames).toHaveLength(0)
})

it('reuses the first Bulk delivery attachment request after an uncertain response',async()=>{
  const fetch=mockFetch.getMockImplementation()!
  let attempts=0
  mockFetch.mockImplementation(async(url,init)=>{
    if(String(url).endsWith('/analyst-workspace/delivery-artifacts')&&++attempts===1)
      return Response.json({detail:{code:'internal_error'}},{status:503})
    return fetch(url,init)
  })
  const view=<BulkWorkflowWorkspace projectId="p1" navigation={bulkRoute('delivery','de-v2')} active allowNewAnalysis files={files}
    onNavigate={vi.fn()} onUpload={vi.fn()} deliveryTarget={{assignmentRevision:4}}/>
  const mounted=render(view)
  fireEvent.click(await screen.findByRole('button',{name:'预览报告事实'}))
  fireEvent.click(await screen.findByRole('button',{name:'加入交付候选 · Bulk Word'}))
  await screen.findByRole('alert')
  mounted.unmount()
  render(view)
  fireEvent.click(await screen.findByRole('button',{name:'预览报告事实'}))
  fireEvent.click(await screen.findByRole('button',{name:'加入交付候选 · Bulk Word'}))
  await screen.findByText('已加入交付候选 · bulk-report.docx')
  expect(bodyFor('/delivery/prepare/word')).toHaveLength(1)
  const calls=mockFetch.mock.calls.filter(([url])=>String(url).endsWith('/analyst-workspace/delivery-artifacts'))
  expect(calls).toHaveLength(2)
  expect(calls[0][1]?.body).toBe(calls[1][1]?.body)
  expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'))
})

it('links every main view and preserves fixed history alongside live task navigation',async()=>{
  const navigate=vi.fn()
  render(<><BulkWorkflowNav view="differential" nested={false} onNavigate={navigate}/>{workspace('differential',undefined,navigate)}</>)
  const nav=within(screen.getByRole('navigation',{name:'Bulk RNA-seq 工作流'}))
  for(const [index,label] of ['研究设计','数据与样本','质控','差异分析','功能分析','报告与下载'].entries()) {
    fireEvent.click(nav.getByRole('button',{name:label}))
    expect(navigate).toHaveBeenLastCalledWith(bulkRoute(bulkWorkflowViews[index]))
  }
  expect((await screen.findByRole('link',{name:'查看任务进度与恢复'})).getAttribute('href')).toBe('#project=p1&section=tasks&task=de-task')
  const historyLabel=screen.getByText('固定版本与历史记录 · 1')
  fireEvent.click(historyLabel)
  const history=within(historyLabel.closest('details')!)
  expect(history.getByText('此历史版本使用旧依赖，固定结果仍可读取。')).toBeTruthy()
  fireEvent.click(history.getByRole('button',{name:'查看固定结果'}))
  expect(navigate).toHaveBeenLastCalledWith({view:'bio-insight-result',fileId:'',bulkView:'differential',resultVersionId:'de-v1'})
  expect(mockFetch.mock.calls.every(([,init])=>!init?.method)).toBe(true)
})

it('reviews two fixed sensitivity modes and restores the selected alternative after reopening',async()=>{
  const element=workspace('differential')
  const mounted=render(element)
  fireEvent.change(await screen.findByLabelText('基线固定比较版本'),{target:{value:'de-v2'}})
  fireEvent.change(within(screen.getByRole('group',{name:'基线筛选'})).getByLabelText('固定比较方向'),{target:{value:'treated-control'}})
  fireEvent.change(within(screen.getByRole('group',{name:'变体筛选'})).getByLabelText('q 阈值'),{target:{value:'0.02'}})
  fireEvent.click(screen.getByRole('button',{name:'核对并比较固定结果'}))
  await screen.findByRole('table',{name:'基因稳健性对照结果'})
  expect(bodyFor('/sensitivity')[0]).toMatchObject({baseline_version_id:'de-v2',scenario_version_id:'de-v2',
    baseline_selection:selection,scenario_selection:{...selection,q_threshold:0.02}})
  fireEvent.change(screen.getByLabelText('稳健性对照类型'),{target:{value:'run'}})
  fireEvent.change(screen.getByLabelText('另一个固定比较版本'),{target:{value:'de-v1'}})
  fireEvent.change(within(screen.getByRole('group',{name:'变体筛选'})).getByLabelText('固定比较方向'),{target:{value:'variant-treated-control'}})
  fireEvent.click(screen.getByRole('button',{name:'核对并比较固定结果'}))
  expect(await screen.findByText('变体移除样本 · S6')).toBeTruthy()
  expect(bodyFor('/sensitivity')[1]).toMatchObject({baseline_version_id:'de-v2',scenario_version_id:'de-v1'})
  mounted.unmount()
  const reopened=render(element)
  expect((await screen.findByLabelText('另一个固定比较版本') as HTMLSelectElement).value).toBe('de-v1')
  expect(bodyFor('/sensitivity')).toHaveLength(2)
  reopened.unmount()
  render(workspace('delivery','de-v2'))
  fireEvent.click(await screen.findByRole('checkbox',{name:/附上已核对的稳健性对照/}))
  fireEvent.click(screen.getByRole('button',{name:'预览报告事实'}))
  await screen.findByText('Local fixture only')
  expect(bodyFor('/delivery/preview')[0].sensitivity).toEqual({baseline_version_id:'de-v2',scenario_version_id:'de-v1',
    baseline_selection:selection,scenario_selection:{...selection,contrast_id:'variant-treated-control'}})
})

it('requires exact preview before both native downloads and separates evidence from compatible results',async()=>{
  render(workspace('delivery','de-v2'))
  expect((await screen.findByLabelText('报告主比较固定版本') as HTMLSelectElement).value).toBe('de-v2')
  const checkbox=screen.getByRole('checkbox',{name:/ora-v2/})
  expect(screen.queryByRole('checkbox',{name:/wrong-lineage/})).toBeNull()
  expect(screen.queryByRole('checkbox',{name:/unsupported-candidate/})).toBeNull()
  expect(screen.queryByRole('button',{name:'下载 Bulk Word 报告'})).toBeNull()
  fireEvent.click(checkbox)
  fireEvent.change(screen.getByLabelText('佐证类型'),{target:{value:'independent_analysis'}})
  await screen.findByRole('option',{name:/qPCR fixed comparison/})
  fireEvent.change(screen.getByLabelText('选择独立分析版本'),{target:{value:'qpcr-v3'}})
  fireEvent.click(screen.getByRole('button',{name:'添加佐证引用'}))
  fireEvent.change(screen.getByLabelText('佐证类型'),{target:{value:'experimental_material'}})
  fireEvent.change(screen.getByLabelText('选择实验材料原件'),{target:{value:'experiment-1'}})
  fireEvent.click(screen.getByRole('button',{name:'添加佐证引用'}))
  fireEvent.click(screen.getByRole('button',{name:'预览报告事实'}))
  expect(await screen.findByText('Local fixture only')).toBeTruthy()
  expect(within(screen.getByRole('region',{name:'固定报告事实预览'})).getByText('保留样本数')).toBeTruthy()
  const request={comparison_version_id:'de-v2',result_version_ids:['ora-v2'],language:'zh',selections:[],sensitivity:null,
    evidence:[{kind:'independent_analysis',source_id:'qpcr-v3',note:''},{kind:'experimental_material',source_id:'experiment-1',note:''}]}
  expect(bodyFor('/delivery/preview')).toEqual([request])
  fireEvent.click(screen.getByRole('button',{name:'下载 Bulk Word 报告'}))
  fireEvent.click(screen.getByRole('button',{name:'下载 Bulk 完整复现包'}))
  await waitFor(()=>expect(downloadNames).toEqual(['bulk-rna-report-aaaaaaaaaaaa.docx','bulk-rna-reproducibility-aaaaaaaaaaaa.zip']))
  expect(bodyFor('/prepare/word')).toEqual([{...request,facts_digest:hash}])
  expect(bodyFor('/prepare/archive')).toEqual([{...request,facts_digest:hash}])
  fireEvent.change(screen.getByLabelText('报告语言'),{target:{value:'en'}})
  expect(screen.queryByRole('button',{name:'下载 Bulk Word 报告'})).toBeNull()
})

it('continues differential analysis from the server-designated reusable QC result',async()=>{
  const original=mockFetch.getMockImplementation()!
  mockFetch.mockImplementation((url,init)=>String(url).endsWith('/bulk-workflow')?Promise.resolve(Response.json({
    ...overview,stages:overview.stages.map(stage=>stage.key==='qc'?{
      ...stage,refs:{recipe_version_id:'new-display-recipe'},reusable_processed_refs:{processed_version_id:'qc-v2'},
    }:stage),
  })):original(url,init))
  const navigate=vi.fn()
  render(workspace('differential',undefined,navigate))
  fireEvent.click(await screen.findByRole('button',{name:'从当前质控版本配置差异分析'}))
  expect(navigate).toHaveBeenCalledWith({view:'bio-insights',fileId:'',bulkView:'differential',processedId:'qc-v2'})
})
