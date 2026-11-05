import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import DeliveryPackagePanel from './DeliveryPackagePanel'
import {clearApiSession,setApiSession} from '../../shared/api/client'
import {parseNavigation,serializeNavigation} from '../projects/projectNavigation'
import {isTask,isWorkspace,sameInputVersion} from '../tasks/taskTypes'
import {taskFixture} from '../tasks/taskFixtures'
import userEvent from '@testing-library/user-event'

const selection={kind:'file',file_id:'f1'}
const member={id:'member1',selection,name:'plot.png',format:'png',size_bytes:25,sha256:'b'.repeat(64),image:{mapping_status:'pending_verification',dpi:null},source_metadata:{source_notices:['region-enriched only','license unknown']},download_url:'/api/v1/projects/p1/deliveries/d1/snapshots/s1/members/member1/download'}
const snapshot={id:'s1',sha256:'a'.repeat(64),revision:1,parent_snapshot_id:null,requirement_version_id:'r1',stage:'first',mode:'complete',required_formats:['docx'],change_note:'first scope',opinion_round:'not applicable',members:[member],gaps:['required_format:pdf'],quality_items:['字体核对：未知'],completeness:'missing_required',changes:{added:['member1'],removed:[],replaced:[],reason:'first scope'},created_at:'2026-11-02T00:00:00Z'}
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
 expect(body).toMatchObject({stage:'final',parent_snapshot_id:'s1',expected_revision:1,requirement_version_id:'r1',required_formats:['docx'],mode:'complete'})
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
 const fetcher=mockApi();render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);await screen.findByRole('button',{name:'从此快照派生新版本'});fireEvent.click(screen.getByRole('button',{name:'封包与接受'}));fireEvent.click(screen.getByRole('button',{name:'追加接受或纠正记录'}));const form=screen.getByRole('group',{name:'追加接受或纠正记录'})
 fireEvent.change(within(form).getByLabelText('明确接受范围'),{target:{value:'Engineering scope only'}});fireEvent.change(within(form).getByLabelText('接受或纠正意见'),{target:{value:'Fixture check'}});fireEvent.click(within(form).getByRole('button',{name:'追加本次记录'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([u,i])=>u.endsWith('/acceptances')&&i?.method==='POST')).toBe(true));const body=JSON.parse(String(fetcher.mock.calls.find(([u,i])=>u.endsWith('/acceptances')&&i?.method==='POST')![1]?.body))
 expect(body).toMatchObject({snapshot_sha256:snapshot.sha256,scope:'Engineering scope only',kind:'accept',customer_reply:null,corrects_event_id:null});expect(body.actor_id).toBeUndefined();fireEvent.click(screen.getByRole('button',{name:'接受记录'}));expect(screen.getByText('由当前有权用户记录；客户回复为所提供文本，不代表客户本人登录。')).toBeTruthy()
 expect(fetcher.mock.calls.filter(([u,i])=>u.endsWith('/package')&&i?.method==='POST')).toHaveLength(0)
})
it('allows ordinary keyboard entry of multiple required formats and stops an in-flight preview on unmount',async()=>{
 const user=userEvent.setup();const fetcher=mockApi();const view=render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);await user.click(await screen.findByRole('button',{name:'从此快照派生新版本'}));const formats=screen.getByLabelText('本次必需格式（逗号分隔）')
 await user.clear(formats);await user.type(formats,'docx,png');expect((formats as HTMLInputElement).value).toBe('docx,png')
 fireEvent.change(screen.getByLabelText('本次修改说明'),{target:{value:'Pending preview'}});let signal:AbortSignal|undefined
 fetcher.mockImplementation(async(_url,init)=>{signal=init?.signal??undefined;return new Promise<Response>(()=>{})});fireEvent.click(screen.getByRole('button',{name:'核对所选成员与缺口'}));view.unmount();expect(signal?.aborted).toBe(true)
})

it('presents saved delivery facts without technical identities while retaining downloads',async()=>{
 mockApi();render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);await screen.findByRole('button',{name:'从此快照派生新版本'});expect(document.body.textContent).not.toContain(snapshot.sha256);expect(document.body.textContent).not.toContain(member.sha256);expect(document.body.textContent).not.toContain('SHA256');expect(document.querySelector('pre')).toBeNull();expect(document.body.textContent).toContain('region-enriched only');expect(document.body.textContent).toContain('license unknown');fireEvent.click(screen.getByRole('button',{name:'从此快照派生新版本'}));expect((screen.getByLabelText('固定需求版本') as HTMLSelectElement).value).toBe('r1');expect(document.body.textContent).not.toContain(candidates.requirements[0].sha256);fireEvent.click(screen.getByRole('button',{name:'固定交付快照'}));expect(screen.getByRole('link',{name:'下载已有成员 plot.png'}).getAttribute('href')).toContain('/members/member1/download');
})

it.each([true,false])('preserves historical PDF facts without delivery when its candidate exists: %s',async candidateExists=>{
 const retiredSelection={kind:'research_figure_member',version_id:'old-figure',member_id:'old-pdf'},retiredMember={...member,id:'old-pdf',selection:retiredSelection,name:'old-figure.pdf',format:'pdf'},historic={...snapshot,members:[retiredMember,member,{...member,id:'zip',name:'old-package.zip',format:'zip',source_metadata:{inner_members:[{name:'analysis.docx'}]}}]}
 const available={...candidates,items:[...candidates.items,...(candidateExists?[{selection:retiredSelection,label:'generated-figure.pdf',format:'pdf',status:'succeeded'}]:[]),{selection:{kind:'pdf_export',export_id:'pdf1'},label:'generated-report.pdf',format:'pdf',status:'succeeded'},{selection:{kind:'file',file_id:'original-pdf'},label:'original-material.pdf',format:'pdf',status:'existing_upload'}]}
 const fetcher=vi.fn(async(url:string)=>Response.json(url.endsWith('/candidates')?available:url.endsWith('/snapshots/s1')?historic:url.endsWith('/snapshots')?{items:[historic]}:url.endsWith('/package')?{task:{id:'package1',status:'succeeded'},progress:null,task_id:'package1',download_url:'/api/v1/projects/p1/deliveries/d1/snapshots/s1/package/download'}:{items:[]}));vi.stubGlobal('fetch',fetcher)
 render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);await screen.findByRole('link',{name:'下载已有成员 plot.png'});expect(screen.queryByRole('link',{name:'下载已有成员 old-figure.pdf'})).toBeNull();expect(screen.queryByRole('link',{name:'下载此固定交付 ZIP'})).toBeNull();expect(screen.getByRole('link',{name:'下载已有成员 old-package.zip'})).toBeTruthy();fireEvent.click(await screen.findByRole('button',{name:'从此快照派生新版本'}));fireEvent.change(screen.getByLabelText('本次修改说明'),{target:{value:'Keep other draft inputs'}})
 expect(screen.queryByLabelText(/generated-figure.pdf/)).toBeNull();expect(screen.queryByLabelText(/generated-report.pdf/)).toBeNull();expect(screen.queryByLabelText(/original-material.pdf/)).toBeNull()
 expect(screen.getByText(/新交付不再支持 PDF 成果/)).toBeTruthy();expect(screen.getByRole('button',{name:'核对所选成员与缺口'}).hasAttribute('disabled')).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'移除此原选择'}));expect((screen.getByLabelText('本次修改说明') as HTMLTextAreaElement).value).toBe('Keep other draft inputs');expect(screen.queryByRole('link',{name:'下载已有成员 old-figure.pdf'})).toBeNull()
})

it('blocks a PDF required format until explicit removal while keeping delivery inputs',async()=>{
 mockApi();render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);fireEvent.click(await screen.findByRole('button',{name:'从此快照派生新版本'}));fireEvent.change(screen.getByLabelText('本次修改说明'),{target:{value:'Retained note'}})
 fireEvent.change(screen.getByLabelText('本次必需格式（逗号分隔）'),{target:{value:'docx,PDF,png'}})
 expect(screen.getByRole('button',{name:'核对所选成员与缺口'})).toHaveProperty('disabled',true)
 fireEvent.click(screen.getByRole('button',{name:'移除 PDF 格式'}))
 expect(screen.getByLabelText('本次必需格式（逗号分隔）')).toHaveProperty('value','docx,png');expect(screen.getByLabelText('本次修改说明')).toHaveProperty('value','Retained note');expect(screen.getByRole('button',{name:'核对所选成员与缺口'})).toHaveProperty('disabled',false)
})

const nestedSelection={kind:'research_report_member',version_id:'report1',member_id:'zip1'}
const nestedCandidate={selection:nestedSelection,label:'legacy-report.zip',format:'zip',status:'succeeded'}
const nestedPdf={...member,id:'nested',selection:nestedSelection,name:'legacy-report.zip',format:'zip',source_metadata:{inner_members:[{name:'figures/figure_01/analysis.PDF'},{name:'report.docx'}]}}
it.each([false,true])('blocks an existing PDF-containing ZIP from selection and packaging, saved package: %s',async packaged=>{
 const historic={...snapshot,members:[nestedPdf,member]},available={...candidates,items:[...candidates.items,nestedCandidate]}
 const fetch=vi.fn(async(url:string)=>Response.json(url.endsWith('/candidates')?available:url.endsWith('/snapshots')?{items:[historic]}:url.endsWith('/snapshots/s1')?historic:url.endsWith('/package')?{task:packaged?{id:'pack1',status:'succeeded'}:null,download_url:packaged?'/api/v1/projects/p1/deliveries/d1/snapshots/s1/download':null}:{items:[]}));vi.stubGlobal('fetch',fetch)
 render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);await screen.findByRole('link',{name:'下载已有成员 plot.png'});expect(screen.queryByRole('link',{name:'下载已有成员 legacy-report.zip'})).toBeNull();expect(screen.queryByRole('link',{name:'下载此固定交付 ZIP'})).toBeNull();expect(screen.queryByRole('button',{name:'创建此快照的统一 ZIP'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'从此快照派生新版本'}));expect(screen.queryByLabelText(/legacy-report.zip/)).toBeNull();expect(screen.getByText(/新交付不再支持 PDF 成果/)).toBeTruthy()
})
it('requires removal when preview first reveals PDF inside a selected ZIP and never offers freeze',async()=>{
 const fetch=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/preview')?{...snapshot,members:[member,nestedPdf]}:url.endsWith('/candidates')?{...candidates,items:[...candidates.items,nestedCandidate]}:url.endsWith('/snapshots')?{items:[snapshot]}:url.endsWith('/snapshots/s1')?snapshot:{items:[],task:null,download_url:null}));vi.stubGlobal('fetch',fetch)
 render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);fireEvent.click(await screen.findByRole('button',{name:'从此快照派生新版本'}));fireEvent.change(screen.getByLabelText('本次修改说明'),{target:{value:'Retained ZIP draft'}});fireEvent.click(screen.getByLabelText(/legacy-report.zip/));fireEvent.click(screen.getByRole('button',{name:'核对所选成员与缺口'}))
 await waitFor(()=>expect(fetch.mock.calls.some(([url])=>url.endsWith('/preview'))).toBe(true));await screen.findByText(/新交付不再支持 PDF 成果/);expect(screen.queryByRole('button',{name:'冻结本次交付快照'})).toBeNull();expect(screen.getByLabelText('本次修改说明')).toHaveProperty('value','Retained ZIP draft')
})

it.each(['pdf_export','file','nested'])('retains an original %s freeze request for lookup without offering a new POST',async kind=>{
 setApiSession('csrf','owner');const pdfFile={...member,id:'pdf-file',selection:{kind:'file',file_id:'pdf-file'},name:'source.pdf',format:'pdf'},historic={...snapshot,members:[member,nestedPdf,pdfFile]},selection=kind==='pdf_export'?{kind:'pdf_export',export_id:'pdf1'}:kind==='file'?pdfFile.selection:nestedSelection
 const pending={key:'original-freeze',operation:'freeze',url:'/api/v1/projects/p1/deliveries/d1/snapshots',lookup:'/api/v1/projects/p1/deliveries/d1/snapshots/requests/original-freeze',body:{...snapshot,members:[selection]}}
 const storage='paperassist.research-request.v1:owner:p1:delivery:d1:freeze',raw=JSON.stringify(pending);sessionStorage.setItem(storage,raw)
 const fetch=vi.fn(async(url:string,_init?:RequestInit)=>url.includes('/requests/')?Response.json({detail:{}},{status:404}):Response.json(url.endsWith('/candidates')?candidates:url.endsWith('/snapshots')?{items:[historic]}:url.endsWith('/snapshots/s1')?historic:{items:[],task:null,download_url:null}));vi.stubGlobal('fetch',fetch)
 render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);fireEvent.click(await screen.findByRole('button',{name:'查询原请求结果'}));await screen.findByText('尚无原请求回执；可显式使用原键和固定输入重试。');expect(screen.queryByRole('button',{name:'用原键重试固定请求'})).toBeNull();expect(sessionStorage.getItem(storage)).toBe(raw);expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false)
})
it.each([true,false])('allows an unresolved package retry only for a snapshot without PDF: %s',async containsPdf=>{
 setApiSession('csrf','owner');const historic={...snapshot,members:containsPdf?[nestedPdf]:[member]},base='/api/v1/projects/p1/deliveries/d1/snapshots/s1/package',pending={key:'original-package',operation:'package',url:base,lookup:base,body:{}}
 const storage='paperassist.research-request.v1:owner:p1:delivery:d1:package:s1',raw=JSON.stringify(pending);sessionStorage.setItem(storage,raw)
 const fetch=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/candidates')?candidates:url.endsWith('/snapshots')?{items:[historic]}:url.endsWith('/snapshots/s1')?historic:{items:[],task:null,task_id:null,download_url:null}));vi.stubGlobal('fetch',fetch)
 render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);await screen.findByRole('button',{name:'从此快照派生新版本'});fireEvent.click(screen.getByRole('button',{name:'封包与接受'}));fireEvent.click(await screen.findByRole('button',{name:'查询原请求结果'}));await screen.findByText('原快照尚无封包任务，可用原键重试固定请求。');expect(!!screen.queryByRole('button',{name:'用原键重试固定请求'})).toBe(!containsPdf);expect(sessionStorage.getItem(storage)).toBe(raw);expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false)
})

it.each([true,false])('checks the original unresolved freeze body before retry when no historical ZIP metadata exists, PDF: %s',async containsPdf=>{
 setApiSession('csrf','owner');const body={stage:'first',parent_snapshot_id:null,expected_revision:0,requirement_version_id:'r1',change_note:'Original input',opinion_round:'not applicable',mode:'complete',required_formats:['docx'],quality_items:[],members:[nestedSelection]},pending={key:'old-freeze',operation:'freeze',url:'/api/v1/projects/p1/deliveries/d1/snapshots',lookup:'/api/v1/projects/p1/deliveries/d1/snapshots/requests/old-freeze',body}
 const storage='paperassist.research-request.v1:owner:p1:delivery:d1:freeze',raw=JSON.stringify(pending);sessionStorage.setItem(storage,raw)
 const checked={...snapshot,members:[{...nestedPdf,source_metadata:{inner_members:[{name:containsPdf?'figure.pdf':'report.docx'}]}}]}
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>url.includes('/requests/')?Response.json({detail:{}},{status:404}):Response.json(url.endsWith('/preview')?checked:url.endsWith('/candidates')?{...candidates,items:[nestedCandidate]}:url.endsWith('/snapshots')&&init?.method==='POST'?checked:{items:[]}));vi.stubGlobal('fetch',fetch)
 render(<DeliveryPackagePanel {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'查询原请求结果'}));await waitFor(()=>expect(fetch.mock.calls.some(([url])=>url.endsWith('/preview'))).toBe(true))
 const preview=fetch.mock.calls.find(([url])=>url.endsWith('/preview'))!;expect(JSON.parse(String(preview[1]?.body))).toEqual(body)
 if(containsPdf){await screen.findByText('此历史交付包含 PDF，仅保留状态与原请求查询。');expect(screen.queryByRole('button',{name:'用原键重试固定请求'})).toBeNull();expect(sessionStorage.getItem(storage)).toBe(raw)}
 else{fireEvent.click(await screen.findByRole('button',{name:'用原键重试固定请求'}));await waitFor(()=>expect(fetch.mock.calls.some(([url,init])=>url===pending.url&&init?.method==='POST')).toBe(true));const post=fetch.mock.calls.find(([url,init])=>url===pending.url&&init?.method==='POST')!;expect(JSON.parse(String(post[1]?.body))).toEqual(body);expect(new Headers(post[1]?.headers).get('Idempotency-Key')).toBe('old-freeze')}
})

it('rechecks the original Word freeze after a transient preview failure and another explicit lookup',async()=>{
 setApiSession('csrf','owner');const pending={key:'recover-preview',operation:'freeze',url:'/api/v1/projects/p1/deliveries/d1/snapshots',lookup:'/api/v1/projects/p1/deliveries/d1/snapshots/requests/recover-preview',body:{...snapshot,members:[selection]}}
 sessionStorage.setItem('paperassist.research-request.v1:owner:p1:delivery:d1:freeze',JSON.stringify(pending));let previews=0
 const fetch=vi.fn(async(url:string)=>url.includes('/requests/')?Response.json({detail:{}},{status:404}):url.endsWith('/preview')?++previews===1?Response.json({detail:{}},{status:503}):Response.json(snapshot):Response.json(url.endsWith('/candidates')?candidates:{items:[]}));vi.stubGlobal('fetch',fetch)
 render(<DeliveryPackagePanel {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'查询原请求结果'}));await waitFor(()=>expect(previews).toBe(1));await screen.findAllByRole('alert');expect(screen.queryByRole('button',{name:'用原键重试固定请求'})).toBeNull();fireEvent.click(screen.getByRole('button',{name:'查询原请求结果'}));expect(await screen.findByRole('button',{name:'用原键重试固定请求'})).toBeTruthy();expect(previews).toBe(2)
})

it('keeps acceptance and snapshot drafts while switching delivery modules',async()=>{
 const fetcher=mockApi();const {container}=render(<DeliveryPackagePanel {...props} snapshotId="s1"/>);fireEvent.click(await screen.findByRole('button',{name:'从此快照派生新版本'}));fireEvent.change(screen.getByLabelText('本次修改说明'),{target:{value:'保留交付草稿'}});
 fireEvent.click(screen.getByRole('button',{name:'封包与接受'}));fireEvent.click(screen.getByRole('button',{name:'追加接受或纠正记录'}));fireEvent.change(screen.getByLabelText('明确接受范围'),{target:{value:'尚未提交的范围'}});
 fireEvent.click(screen.getByRole('button',{name:'交付草稿'}));expect(screen.getByLabelText('本次修改说明')).toHaveProperty('value','保留交付草稿');fireEvent.click(screen.getByRole('button',{name:'封包与接受'}));expect(screen.getByLabelText('明确接受范围')).toHaveProperty('value','尚未提交的范围');expect(container.querySelector('details')).toBeNull();expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
})
