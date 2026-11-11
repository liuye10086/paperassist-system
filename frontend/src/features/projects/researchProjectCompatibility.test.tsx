import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import ProjectWorkspace from './ProjectWorkspace'
import {apiFetch} from '../../shared/api/client'
import {workflowStateFixture} from '../../test/fixtures/workflowStateFixture'
import ProjectManuscripts from '../manuscripts/ProjectManuscripts'
import ReviewsWorkspace from '../reviews/ReviewsWorkspace'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
vi.mock('../manuscripts/ProjectManuscripts',()=>({default:vi.fn(()=>null)}))
vi.mock('../reviews/ReviewsWorkspace',()=>({default:vi.fn(()=>null)}))
vi.mock('../journals/JournalWorkspace',()=>({default:()=>null}))
vi.mock('../school-templates/SchoolTemplates',()=>({default:()=>null}))
vi.mock('../literature/ProjectLiterature',()=>({default:()=>null}))
vi.mock('../model-usage/ProjectModelUsage',()=>({default:()=>null}))
vi.mock('../tasks/ProjectTasks',()=>({default:()=>null}))
vi.mock('./ProjectSummary',()=>({default:()=>null}))
vi.mock('./ProjectResources',()=>({default:()=>null}))
vi.mock('./ProjectDetails',()=>({default:()=>null}))
vi.mock('../research-intake/ResearchIntake',()=>({default:()=>null}))
const project={id:'p1',name:'Research',research_topic:'Topic',project_type:'research' as const,file_count:0,created_at:'2026-10-29T00:00:00Z',updated_at:'2026-10-29T00:00:00Z'}
const base=`/api/v1/projects/${project.id}`
function readProject(url:string){
 if(url===base)return Response.json(project)
 if(url===`${base}/workflow-state`)return Response.json(workflowStateFixture(project))
 if(url===`${base}/research-intake`)return Response.json({deliveries:[]})
 if(url===`${base}/manuscripts`)return Response.json({items:[]})
 return Response.json({items:[],total:0,page:1,page_size:5})
}
afterEach(()=>{cleanup();vi.clearAllMocks();window.history.replaceState(null,'','/')})
it('owner-loads a research deep link without mounting legacy writing or reviews',async()=>{
 window.history.replaceState(null,'','/#project=p1&section=manuscripts')
 vi.mocked(apiFetch).mockImplementation(async url=>readProject(url))
 render(<ProjectWorkspace/>)
 await screen.findByRole('heading',{name:'正式稿件与历史版本'})
 await screen.findByText('还没有已发布稿件，请先核对并显式发布事实候选。')
 expect(ProjectManuscripts).not.toHaveBeenCalled()
 expect(ReviewsWorkspace).not.toHaveBeenCalled()
 expect(vi.mocked(apiFetch).mock.calls.some(([url])=>url===base)).toBe(true)
})
it('creates a research project with service selection and idempotency key',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>init?.method==='POST'?Response.json(project):readProject(url))
 render(<ProjectWorkspace/>)
 fireEvent.click(screen.getByLabelText('新建研究项目'))
 fireEvent.change(screen.getByLabelText('项目名称'),{target:{value:'Research'}})
 fireEvent.change(screen.getByLabelText('研究主题'),{target:{value:'Topic'}})
 fireEvent.click(screen.getByLabelText('SCI 稿件'))
 fireEvent.click(screen.getByText('创建项目'))
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull())
 const call=vi.mocked(apiFetch).mock.calls.find(([,init])=>init?.method==='POST')!
 expect(JSON.parse(String(call[1]!.body))).toEqual({name:'Research',research_topic:'Topic',project_type:'research',delivery_kinds:['analysis','sci_draft']})
 expect(new Headers(call[1]?.headers).get('Idempotency-Key')).toBeTruthy()
})
it('recovers unknown project creation by its original request key before any repeat POST',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method==='POST')throw new TypeError('lost')
  if(url.startsWith('/api/v1/project-create-requests/'))return Response.json(project)
  return readProject(url)
 })
 render(<ProjectWorkspace/>)
 fireEvent.click(screen.getByLabelText('新建研究项目'))
 fireEvent.change(screen.getByLabelText('项目名称'),{target:{value:'Research'}})
 fireEvent.change(screen.getByLabelText('研究主题'),{target:{value:'Topic'}})
 fireEvent.click(screen.getByText('创建项目'))
 fireEvent.click(await screen.findByText('核对创建结果'))
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull())
 const posts=vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')
 expect(posts).toHaveLength(1)
 const key=new Headers(posts[0][1]?.headers).get('Idempotency-Key')
 expect(key).toBeTruthy()
 expect(vi.mocked(apiFetch).mock.calls.some(([url])=>url===`/api/v1/project-create-requests/${key}`)).toBe(true)
})
