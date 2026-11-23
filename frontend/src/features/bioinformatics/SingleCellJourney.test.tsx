import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import SingleCellDirectStart from './SingleCellDirectStart'
import BioDatasetDetail from './BioDatasetDetail'
import BioAnalysisReview from './BioAnalysisReview'
import {capabilitiesFixture,processedFixture,rawFixture,runFixture} from './spatialFixtures'

vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',captureApiSession:()=>()=>true,onApiSessionChanged:()=>()=>{}}))
const source={...rawFixture,parser_version:'single_cell_import_v1'}
const posts=()=>vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear()})

it('links all rows of the customer CSV to the guided run after review, without requiring a registered sample design',async()=>{
 const table={file_id:'metadata',sha256:'f'.repeat(64),sheet:0,mapping:{barcode:'barcode',donor:'donor',group:'group'}}
 const counts={mapped:960,unmapped:0,total:960}
 let errors=[{row:2,message:'Unknown barcode'}]
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(url.endsWith('table-previews'))return Response.json({table_source:table,valid:errors.length?959:960,errors,total:960,counts,preview_rows:[]})
  if(url.endsWith('/bio-observation-maps'))return Response.json({id:'mapping-v1',set_id:'mapset',revision:1,design_version_id:null,raw_source:source,rows:[],counts,total:960})
  if(url.endsWith('/single-cell-analysis-runs'))return Response.json({id:'run',task:{id:'task'}})
  if(url.includes('bio-analysis-capabilities'))return Response.json({...capabilitiesFixture,requires_qc_confirmation:true})
  if(init?.method)throw Error(String(url))
  return Response.json({id:'v1',source,shape:{features:12667,observations:960},checks:[],members:[],summary:{}})
 })
 render(<BioDatasetDetail projectId="p1" datasetId="d1" versionId="v1" onNavigate={vi.fn()} mappingFiles={[{id:'metadata',filename:'cell_mapping.csv'}]}/>)
 fireEvent.click(await screen.findByRole('button',{name:'下一步：关联分组表'}))
 expect(screen.getByLabelText('映射来源文件')).toHaveProperty('value','metadata')
 expect(screen.queryByLabelText('样本列')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'检查条码是否匹配'}))
 expect(await screen.findByRole('button',{name:'使用这份分组表，继续分析'})).toHaveProperty('disabled',true)
 errors=[]
 fireEvent.click(screen.getByRole('button',{name:'检查条码是否匹配'}))
 fireEvent.click(await screen.findByRole('button',{name:'使用这份分组表，继续分析'}))
 await screen.findByText('已关联细胞分组表。')
 expect(posts().map(([,init])=>JSON.parse(String(init?.body)))).toEqual([
   expect.objectContaining({mapping:table.mapping}),expect.objectContaining({mapping:table.mapping}),
   expect.objectContaining({table_source:table,rows:[],design_version_id:null}),
 ])
 fireEvent.click(await screen.findByRole('button',{name:'下一步：检查并运行'}))
 fireEvent.click(screen.getByRole('button',{name:'开始单细胞质控'}))
 await waitFor(()=>expect(JSON.parse(String(posts().at(-1)?.[1]?.body))).toMatchObject({observation_map_version_id:'mapping-v1',raw_source:source}))
})

it('reviews parameters without submitting and restores the same draft and step after reload',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(_url,init)=>Response.json(init?.method==='POST'?{id:'run-next',task:{id:'task-next'}}:capabilitiesFixture))
 const navigate=vi.fn(),first=render(<SingleCellDirectStart projectId="p1" source={source} onNavigate={navigate}/>)
 fireEvent.change(await screen.findByLabelText('分析名称'),{target:{value:'我的单细胞分析'}})
 fireEvent.change(screen.getByLabelText('HVG 数量'),{target:{value:'1200'}})
 fireEvent.click(screen.getByRole('button',{name:'下一步：检查并运行'}))
 expect(posts()).toHaveLength(0)
 expect(screen.getByRole('heading',{name:'检查并运行'})).toBeTruthy()
 first.unmount()
 render(<SingleCellDirectStart projectId="p1" source={source} onNavigate={navigate}/>)
 expect(await screen.findByRole('heading',{name:'检查并运行'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'上一步：调整参数'}))
 expect(screen.getByLabelText('分析名称')).toHaveProperty('value','我的单细胞分析')
 expect(screen.getByLabelText('HVG 数量')).toHaveProperty('value','1200')
 fireEvent.click(screen.getByRole('button',{name:'下一步：检查并运行'}))
 fireEvent.click(screen.getByRole('button',{name:'开始单细胞分析'}))
 await waitFor(()=>expect(navigate).toHaveBeenCalledWith({view:'bio-analysis',fileId:'',runId:'run-next'}))
 expect(posts()).toHaveLength(1)
 expect(JSON.parse(String(posts()[0][1]?.body))).toMatchObject({name:'我的单细胞分析',raw_source:source,params:{hvg_count:1200}})
})

it('keeps analysis drafts separate for different source versions',async()=>{
 vi.mocked(apiFetch).mockImplementation(async()=>Response.json(capabilitiesFixture))
 const first=render(<SingleCellDirectStart projectId="p1" source={source} onNavigate={()=>{}}/>)
 fireEvent.change(await screen.findByLabelText('HVG 数量'),{target:{value:'1200'}})
 first.unmount()
 render(<SingleCellDirectStart projectId="p1" source={{...source,dataset_version_id:'v2',version:2}} onNavigate={()=>{}}/>)
 expect(await screen.findByLabelText('HVG 数量')).toHaveProperty('value','2000')
 expect(posts()).toHaveLength(0)
})

it('keeps the reviewed default parameters when capabilities change after reload',async()=>{
 vi.mocked(apiFetch).mockImplementation(async()=>Response.json(capabilitiesFixture))
 const first=render(<SingleCellDirectStart projectId="p1" source={source} onNavigate={()=>{}}/>)
 fireEvent.click(await screen.findByRole('button',{name:'下一步：检查并运行'}))
 first.unmount()
 vi.mocked(apiFetch).mockImplementation(async()=>Response.json({...capabilitiesFixture,default_params:{...capabilitiesFixture.default_params,hvg_count:1000}}))
 render(<SingleCellDirectStart projectId="p1" source={source} onNavigate={()=>{}}/>)
 await screen.findByRole('heading',{name:'检查并运行'})
 fireEvent.click(screen.getByRole('button',{name:'上一步：调整参数'}))
 expect(screen.getByLabelText('HVG 数量')).toHaveProperty('value','2000')
 expect(posts()).toHaveLength(0)
})

it('opens analysis from the dataset next action and remembers the selected panel on reload',async()=>{
 const dataset={id:'v1',dataset_id:'d1',version:1,source,shape:{features:4,observations:3},checks:[],members:[],summary:{}}
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('capabilities')?capabilitiesFixture:dataset))
 const first=render(<BioDatasetDetail projectId="p1" datasetId="d1" versionId="v1" onNavigate={()=>{}}/>)
 const next=await screen.findByRole('button',{name:'下一步：配置分析'});const datasetBody=first.container.querySelector('.module-views')!;const datasetFooter=first.container.querySelector('.bio-confirmation-actions')!;expect(datasetBody.compareDocumentPosition(datasetFooter)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
 fireEvent.click(next)
 expect(await screen.findByRole('textbox',{name:'分析名称'})).toBeTruthy()
 first.unmount()
 render(<BioDatasetDetail projectId="p1" datasetId="d1" versionId="v1" onNavigate={()=>{}}/>)
 expect(await screen.findByRole('textbox',{name:'分析名称'})).toBeTruthy()
 expect(posts()).toHaveLength(0)
})

it('shows a queue state without claiming computation has started',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json({...runFixture,raw_source:source,candidate:null,task:{...runFixture.task,status:'queued'}}))
 render(<BioAnalysisReview projectId="p1" runId="run1" onNavigate={()=>{}}/>)
 expect(await screen.findByText('排队中，轮到此任务后开始分析。')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'下一步：查看结果与 Word'})).toBeNull()
})

it.each([['queued','所选数据的质控任务正在排队。'],['running','正在对所选数据运行质控。']])('shows the QC stage before analyst confirmation (%s)',async(status,message)=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json({...runFixture,raw_source:source,candidate:null,task:{...runFixture.task,status,phase:'parse'}}))
 render(<BioAnalysisReview projectId="p1" runId="run1" onNavigate={()=>{}}/>)
 expect(await screen.findByText(message)).toBeTruthy()
})

it('continues to the completed result without submitting another analysis',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json({...runFixture,raw_source:source,candidate:null,result_source:processedFixture.source,task:{...runFixture.task,status:'succeeded'}}))
 const navigate=vi.fn()
 render(<BioAnalysisReview projectId="p1" runId="run1" onNavigate={navigate}/>)
 fireEvent.click(await screen.findByRole('button',{name:'下一步：查看结果与 Word'}))
 expect(navigate).toHaveBeenCalledWith({view:'bio-result',fileId:'',processedId:'processed1',tab:'qc'})
 expect(posts()).toHaveLength(0)
})
