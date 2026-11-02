import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import DeliveryPackagePanel from './DeliveryPackagePanel'
import {clearApiSession} from '../../shared/api/client'
import {parseNavigation,serializeNavigation} from '../projects/projectNavigation'
import {isTask,isWorkspace,sameInputVersion} from '../tasks/taskTypes'
import {taskFixture} from '../tasks/taskFixtures'
import userEvent from '@testing-library/user-event'

const selection={kind:'file',file_id:'f1'}
const member={id:'member1',selection,name:'plot.png',format:'png',size_bytes:25,sha256:'b'.repeat(64),image:{mapping_status:'pending_verification',dpi:null},source_metadata:{source_notices:['region-enriched only','license unknown']},download_url:'/api/v1/projects/p1/deliveries/d1/snapshots/s1/members/member1/download'}
const snapshot={id:'s1',sha256:'a'.repeat(64),revision:1,parent_snapshot_id:null,requirement_version_id:'r1',stage:'first',mode:'complete',required_formats:['docx','pdf'],change_note:'first scope',opinion_round:'not applicable',members:[member],gaps:['required_format:pdf'],quality_items:['字体核对：未知'],completeness:'missing_required',changes:{added:['member1'],removed:[],replaced:[],reason:'first scope'},created_at:'2026-11-02T00:00:00Z'}
const candidates={items:[{selection,label:'plot.png',format:'png',status:'existing_upload'},{selection:{kind:'pdf_export',export_id:'failed'},label:'failed.pdf',format:'pdf',status:'failed'},{selection:{kind:'manuscript_export',manuscript_id:'m1',version_id:'v1',export_id:'e1'},label:'draft.docx',format:'docx',status:'succeeded',review_mode:'identified'},{selection:{kind:'manuscript_export',manuscript_id:'m1',version_id:'v1',export_id:'e2'},label:'blind.docx',format:'docx',status:'succeeded',review_mode:'blind'}],requirements:[{id:'r1',version:1,sha256:'c'.repeat(64)}],opinion_rounds:[{id:'round1',round_number:1,label:'review',events:[{id:'event1',revision:1,kind:'saved',sha256:'d'.repeat(64)}]}]}
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();sessionStorage.clear()})
function mockApi({lost=false,conflict=false,history=true}={}){
 let saved=false
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){
   if(url.endsWith('/preview'))return Response.json({...snapshot,id:undefined,sha256:undefined,stage:'final'})
   if(url.endsWith('/snapshots')){if(conflict)return Response.json({detail:{code:'research_revision_conflict'}},{status:409});saved=true;if(lost)throw Error('lost');return Response.json({...snapshot,id:'s2',revision:2,stage:'final'})}
   if(url.endsWith('/acceptances'))return Response.json({id:'accept1',...JSON.parse(String(init.body)),actor_id:'user1',actor_kind:'current_user',created_at:'2026-11-02T01:00:00Z'})
  }
  if(url.includes('/requests/'))return saved?Response.json({...snapshot,id:'s2',revision:2,stage:'final'}):Response.json({detail:{}},{status:404})
  if(url.endsWith('/candidates'))return Response.json(candidates)
  if(url.endsWith('/snapshots'))return Response.json({items:history?[snapshot]:[]})
  if(url.endsWith('/package'))return Response.json({task:null,task_id:null,download_url:null,progress:null})
  if(url.endsWith('/acceptances'))return Response.json({items:[]})
  return Response.json(snapshot)
 });vi.stubGlobal('fetch',fetcher);return fetcher
}
const props={projectId:'p1',deliveryId:'d1',active:true,onSelect:vi.fn()}
it('round trips exact delivery history and rejects incomplete or unrelated snapshot identities',()=>{
 const hash='#project=p1&section=overview&view=deliveries&delivery=d1&snapshot=s1',route=parseNavigation(hash)
 expect(route).not.toBeNull();expect(serializeNavigation(route!)).toBe(hash)
 for(const bad of ['#project=p1&section=overview&view=deliveries&snapshot=s1','#project=p1&section=overview&view=requirements&delivery=d1','#project=p1&section=files&delivery=d1'])expect(parseNavigation(bad)).toBeNull()
})
it('accepts only exact offline delivery tasks and the normal failed-task recovery workspace',()=>{
 const input={kind:'delivery_package',schema_version:1,workflow_version:'delivery_package_v1',source_sha256:'a'.repeat(64),output_language:'zh-CN',real_model_calls:false,real_network_calls:false}
 const task={...taskFixture,task_type:'delivery_package',phase:'export',status:'failed',input_version:input}
 const workspace={task,source:{file_id:null,filename:'Frozen delivery',analysis_run_id:null,is_current:true},wait:null,allowed_actions:['retry'],artifacts:{figure:null,explanation:null,report:null}}
 expect(isTask(task,'p1')).toBe(true);expect(isWorkspace(workspace,'p1','t1')).toBe(true)
 expect(isTask({...task,input_version:{...input,real_model_calls:true}},'p1')).toBe(false)
 expect(isWorkspace({...workspace,source:{...workspace.source,file_id:'cross-file'}},'p1','t1')).toBe(false)
 expect(sameInputVersion(input as never,{...input,source_sha256:'b'.repeat(64)} as never)).toBe(false)
})
it('derives an explicit final snapshot and freezes identifiers after showing server gaps and quality',async()=>{
 const fetcher=mockApi();render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);fireEvent.click(await screen.findByRole('button',{name:'从此快照派生新版本'}))
 fireEvent.change(screen.getByLabelText('交付阶段'),{target:{value:'final'}});fireEvent.change(screen.getByLabelText('本次修改说明'),{target:{value:'Reuse existing files; PDF remains missing'}})
 fireEvent.click(screen.getByLabelText('draft.docx · Word 文档 · 署名版'))
 fireEvent.click(screen.getByRole('button',{name:'核对所选成员与缺口'}));await screen.findByText('缺必需格式')
 expect(screen.getAllByText(/字体核对：未知/).length).toBeGreaterThan(0);expect(screen.queryByLabelText('failed.pdf')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'冻结本次交付快照'}));await waitFor(()=>expect(props.onSelect).toHaveBeenCalledWith('s2'))
 const post=fetcher.mock.calls.find(([u,i])=>u.endsWith('/snapshots')&&i?.method==='POST')!,body=JSON.parse(String(post[1]?.body))
 expect(body).toMatchObject({stage:'final',parent_snapshot_id:'s1',expected_revision:1,requirement_version_id:'r1',required_formats:['docx','pdf'],mode:'complete'})
 expect(body.members[0]).toEqual(selection);expect(body.members[0].sha256).toBeUndefined();expect(body.members).toHaveLength(2)
 expect(fetcher.mock.calls.filter(([u,i])=>i?.method==='POST'&&!u.includes('/snapshots'))).toHaveLength(0)
})
it('recovers an unknown freeze through the original key without posting a new snapshot',async()=>{
 const fetcher=mockApi({lost:true});render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);fireEvent.click(await screen.findByRole('button',{name:'从此快照派生新版本'}));fireEvent.change(screen.getByLabelText('本次修改说明'),{target:{value:'Known input'}})
 fireEvent.click(screen.getByRole('button',{name:'核对所选成员与缺口'}));await screen.findByRole('button',{name:'冻结本次交付快照'});fireEvent.click(screen.getByRole('button',{name:'冻结本次交付快照'}));fireEvent.click(await screen.findByRole('button',{name:'查询原请求结果'}));await waitFor(()=>expect(fetcher.mock.calls.some(([u])=>u.includes('/requests/'))).toBe(true))
 const posts=fetcher.mock.calls.filter(([u,i])=>u.endsWith('/snapshots')&&i?.method==='POST');expect(posts).toHaveLength(1);expect(fetcher.mock.calls.some(([u])=>u.endsWith('/requests/'+new Headers(posts[0][1]?.headers).get('Idempotency-Key')))).toBe(true)
})
it('preserves the conflicting input, separates blind selection and clears sensitive drafts on session change',async()=>{
 mockApi({conflict:true});render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);fireEvent.click(await screen.findByRole('button',{name:'从此快照派生新版本'}));fireEvent.change(screen.getByLabelText('本次修改说明'),{target:{value:'Private retained input'}})
 fireEvent.click(screen.getByRole('button',{name:'核对所选成员与缺口'}));await screen.findByRole('button',{name:'冻结本次交付快照'});fireEvent.click(screen.getByRole('button',{name:'冻结本次交付快照'}));await screen.findByText('版本冲突：草稿已保留。读取服务器历史，明确比较父快照与修订号后重新预览。')
 expect((screen.getByLabelText('本次修改说明') as HTMLTextAreaElement).value).toBe('Private retained input')
 fireEvent.change(screen.getByLabelText('交付模式'),{target:{value:'blind'}});expect(screen.queryByLabelText('draft.docx · Word 文档 · 署名版')).toBeNull();expect(screen.getByLabelText('blind.docx · Word 文档 · 盲审版')).toBeTruthy();expect((screen.getByLabelText('已选择成员数') as HTMLOutputElement).textContent).toBe('0')
 act(()=>clearApiSession());expect(screen.queryByDisplayValue('Private retained input')).toBeNull();expect(Object.values(sessionStorage).join('')).not.toContain('Private retained input')
})
it('records an explicit current-user acceptance bound to the historical SHA without packaging or assuming customer login',async()=>{
 const fetcher=mockApi();render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);const form=await screen.findByRole('group',{name:'追加接受或纠正记录'})
 fireEvent.change(within(form).getByLabelText('明确接受范围'),{target:{value:'Engineering scope only'}});fireEvent.change(within(form).getByLabelText('接受或纠正意见'),{target:{value:'Fixture check'}});fireEvent.click(within(form).getByRole('button',{name:'追加本次记录'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([u,i])=>u.endsWith('/acceptances')&&i?.method==='POST')).toBe(true));const body=JSON.parse(String(fetcher.mock.calls.find(([u,i])=>u.endsWith('/acceptances')&&i?.method==='POST')![1]?.body))
 expect(body).toMatchObject({snapshot_sha256:snapshot.sha256,scope:'Engineering scope only',kind:'accept',customer_reply:null,corrects_event_id:null});expect(body.actor_id).toBeUndefined();expect(screen.getByText('由当前有权用户记录；客户回复为所提供文本，不代表客户本人登录。')).toBeTruthy()
 expect(fetcher.mock.calls.filter(([u,i])=>u.endsWith('/package')&&i?.method==='POST')).toHaveLength(0)
})
it('allows ordinary keyboard entry of multiple required formats and stops an in-flight preview on unmount',async()=>{
 const user=userEvent.setup();const fetcher=mockApi();const view=render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);await user.click(await screen.findByRole('button',{name:'从此快照派生新版本'}));const formats=screen.getByLabelText('本次必需格式（逗号分隔）')
 await user.clear(formats);await user.type(formats,'docx,pdf,png');expect((formats as HTMLInputElement).value).toBe('docx,pdf,png')
 fireEvent.change(screen.getByLabelText('本次修改说明'),{target:{value:'Pending preview'}});let signal:AbortSignal|undefined
 fetcher.mockImplementation(async(_url,init)=>{signal=init?.signal??undefined;return new Promise<Response>(()=>{})});fireEvent.click(screen.getByRole('button',{name:'核对所选成员与缺口'}));view.unmount();expect(signal?.aborted).toBe(true)
})

it('presents saved delivery facts without technical identities while retaining downloads',async()=>{
 mockApi();render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);await screen.findByRole('button',{name:'从此快照派生新版本'});expect(document.body.textContent).not.toContain(snapshot.sha256);expect(document.body.textContent).not.toContain(member.sha256);expect(document.body.textContent).not.toContain('SHA256');expect(document.querySelector('pre')).toBeNull();expect(document.body.textContent).toContain('region-enriched only');expect(document.body.textContent).toContain('license unknown');fireEvent.click(screen.getByRole('button',{name:'从此快照派生新版本'}));expect((screen.getByLabelText('固定需求版本') as HTMLSelectElement).value).toBe('r1');expect(document.body.textContent).not.toContain(candidates.requirements[0].sha256);expect(screen.getByRole('link',{name:'下载已有成员 plot.png'}).getAttribute('href')).toContain('/members/member1/download');
})

it('preserves historical generated PDFs but requires removal before deriving a new delivery',async()=>{
 const retiredSelection={kind:'research_figure_member',version_id:'old-figure',member_id:'old-pdf'},retiredMember={...member,id:'old-pdf',selection:retiredSelection,name:'old-figure.pdf',format:'pdf'},historic={...snapshot,members:[retiredMember]}
 const available={...candidates,items:[...candidates.items,{selection:retiredSelection,label:'generated-figure.pdf',format:'pdf',status:'succeeded'},{selection:{kind:'pdf_export',export_id:'pdf1'},label:'generated-report.pdf',format:'pdf',status:'succeeded'},{selection:{kind:'file',file_id:'original-pdf'},label:'original-material.pdf',format:'pdf',status:'existing_upload'}]}
 const fetcher=vi.fn(async(url:string)=>Response.json(url.endsWith('/candidates')?available:url.endsWith('/snapshots/s1')?historic:url.endsWith('/snapshots')?{items:[historic]}:{items:[],task:null,progress:null,task_id:null,download_url:null}));vi.stubGlobal('fetch',fetcher)
 render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);await screen.findByRole('link',{name:'下载已有成员 old-figure.pdf'});fireEvent.click(await screen.findByRole('button',{name:'从此快照派生新版本'}));fireEvent.change(screen.getByLabelText('本次修改说明'),{target:{value:'Keep other draft inputs'}})
 expect(screen.queryByLabelText(/generated-figure.pdf/)).toBeNull();expect(screen.queryByLabelText(/generated-report.pdf/)).toBeNull();expect(screen.getByLabelText(/original-material.pdf/)).toBeTruthy()
 expect(screen.getByText(/新交付不再支持生成的 PDF 成果/)).toBeTruthy();expect(screen.getByRole('button',{name:'核对所选成员与缺口'}).hasAttribute('disabled')).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'移除此原选择'}));expect((screen.getByLabelText('本次修改说明') as HTMLTextAreaElement).value).toBe('Keep other draft inputs');expect(screen.getByRole('link',{name:'下载已有成员 old-figure.pdf'})).toBeTruthy()
})
