import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import BioAnalysisSetup from './BioAnalysisSetup'
import BioAnalysisReview from './BioAnalysisReview'
import BioAnalysisResult from './BioAnalysisResult'
import BioImports from './BioImports'
import {capabilitiesFixture,processedFixture,runFixture,setupFixture} from './spatialFixtures'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
vi.mock('../../shared/components/ProjectDownloadLink',()=>({default:({children}:{children:import('react').ReactNode})=><span>{children}</span>}))
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear()})
it('shows saved single-cell model coverage and offers only an emitted correction layer',async()=>{
 const result={...processedFixture,tables:[],manifest:{assay:'single_cell',layers:{counts:{},decontx_counts:{}},summary:{single_cell_algorithms:{
  doublet:{status:'completed',computed_cells:100,predicted_doublets:5,excluded_cells:0,completed_libraries:2,libraries:2},
  decontx:{status:'completed',computed_cells:100,corrected_cells:100,layer_emitted:true,completed_libraries:2,libraries:2},
  versions:{R:'4.4.3',scDblFinder:'1.20.2',decontX:'1.4.0'},
 }}}}
 vi.mocked(apiFetch).mockResolvedValue(Response.json(result))
 render(<BioAnalysisResult projectId="p1" processedId="processed1" tab="qc" onNavigate={()=>{}}/>)
 fireEvent.click(await screen.findByRole('button',{name:'质控模型'}))
 expect(await screen.findByRole('heading',{name:'双细胞与环境 RNA 结果'})).toBeTruthy()
 expect(screen.getByText('预测双细胞：5；实际排除：0')).toBeTruthy()
 expect(screen.getByText('已保存环境 RNA 校正计数；原始计数及后续分析使用的数据保持不变。')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'矩阵预览'}))
 const layers=screen.getByLabelText('有界矩阵数据层') as HTMLSelectElement
 expect(Array.from(layers.options).map(v=>v.value)).toContain('decontx_counts')
})
it('shows partial model failure without offering a missing correction layer',async()=>{
 const result={...processedFixture,tables:[],steps:[{key:'decontx',status:'partial',reason:'some_libraries_not_computable_or_failed'}],manifest:{assay:'single_cell',layers:{counts:{}},summary:{single_cell_algorithms:{
  doublet:{status:'not_requested',reason:'disabled'},
  decontx:{status:'partial',reason:'some_libraries_not_computable_or_failed',computed_cells:100,input_cells:140,layer_emitted:false,completed_libraries:1,libraries:2},
 }}}}
 vi.mocked(apiFetch).mockResolvedValue(Response.json(result))
 render(<BioAnalysisResult projectId="p1" processedId="processed1" tab="qc" onNavigate={()=>{}}/>)
 fireEvent.click(await screen.findByRole('button',{name:'质控模型'}))
 await screen.findByRole('heading',{name:'双细胞与环境 RNA 结果'})
 expect(screen.getByText('状态：部分完成；完成文库：1 / 2；已计算细胞：100 / 140')).toBeTruthy()
 expect(screen.getByText('部分文库不可计算或失败，详见逐文库结果表')).toBeTruthy()
 expect(screen.getByText('未生成可供后续使用的校正数据；原始计数及后续分析使用的数据保持不变。')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'矩阵预览'}))
 const layers=screen.getByLabelText('有界矩阵数据层') as HTMLSelectElement
 expect(Array.from(layers.options).map(v=>v.value)).not.toContain('decontx_counts')
})
it('opens QC results from upload without showing downstream analysis actions',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json(processedFixture))
 render(<BioImports projectId="p1" active sectioned navigation={{view:'bio-result',fileId:'',processedId:'processed1',tab:'qc'}} onNavigate={()=>{}}/>)
 await screen.findByRole('heading',{name:'空间分析处理结果'})
 expect(screen.queryByRole('button',{name:'差异与功能分析'})).toBeNull()
 expect(screen.queryByRole('button',{name:'整理研究发现与报告'})).toBeNull()
 expect(screen.getByRole('button',{name:'QC 与过滤'})).toBeTruthy()
})
it('opens the submitted single-cell import with its own matrix flow and draft',async()=>{
 sessionStorage.setItem('paperassist.research-draft.v1:owner1:p1:bio-import:analysis:workflow',JSON.stringify('v1'))
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).endsWith('/files')?[]:{items:[],total:0}))
 render(<BioImports projectId="p1" active sectioned qualityMode={false} allowCloud={false}
  navigation={{view:'bio-datasets',fileId:'',intent:'single_cell_import',entry:{requirementVersionId:'submitted',scopeItemId:'customer.type.single_cell'}}}
  onNavigate={vi.fn()}/>)
 expect(await screen.findByRole('heading',{name:'导入并核对单细胞矩阵'})).toBeTruthy()
 expect(screen.getByRole('button',{name:'导入与检查'}).getAttribute('aria-pressed')).toBe('true')
 expect(screen.getByLabelText('单细胞矩阵格式')).toBeTruthy()
 expect(screen.queryByLabelText('导入核对流程')).toBeNull()
 expect(vi.mocked(apiFetch).mock.calls.every(([,init])=>!init?.method)).toBe(true)
})
it('opens an existing single-cell UMAP through the scoped processing history',async()=>{
 const rawSource={...runFixture.raw_source,parser_version:'single_cell_import_v1'}
 const completed={...runFixture,raw_source:rawSource,task:{...runFixture.task,status:'succeeded'},result_source:processedFixture.source}
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).endsWith('/files')?[]:{
  items:String(url).includes('/bio-analysis-runs?')?[completed,{...completed,id:'visium',raw_source:runFixture.raw_source}]:[],total:2,
 }))
 const navigate=vi.fn(),entry={requirementVersionId:'submitted',scopeItemId:'customer.figure.single_cell.umap'}
 render(<BioImports projectId="p1" active sectioned qualityMode={false} navigation={{view:'bio-datasets',fileId:'',intent:'single_cell_results',entry}} onNavigate={navigate}/>)
 fireEvent.click(await screen.findByRole('button',{name:'打开固定处理结果'}))
 expect(screen.queryByRole('button',{name:'查看空间分析运行与 QC 确认'})).toBeNull()
 expect(navigate).toHaveBeenCalledWith({view:'bio-result',fileId:'',entry,intent:'single_cell_results',processedId:processedFixture.id,tab:'embedding'})
})
it('explains the analysis source and blocker without exposing runtime codes',async()=>{
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('capabilities')?{...capabilitiesFixture,available:false,blockers:['environment_unavailable']}:setupFixture))
 render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>)
 fireEvent.click(await screen.findByRole('button',{name:'能力与来源'}))
 await screen.findByText('生信计算环境尚未就绪；任务不能开始正式计算。')
 expect(screen.getByRole('button',{name:'开始分析'})).toHaveProperty('disabled',true)
 expect(screen.getByText(/空间表达数据/)).toBeTruthy()
 expect(screen.queryByText(capabilitiesFixture.raw_source.parser_version)).toBeNull()
 expect(document.querySelector('details, summary')).toBeNull()
})
it('preserves modified recipe inputs on a revision conflict',async()=>{vi.mocked(apiFetch).mockImplementation(async(url,init)=>init?.method==='POST'?Response.json({detail:{code:'conflict'}},{status:409}):Response.json(String(url).includes('capabilities')?capabilitiesFixture:setupFixture));render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>);const input=await screen.findByLabelText('最低 counts');fireEvent.change(input,{target:{value:'12'}});fireEvent.click(screen.getByText('保存新配方版本'));await screen.findByText('版本已更新；草稿已保留，请重新读取最新版本后核对。');expect((input as HTMLInputElement).value).toBe('12');const call=vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST');expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({expected_revision:1,raw_source:capabilitiesFixture.raw_source,params:{min_counts:12}})})
it('requires explicit QC acceptance and submits the frozen checkpoint identity',async()=>{vi.mocked(apiFetch).mockResolvedValue(Response.json(runFixture));render(<BioAnalysisReview projectId="p1" runId="run1" onNavigate={()=>{}}/>);const button=await screen.findByText('确认此 QC 候选并继续计算');expect((button as HTMLButtonElement).disabled).toBe(true);expect(screen.queryByText('处理版本已发布')).toBeNull();fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(button);await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(c=>c[1]?.method==='POST')).toBe(true));const call=vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST');expect(JSON.parse(String(call?.[1]?.body))).toEqual({task_revision:2,checkpoint_id:'checkpoint1',wait_id:'wait1',candidate_sha256:'d'.repeat(64),expected_setup_revision:1})})
it('shows the QC summary first and leaves advanced data and result files in separate views',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json(processedFixture))
 const navigate=vi.fn()
 const props={projectId:'p1',processedId:'processed1',onNavigate:navigate}
 const view=render(<BioAnalysisResult {...props} tab="qc"/>)
 await screen.findByRole('table',{name:'原始、保留与排除数量对账'})
 expect(screen.queryByRole('heading',{name:'实际步骤状态和缺口'})).toBeNull()
 expect(screen.queryByRole('heading',{name:'查看高级数据结构'})).toBeNull()
 expect(screen.queryByText('visium_explore_v1.0.0')).toBeNull()
 expect(screen.getByText('spot 或组织片段不代表独立供体；marker 仅为探索性区域或 cluster 关联。')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'方法与复现'}))
 expect(navigate).toHaveBeenCalledWith({view:'bio-result',fileId:'',processedId:'processed1',tab:'methods'})
 view.rerender(<BioAnalysisResult {...props} tab="methods"/>)
 expect(screen.getByRole('table',{name:'实际步骤状态和缺口'})).toBeTruthy()
 expect(screen.getByText('仅有一个聚类，无法进行组间比较')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'高级数据'}))
 expect(screen.getByRole('heading',{name:'查看高级数据结构'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'结果文件'}))
 expect(screen.queryByRole('heading',{name:'查看高级数据结构'})).toBeNull()
 expect(screen.getByText('暂无已发布成员')).toBeTruthy()
})
it('distinguishes the saved marker figure pages without exposing their storage names',async()=>{
 const kind='marker_dotplot' as const
 const member=(key:string)=>({id:key,key,format:'png',sha256:'d'.repeat(64),size_bytes:100,download_url:'/api/v1/projects/p1/figures/'+key+'/download'})
 const figures=['marker_dotplot','marker_dotplot_page_2'].map(title=>({id:title,root_id:title,version:1,processed_source:processedFixture.source,
  annotation_version_id:null,config:{kind,title},manifest_sha256:'e'.repeat(64),members:[member(title+'_png')]}))
 vi.mocked(apiFetch).mockResolvedValue(Response.json({...processedFixture,figures}))
 const onNavigate=vi.fn()
 render(<BioAnalysisResult projectId="p1" processedId="processed1" tab="markers" onNavigate={onNavigate}/>)
 const select=await screen.findByRole('combobox',{name:'图表'})
 expect(screen.getByRole('option',{name:'标记基因气泡图 - 第 2 张'})).toBeTruthy()
 expect(screen.queryByText('marker_dotplot_page_2')).toBeNull()
 fireEvent.change(select,{target:{value:figures[1].id}})
 fireEvent.click(screen.getByRole('button',{name:'打开固定单图版本'}))
 expect(onNavigate).toHaveBeenCalledWith({view:'bio-figure',fileId:'',figureId:figures[1].id})
})
it('requires new acceptance when a reread returns a different QC candidate digest',async()=>{let read=0;vi.mocked(apiFetch).mockImplementation(async()=>Response.json(++read===1?runFixture:{...runFixture,candidate:{...runFixture.candidate,sha256:'f'.repeat(64)}}));render(<BioAnalysisReview projectId="p1" runId="run1" onNavigate={()=>{}}/>);const checkbox=await screen.findByRole('checkbox');fireEvent.click(checkbox);expect((checkbox as HTMLInputElement).checked).toBe(true);fireEvent.click(screen.getByText('重新读取'));await waitFor(()=>expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false));expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);expect((screen.getByText('确认此 QC 候选并继续计算') as HTMLButtonElement).disabled).toBe(true)})
it('keeps recipe inputs visible after a same-source reread fails',async()=>{let failed=false;vi.mocked(apiFetch).mockImplementation(async url=>{if(String(url).includes('capabilities'))return Response.json(capabilitiesFixture);if(failed)throw new TypeError('network');return Response.json(setupFixture)});render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>);const input=await screen.findByLabelText('最低 counts');fireEvent.change(input,{target:{value:'12'}});failed=true;fireEvent.click(screen.getByText('重新读取最新版本（保留草稿）'));await screen.findByText('空间分析读取失败，请重试。');expect((screen.getByLabelText('最低 counts') as HTMLInputElement).value).toBe('12')})
