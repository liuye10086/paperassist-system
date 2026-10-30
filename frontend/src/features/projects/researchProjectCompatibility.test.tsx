import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import ProjectWorkspace from './ProjectWorkspace'
import {apiFetch} from '../../shared/api/client'
import ProjectManuscripts from '../manuscripts/ProjectManuscripts'
import ReviewsWorkspace from '../reviews/ReviewsWorkspace'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),onApiSessionChanged:()=>()=>{}}))
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
const project={id:'p1',name:'Research',research_topic:'Topic',project_type:'research',file_count:0,created_at:'2026-10-29T00:00:00Z',updated_at:'2026-10-29T00:00:00Z'}
afterEach(()=>{cleanup();vi.clearAllMocks();window.history.replaceState(null,'','/')})
it('owner-loads a research deep link without mounting legacy writing or reviews',async()=>{window.history.replaceState(null,'','/#project=p1&section=manuscripts');vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('?')?{items:[project],total:1,page:1,page_size:5}:project));render(<ProjectWorkspace/>);await screen.findByText('已登记，当前流程未开放');expect(ProjectManuscripts).not.toHaveBeenCalled();expect(ReviewsWorkspace).not.toHaveBeenCalled();expect(vi.mocked(apiFetch).mock.calls.some(([url])=>url==='/api/v1/projects/p1')).toBe(true)})
it('creates a research project with service selection and idempotency key',async()=>{vi.mocked(apiFetch).mockImplementation(async(_url,init)=>init?.method==='POST'?Response.json(project):Response.json({items:[],total:0,page:1,page_size:5}));render(<ProjectWorkspace/>);fireEvent.click(screen.getByLabelText('开始一项新研究'));fireEvent.change(screen.getByLabelText('项目名称'),{target:{value:'Research'}});fireEvent.change(screen.getByLabelText('研究主题'),{target:{value:'Topic'}});fireEvent.click(screen.getByLabelText('SCI 稿件'));fireEvent.click(screen.getByText('创建项目'));await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(([,init])=>init?.method==='POST')).toBe(true));const call=vi.mocked(apiFetch).mock.calls.find(([,init])=>init?.method==='POST')!;expect(JSON.parse(String(call[1]!.body))).toEqual({name:'Research',research_topic:'Topic',project_type:'research',delivery_kinds:['analysis','sci_draft']});expect(new Headers(call[1]?.headers).get('Idempotency-Key')).toBeTruthy()})
it('recovers unknown project creation by its original request key before any repeat POST',async()=>{let posts=0;vi.mocked(apiFetch).mockImplementation(async(url,init)=>{if(init?.method==='POST'){posts++;throw new TypeError('lost')}if(String(url).includes('/project-create-requests/'))return Response.json(project);if(String(url)==='/api/v1/projects/p1')return Response.json(project);return Response.json({items:[],total:0,page:1,page_size:5})});render(<ProjectWorkspace/>);fireEvent.click(screen.getByLabelText('开始一项新研究'));fireEvent.change(screen.getByLabelText('项目名称'),{target:{value:'Research'}});fireEvent.change(screen.getByLabelText('研究主题'),{target:{value:'Topic'}});fireEvent.click(screen.getByText('创建项目'));fireEvent.click(await screen.findByText('核对创建结果'));await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());expect(posts).toBe(1);const post=vi.mocked(apiFetch).mock.calls.find(([,init])=>init?.method==='POST')!;const key=new Headers(post[1]?.headers).get('Idempotency-Key');expect(vi.mocked(apiFetch).mock.calls.some(([url])=>String(url).endsWith('/project-create-requests/'+key))).toBe(true)})
