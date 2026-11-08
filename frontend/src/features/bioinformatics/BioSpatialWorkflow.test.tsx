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
afterEach(()=>{cleanup();vi.clearAllMocks()})
it('shows saved single-cell model coverage and offers only an emitted correction layer',async()=>{
 const result={...processedFixture,tables:[],manifest:{assay:'single_cell',layers:{counts:{},decontx_counts:{}},summary:{single_cell_algorithms:{
  doublet:{status:'completed',computed_cells:100,predicted_doublets:5,excluded_cells:0,completed_libraries:2,libraries:2},
  decontx:{status:'completed',computed_cells:100,corrected_cells:100,layer_emitted:true,completed_libraries:2,libraries:2},
  versions:{R:'4.4.3',scDblFinder:'1.20.2',decontX:'1.4.0'},
 }}}}
 vi.mocked(apiFetch).mockResolvedValue(Response.json(result))
 render(<BioAnalysisResult projectId="p1" processedId="processed1" tab="qc" onNavigate={()=>{}}/>)
 expect(await screen.findByRole('heading',{name:'双细胞与环境 RNA 结果'})).toBeTruthy()
 expect(screen.getByText('预测双细胞：5；实际排除：0')).toBeTruthy()
 expect(screen.getByText('已保存独立 decontx_counts 层；原始 counts 及当前下游输入保持不变。')).toBeTruthy()
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
 await screen.findByRole('heading',{name:'双细胞与环境 RNA 结果'})
 expect(screen.getByText('状态：部分完成；完成文库：1 / 2；已计算细胞：100 / 140')).toBeTruthy()
 expect(screen.getByText('部分文库不可计算或失败，详见逐文库结果表')).toBeTruthy()
 expect(screen.getByText('未生成可供后续使用的校正层；原始 counts 及当前下游输入保持不变。')).toBeTruthy()
 const layers=screen.getByLabelText('有界矩阵数据层') as HTMLSelectElement
 expect(Array.from(layers.options).map(v=>v.value)).not.toContain('decontx_counts')
})
it('opens QC results from upload without showing downstream analysis actions',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json(processedFixture))
 render(<BioImports projectId="p1" active sectioned navigation={{view:'bio-result',fileId:'',processedId:'processed1',tab:'qc'}} onNavigate={()=>{}}/>)
 await screen.findByText('single_cluster')
 expect(screen.queryByRole('button',{name:'差异与功能分析'})).toBeNull()
 expect(screen.queryByRole('button',{name:'整理研究发现与报告'})).toBeNull()
 expect(screen.getByRole('button',{name:'QC 与过滤'})).toBeTruthy()
})
it('shows immutable source and blocks computation when capability is unavailable',async()=>{vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('capabilities')?{...capabilitiesFixture,available:false,blockers:['environment_unavailable']}:setupFixture));render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>);fireEvent.click(await screen.findByRole('button',{name:'能力与来源'}));await screen.findByText('environment_unavailable');expect((screen.getByText('开始分析') as HTMLButtonElement).disabled).toBe(true);expect(screen.getByText(capabilitiesFixture.raw_source.parser_version)).toBeTruthy();expect(document.querySelector('details, summary')).toBeNull()})
it('preserves modified recipe inputs on a revision conflict',async()=>{vi.mocked(apiFetch).mockImplementation(async(url,init)=>init?.method==='POST'?Response.json({detail:{code:'conflict'}},{status:409}):Response.json(String(url).includes('capabilities')?capabilitiesFixture:setupFixture));render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>);const input=await screen.findByLabelText('最低 counts');fireEvent.change(input,{target:{value:'12'}});fireEvent.click(screen.getByText('保存新配方版本'));await screen.findByText('版本已更新；草稿已保留，请重新读取最新版本后核对。');expect((input as HTMLInputElement).value).toBe('12');const call=vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST');expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({expected_revision:1,raw_source:capabilitiesFixture.raw_source,params:{min_counts:12}})})
it('requires explicit QC acceptance and submits the frozen checkpoint identity',async()=>{vi.mocked(apiFetch).mockResolvedValue(Response.json(runFixture));render(<BioAnalysisReview projectId="p1" runId="run1" onNavigate={()=>{}}/>);const button=await screen.findByText('确认此 QC 候选并继续计算');expect((button as HTMLButtonElement).disabled).toBe(true);expect(screen.queryByText('处理版本已发布')).toBeNull();fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(button);await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(c=>c[1]?.method==='POST')).toBe(true));const call=vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST');expect(JSON.parse(String(call?.[1]?.body))).toEqual({task_revision:2,checkpoint_id:'checkpoint1',wait_id:'wait1',candidate_sha256:'d'.repeat(64),expected_setup_revision:1})})
it('hides internal engine versions while preserving marker limitations',async()=>{vi.mocked(apiFetch).mockResolvedValue(Response.json(processedFixture));render(<BioAnalysisResult projectId="p1" processedId="processed1" tab="qc" onNavigate={()=>{}}/>);await screen.findByText('single_cluster');expect(screen.queryByText('visium_explore_v1.0.0')).toBeNull();expect(screen.getByText('spot 或组织片段不代表独立供体；marker 仅为探索性区域或 cluster 关联。')).toBeTruthy()})
it('requires new acceptance when a reread returns a different QC candidate digest',async()=>{let read=0;vi.mocked(apiFetch).mockImplementation(async()=>Response.json(++read===1?runFixture:{...runFixture,candidate:{...runFixture.candidate,sha256:'f'.repeat(64)}}));render(<BioAnalysisReview projectId="p1" runId="run1" onNavigate={()=>{}}/>);const checkbox=await screen.findByRole('checkbox');fireEvent.click(checkbox);expect((checkbox as HTMLInputElement).checked).toBe(true);fireEvent.click(screen.getByText('重新读取'));await waitFor(()=>expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false));expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);expect((screen.getByText('确认此 QC 候选并继续计算') as HTMLButtonElement).disabled).toBe(true)})
it('keeps recipe inputs visible after a same-source reread fails',async()=>{let failed=false;vi.mocked(apiFetch).mockImplementation(async url=>{if(String(url).includes('capabilities'))return Response.json(capabilitiesFixture);if(failed)throw new TypeError('network');return Response.json(setupFixture)});render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>);const input=await screen.findByLabelText('最低 counts');fireEvent.change(input,{target:{value:'12'}});failed=true;fireEvent.click(screen.getByText('重新读取最新版本（保留草稿）'));await screen.findByText('空间分析读取失败，请重试。');expect((screen.getByLabelText('最低 counts') as HTMLInputElement).value).toBe('12')})
