import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import type {ReactNode} from 'react'
import ProjectWorkspace from './ProjectWorkspace'
import {setApiSession,clearApiSession} from '../../shared/api/client'
vi.mock('./ProjectResources',()=>({default:()=>null}))
vi.mock('./ProjectSummary',()=>({default:()=>null}))
vi.mock('./ProjectDetails',()=>({default:({renderHeader}:{renderHeader?:(v:ReactNode)=>ReactNode})=>renderHeader?.(null)??null}))
vi.mock('../research-intake/ResearchIntake',()=>({default:()=>null}))
vi.mock('../research-results/ResearchFindings',()=>({default:()=>null}))
vi.mock('../research-results/ResearchFigureComposer',()=>({default:()=>null}))
vi.mock('../research-results/ResearchReport',()=>({default:()=>null}))
vi.mock('../research-results/ResearchWritingHandoff',()=>({default:()=>null}))
vi.mock('../research-results/ResearchPublished',()=>({default:()=>null}))
vi.mock('../manuscripts/ProjectManuscripts',()=>({default:()=>null}))
vi.mock('../reviews/ReviewsWorkspace',()=>({default:()=>null}))
vi.mock('../journals/JournalWorkspace',()=>({default:()=>null}))
vi.mock('../school-templates/SchoolTemplates',()=>({default:()=>null}))
vi.mock('../literature/ProjectLiterature',()=>({default:()=>null}))
vi.mock('../model-usage/ProjectModelUsage',()=>({default:()=>null}))
vi.mock('../tasks/ProjectTasks',()=>({default:()=>null}))
beforeEach(()=>setApiSession('csrf','owner'))
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession();window.history.replaceState(null,'','/')})
it('switches explicit SCI to thesis writing with the new delivery in the route',async()=>{
 const project={id:'p1',name:'客户流程',research_topic:'比较两组样本',project_type:'research',file_count:1,created_at:'2026-10-26T00:00:00Z',updated_at:'2026-10-26T00:00:00Z'}
 const intake={current_requirement:{content:{services:['analysis','sci_draft','thesis_draft']}},deliveries:[{id:'sci',kind:'sci_draft',active:true},{id:'thesis',kind:'thesis_draft',active:true}]}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/research-intake')?intake:url.includes('/summary?')?{tasks:{total:1},artifacts:{total:1},future:{writing:{current_manuscript:null}}}:url.endsWith('/projects/p1')?project:{items:[project],total:1,page:1,page_size:5})))
 window.history.replaceState(null,'','/#project=p1&section=artifacts');render(<ProjectWorkspace/>);fireEvent.click(await screen.findByRole('button',{name:'写作与交付'}));fireEvent.click(await screen.findByRole('button',{name:'继续写 SCI 论文'}))
 await waitFor(()=>expect((screen.getByLabelText('已启用的稿件交付') as HTMLSelectElement).value).toBe('sci'));expect(window.location.hash).toContain('writingDelivery=sci')
 fireEvent.click(screen.getByRole('button',{name:'第 5 步：查看结果'}));fireEvent.click(await screen.findByRole('button',{name:'写作与交付'}));fireEvent.click(await screen.findByRole('button',{name:'继续写毕业论文'}))
 await waitFor(()=>expect((screen.getByLabelText('已启用的稿件交付') as HTMLSelectElement).value).toBe('thesis'));expect(window.location.hash).toContain('writingDelivery=thesis')
})
