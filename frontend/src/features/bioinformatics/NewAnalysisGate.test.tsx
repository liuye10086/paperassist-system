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
