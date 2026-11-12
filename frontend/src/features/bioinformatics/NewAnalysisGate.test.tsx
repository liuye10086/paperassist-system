import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import ProjectResources from '../projects/ProjectResources'
import BioAnalysisResult from './BioAnalysisResult'
import SingleCellDirectStart from './SingleCellDirectStart'
import {BioFigureComposer} from './BioFigureDetail'
import BioInsightsWorkspace from '../bio-insights/BioInsightsWorkspace'
import {capabilitiesFixture,processedFixture,rawFixture} from './spatialFixtures'

vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',captureApiSession:()=>()=>true,onApiSessionChanged:()=>()=>{}}))
vi.mock('../../shared/components/ProjectDownloadLink',()=>({default:({href,children}:{href:string;children:React.ReactNode})=><a href={href}>{children}</a>}))
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear()})
const source={...rawFixture,parser_version:'single_cell_import_v1'}
const result={...processedFixture,source:{...processedFixture.source,raw_source:source},manifest:{assay:'single_cell',params:capabilitiesFixture.default_params}}
const annotation={id:'annv1',set_id:'ann1',name:'Manual labels',version:1,revision:1,raw_source:source,processed_dataset_version_id:result.id,labels:[],regions:[],evidence:[],checks:[],assignments:[],overlap_policy:'ambiguity'}
const posts=()=>vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')
function reads(url:RequestInfo|URL){
 const path=String(url)
 return Response.json(path.endsWith('/repeat-context')?{params:capabilitiesFixture.default_params,observation_map_version_id:null,design_version_id:null,repeat_allowed:true}:path.includes('/bio-analysis-capabilities')?capabilitiesFixture:path.endsWith('/annotations')?{items:[annotation]}:path.endsWith('/bio-single-cell-references')?{items:[{reference_id:'monaco',available:true,species:'human',gene_id_type:'symbol'}]}:path.endsWith('/annotation-runs')?{items:[]}:path.endsWith('/files')?[]:path.endsWith('/research-intake')?{current_requirement:null}:path.includes('/bio-processed-datasets/processed1')?result:{items:[],total:0})
}

it('passes the current workflow gate through resources and imports while keeping historical Word readable',async()=>{
 vi.mocked(apiFetch).mockImplementation(async url=>reads(url))
 render(<ProjectResources allowNewAnalysis={false} projectId="p1" section="analysis" analysisNavigation={{view:'bio-result',fileId:'',processedId:result.id,tab:'methods'}} onSaved={()=>{}} onSectionChange={()=>{}}/>)
 expect(await screen.findByRole('link',{name:'下载 Word 分析报告'})).toBeTruthy()
 expect(await screen.findByRole('button',{name:'用此参数打开分析方案'})).toHaveProperty('disabled',true)
 expect(posts()).toHaveLength(0)
})

it('adds the exact fixed single-cell Word and PNG to delivery only after explicit actions',async()=>{
 const png={id:'umap1',key:'umap_png',role:'figure_png',format:'png',filename:'umap.png',sha256:'c'.repeat(64),size_bytes:20,download_url:'/api/v1/projects/p1/bio-processed-datasets/processed1/members/umap1/download'}
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method==='POST'){
   const input=JSON.parse(String(init.body))
   const image=input.kind==='single_cell_png'
   return Response.json({file_id:image?'png-file':'word-file',filename:image?'umap.png':'single-cell.docx',format:image?'png':'docx',size_bytes:20,sha256:'c'.repeat(64)},{status:201})
  }
  return String(url).endsWith('/bio-processed-datasets/processed1')?Response.json({...result,members:[png]}):reads(url)
 })
 const deliveries=vi.fn()
 render(<ProjectResources assigned assignmentRevision={2} onDeliveries={deliveries} projectId="p1" section="analysis" analysisNavigation={{view:'bio-result',fileId:'',processedId:result.id,tab:'embedding'}} onSaved={()=>{}} onSectionChange={()=>{}}/>)
 const word=await screen.findByRole('button',{name:'加入交付候选 · Word'})
 expect(posts()).toHaveLength(0)
 fireEvent.click(word)
 await screen.findByText('已加入交付候选 · single-cell.docx')
 fireEvent.click(screen.getByRole('button',{name:'加入交付候选 · umap.png'}))
 await screen.findByText('已加入交付候选 · umap.png')
 expect(posts().map(([url,init])=>[String(url),JSON.parse(String(init?.body))])).toEqual([
  ['/api/v1/projects/p1/analyst-workspace/delivery-artifacts',{assignment_revision:2,kind:'single_cell_word',version_id:result.id}],
  ['/api/v1/projects/p1/analyst-workspace/delivery-artifacts',{assignment_revision:2,kind:'single_cell_png',version_id:result.id,member_id:'umap1'}],
 ])
 expect(new Headers(posts()[0][1]?.headers).get('Idempotency-Key')).toBeTruthy()
 expect(deliveries).not.toHaveBeenCalled()
 fireEvent.click(screen.getAllByRole('button',{name:'打开分析交付'})[0])
 expect(deliveries).toHaveBeenCalledOnce()
})

it.each([
 {available:false,clusters:2,message:'当前环境未验证 Slingshot，可继续查看已有结果。'},
 {available:true,clusters:1,message:'拟时分析需要至少两个固定聚类和可用的 PCA。'},
 {available:true,clusters:2,message:null},
])('checks the fixed data and runtime before offering pseudotime ($available/$clusters)',async({available,clusters,message})=>{
 const pca={id:'pca1',key:'pca',format:'tsv',sha256:'c'.repeat(64),size_bytes:20,download_url:'/pca'}
 const fixed={...result,manifest:{...result.manifest,summary:{clusters,retained_observations:10}},members:[pca]}
 vi.mocked(apiFetch).mockImplementation(async url=>String(url).endsWith('/bio-insights/capabilities')
  ?Response.json({single_cell_topic_runtimes:{slingshot:{available}}}):Response.json(fixed))
 const navigate=vi.fn(),entry={requirementVersionId:'req1',scopeItemId:'customer.analysis.single_cell.pseudotime'}
 render(<BioAnalysisResult projectId="p1" processedId={result.id} tab="embedding" entry={entry} onNavigate={navigate}/>)
 if(message){
  await screen.findByText(message)
  expect(screen.queryByRole('button',{name:'配置 Slingshot 拟时分析'})).toBeNull()
 }else{
  fireEvent.click(await screen.findByRole('button',{name:'配置 Slingshot 拟时分析'}))
  expect(navigate).toHaveBeenCalledWith({view:'bio-insights',fileId:'',processedId:result.id,intent:'single_cell_topic'})
 }
 expect(posts()).toHaveLength(0)
})

it('blocks a new direct run at both its button and submit handler after the gate changes',async()=>{
 vi.mocked(apiFetch).mockImplementation(async url=>reads(url))
 const props={projectId:'p1',source,onNavigate:vi.fn()}
 const view=render(<SingleCellDirectStart {...props}/> )
 fireEvent.click(await screen.findByRole('button',{name:'下一步：检查并运行'}))
 view.rerender(<SingleCellDirectStart {...props} allowNewAnalysis={false}/>)
 const start=screen.getByRole('button',{name:'开始单细胞分析'})
 expect(start).toHaveProperty('disabled',true)
 fireEvent.submit(start.closest('form')!)
 expect(posts()).toHaveLength(0)
})

it('blocks new subsets, SingleR and annotation plots while retaining manual annotation and Word actions',async()=>{
 vi.mocked(apiFetch).mockImplementation(async url=>reads(url))
 render(<BioAnalysisResult allowNewAnalysis={false} projectId="p1" processedId={result.id} tab="spatial" onNavigate={()=>{}}/>)
 fireEvent.change(await screen.findByLabelText('父 cluster ID 列表'),{target:{value:'0'}})
 const subset=screen.getByRole('button',{name:'创建亚群并重新聚类'})
 expect(subset).toHaveProperty('disabled',true)
 fireEvent.submit(subset.closest('form')!)
 await screen.findByRole('option',{name:/monaco/})
 fireEvent.change(screen.getByLabelText('本地参考'),{target:{value:'monaco'}})
 expect(screen.getByRole('button',{name:'运行 SingleR 候选注释'})).toHaveProperty('disabled',true)
 await screen.findByRole('option',{name:'Manual labels · v1'})
 fireEvent.change(screen.getByLabelText('报告使用的人工标签'),{target:{value:annotation.id}})
 expect(screen.getByRole('button',{name:'按此标签绘制 UMAP'})).toHaveProperty('disabled',true)
 expect(screen.getByRole('link',{name:'下载包含所选标签的 Word 报告'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'新建人工注释'}))
 expect(screen.getByRole('button',{name:'添加人工标签'})).toHaveProperty('disabled',false)
 expect(posts()).toHaveLength(0)
})

it('blocks direct figure creation without hiding existing unknown-request recovery',async()=>{
 const key='12345678-1234-1234-1234-123456789012',navigate=vi.fn()
 sessionStorage.setItem('paperassist.bio-request.v1:owner1:p1:figure',key)
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('/bio-requests/')?{kind:'figure',id:'old-figure',root_id:'old-root'}:{items:[]}))
 render(<BioFigureComposer allowNewAnalysis={false} projectId="p1" result={result} onNavigate={navigate}/>)
 expect(screen.getByRole('button',{name:'生成独立单图版本'})).toHaveProperty('disabled',true)
 fireEvent.click(screen.getByRole('button',{name:'按原请求身份核对'}))
 await waitFor(()=>expect(navigate).toHaveBeenCalledWith({view:'bio-figure',fileId:'',figureId:'old-figure'}))
 expect(posts()).toHaveLength(0)
})

it('blocks a new figure when there is no pending request to mask the workflow gate',async()=>{
 vi.mocked(apiFetch).mockImplementation(async()=>Response.json({id:'new-figure'}))
 render(<BioFigureComposer allowNewAnalysis={false} projectId="p1" result={result} onNavigate={()=>{}}/>)
 const create=screen.getByRole('button',{name:'生成独立单图版本'})
 expect(create).toHaveProperty('disabled',true)
 fireEvent.click(create)
 expect(posts()).toHaveLength(0)
})

it('keeps a historical insight run readable but blocks new resource jobs in its local resource panel',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>Response.json(String(url).includes('/bio-insight-runs/old-run')?{id:'old-run',kind:'comparison',task:{id:'old-task',status:'succeeded',phase:'completed'}}:init?.method==='POST'?{executable:true}:{items:[],total:0}))
 render(<BioInsightsWorkspace allowNewAnalysis={false} projectId="p1" active navigation={{view:'bio-insight-plan',fileId:'',runId:'old-run'}} onNavigate={()=>{}}/>)
 expect(await screen.findByText('固定计划后台运行')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'资源管理'}))
 fireEvent.click(await screen.findByRole('button',{name:'预检资源身份与使用范围'}))
 await screen.findByText('资源预检结果')
 const start=screen.getByRole('button',{name:'确认导入资源并创建后台任务'})
 expect(start).toHaveProperty('disabled',true)
 fireEvent.click(start)
 expect(posts().map(([url])=>String(url))).toEqual(['/api/v1/projects/p1/bio-resources/preview'])
})
