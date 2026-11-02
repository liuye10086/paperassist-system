import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {setApiSession,clearApiSession} from '../../shared/api/client'
import {manuscriptFixture} from '../manuscripts/manuscriptFixtures'
import ResearchPublished from './ResearchPublished'
import ResearchWorkspace from './ResearchWorkspace'
vi.mock('../manuscripts/ManuscriptPreview',()=>({default:()=>null}))
vi.mock('../manuscripts/ManuscriptWriting',()=>({default:()=>null}))
vi.mock('../manuscripts/ManuscriptExports',()=>({default:()=>null}))
vi.mock('../manuscripts/WritingMaterialsPreview',()=>({default:()=>null}))
beforeEach(()=>{setApiSession('csrf','owner');sessionStorage.clear()})
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession()})
it('shows manuscript title, real version and readable status while retaining selection identity',async()=>{
 const manuscript={...manuscriptFixture,id:'private-manuscript',title:'已发布研究稿件',versions:[{...manuscriptFixture.versions[0],id:'private-fixed-version',revision:1,status:'published'}]};vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/manuscripts')?{items:[manuscript]}:manuscript)));const onSelect=vi.fn()
 const {container}=render(<ResearchPublished projectId="p1" active manuscriptId={manuscript.id} revision={1} view="versions" onView={vi.fn()} onSelect={onSelect}/>);const version=await screen.findByRole('button',{name:'已发布研究稿件 · 版本 1 · 已发布'});expect(container.textContent).not.toContain('private-fixed-version');expect(container.textContent).not.toContain('revision');fireEvent.click(version);expect(onSelect).toHaveBeenCalledWith('private-manuscript',1);expect(screen.getByText('固定稿件版本：已发布研究稿件 · 版本 1 · 已发布')).toBeTruthy()
})
it('keeps manual candidate lookup collapsed while preserving explicit history access',()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[],deliveries:[]})));const onCandidate=vi.fn();render(<ResearchWorkspace projectId="p1" projectType="research" active section="manuscripts" analysis={{view:'overview',fileId:''}} artifact={{view:'list',artifactId:'',kind:'',page:1}} manuscriptView="research-candidates" manuscriptId="" revision={0} onAnalysis={vi.fn()} onArtifact={vi.fn()} onManuscriptView={vi.fn()} onCandidate={onCandidate} onPublished={vi.fn()} schoolNavigation={{view:'list',templateId:''}} onSchoolNavigate={vi.fn()}/>);
 const summary=screen.getByText('高级历史查找');expect((summary.closest('details') as HTMLDetailsElement).open).toBe(false);expect(screen.getByLabelText('候选记录号').closest('details')).toBe(summary.closest('details'));fireEvent.click(summary);fireEvent.change(screen.getByLabelText('候选记录号'),{target:{value:'record-one'}});fireEvent.click(screen.getByRole('button',{name:'打开固定候选'}));expect(onCandidate).toHaveBeenCalledWith('record-one')
})
