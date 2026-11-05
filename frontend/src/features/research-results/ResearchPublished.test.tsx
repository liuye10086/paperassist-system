import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {setApiSession,clearApiSession} from '../../shared/api/client'
import {manuscriptFixture} from '../manuscripts/manuscriptFixtures'
import ResearchPublished from './ResearchPublished'
import ResearchWorkspace from './ResearchWorkspace'
vi.mock('../manuscripts/ManuscriptPreview',()=>({default:()=>null}))
vi.mock('../manuscripts/ManuscriptWriting',()=>({default:()=>null}))
vi.mock('../manuscripts/ManuscriptExports',()=>({default:vi.fn(()=>null)}))
import ManuscriptExports from '../manuscripts/ManuscriptExports'
vi.mock('../manuscripts/WritingMaterialsPreview',()=>({default:()=>null}))
beforeEach(()=>{setApiSession('csrf','owner');sessionStorage.clear()})
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession()})
it('shows manuscript title, real version and readable status while retaining selection identity',async()=>{
 const manuscript={...manuscriptFixture,id:'private-manuscript',title:'已发布研究稿件',versions:[{...manuscriptFixture.versions[0],id:'private-fixed-version',revision:1,status:'published'}]};vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/manuscripts')?{items:[manuscript]}:manuscript)));const onSelect=vi.fn()
 const {container}=render(<ResearchPublished projectId="p1" active manuscriptId={manuscript.id} revision={1} view="versions" onView={vi.fn()} onSelect={onSelect}/>);const version=await screen.findByRole('button',{name:'已发布研究稿件 · 版本 1 · 已发布'});expect(container.textContent).not.toContain('private-fixed-version');expect(container.textContent).not.toContain('revision');fireEvent.click(version);expect(onSelect).toHaveBeenCalledWith('private-manuscript',1);expect(screen.getByText('固定稿件版本：已发布研究稿件 · 版本 1 · 已发布')).toBeTruthy()
})
it('removes technical candidate lookup while retaining the candidate workspace',()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[],deliveries:[]})));render(<ResearchWorkspace projectId="p1" projectType="research" active section="manuscripts" analysis={{view:'overview',fileId:''}} artifact={{view:'list',artifactId:'',kind:'',page:1}} manuscriptView="research-candidates" manuscriptId="" revision={0} onAnalysis={vi.fn()} onArtifact={vi.fn()} onManuscriptView={vi.fn()} onCandidate={vi.fn()} onPublished={vi.fn()} schoolNavigation={{view:'list',templateId:''}} onSchoolNavigate={vi.fn()}/>);
 expect(screen.queryByLabelText('候选记录号')).toBeNull();expect(screen.queryByText('高级历史查找')).toBeNull();expect(screen.getByText('生成事实候选后在这里核对，正式稿件在显式发布后建立。')).toBeTruthy()
})

it('opens the explicitly selected fixed version in Word and forwards its versions and task navigation',async()=>{
 const v1=manuscriptFixture.versions[0],v2={...v1,id:'v2',revision:2,exports:[]};const manuscript={...manuscriptFixture,current_revision:2,versions:[v1,v2]};const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/manuscripts')?{items:[manuscript]}:manuscript));vi.stubGlobal('fetch',fetcher);const onSelect=vi.fn(),onOpenTask=vi.fn()
 render(<ResearchPublished projectId="p1" active manuscriptId="m1" revision={1} view="versions" onView={vi.fn()} onSelect={onSelect} onOpenTask={onOpenTask}/>)
 fireEvent.click(await screen.findByRole('button',{name:'查看版本 1 的 Word'}));expect(onSelect).toHaveBeenCalledWith('m1',1,'exports')
 expect(vi.mocked(ManuscriptExports).mock.calls.some(([props])=>props.version.id==='v1'&&props.versions?.length===2&&props.onOpenTask===onOpenTask)).toBe(true)
 expect(fetcher.mock.calls.every(([,init])=>!init?.method)).toBe(true)
})

it('does not report an empty manuscript list when its first read fails',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({detail:'unavailable'},{status:503})))
 render(<ResearchPublished projectId="p1" active manuscriptId="" revision={0} view="list" onView={vi.fn()} onSelect={vi.fn()}/>)
 await screen.findByRole('alert');expect(screen.queryByText('还没有已发布稿件，请先核对并显式发布事实候选。')).toBeNull()
})
