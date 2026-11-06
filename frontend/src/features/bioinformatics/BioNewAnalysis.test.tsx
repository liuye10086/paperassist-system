import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import BioNewAnalysis from './BioNewAnalysis'
import {capabilitiesFixture,rawFixture,recipeFixture} from './spatialFixtures'
import useProjectSelection from '../projects/useProjectSelection'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear();window.history.replaceState(null,'','/')})
it('creates a frozen setup separately from starting any scientific task',async()=>{vi.mocked(apiFetch).mockImplementation(async(_url,init)=>Response.json(init?.method==='POST'?recipeFixture:capabilitiesFixture));const navigate=vi.fn();render(<BioNewAnalysis projectId="p1" source={rawFixture} onNavigate={navigate}/>);fireEvent.click(await screen.findByText('新建空间分析配置'));await waitFor(()=>expect(navigate).toHaveBeenCalledWith({view:'bio-analysis-setup',fileId:'',setupId:'setup1'}));expect(vi.mocked(apiFetch).mock.calls.filter(c=>c[1]?.method==='POST')).toHaveLength(1);expect(vi.mocked(apiFetch).mock.calls.some(c=>String(c[0]).includes('/bio-analysis-runs'))).toBe(false)})
it('starts single-cell analysis once with edited parameters and opens the existing run',async()=>{
 const source={...rawFixture,parser_version:'single_cell_import_v1'},navigate=vi.fn()
 vi.mocked(apiFetch).mockImplementation(async(_url,init)=>Response.json(init?.method==='POST'?{id:'direct1',task:{id:'task1'}}:{...capabilitiesFixture,raw_source:source,recipes:['single_cell_explore_v1']}))
 render(<BioNewAnalysis projectId="p1" source={source} onNavigate={navigate}/>)
 fireEvent.change(await screen.findByLabelText('最低检测基因数'),{target:{value:'7'}})
 fireEvent.click(screen.getByRole('button',{name:'开始单细胞分析'}))
 await waitFor(()=>expect(navigate).toHaveBeenCalledWith({view:'bio-analysis',fileId:'',runId:'direct1'}))
 const posts=vi.mocked(apiFetch).mock.calls.filter(c=>c[1]?.method==='POST')
 expect(posts).toHaveLength(1);expect(String(posts[0][0])).toContain('/single-cell-analysis-runs')
 expect(JSON.parse(posts[0][1]!.body as string)).toMatchObject({raw_source:source,params:{min_genes:7,in_tissue_only:false}})
 expect(screen.queryByText('新建单细胞分析配置')).toBeNull()
})
it('recovers an uncertain single-cell start with the original run identity without another POST',async()=>{
 const source={...rawFixture,parser_version:'single_cell_import_v1'},navigate=vi.fn()
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method==='POST')throw new TypeError('connection interrupted')
  return Response.json(String(url).includes('/bio-requests/')?{kind:'run',id:'recovered1',root_id:null,task_id:'task1',request_digest:'a'.repeat(64)}:{...capabilitiesFixture,raw_source:source})
 })
 render(<BioNewAnalysis projectId="p1" source={source} onNavigate={navigate}/>)
 fireEvent.click(await screen.findByRole('button',{name:'开始单细胞分析'}))
 fireEvent.click(await screen.findByRole('button',{name:'按原请求身份核对'}))
 await waitFor(()=>expect(navigate).toHaveBeenCalledWith({view:'bio-analysis',fileId:'',runId:'recovered1'}))
 expect(vi.mocked(apiFetch).mock.calls.filter(c=>c[1]?.method==='POST')).toHaveLength(1)
 const post=vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')!
 const key=new Headers(post[1]?.headers).get('Idempotency-Key')
 expect(vi.mocked(apiFetch).mock.calls.some(c=>String(c[0]).includes(`/bio-requests/${key}?kind=run`))).toBe(true)
})
it('disables single-cell start while the runtime is unavailable',async()=>{
 const source={...rawFixture,parser_version:'single_cell_import_v1'}
 vi.mocked(apiFetch).mockResolvedValue(Response.json({...capabilitiesFixture,available:false,blockers:['bio_environment_unavailable']}))
 render(<BioNewAnalysis projectId="p1" source={source} onNavigate={vi.fn()}/>)
 const button=await screen.findByRole('button',{name:'开始单细胞分析'})
 expect((button as HTMLButtonElement).disabled).toBe(true)
 expect(screen.getByText('bio_environment_unavailable')).toBeTruthy()
 expect(vi.mocked(apiFetch).mock.calls.some(c=>c[1]?.method==='POST')).toBe(false)
})
function Harness(){const s=useProjectSelection(()=>{},()=>{});return <><output>{s.analysisNavigation.view}</output><BioNewAnalysis projectId="p1" source={rawFixture} onNavigate={s.selectAnalysis} registerLeaveGuard={s.registerLeaveGuard}/></>}
it('can navigate to a successfully saved setup through the real pending leave guard',async()=>{window.history.replaceState(null,'','/#project=p1&section=analysis&view=bio-dataset&dataset=d1&version=v1');vi.spyOn(window,'alert').mockImplementation(()=>{});vi.mocked(apiFetch).mockImplementation(async(url,init)=>Response.json(init?.method==='POST'?recipeFixture:String(url).endsWith('/p1')?{id:'p1',name:'Research',research_topic:'T',project_type:'research',file_count:0,created_at:'x',updated_at:'x'}:capabilitiesFixture));render(<Harness/>);fireEvent.click(await screen.findByText('新建空间分析配置'));await waitFor(()=>expect(window.location.hash).toContain('view=bio-analysis-setup&setup=setup1'));expect(window.alert).not.toHaveBeenCalled()})
