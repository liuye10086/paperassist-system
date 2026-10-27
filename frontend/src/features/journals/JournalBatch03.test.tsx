import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import JournalGuideForm from './JournalGuideForm'
import JournalWorkspace from './JournalWorkspace'
import JournalAdaptationPanel from './JournalAdaptationPanel'
import {isRequirement,type GuideRequest} from './formatContracts'
import {isTask,isWorkspace,sameInputVersion,taskDisplayName,taskPhaseName,type InputVersion} from '../tasks/taskTypes'
import {taskFixture} from '../tasks/taskFixtures'
import ManuscriptPreview from '../manuscripts/ManuscriptPreview'
import {snapshotFixture} from '../manuscripts/manuscriptFixtures'
import {validSnapshot,type Snapshot} from '../manuscripts/manuscriptTypes'
import {clearApiSession} from '../../shared/api/client'

const ids=['title','abstract','introduction','results','discussion','materials_and_methods','references'] as const
const names=Object.fromEntries(ids.map(id=>[id,`Journal ${id}`])) as Record<typeof ids[number],string>
const sha='a'.repeat(64)
const rule={id:'r1',key:'heading_font_size_pt',value:12.5,status:'known',quote:'Heading font size: 12.5 pt',location:'line:1',article_type:null,count_method:null,origin:'journal',note:''}
const input={kind:'journal_adaptation',adaptation_id:'a1',target_id:'target1',check_id:'c1',manuscript_version_id:'v1',requirements_version:sha,workflow_version:'journal_adaptation_v1'} as const
const task={...taskFixture,task_type:'journal_adaptation',phase:'verify',status:'queued',display_status:'queued',reason_code:null,error_code:null,input_version:input}
const profile={id:'p-old',project_id:'p1',name:'synthetic Journal',source_type:'synthetic',source_text:'original',source_url:'',official_url:'',source_status:'available',verified_on:'2026-10-23',conditions:'offline',permission:'fixture',synthetic:true,verification_level:'synthetic_material_only',created_at:'2026-10-23T00:00:00Z',fields:{}}
const guide={...profile,id:'g1',profile_id:profile.id,source_version:'v1',acquired_on:'2026-10-23',article_types:['research'],requirements_version:sha,requirements:[],extracted_requirements:[],permission_status:'allowed',extract:true}
const target={id:'target1',project_id:'p1',recommendation_id:'rec1',profile_id:profile.id,guide_id:'g1',requirements_version:sha,article_type:'research',additional_guide_ids:[],resolutions:[],candidate:{profile},guide,additional_guides:[],selected_requirements:[],conflicts:[],decisions:[],warnings:[],synthetic:true,confirmed_by:'me',confirmed_at:profile.created_at}
const fixed={id:'m1',revision:1,version_id:'v1'}
const check={id:'c1',created_at:profile.created_at,task:{...task,id:'tc',task_type:'journal_format_check',status:'succeeded',display_status:'succeeded',input_version:{kind:'journal_format_check',check_id:'c1',target_id:'target1',guide_id:'g1',manuscript_version_id:'v1',requirements_version:sha,check_version:1,workflow_version:'journal_format_check_v1'}},input_snapshot:{id:'c1',project_id:'p1',kind:'journal_format_check',workflow_version:'journal_format_check_v1',target,manuscript:fixed,check_version:1,public_check_version:2,real_model_calls:false,real_network_calls:false},result:null}
const preview={target_id:'target1',check_id:'c1',manuscript:fixed,expected_current_revision:2,preview_sha256:sha,sections:ids.map(section_id=>({section_id,before:{display_name:section_id},after:{display_name:names[section_id]},changed:true})),actions:[{id:'r1',key:'heading_font_size_pt',before:null,after:12.5,evidence:[rule],reason:'明确原文'}],unexecuted:[{key:'dpi',reason:'许可未知',evidence:[]}],synthetic:true,can_adopt:true,display_version:'journal_display_v1'}
const adaptation={id:'a1',created_at:profile.created_at,task,input_snapshot:{id:'a1',project_id:'p1',kind:'journal_adaptation',workflow_version:'journal_adaptation_v1',target_id:'target1',check_id:'c1',manuscript:fixed,requirements_version:sha,expected_current_revision:2,preview_sha256:sha,preview,selected_action_ids:['r1'],synthetic:true,real_model_calls:false,real_network_calls:false},result:null}
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals()})
it('accepts exact independent adaptation task contracts and rejects extra or changed frozen identities',()=>{
 expect(isTask(task,'p1')).toBe(true)
 expect(isTask({...task,input_version:{...input,guide_id:'g1'}},'p1')).toBe(false)
 expect(isTask({...task,phase:'plan'},'p1')).toBe(false)
 expect(sameInputVersion(input,{...input,check_id:'c2'} as InputVersion)).toBe(false)
 expect(taskPhaseName(task as never)).toBe('期刊指南适配')
 expect(taskDisplayName({...task,status:'running',display_status:'analyzing'} as never)).toBe('指南适配中')
 expect(isWorkspace({task,source:{file_id:null,filename:'Old',analysis_run_id:null,is_current:true},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}},'p1','t1')).toBe(true)
})
it('supports finite decimal unit rules and seven explicit display mappings in ordinary guide controls',()=>{
 expect(isRequirement(rule)).toBe(true)
 expect(isRequirement({...rule,value:37})).toBe(false)
 expect(isRequirement({...rule,key:'section_display_names',value:ids.map(section_id=>({section_id,display_name:names[section_id]}))})).toBe(true)
 render(<JournalGuideForm projectId="p1" profiles={[]} guides={[]} materials={[]} busy={false} onSave={vi.fn()} onUnavailable={vi.fn()}/>)
 fireEvent.click(screen.getByText('登记作者指南新版本'));fireEvent.click(screen.getByRole('button',{name:'添加规则'}))
 fireEvent.change(screen.getByLabelText('规则 1 类型'),{target:{value:'section_display_names'}})
 for(const id of ids)expect(screen.getByLabelText(`规则 1 ${id} 显示名称`)).toBeTruthy()
 expect(screen.getByText(/section_id=display_name/)).toBeTruthy()
})
it('saves seven names, the matching order and all eight scalar format values with original evidence',async()=>{
 const save=vi.fn(async(_value:GuideRequest)=>false)
 render(<JournalGuideForm projectId="p1" profiles={[profile] as never} guides={[guide] as never} materials={[]} busy={false} onSave={save} onUnavailable={vi.fn()}/>);fireEvent.click(screen.getByText('登记作者指南新版本'));fireEvent.change(screen.getByLabelText('基于指南另存版本'),{target:{value:'g1'}})
 const keys=['section_display_names','section_order','heading_font_size_pt','body_font_size_pt','heading_line_spacing','body_line_spacing','heading_space_before_pt','heading_space_after_pt','body_space_before_pt','body_space_after_pt']
 for(const [index,key] of keys.entries()){
  const prefix=`规则 ${index+1}`;fireEvent.click(screen.getByRole('button',{name:'添加规则'}));fireEvent.change(screen.getByLabelText(`${prefix} 类型`),{target:{value:key}});fireEvent.change(screen.getByLabelText(`${prefix} 状态`),{target:{value:'known'}})
  if(key==='section_display_names')for(const id of ids)fireEvent.change(screen.getByLabelText(`${prefix} ${id} 显示名称`),{target:{value:names[id]}})
  else if(key==='section_order')fireEvent.change(screen.getByLabelText(`${prefix} 标题列表（| 或换行分隔）`),{target:{value:ids.map(id=>names[id]).join(' | ')}})
  else fireEvent.change(screen.getByLabelText(`${prefix} 数值（${key.endsWith('line_spacing')?'倍':'pt'}）`),{target:{value:key.endsWith('line_spacing')?'1.5':key.endsWith('font_size_pt')?'12.5':'6'}})
  fireEvent.change(screen.getByLabelText(`${prefix} 原文引文`),{target:{value:key==='section_display_names'?`Display sections: ${ids.map(id=>`${id}=${names[id]}`).join(' | ')}`:key==='section_order'?`Section order: ${ids.map(id=>names[id]).join(' | ')}`:`${key}: ${key.endsWith('line_spacing')?'1.5 multiple':key.endsWith('font_size_pt')?'12.5 pt':'6 pt'}`}});fireEvent.change(screen.getByLabelText(`${prefix} 原文位置`),{target:{value:`line:${index+1}`}})
 }
 fireEvent.click(screen.getByRole('button',{name:'保存作者指南新版本'}));await waitFor(()=>expect(save).toHaveBeenCalledOnce())
 const request=save.mock.calls[0]![0] as unknown as {requirements:{key:string;value:unknown}[]}
 expect(request.requirements).toHaveLength(10);expect(request.requirements[0].value).toEqual(ids.map(section_id=>({section_id,display_name:names[section_id]})));expect(request.requirements[2].value).toBe(12.5);expect(request.requirements[4].value).toBe(1.5)
})
it('projects saved finite display order and headings while keeping semantic ids and paragraphs',()=>{
 const snapshot={...snapshotFixture,sections:ids.map(id=>({id,paragraphs:[]})),journal_display_context:{version:'journal_display_v1',names,order:['title','abstract','materials_and_methods','introduction','results','discussion','references'],styles:{heading_font_size_pt:12.5}},journal_adaptation_provenance:{adaptation_id:'a1',base_version_id:'v1',input_sha256:sha,display_version:'journal_display_v1'}} as Snapshot
 expect(validSnapshot(snapshot,'p1')).toBe(true)
 expect(validSnapshot({...snapshot,journal_display_context:{...snapshot.journal_display_context,order:['title']}},'p1')).toBe(false)
 render(<ManuscriptPreview snapshot={snapshot}/>)
 const headings=screen.getAllByRole('heading',{level:4}).map(h=>h.textContent)
 expect(headings.slice(0,7)).toEqual(snapshot.journal_display_context!.order.map(id=>names[id]))
 expect(screen.getByRole('link',{name:'查看期刊适配依据'}).getAttribute('href')).toContain('adaptation=a1')
})
function setup(noChanges=false){const posts:{url:string;body:Record<string,unknown>}[]=[];let items:unknown[]=[];let events:unknown[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
 if(init?.method==='POST'){const body=JSON.parse(String(init.body));posts.push({url,body})
 if(url.endsWith('/adaptations/preview'))return Response.json(noChanges?{...preview,actions:[],can_adopt:false}:preview)
 if(url.endsWith('/adaptations')){items=[adaptation];return Response.json(adaptation,{status:202})}
 if(url.endsWith('/submission-events')){const event={...body,id:`e${events.length+1}`,project_id:'p1',created_at:profile.created_at,recorded_by:'me',manuscript:body.manuscript??null,export_id:body.export_id??null,corrects_event_id:body.corrects_event_id??null};events=[event,...events];return Response.json(event,{status:201})}
 }
 if(url.endsWith('/config'))return Response.json({workflow_version:'journal_recommendation_v1',metrics_enabled:false,real_model_calls:false,real_network_calls:false,default_limit:3,max_limit:5,configuration:{status:'legacy_unbound',version_id:null,sha256:null}})
 if(url.endsWith('/manuscripts'))return Response.json({items:[{id:'m1',title:'New',versions:[{id:'v1',revision:1,status:'published'},{id:'v2',revision:2,status:'published'}]}]})
 if(url.endsWith('/submission-events'))return Response.json({items:events,current_by_target:events.length?{target1:events[0]}:{}})
 if(url.endsWith('/adaptations'))return Response.json({items})
 return Response.json({items:url.endsWith('/profiles')?[profile]:url.endsWith('/targets')?[target]:url.endsWith('/guides')?[guide]:url.endsWith('/checks')?[check]:[]})
 }));render(<JournalWorkspace projectId="p1" active/>);return posts}
it('previews the selected old input and adopts only selected supported actions without writing progress',async()=>{
 const posts=setup();await waitFor(()=>expect((screen.getByLabelText('适配成功检查') as HTMLSelectElement).disabled).toBe(false))
 fireEvent.change(screen.getByLabelText('适配成功检查'),{target:{value:'c1'}})
 fireEvent.click(screen.getByRole('button',{name:'预览固定稿件适配'}));await screen.findByText('许可未知')
 expect(posts[0].body).toEqual({target_id:'target1',check_id:'c1',manuscript:fixed})
 expect(screen.getByText(/固定父稿 m1.*revision 1.*v1/)).toBeTruthy()
 const view=screen.getByRole('region',{name:'七部分差异预览'});expect(within(view).getAllByRole('article')).toHaveLength(7)
 fireEvent.click(screen.getByLabelText(/采用动作 r1/));expect((screen.getByRole('button',{name:'采用所选差异并创建公共任务'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByLabelText(/采用动作 r1/));fireEvent.click(screen.getByRole('button',{name:'采用所选差异并创建公共任务'}));await waitFor(()=>expect(posts).toHaveLength(2))
 expect(posts[1].body).toEqual({target_id:'target1',check_id:'c1',manuscript:fixed,preview_sha256:sha,expected_current_revision:2,selected_action_ids:['r1']})
 expect(posts.every(p=>!p.url.includes('submission-events'))).toBe(true)
 clearApiSession();await waitFor(()=>expect(screen.queryByRole('heading',{name:'指南适配与新版本'})).toBeNull())
})
it('blocks empty adaptations and records corrections as independent appended user events',async()=>{
 const posts=setup(true);await waitFor(()=>expect((screen.getByLabelText('适配成功检查') as HTMLSelectElement).disabled).toBe(false));fireEvent.change(screen.getByLabelText('适配成功检查'),{target:{value:'c1'}});fireEvent.click(screen.getByRole('button',{name:'预览固定稿件适配'}));await screen.findByText('没有可执行差异；不生成空新版本。')
 expect((screen.getByRole('button',{name:'采用所选差异并创建公共任务'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('投稿记录目标'),{target:{value:'target1'}});fireEvent.change(screen.getByLabelText('实际投稿状态'),{target:{value:'submitted'}});fireEvent.change(screen.getByLabelText('投稿记录备注'),{target:{value:'本人实际投稿'}});fireEvent.click(screen.getByRole('button',{name:'保存实际投稿事件'}));await waitFor(()=>expect(posts).toHaveLength(2))
 expect(posts[1].body).toMatchObject({target_id:'target1',status:'submitted',note:'本人实际投稿'})
 fireEvent.change(screen.getByLabelText('纠正已有事件'),{target:{value:'e1'}});fireEvent.change(screen.getByLabelText('实际投稿状态'),{target:{value:'not_recorded'}});fireEvent.click(screen.getByRole('button',{name:'保存实际投稿事件'}));await waitFor(()=>expect(posts).toHaveLength(3));expect(posts[2].body).toMatchObject({corrects_event_id:'e1',status:'not_recorded'})
})
it('requires a check for the selected manuscript and clears private journal state after 403',async()=>{
 setup();await waitFor(()=>expect((screen.getByLabelText('适配成功检查') as HTMLSelectElement).disabled).toBe(false));fireEvent.change(screen.getByLabelText('适配成功检查'),{target:{value:'c1'}});fireEvent.change(screen.getByLabelText('适配稿件版本'),{target:{value:'m1:2'}})
 expect(screen.getByRole('alert').textContent).toContain('检查来自别稿');expect((screen.getByRole('button',{name:'预览固定稿件适配'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('适配稿件版本'),{target:{value:'m1:1'}})
 const original=vi.mocked(fetch).getMockImplementation()!;vi.mocked(fetch).mockImplementation(async(...args)=>args[1]?.method==='POST'?Response.json({detail:{code:'project_forbidden'}},{status:403}):original(...args))
 fireEvent.click(screen.getByRole('button',{name:'预览固定稿件适配'}));await screen.findByText('会话或项目访问已变化，请重新打开项目。');expect(screen.queryByLabelText('投稿记录目标')).toBeNull();expect(screen.queryByText('synthetic Journal')).toBeNull()
})
it('shows failed public validation and retries only the frozen adaptation, keeping the original manuscript',async()=>{
 const posts=setup();const original=vi.mocked(fetch).getMockImplementation()!
 const failed={...adaptation,task:{...task,status:'failed',display_status:'failed',error_code:'manuscript_review_blocked'},validation:{public_issues:[{id:'numeric-error',message:'固定数值绑定错误',severity:'error'}],public_check_version:3,candidate_sha256:sha,can_publish:false}}
 vi.mocked(fetch).mockImplementation(async(...args)=>{const url=String(args[0]);if(url.endsWith('/adaptations')&&!args[1]?.method)return Response.json({items:[failed]});if(url.endsWith('/adaptations/a1/retry')){posts.push({url,body:JSON.parse(String(args[1]?.body))});return Response.json({...failed,task:{...task,status:'queued',display_status:'queued'}})}return original(...args)})
 fireEvent.click(screen.getByRole('button',{name:'刷新期刊资料'}));await screen.findByText(/固定数值绑定错误/);expect(screen.getByText('公共检查阻止发布；旧稿保留，不存在可导出的新稿。')).toBeTruthy();expect(screen.queryByLabelText('固定公共新稿与导出')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'重试固定适配'}));await waitFor(()=>expect(posts.some(p=>p.url.endsWith('/adaptations/a1/retry'))).toBe(true));expect(posts.at(-1)?.body).toEqual({});expect(posts.some(p=>p.url.endsWith('/submission-events'))).toBe(false)
})
it('reports actual seven-part changes from adopted actions instead of showing all proposed changes as executed',async()=>{
 setup();const original=vi.mocked(fetch).getMockImplementation()!
 const saved={...adaptation,task:{...task,status:'succeeded',display_status:'succeeded'},result:{actual_changes:preview.actions,unexecuted:preview.unexecuted,public_issues:[],synthetic:true,display_version:'journal_display_v1',output:{manuscript_id:'m1',version_id:'v3',revision:3,parent_version_id:'v1',task_id:'new-task'}}}
 vi.mocked(fetch).mockImplementation(async(...args)=>String(args[0]).endsWith('/adaptations')&&!args[1]?.method?Response.json({items:[saved]}):original(...args))
 fireEvent.click(screen.getByRole('button',{name:'刷新期刊资料'}));const region=await screen.findByRole('region',{name:'七部分实际变更'})
 expect(within(region).getAllByRole('article')).toHaveLength(7);expect(region.textContent).not.toContain('Journal title');expect(region.textContent).toContain('12.5')
})
it('polls a pending adaptation only while the page is active and visible, without inferring submission events',async()=>{
 vi.useFakeTimers();const posts=setup();await act(async()=>{})
 const original=vi.mocked(fetch).getMockImplementation()!;let pending=true,reads=0
 vi.mocked(fetch).mockImplementation(async(...args)=>{if(String(args[0]).endsWith('/adaptations')&&!args[1]?.method){reads++;return Response.json({items:pending?[adaptation]:[]})}return original(...args)})
 fireEvent.click(screen.getByRole('button',{name:'刷新期刊资料'}));await act(async()=>{});const initial=reads
 await act(async()=>vi.advanceTimersByTimeAsync(3000));expect(reads).toBe(initial+1)
 Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});act(()=>document.dispatchEvent(new Event('visibilitychange')));const hidden=reads;await act(async()=>vi.advanceTimersByTimeAsync(6000));expect(reads).toBe(hidden)
 pending=false;Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});act(()=>document.dispatchEvent(new Event('visibilitychange')));await act(async()=>{});const terminal=reads;await act(async()=>vi.advanceTimersByTimeAsync(6000));expect(reads).toBe(terminal);expect(posts).toHaveLength(0)
 vi.useRealTimers()
})

it('reports stable adaptation history selection and restores an external fixed adaptation without losing the panel',()=>{
 const select=vi.fn();const common={projectId:'p1',active:true,checks:[],targets:[],manuscripts:[],items:[adaptation,{...adaptation,id:'a2'}] as never[],busy:false,onPreview:vi.fn(),onAdopt:vi.fn(),onRetry:vi.fn(),onUnavailable:vi.fn(),onSelectAdaptation:select}
 const view=render(<JournalAdaptationPanel {...common} initialAdaptation="a1"/>)
 fireEvent.click(screen.getByRole('button',{name:/a2.*父稿/}))
 expect(select).toHaveBeenCalledWith('a2')
 expect(screen.getByRole('heading',{name:'实际适配结果 a2'})).toBeTruthy()
 view.rerender(<JournalAdaptationPanel {...common} initialAdaptation="a2"/>)
 view.rerender(<JournalAdaptationPanel {...common} initialAdaptation="a1"/>)
 expect(screen.getByRole('heading',{name:'实际适配结果 a1'})).toBeTruthy()
})

it('retains each visited fixed output while selecting another adaptation history record',()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({})))
 const result={actual_changes:preview.actions,unexecuted:[],public_issues:[],synthetic:true,display_version:'journal_display_v1',output:{manuscript_id:'m1',version_id:'v3',revision:3,parent_version_id:'v1',task_id:'new-task'}}
 const saved={...adaptation,task:{...task,status:'succeeded',display_status:'succeeded'},result}
 render(<JournalAdaptationPanel projectId="p1" active checks={[]} targets={[]} manuscripts={[]} items={[saved,{...saved,id:'a2'}] as never[]} busy={false} initialAdaptation="a1" onPreview={vi.fn()} onAdopt={vi.fn()} onRetry={vi.fn()} onUnavailable={vi.fn()}/>)
 const first=screen.getByRole('region',{name:'固定公共新稿与导出'})
 fireEvent.click(screen.getByRole('button',{name:/a2.*父稿/}))
 expect(document.body.contains(first)).toBe(true)
 expect(screen.getByRole('region',{name:'固定公共新稿与导出'})).not.toBe(first)
 fireEvent.click(screen.getByRole('button',{name:/a1.*父稿/}))
 expect(screen.getByRole('region',{name:'固定公共新稿与导出'})).toBe(first)
})
