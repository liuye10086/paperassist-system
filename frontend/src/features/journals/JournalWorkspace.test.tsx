import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import JournalWorkspace from './JournalWorkspace'
import {taskFixture} from '../tasks/taskFixtures'
import {clearApiSession} from '../../shared/api/client'
import {captureProjectAccess,watchProjectAccess} from '../../shared/api/projectAccess'
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals()})
const profile={id:'profile-old',project_id:'p1',name:'synthetic Journal',source_type:'synthetic',source_text:'cancer research',source_url:'https://journal.test/guide',official_url:'https://journal.test',source_status:'available',verified_on:'2026-10-23',conditions:'offline only',permission:'test',synthetic:true,verification_level:'synthetic_material_only',created_at:'2026-10-23T00:00:00Z',fields:{topics:{value:['cancer'],status:'verified',quote:'cancer',location:'paragraph 1',verified_on:'2026-10-23',conditions:'offline only'},fee:{value:null,status:'unknown',quote:'',location:''}}}
function recommendation(id='j1',status='succeeded',budget=100){return {id,created_at:'2026-10-23T00:00:00Z',input_snapshot:{id,kind:'journal_recommendation',recommendation_id:id,project_id:'p1',workflow_version:'journal_recommendation_v1',research:{limit:3,title:'Cancer',topics:['cancer'],article_type:'research',budget:{amount:budget,currency:'USD'},hard_filters:['article_types','fee','unit_requirements']},materials:[],manuscript:null,profiles:[profile],real_model_calls:false,real_network_calls:false},task:{...taskFixture,id:`task-${id}`,task_type:'journal_recommendation',phase:'plan',status,display_status:status,error_code:status==='failed'?'task_failed':null,reason_code:null,input_version:{kind:'journal_recommendation',recommendation_id:id,workflow_version:'journal_recommendation_v1'}},result:status==='succeeded'?{candidates:[{profile,reasons:[{field:'topics',state:'match',message:'明确主题标签匹配',evidence:profile.fields.topics}],matched_tag_count:1,preference_match_count:0}],excluded:[],pending_verification:[],candidate_total:1,limitations:['离线规则建议'],real_model_calls:false,real_network_calls:false}:null}}
function setup(initial:ReturnType<typeof recommendation>[]=[],initialProfiles:typeof profile[]=[profile],failLoad=false,formal=false){
 const requests:{url:string;body:Record<string,unknown>;key:string|null}[]=[];let history=[...initial];let profiles=[...initialProfiles]
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){
   const body=JSON.parse(String(init.body));requests.push({url,body,key:new Headers(init.headers).get('Idempotency-Key')})
   if(url.endsWith('/profiles')){const saved={...profile,...body,id:'profile-new',synthetic:body.source_type==='synthetic'};profiles=[saved,...profiles];return Response.json(saved,{status:201})}
   if(url.endsWith('/retry')){const value=recommendation('j1','queued');history=[value];return Response.json(value)}
   const value=recommendation(`j${history.length+1}`);value.input_snapshot.research={...value.input_snapshot.research,...body} as typeof value.input_snapshot.research;history=[value,...history];return Response.json(value,{status:202})
  }
  if(url.endsWith('/config'))return failLoad?Response.json({}, {status:503}):Response.json({workflow_version:'journal_recommendation_v1',real_model_calls:false,real_network_calls:false,metrics_enabled:false,default_limit:3,max_limit:5,configuration:{status:'legacy_unbound',version_id:null,sha256:null}})
  if(url.endsWith('/submission-events'))return Response.json({items:[],current_by_target:{}})
  if(['/adaptations','/guides','/targets','/checks'].some(path=>url.endsWith(path)))return Response.json({items:[]})
  if(url.endsWith('/profiles'))return Response.json({items:profiles})
  if(url.endsWith('/recommendations'))return Response.json({items:history})
  if(/\/recommendations\/j\d+$/.test(url))return Response.json(history.find(x=>x.id===url.split('/').at(-1)))
  if(url.endsWith('/manuscripts/candidates'))return Response.json({items:[],citation_drafts:[],methods_fields:[]})
  if(url.endsWith('/manuscripts'))return Response.json({items:[{id:'m1',title:'Latest manuscript',current_revision:2,versions:[{id:'v1',revision:1,status:'published',snapshot:{title:'Old manuscript'}},{id:'v2',revision:2,status:'published',snapshot:{title:'Latest manuscript'}}]}]})
  throw new Error(`Unexpected local request ${url}`)
 });vi.stubGlobal('fetch',fetch);const rendered=render(<JournalWorkspace projectId="p1" active onOpenTask={vi.fn()} {...(formal?{view:'overview' as const}:{})}/>);return {requests,fetch,...rendered}
}
async function fillResearch(){await screen.findByRole('option',{name:/Old manuscript.*版本 1/});fireEvent.change(screen.getByLabelText('研究标题'),{target:{value:'Cancer'}});fireEvent.change(screen.getByLabelText('主题标签（逗号或换行分隔）'),{target:{value:'cancer'}});fireEvent.change(screen.getByRole('textbox',{name:'文章类型'}),{target:{value:'research'}})}
it('creates before a draft, freezes explicit old revision and creates a new batch for changed preferences',async()=>{
 const {requests}=setup();await fillResearch();fireEvent.click(screen.getByRole('button',{name:'创建建议批次'}));await waitFor(()=>expect(requests.length).toBe(1));expect(requests[0].body.manuscript).toBeNull();expect(requests[0].body.hard_filters).toEqual(['article_types','fee','unit_requirements']);expect(requests[0].body).not.toHaveProperty('limit')
 fireEvent.change(screen.getByLabelText('固定稿件版本'),{target:{value:'m1:1'}});fireEvent.change(screen.getByLabelText('预算金额'),{target:{value:'200'}});fireEvent.click(screen.getByRole('button',{name:'创建建议批次'}));await waitFor(()=>expect(requests.length).toBe(2));expect(requests[1].body.manuscript).toEqual({id:'m1',revision:1});expect(requests[1].body.budget).toEqual({amount:200,currency:'USD'});expect(requests[0].key).not.toBe(requests[1].key)
})
it('shows frozen evidence, synthetic labels, unknown fields and history despite an unavailable successor',async()=>{
 const old=recommendation();old.input_snapshot.materials=[{kind:'original',id:'f1',file_id:'f1',label:'Fixed research source',content:{items:[]}}] as never[]
 setup([recommendation('j2','succeeded',200),old],[{...profile,id:'profile-new',source_status:'unavailable',name:'synthetic Updated'}]);await screen.findByRole('button',{name:/j1/});fireEvent.click(screen.getByRole('button',{name:/j1/}));await screen.findByText('明确主题标签匹配');expect(screen.getAllByText('合成材料，仅验证离线工程').length).toBeGreaterThan(1);expect(screen.getAllByText('未知').length).toBeGreaterThan(0);expect(screen.getAllByText('paragraph 1').length).toBeGreaterThan(0);expect(screen.getByText(/Fixed research source/)).toBeTruthy()
 const detail=screen.getByRole('region',{name:'当前建议批次'});expect(within(detail).getByText(/100 USD/)).toBeTruthy();expect(within(detail).getAllByText('synthetic Journal').length).toBeGreaterThan(0);expect(within(detail).queryByText('synthetic Updated')).toBeNull();expect(screen.getByText(/SCI\/SCIE、JIF\/JCR、分区未接入/)).toBeTruthy()
})
it('finishes initial loading on error and does not label real local material as synthetic',async()=>{
 setup([],[{...profile,name:'Local journal',source_type:'user_provided',synthetic:false,verification_level:'user_material_only'}],true)
 await screen.findByRole('alert');expect(screen.queryByText('正在读取期刊资料……')).toBeNull();expect(screen.queryByText('合成材料，仅验证离线工程',{selector:'p'})).toBeNull();expect(screen.getByRole('button',{name:'刷新期刊资料'})).toBeTruthy()
})
it('shows a recoverable error after a local request timeout instead of an endless loading state',async()=>{
 vi.useFakeTimers();vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(()=>{})));render(<JournalWorkspace projectId="p1" active/>);await act(async()=>{await vi.advanceTimersByTimeAsync(15001)});expect(screen.queryByText('正在读取期刊资料……')).toBeNull();expect(screen.getAllByRole('alert').length).toBeGreaterThan(0)
})
it('retries a failed task using the same frozen batch and clears content when session changes',async()=>{
 const {requests}=setup([recommendation('j1','failed')]);await screen.findByRole('button',{name:'重试本批任务'});fireEvent.click(screen.getByRole('button',{name:'重试本批任务'}));await waitFor(()=>expect(requests[0]?.url).toMatch(/recommendations\/j1\/retry$/));expect(requests[0].body).toEqual({});act(()=>clearApiSession());expect(screen.queryByText('synthetic Journal')).toBeNull();expect(screen.getByText('会话或项目访问已变化，请重新打开项目。')).toBeTruthy()
})
it('registers a synthetic source through ordinary fields, preserves unknowns and forks an old source',async()=>{
 const {requests}=setup();await screen.findByRole('option',{name:/Old manuscript.*版本 1/});fireEvent.click(screen.getByText('登记期刊资料与版本'));fireEvent.change(screen.getByLabelText('以已有资料另存新版本'),{target:{value:'profile-old'}})
 expect((screen.getByLabelText('来源类型') as HTMLSelectElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('来源状态'),{target:{value:'unavailable'}});fireEvent.click(screen.getByRole('button',{name:'保存期刊资料新版本'}));await waitFor(()=>expect(requests.length).toBe(1));expect(requests[0].body.previous_version_id).toBe('profile-old');expect(requests[0].body.source_type).toBe('synthetic');expect((requests[0].body.fields as typeof profile.fields).fee.value).toBeNull();expect(requests[0].body.source_status).toBe('unavailable')
})
it('keeps a sibling request in its parent project scope when the journal panel mounts inactive',()=>{
 const parentUnavailable=vi.fn();const dispose=watchProjectAccess('scope-project',parentUnavailable);const sibling=captureProjectAccess('/api/v1/projects/scope-project/files')
 try{render(<JournalWorkspace projectId="scope-project" active={false}/>);expect(()=>sibling.check()).not.toThrow()}finally{dispose()}
})
it('routes project unavailability to the parent owner after an inactive journal panel mounts',()=>{
 const parentUnavailable=vi.fn();const dispose=watchProjectAccess('scope-project',parentUnavailable)
 try{render(<JournalWorkspace projectId="scope-project" active={false}/>);act(()=>captureProjectAccess('/api/v1/projects/scope-project/summary').unavailable());expect(parentUnavailable).toHaveBeenCalledTimes(1)}finally{dispose()}
})

it('separates the formal tasks and preserves a research draft across inactive and task views',async()=>{
 const {rerender,fetch}=setup([], [profile],false,true)
 await screen.findByRole('button',{name:'研究条件'})
 expect(screen.queryByRole('textbox',{name:'研究标题'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'研究条件'}))
 await screen.findByRole('textbox',{name:'研究标题'})
 fireEvent.change(screen.getByLabelText('研究标题'),{target:{value:'Unsaved research'}})
 rerender(<JournalWorkspace projectId="p1" active={false} view="research"/>)
 expect(screen.queryByRole('textbox',{name:'研究标题'})).toBeNull()
 const reads=fetch.mock.calls.length
 rerender(<JournalWorkspace projectId="p1" active view="research"/>)
 expect((screen.getByLabelText('研究标题') as HTMLInputElement).value).toBe('Unsaved research')
 fireEvent.click(screen.getByRole('button',{name:'来源资料'}))
 expect(screen.queryByRole('textbox',{name:'研究标题'})).toBeNull()
 expect(screen.queryByRole('textbox',{name:'期刊及来源名称'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'登记来源资料'}))
 expect(screen.getByRole('textbox',{name:'期刊及来源名称'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'研究条件'}))
 expect((screen.getByLabelText('研究标题') as HTMLInputElement).value).toBe('Unsaved research')
 expect(fetch.mock.calls.length).toBeGreaterThanOrEqual(reads)
})
it('keeps formal guide authoring, target confirmation and checks in separate tasks',async()=>{
 setup([], [profile],false,true)
 fireEvent.click(await screen.findByRole('button',{name:'指南与检查'}))
 expect(screen.queryByRole('button',{name:'确认固定目标'})).toBeNull()
 expect(screen.queryByRole('textbox',{name:'指南名称'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'登记指南资料'}))
 expect(screen.getByRole('textbox',{name:'指南名称'})).toBeTruthy()
 fireEvent.change(screen.getByLabelText('指南名称'),{target:{value:'Unsaved guide'}})
 fireEvent.click(screen.getByRole('button',{name:'确认目标'}))
 expect(screen.getByRole('button',{name:'确认固定目标'})).toBeTruthy()
 expect(screen.queryByRole('button',{name:'保存作者指南新版本'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'检查历史'}))
 expect(screen.queryByRole('button',{name:'确认固定目标'})).toBeNull()
 expect(screen.getByRole('region',{name:'格式检查历史'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'指南资料'}))
 expect((screen.getByLabelText('指南名称') as HTMLInputElement).value).toBe('Unsaved guide')
})
it('registers research draft protection while allowing an explicit confirmed departure',async()=>{
 setup([], [profile],false,true)
 const guards=new Set<()=>boolean>();const register=(guard:()=>boolean)=>{guards.add(guard);return()=>{guards.delete(guard)}}
 cleanup();render(<JournalWorkspace projectId="p1" active view="research" registerLeaveGuard={register}/>)
 await screen.findByRole('option',{name:/Old manuscript.*版本 1/})
 fireEvent.change(screen.getByLabelText('研究标题'),{target:{value:'Pending draft'}})
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
 expect([...guards].every(g=>g())).toBe(false)
 confirm.mockReturnValue(true)
 expect([...guards].every(g=>g())).toBe(true)
 confirm.mockRestore()
})

it('treats unknown recommendation results as confirmable dirty state and reuses its original key',async()=>{
 const {fetch,rerender}=setup([], [profile],false,true)
 const guards=new Set<()=>boolean>();const register=(guard:()=>boolean)=>{guards.add(guard);return()=>{guards.delete(guard)}}
 rerender(<JournalWorkspace projectId="p1" active view="research" registerLeaveGuard={register}/>)
 await fillResearch()
 const original=fetch.getMockImplementation()!;const keys:string[]=[]
 fetch.mockImplementation(async(url,init)=>{if(init?.method==='POST'){keys.push(new Headers(init.headers).get('Idempotency-Key')!);throw new TypeError('offline')}return original(url,init)})
 fireEvent.click(screen.getByRole('button',{name:'创建建议批次'}))
 await waitFor(()=>expect(screen.getByRole('button',{name:'创建建议批次'}).closest('fieldset')?.disabled).toBe(false))
 const alert=vi.spyOn(window,'alert').mockImplementation(()=>{});const confirm=vi.spyOn(window,'confirm').mockReturnValue(true)
 expect([...guards].every(g=>g())).toBe(true);expect(alert).not.toHaveBeenCalled();expect(confirm).toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'创建建议批次'}));await waitFor(()=>expect(keys).toHaveLength(2));expect(keys[0]).toBe(keys[1])
 alert.mockRestore();confirm.mockRestore()
})
it('keeps the selected historical batch when a late creation finishes in another task view',async()=>{
 const {fetch}=setup([recommendation('j1')],[profile],false,true)
 fireEvent.click(await screen.findByRole('button',{name:'建议批次'}));fireEvent.click(await screen.findByRole('button',{name:/Cancer.*j1/}))
 fireEvent.click(screen.getByRole('button',{name:'研究条件'}));await fillResearch()
 let finish!:(value:Response)=>void;const original=fetch.getMockImplementation()!
 fetch.mockImplementation(async(url,init)=>init?.method==='POST'?new Promise<Response>(resolve=>{finish=resolve}):original(url,init))
 fireEvent.click(screen.getByRole('button',{name:'创建建议批次'}));fireEvent.click(screen.getByRole('button',{name:'来源资料'}))
 await act(async()=>finish(Response.json(recommendation('j2'),{status:202})))
 expect(screen.getByRole('region',{name:'期刊来源列表'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'建议批次'}))
 expect(within(screen.getByRole('region',{name:'当前建议批次'})).getByRole('heading',{level:3}).textContent).toContain('j1')
})
