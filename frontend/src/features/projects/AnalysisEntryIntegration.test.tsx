import {useState} from 'react'
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {apiFetch} from '../../shared/api/client'
import ProjectResources from './ProjectResources'
import type {AnalysisNavigation} from './analysisViews'
import type {Version} from '../research-intake/contracts'

vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),onApiSessionChanged:()=>()=>{}}))
vi.mock('../files/ProjectFileLibrary',()=>({default:()=>null}))
vi.mock('../files/BatchUpload',()=>({default:()=>null}))
vi.mock('../files/ExcelPreview',()=>({default:()=>null}))
vi.mock('../bioinformatics/BioUpload',()=>({default:()=>null}))
vi.mock('../bioinformatics/BioImports',()=>({default:({active,initialFileIds}:{active:boolean;initialFileIds?:string[]})=>active?<output>import:{initialFileIds?.join(',')}</output>:null}))
vi.mock('../bio-insights/BioInsightsWorkspace',()=>({default:({active,navigation}:{active:boolean;navigation:AnalysisNavigation})=>active?<output>insight:{navigation.intent}</output>:null}))
vi.mock('../analysis/AnalysisSetup',()=>({default:({fileId}:{fileId:string})=><output>table:{fileId}</output>}))
vi.mock('../analysisPlan/ProjectRequirements',()=>({default:()=>null}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
const saved=(id='old',kind='qc',fileId='one'):Version=>({id,version:id==='old'?1:2,operation:'save',created_at:'',sha256:'hash',content:{schema_version:1,scope_items:[{id:'questionnaire.analysis.'+kind,title:'需求-'+kind,delivery_kind:'analysis',status:'planned'}]},material_refs:[{file_id:fileId,availability:'provided',purpose:'raw_data'}]})
const files=[{id:'one',filename:'one.xlsx',file_type:'xlsx',parse_status:'parsed',size_bytes:10,uploaded_at:'',error:null},{id:'raw',filename:'original.zip',file_type:'bio_bundle',parse_status:'stored',size_bytes:10,uploaded_at:'',error:null}]
function Harness({projectId='p1',initial={view:'overview',fileId:''},accepted}:{projectId?:string;initial?:AnalysisNavigation;accepted?:Version}){
 const [navigation,setNavigation]=useState(initial)
 return <ProjectResources projectId={projectId} active section="analysis" onSaved={()=>{}} onSectionChange={()=>{}} analysisNavigation={navigation} onAnalysisNavigate={setNavigation} savedRequirement={accepted}/>
}
function reads(current:Version,fixed=current){vi.mocked(apiFetch).mockImplementation(async(url)=>{
 if(String(url).endsWith('/files'))return Response.json(files)
 if(String(url).includes('/tasks?'))return Response.json({items:[],total:0})
 if(String(url).endsWith('/research-intake'))return Response.json({current_requirement:current})
 if(String(url).includes('/requirements/'))return Response.json(fixed)
 throw Error(String(url))
})}
it('opens a unique table, rereads its exact requirement and makes no computation request',async()=>{
 reads(saved());render(<Harness/>);await screen.findByRole('button',{name:'进入配置'});await waitFor(()=>expect((screen.getByRole('button',{name:'进入配置'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'进入配置'}));await screen.findByText('table:one')
 expect(vi.mocked(apiFetch).mock.calls.some(([url])=>String(url).endsWith('/requirements/old'))).toBe(true)
 expect(vi.mocked(apiFetch).mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
})
it('refreshes a fixed requirement without silently switching to the newer current version',async()=>{
 reads(saved('new','multiomics'),saved());render(<Harness initial={{view:'profile',fileId:'one',entry:{requirementVersionId:'old',scopeItemId:'questionnaire.analysis.qc'},intent:'table'}}/> )
 await screen.findByText('已有更新的需求版本，当前仍保留原入口。切换前请核对现有草稿。')
 expect(screen.getByText('table:one')).toBeTruthy();expect(screen.queryByText('insight:integration')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'查看当前需求清单'}))
 await screen.findByRole('article',{name:'需求-multiomics'})
})
it('uses the successful save version while a delayed intake read still returns the old one',async()=>{
 reads(saved());render(<Harness accepted={saved('new','multiomics')}/>)
 await screen.findByRole('article',{name:'需求-multiomics'});await waitFor(()=>expect((screen.getByRole('button',{name:'进入配置'}) as HTMLButtonElement).disabled).toBe(false))
 expect(screen.queryByRole('article',{name:'需求-qc'})).toBeNull()
})
it('routes stored originals to import review without claiming they are published',async()=>{
 reads(saved('old','qc','raw'));render(<Harness/>);await screen.findByRole('button',{name:'进入导入核对'})
 await waitFor(()=>expect((screen.getByRole('button',{name:'进入导入核对'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'进入导入核对'}));await screen.findByText('import:raw')
 expect(vi.mocked(apiFetch).mock.calls.every(([,init])=>!init?.method)).toBe(true)
})
it('discards late responses from the previous project',async()=>{
 let resolveOld!:(r:Response)=>void
 vi.mocked(apiFetch).mockImplementation(async(url)=>{
 if(String(url).endsWith('/files'))return Response.json(files)
 if(String(url).includes('/tasks?'))return Response.json({items:[],total:0})
 if(String(url).includes('/p1/'))return new Promise<Response>(resolve=>{resolveOld=resolve})
 return Response.json({current_requirement:saved('new','multiomics')})
 })
 const {rerender}=render(<Harness/>);rerender(<Harness projectId="p2"/>);await screen.findByRole('article',{name:'需求-multiomics'})
 await act(async()=>resolveOld(Response.json({current_requirement:saved()})))
 expect(screen.queryByRole('article',{name:'需求-qc'})).toBeNull()
})
