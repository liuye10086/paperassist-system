import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ProjectWorkspace from './ProjectWorkspace'
import OperationsWorkspace from '../operations/OperationsWorkspace'
import {AuthIdentityContext} from '../auth/AuthIdentityContext'
vi.mock('./ProjectDetails',()=>({default:()=>null}))
vi.mock('./ProjectResources',()=>({default:({section,resourceNavigation,onResourceNavigate}:{section:string;resourceNavigation:{view:string;fileId:string};onResourceNavigate:(next:{view:string;fileId:string})=>void})=>section==='files'?<section aria-label="目标材料">{resourceNavigation.view}:{resourceNavigation.fileId}<button onClick={()=>onResourceNavigate({view:'detail',fileId:'f1'})}>打开材料详情</button></section>:null}))
vi.mock('./ProjectSummary',()=>({default:()=>null}))
vi.mock('../model-usage/ProjectModelUsage',()=>({default:()=>null}))
vi.mock('../reviews/ReviewsWorkspace',()=>({default:({active,view,roundId,selectedItemId,onViewChange,onSelectItem}:{active:boolean;view:string;roundId:string;selectedItemId:string;onViewChange:(view:string)=>void;onSelectItem:(id:string)=>void})=>active?<section aria-label="评审视图">{view}:{roundId}:{selectedItemId}<button onClick={()=>{onSelectItem('i1');onViewChange('plan')}}>整理此意见计划</button></section>:null}))
vi.mock('../journals/JournalWorkspace',()=>({default:()=>null}))
vi.mock('../school-templates/SchoolTemplates',()=>({default:()=>null}))
vi.mock('../manuscripts/ProjectManuscripts',()=>({default:()=>null}))
vi.mock('../tasks/ProjectTasks',()=>({default:({active,selectedTaskId,detailView,onDetailViewChange}:{active:boolean;selectedTaskId:string;detailView:string;onDetailViewChange:(view:string)=>void})=>active?<><section aria-label="目标任务">{selectedTaskId}</section><section aria-label="任务视图">{detailView}<button onClick={()=>onDetailViewChange('events')}>查看任务事件视图</button></section></>:null}))
vi.mock('../literature/ProjectLiterature',()=>({default:({active,initialSearchId,literatureNavigation,onLiteratureNavigate}:{active:boolean;initialSearchId:string;literatureNavigation:{view:string;referenceId:string};onLiteratureNavigate:(next:{view:string;referenceId:string})=>void})=>active?<><section aria-label="目标文献">{initialSearchId}</section><section aria-label="文献视图">{literatureNavigation.view}:{literatureNavigation.referenceId}<button onClick={()=>onLiteratureNavigate({view:'citations',referenceId:''})}>打开引用视图</button></section></>:null}))
afterEach(()=>{cleanup();vi.unstubAllGlobals();window.history.replaceState(null,'','/')})
const project={id:'p1',name:'研究',research_topic:'主题',project_type:'sci',file_count:0,created_at:'2026-10-08T00:00:00Z',updated_at:'2026-10-08T00:00:00Z',default_output_language:'zh-CN'}
function ownerFetch(){vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/projects?')?{items:[],total:0,page:1,page_size:20}:project)))}
function follow(hash:string){act(()=>{window.history.replaceState(null,'','/#'+hash);window.dispatchEvent(new HashChangeEvent('hashchange'))})}
it('wires resource and literature view routes through the production workspace',async()=>{
 window.history.replaceState(null,'','/#project=p1&section=files');ownerFetch();render(<ProjectWorkspace/>)
 fireEvent.click(await screen.findByRole('button',{name:'打开材料详情'}))
 expect(window.location.hash).toBe('#project=p1&section=files&view=detail&file=f1')
 expect(screen.getByRole('region',{name:'目标材料'}).textContent).toContain('detail:f1')
 follow('project=p1&section=literature&view=detail&reference=r1&search=s1')
 await waitFor(()=>expect(screen.getByRole('region',{name:'文献视图'}).textContent).toContain('detail:r1'))
 fireEvent.click(screen.getByRole('button',{name:'打开引用视图'}))
 expect(window.location.hash).toBe('#project=p1&section=literature&view=citations&search=s1')
 expect(screen.getByRole('region',{name:'目标文献'}).textContent).toBe('s1')
})
it.each(['工作台','我的项目'])('shows linked task from %s through the real workspace and selection hook',async origin=>{
 ownerFetch();render(<ProjectWorkspace/>);fireEvent.click(screen.getByRole('button',{name:origin}))
 follow('project=p1&section=tasks&task=t1')
 await waitFor(()=>expect(screen.getByRole('region',{name:'目标任务'}).textContent).toBe('t1'))
 expect(screen.getByRole('region',{name:'当前项目工作区'}).hidden).toBe(false)
})
it('reveals a same-project literature destination after returning home',async()=>{
 window.history.replaceState(null,'','/#project=p1');ownerFetch();render(<ProjectWorkspace/>)
 await waitFor(()=>expect(screen.getByRole('button',{name:'研究'})).toBeTruthy())
 fireEvent.click(screen.getByRole('button',{name:'工作台'}))
 follow('project=p1&section=literature&search=s1')
 await waitFor(()=>expect(screen.getByRole('region',{name:'目标文献'}).textContent).toBe('s1'))
 expect(screen.getByRole('region',{name:'当前项目工作区'}).hidden).toBe(false)
})
it('does not leave home for malformed hash navigation',async()=>{
 ownerFetch();render(<ProjectWorkspace/>);follow('project=p1&section=tasks&task=bad/id')
 expect(screen.getByRole('button',{name:'工作台'}).getAttribute('aria-current')).toBe('page')
 expect(screen.queryByRole('region',{name:'当前项目工作区'})).toBeNull()
})

it.each(['工作台','我的项目'])('reopens the unchanged task href from admin after returning to %s',async origin=>{
 const hash='#project=p1&section=tasks&task=t1'
 window.history.replaceState(null,'','/'+hash)
 const ownTask={id:'t1',user_id:'self',user_email:'self@example.test',project_id:'p1',task_type:'boxplot',phase:'compute',status:'failed',revision:3,created_at:'2026-10-23T00:00:00Z',updated_at:'2026-10-23T00:01:00Z',elapsed_ms:null,started_at:null,finished_at:null,current_attempt:1,attempt_count:1,error_code:'task_execution_failed',request_id:null,can_open_workspace:true,allowed_actions:[],workspace_url:'/api/v1/tasks/t1/workspace'}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
  if(url==='/api/v1/auth/me')return Response.json({user:{id:'self',email:'self@example.test',role:'admin'}})
  if(url.startsWith('/api/v1/admin/tasks?'))return Response.json({items:[ownTask],total:1,page:1,page_size:10})
  if(url==='/api/v1/admin/tasks/t1')return Response.json(ownTask)
  if(url.startsWith('/api/v1/admin/users?'))return Response.json({items:[],total:0,page:1,page_size:10})
  return Response.json(url.includes('/projects?')?{items:[],total:0,page:1,page_size:20}:project)
 }))
 render(<AuthIdentityContext.Provider value={{id:'self',email:'self@example.test',role:'admin'}}><OperationsWorkspace><ProjectWorkspace/></OperationsWorkspace></AuthIdentityContext.Provider>)
 await screen.findByRole('region',{name:'目标任务'})
 fireEvent.click(screen.getByRole('button',{name:origin}))
 expect(screen.queryByRole('region',{name:'目标任务'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'管理员'}))
 fireEvent.click(screen.getByRole('button',{name:'系统任务'}))
 fireEvent.click(await screen.findByRole('button',{name:'查看安全详情'}))
 const link=await screen.findByRole('link',{name:'在项目中打开'})
 expect(link.getAttribute('href')).toBe(hash);expect(window.location.hash).toBe(origin==='工作台'?'#workspace=home':'#workspace=projects')
 fireEvent.click(link)
 await waitFor(()=>expect(screen.getByRole('region',{name:'目标任务'}).textContent).toBe('t1'))
 expect(screen.getByRole('region',{name:'当前项目工作区'}).hidden).toBe(false)
})

it.each([
 {label:'ctrl',click:{ctrlKey:true}}, {label:'meta',click:{metaKey:true}},
 {label:'shift',click:{shiftKey:true}}, {label:'alt',click:{altKey:true}},
 {label:'middle',click:{button:1}}, {label:'download',download:'task'},
 {label:'new window',target:'_blank'}, {label:'prevented',prevent:true},
])('does not reveal retained workspace for $label same-hash clicks',async option=>{
 const hash='#project=p1&section=tasks&task=t1'
 window.history.replaceState(null,'','/'+hash);ownerFetch()
 render(<><a href={hash} download={option.download} target={option.target} onClick={option.prevent?event=>event.preventDefault():undefined}>重复任务链接</a><ProjectWorkspace/></>)
 await screen.findByRole('region',{name:'目标任务'})
 fireEvent.click(screen.getByRole('button',{name:'工作台'}))
 fireEvent.click(screen.getByRole('link',{name:'重复任务链接'}),option.click)
 await act(async()=>{})
 expect(screen.queryByRole('region',{name:'目标任务'})).toBeNull()
 expect(screen.getByRole('button',{name:'工作台'}).getAttribute('aria-current')).toBe('page')
})

it('wires layered review and task routes through the production workspace',async()=>{
 window.history.replaceState(null,'','/#project=p1&section=reviews&round=r1');ownerFetch();render(<ProjectWorkspace/>)
 fireEvent.click(await screen.findByRole('button',{name:'整理此意见计划'}))
 expect(window.location.hash).toBe('#project=p1&section=reviews&view=plan&item=i1&round=r1')
 expect(screen.getByRole('region',{name:'评审视图'}).textContent).toContain('plan:r1:i1')
 follow('project=p1&section=tasks&view=actions&task=t1')
 expect(screen.getByRole('region',{name:'任务视图'}).textContent).toContain('actions')
 fireEvent.click(screen.getByRole('button',{name:'查看任务事件视图'}))
 expect(window.location.hash).toBe('#project=p1&section=tasks&view=events&task=t1')
})
