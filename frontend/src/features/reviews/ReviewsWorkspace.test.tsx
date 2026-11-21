import {cleanup,render,screen,waitFor,within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {afterEach,expect,it,vi} from 'vitest'
import ReviewsWorkspace from './ReviewsWorkspace'
import {clearApiSession} from '../../shared/api/client'
import {STANDARD_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
const inputs={project_type:'sci',manuscripts:[{id:'m1',title:'固定稿',current_revision:2,versions:[{id:'v1',revision:1,status:'published',title:'旧稿'},{id:'v2',revision:2,status:'published',title:'新稿'}]}],documents:[],journal_targets:[],school_confirmations:[]}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN');Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'})})
vi.mock('../files/BatchUpload',()=>({default:({onChanged}:{onChanged:()=>void})=><button onClick={onChanged}>模拟上传完成</button>}))
it('previews immutable original text, allows splitting and merging, and creates against explicitly selected old version',async()=>{const requests:{url:string,body:unknown}[]=[];vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{const body=init?.body?JSON.parse(String(init.body)):null;requests.push({url,body});if(url.endsWith('/inputs'))return Response.json(inputs);if(url.endsWith('/sources/preview'))return Response.json({original_text:'1. Improve clarity.\n2. Add evidence.',segments:[{start:0,end:19,original_number:'1',text:'1. Improve clarity.',location:null},{start:20,end:36,original_number:'2',text:'2. Add evidence.',location:null}],warnings:[],supported:true});if(url.endsWith('/rounds')&&init?.method==='POST')return Response.json({detail:{message:'stop'}},{status:409});return Response.json({items:[]})}));render(<ReviewsWorkspace projectId="p1" projectType="sci" active roundId="" onSelectRound={vi.fn()} onOpenTask={vi.fn()}/>);const user=userEvent.setup();await screen.findByRole('option',{name:'旧稿 · 版本 1'});await user.selectOptions(screen.getByLabelText('固定稿件版本'),'v1');await user.type(screen.getByLabelText('轮次标题'),'第一轮');await user.type(screen.getByLabelText('来源身份'),'Reviewer 1');await user.type(screen.getByLabelText('意见原文'),'1. Improve clarity.\n2. Add evidence.');await user.click(screen.getByRole('button',{name:'预览并分条'}));await screen.findByText('原文分条预览');await user.click(screen.getAllByRole('button',{name:'与下一条合并'})[0]);expect(screen.getAllByLabelText('原始编号')).toHaveLength(1);await user.type(screen.getByLabelText('在本条第几个字符后拆分'),'19');await user.click(screen.getByRole('button',{name:'拆分此条'}));expect(screen.getAllByLabelText('原始编号')).toHaveLength(2);await user.click(screen.getByRole('button',{name:'保存来源'}));await user.click(screen.getByRole('button',{name:'创建本轮意见计划'}));await waitFor(()=>expect(requests.some(r=>r.url.endsWith('/rounds')&&(r.body as {manuscript?:{version_id:string}})?.manuscript?.version_id==='v1')).toBe(true));const creation=requests.find(r=>r.url.endsWith('/rounds')&&r.body)?.body as {synthetic:boolean,sources:{text:string}[]};expect(creation.synthetic).toBe(true);expect(creation.sources[0].text).toBe('1. Improve clarity.\n2. Add evidence.')})
it('clears sensitive review inputs on logout and aborts further creation',async()=>{vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/inputs')?inputs:{items:[]})));render(<ReviewsWorkspace projectId="p1" projectType="sci" active roundId="" onSelectRound={vi.fn()} onOpenTask={vi.fn()}/>);await screen.findByRole('option',{name:'旧稿 · 版本 1'});act(()=>clearApiSession());await waitFor(()=>expect(screen.queryByLabelText('意见原文')).toBeNull())})
import {act,fireEvent} from '@testing-library/react'
import {taskFixture} from '../tasks/taskFixtures'
import {manuscriptFixture} from '../manuscripts/manuscriptFixtures'
const reviewItem={id:'i1',source_id:'s1',number:1,original_number:'1.',original_text:'Please explain the statistical method.',source_location:{page:2},revision:1,status:'waiting_confirmation',uncompleted_reason:'待用户确认',decision:null,category:'statistics',locations:[],translation:null,plan:'核对固定统计来源',evidence_ids:[],needs:[],flags:['ambiguous'],conflicting_item_ids:[],proposed_action:'modify',not_adopt_reason:''}
it('loads only the fixed manuscript version and refreshes a failed location read',async()=>{
 const round=savedRound(), version=manuscriptFixture.versions[0]
 let attempts=0
 const fetcher=vi.fn(async(url:string)=>{
  if(url.endsWith('/inputs'))return Response.json(inputs)
  if(url.endsWith('/rounds'))return Response.json({items:[round]})
  if(url.endsWith('/rounds/round1'))return Response.json(round)
  if(url.endsWith(`/manuscripts/${manuscriptFixture.id}/versions/1`)){
   if(++attempts===1)throw new TypeError('temporary connection failure')
   return Response.json(version)
  }
  return Response.json({items:[]})
 })
 vi.stubGlobal('fetch',fetcher)
 render(<ReviewsWorkspace projectId="p1" projectType="sci" active roundId="round1" onSelectRound={vi.fn()} onOpenTask={vi.fn()}/>)
 await waitFor(()=>expect(attempts).toBe(1))
 await screen.findByRole('alert')
 await userEvent.click(screen.getByRole('button',{name:'刷新意见记录'}))
 await waitFor(()=>expect(attempts).toBe(2))
 await waitFor(()=>expect(screen.queryByRole('alert')).toBeNull())
 expect(fetcher.mock.calls.some(([url])=>url.endsWith('/manuscripts'))).toBe(false)
})
function savedRound(){return {id:'round1',project_id:'p1',title:'合成审稿意见',project_type:'sci',round_number:1,revision:1,synthetic:true,manuscript:{id:manuscriptFixture.id,revision:1,version_id:manuscriptFixture.versions[0].id,title:'固定稿'},sources:[{id:'s1',role:'reviewer',label:'Reviewer 1',format:'text',file_id:null as string|null,document_version_id:null as string|null,original_text:reviewItem.original_text,segments:[],warnings:[]}],items:[structuredClone(reviewItem)],materials:[],constraints:{school_confirmation_id:null,journal_target_id:null},versions:[{id:'history1',revision:1,created_at:taskFixture.created_at,items:[structuredClone(reviewItem)]}],decisions:[],task:{...taskFixture,task_type:'review_round_plan',phase:'verify',input_version:{kind:'review_round_plan',round_id:'round1',base_version_id:manuscriptFixture.versions[0].id,workflow_version:'review_round_plan_v1'}},wait:null,created_at:taskFixture.created_at,real_model_calls:false,real_network_calls:false}}

it.each([
 {customer:true,locale:'zh-CN',label:'方法 · 段落 1'},
 {customer:true,locale:'en',label:'Methods · Paragraph 1'},
 {customer:false,locale:'zh-CN',label:'materials_and_methods/methods:purpose'},
] as const)('shows generated locations in the plan for $locale customer=$customer and saves actual edits only',async({customer,locale,label})=>{
 setLocale(locale)
 const ref='materials_and_methods/methods:purpose',original='📝 '+ref
 const parts=['意见：'+original+'\n固定位置：','\n固定现文：'+original+'\n已读取具体资料：'+original+'\n具体处理：以列出的固定变量和统计记录核对 ',' 中的样本口径及方法说明。']
 const plan=parts.join(ref),start=Array.from(parts[0]).length,second=start+ref.length+Array.from(parts[1]).length
 const spans=[start,second].map(offset=>({kind:'paragraph',id:'methods:purpose',start:offset,end:offset+ref.length}))
 const r={...savedRound(),generated_plan_locations:{i1:spans}}
 r.items[0]={...r.items[0],original_text:original,plan}
 r.versions[0].items=[structuredClone(r.items[0])]
 const v=structuredClone(manuscriptFixture.versions[0]);v.snapshot.methods[0].id='methods:purpose'
 const posted:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/plans'))posted.push(JSON.parse(String(init?.body)).items[0].plan)
  return Response.json(url.endsWith('/inputs')?inputs:url.endsWith('/manuscripts/m1/versions/1')?v:url.endsWith('/rounds')?{items:[r]}:r)
 }))
 render(<ReviewsWorkspace projectId="p1" projectType="sci" active customer={customer} roundId="round1" selectedItemId="i1" view="plan" onSelectRound={vi.fn()} onOpenTask={vi.fn()}/>)
 const field=await screen.findByLabelText(locale==='en'?'Revision plan':'修改计划')
 await waitFor(()=>expect((field as HTMLTextAreaElement).value).toBe(parts.join(label)))
 const save=screen.getByRole('button',{name:locale==='en'?/save.*plan/i:'保存本轮计划修改'})
 fireEvent.click(save)
 await waitFor(()=>expect(posted).toEqual([plan]))
 const authorText='我手写的 '+ref
 await waitFor(()=>expect(field.matches(':disabled')).toBe(false))
 fireEvent.change(field,{target:{value:authorText}})
 expect((field as HTMLTextAreaElement).value).toBe(authorText)
 fireEvent.click(save)
 await waitFor(()=>expect(posted).toEqual([plan,authorText]))
})

it('preserves historical hand-written plans even when a later edit restores the original technical text',async()=>{
 const ref='materials_and_methods/methods:purpose',generated='原位置 '+ref,manual='译者手写 '+ref
 const r={...savedRound(),revision:3,generated_plan_locations:{i1:[{kind:'paragraph',id:'methods:purpose',start:4,end:4+ref.length}]}}
 r.items[0].plan=generated
 r.versions=[generated,manual,generated].map((plan,index)=>({...r.versions[0],id:'v'+index,revision:index+1,items:[{...r.items[0],plan}]}))
 const v=structuredClone(manuscriptFixture.versions[0]);v.snapshot.methods[0].id='methods:purpose'
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/inputs')?inputs:url.endsWith('/manuscripts/m1/versions/1')?v:url.endsWith('/rounds')?{items:[r]}:r)))
 render(<ReviewsWorkspace projectId="p1" projectType="sci" active customer roundId="round1" selectedItemId="i1" view="plan" onSelectRound={vi.fn()} onOpenTask={vi.fn()}/>)
 const field=()=>screen.getByLabelText('修改计划') as HTMLTextAreaElement
 await screen.findByRole('option',{name:'方法 · 段落 1'})
 expect(field().value).toBe(generated)
 fireEvent.change(screen.getByLabelText('查看计划历史'),{target:{value:'2'}})
 expect(field().value).toBe(manual)
 fireEvent.change(screen.getByLabelText('查看计划历史'),{target:{value:'1'}})
 expect(field().value).toBe('原位置 方法 · 段落 1')
 expect(field().matches(':disabled')).toBe(true)
})

async function readyCustomerCreation(post:(init:RequestInit)=>Promise<Response>) {
 const choose=vi.fn(), listing=vi.fn()
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/inputs'))return Response.json(inputs)
  if(url.endsWith('/sources/preview'))return Response.json({original_text:'A',segments:[{start:0,end:1,original_number:'1'}],supported:true,warnings:[]})
  if(url.endsWith('/rounds')&&init?.method==='POST')return post(init)
  if(url.endsWith('/rounds')){listing();return Response.json({items:[savedRound()]})}
  return Response.json(manuscriptFixture.versions[0])
 }))
 render(<ReviewsWorkspace projectId="p1" projectType="sci" customer active view="create" roundId="" onSelectRound={choose} onOpenTask={vi.fn()}/>)
 await screen.findByRole('option',{name:/旧稿/})
 fireEvent.change(screen.getByLabelText('轮次标题'),{target:{value:'合成审稿意见'}})
 fireEvent.change(screen.getByLabelText('固定稿件版本'),{target:{value:'v1'}})
 fireEvent.change(screen.getByLabelText('来源身份'),{target:{value:'Reviewer 1'}})
 fireEvent.change(screen.getByLabelText('意见原文'),{target:{value:'A'}})
 fireEvent.click(screen.getByRole('button',{name:'预览并分条'}))
 fireEvent.click(await screen.findByRole('button',{name:'保存来源'}))
 return {choose,listing,submit:screen.getByRole('button',{name:'创建本轮意见计划'})}
}

it('keeps the original create pending past fifteen seconds and opens the accepted round',async()=>{
 const post=vi.fn((init:RequestInit)=>new Promise<Response>((resolve,reject)=>{
  init.signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')))
  setTimeout(()=>resolve(Response.json(savedRound(),{status:202})),20000)
 }))
 const {choose,submit}=await readyCustomerCreation(post)
 vi.useFakeTimers()
 try {
  fireEvent.click(submit)
  await act(async()=>{await vi.advanceTimersByTimeAsync(15001)})
  expect(post.mock.calls[0][0].signal?.aborted).toBe(false)
  expect(submit.matches(':disabled')).toBe(true)
  await act(async()=>{await vi.advanceTimersByTimeAsync(5000)})
  expect(choose).toHaveBeenCalledWith('round1',{created:true})
  expect(post).toHaveBeenCalledTimes(1)
 }finally{vi.useRealTimers()}
})

it.each(['disconnect','deadline','invalid receipt','server error'] as const)('rereads without replaying an uncertain %s and explicitly retries the original creation',async failure=>{
 const post=vi.fn(async(init:RequestInit)=>{
  if(post.mock.calls.length>1)return Response.json(savedRound(),{status:200})
  if(failure==='disconnect')throw new TypeError('network disconnected')
  if(failure==='invalid receipt')return Response.json({}, {status:202})
  if(failure==='server error')return Response.json({}, {status:503})
  return new Promise<Response>((_,reject)=>init.signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))))
 })
 const {choose,listing,submit}=await readyCustomerCreation(post)
 if(failure==='deadline')vi.useFakeTimers()
 try {
  await act(async()=>{fireEvent.click(submit);if(failure==='deadline')await vi.advanceTimersByTimeAsync(STANDARD_REQUEST_TIMEOUT_MS+1)})
  const retry=screen.getByRole('button',{name:'使用原请求重试'})
  expect(screen.getByLabelText('轮次标题')).toHaveProperty('value','合成审稿意见')
  expect(submit.matches(':disabled')).toBe(true)
  const reads=listing.mock.calls.length
  await act(async()=>{fireEvent.click(screen.getByRole('button',{name:'刷新意见记录'}))})
  expect(listing.mock.calls.length).toBeGreaterThan(reads)
  expect(post).toHaveBeenCalledTimes(1)
  expect(choose).not.toHaveBeenCalled()
  await act(async()=>{fireEvent.click(retry)})
  const [first,second]=post.mock.calls.map(([init])=>[new Headers(init.headers).get('Idempotency-Key'),init.body])
  expect(first[0]).toBeTruthy()
  expect(second).toEqual(first)
  expect(choose).toHaveBeenCalledWith('round1',{created:true})
 }finally{vi.useRealTimers()}
})

it('keeps the form editable after a definitive review creation rejection',async()=>{
 const post=vi.fn(async()=>Response.json({detail:{code:'validation_error'}},{status:422}))
 const {choose,submit}=await readyCustomerCreation(post)
 fireEvent.click(submit)
 await screen.findByRole('alert')
 expect(screen.queryByRole('button',{name:'使用原请求重试'})).toBeNull()
 expect(submit.matches(':disabled')).toBe(false)
 expect(choose).not.toHaveBeenCalled()
})
it('saves full editable plans without changing original opinions, then records decisions and reads history',async()=>{let state=savedRound();const writes:{url:string,body:Record<string,unknown>}[]=[];vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){const body=JSON.parse(String(init.body));writes.push({url,body});if(url.endsWith('/plans')){state={...state,revision:2,items:body.items.map((edit:object)=>({...reviewItem,...edit,revision:2})),versions:[...state.versions,{id:'history2',revision:2,created_at:taskFixture.created_at,items:body.items.map((edit:object)=>({...reviewItem,...edit,revision:2}))}]};return Response.json(state)}return Response.json(state)}if(url.endsWith('/inputs'))return Response.json(inputs);if(url.endsWith('/manuscripts/m1/versions/1'))return Response.json(manuscriptFixture.versions[0]);if(url.endsWith('/rounds'))return Response.json({items:[state]});return Response.json(state)}));const openTask=vi.fn();render(<ReviewsWorkspace projectId="p1" projectType="sci" active roundId="round1" onSelectRound={vi.fn()} onOpenTask={openTask}/>);await screen.findAllByText(reviewItem.original_text);expect(screen.getByText('来源第 2 页')).toBeTruthy();fireEvent.change(screen.getByLabelText('人工译文'),{target:{value:'请解释统计方法。'}});fireEvent.change(screen.getByLabelText('修改计划'),{target:{value:'仅核对已有统计证据'}});fireEvent.click(screen.getByRole('button',{name:'保存本轮计划修改'}));await screen.findByText('意见计划已保存；意见仍待处理。');expect(writes[0].body).toMatchObject({expected_revision:1,items:[{id:'i1',translation:{language:'zh-CN',text:'请解释统计方法。'},plan:'仅核对已有统计证据'}]});expect(JSON.stringify(writes[0].body)).not.toContain('original_text');expect(screen.getAllByText(reviewItem.original_text)).toHaveLength(2);fireEvent.change(screen.getByLabelText('决定理由'),{target:{value:'已人工核对证据范围'}});fireEvent.click(screen.getByRole('button',{name:'保存本轮决定'}));await screen.findByText('决定已记录；可前往任务继续本地计划核查。');expect(writes[1].body).toEqual({expected_revision:2,decisions:[{item_id:'i1',action:'accept',reason:'已人工核对证据范围'}]});fireEvent.change(screen.getByLabelText('查看计划历史'),{target:{value:'1'}});expect(screen.getByLabelText('修改计划')).toHaveProperty('value','核对固定统计来源');expect(screen.getByLabelText('修改计划').matches(':disabled')).toBe(true);fireEvent.click(screen.getByRole('button',{name:'查看任务与继续本地计划'}));expect(openTask).toHaveBeenCalledWith('t1');expect(screen.queryByRole('button',{name:'生成回复信'})).toBeNull()})
it('binds thesis reviews to the selected fixed manuscript school confirmation',async()=>{const chapters=[{id:'c1',title:'第一章',level:1,purpose:'materials_and_methods',output_language:'zh-CN',result_group_ids:[]}],profile={revision:1,school:'学校',department:'',major:'',degree_type:'硕士',education_level:'研究生',applicable_version:'2026',bound_confirmation_id:'confirm1'},school={schema_version:1,profile,template_version_id:'template1',confirmation_id:'confirm1',confirmation_sha256:'a'.repeat(64),confirmation:{id:'confirm1',chapters:[{id:'c1',title:'第一章',level:1}]},source_files:[],chapters};const v={...manuscriptFixture.versions[0],snapshot:{...manuscriptFixture.versions[0].snapshot,thesis_context:school,sections:chapters.map(c=>({...c,paragraphs:[]})),school_content_report:{rules_version:'school_v1',issues:[],can_publish:true,scientifically_verified:false}}};const i={...inputs,project_type:'thesis',manuscripts:[{id:manuscriptFixture.id,title:'固定学校稿',current_revision:1,versions:[{id:v.id,revision:1,status:'published',title:'固定学校稿'}]}],school_confirmations:[{id:'confirm1',label:'旧确认'},{id:'confirm2',label:'新确认'}]};vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/inputs')?i:url.endsWith('/manuscripts/m1/versions/1')?v:{items:[]})));render(<ReviewsWorkspace projectId="p1" projectType="thesis" active roundId="" initialManuscript={manuscriptFixture.id} initialRevision={1} onSelectRound={vi.fn()} onOpenTask={vi.fn()}/>);await waitFor(()=>expect(screen.getByLabelText('固定稿件的学校确认')).toHaveProperty('value','confirm1'));expect(screen.getByLabelText('固定稿件的学校确认').matches(':disabled')).toBe(true)})
import {setLocale} from '../../shared/i18n'
it('localizes review navigation and ordinary creation controls',async()=>{setLocale('en');vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/inputs')?inputs:{items:[]})));render(<ReviewsWorkspace projectId="p1" projectType="sci" active roundId="" onSelectRound={vi.fn()} onOpenTask={vi.fn()}/>);expect(screen.getByRole('heading',{name:'Review revisions'})).toBeTruthy();expect(screen.getByLabelText('Round title')).toBeTruthy();setLocale('zh-CN')})
it('records important choices in one round request and leaves ordinary edits free of approval controls',async()=>{const r=savedRound();r.items=[{...reviewItem,id:'i1'},{...reviewItem,id:'i2',number:2,flags:['conflict']},{...reviewItem,id:'i3',number:3,flags:[]}];r.sources=[{...r.sources[0],format:'document',file_id:'f1',document_version_id:'parse1'}] as typeof r.sources;const posts:unknown[]=[];vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){posts.push(JSON.parse(String(init.body)));return Response.json(r)}return Response.json(url.endsWith('/inputs')?inputs:url.endsWith('/manuscripts/m1/versions/1')?manuscriptFixture.versions[0]:url.endsWith('/rounds')?{items:[r]}:r)}));render(<ReviewsWorkspace projectId="p1" projectType="sci" active roundId="round1" onSelectRound={vi.fn()} onOpenTask={vi.fn()}/>);await screen.findByRole('group',{name:'本轮重要处理决定'});expect(screen.getAllByLabelText('决定理由')).toHaveLength(2);for(const field of screen.getAllByLabelText('决定理由'))fireEvent.change(field,{target:{value:'人工选择并保留原结论范围'}});fireEvent.click(screen.getByRole('button',{name:'保存本轮决定'}));await waitFor(()=>expect(posts).toHaveLength(1));expect(posts[0]).toMatchObject({decisions:[{item_id:'i1'},{item_id:'i2'}]});expect(screen.getByRole('link',{name:'Reviewer 1'}).getAttribute('href')).toBe('/api/v1/projects/p1/files/f1/download')})
it('blocks incomplete parsed opinions and exposes clean text guidance',async()=>{vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/inputs')?inputs:url.endsWith('/sources/preview')?{original_text:'Partial comment',segments:[{start:0,end:15,original_number:'1'}],supported:false,warnings:['DOCX含修订，请提供清洁文本。']}:{items:[]})));render(<ReviewsWorkspace projectId="p1" projectType="sci" active roundId="" onSelectRound={vi.fn()} onOpenTask={vi.fn()}/>);await screen.findByRole('option',{name:'旧稿 · 版本 1'});fireEvent.change(screen.getByLabelText('来源身份'),{target:{value:'Reviewer 1'}});fireEvent.change(screen.getByLabelText('意见原文'),{target:{value:'Partial comment'}});fireEvent.click(screen.getByRole('button',{name:'预览并分条'}));await screen.findByText('DOCX含修订，请提供清洁文本。');expect(screen.getByRole('button',{name:'保存来源'})).toHaveProperty('disabled',true)})

it.each(['visible','active','upload'])('preserves unsaved plan, translation, decision and materials after %s refresh',async trigger=>{
 const r=savedRound(),doc={file_id:'f1',filename:'补充证据.docx',document_version_id:'d1',version:1,kind:'docx_document'};let reads=0
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{if(url.endsWith('/rounds/round1'))reads++;return Response.json(url.endsWith('/inputs')?{...inputs,documents:[doc]}:url.endsWith('/manuscripts/m1/versions/1')?manuscriptFixture.versions[0]:url.endsWith('/rounds')?{items:[r]}:r)}))
 const props={projectId:'p1',projectType:'sci' as const,active:true,roundId:'round1',onSelectRound:vi.fn(),onOpenTask:vi.fn()},view=render(<ReviewsWorkspace {...props}/>);
 await screen.findByLabelText('修改计划');fireEvent.change(screen.getByLabelText('修改计划'),{target:{value:'未保存计划-留存'}});fireEvent.change(screen.getByLabelText('人工译文'),{target:{value:'未保存译文-留存'}});fireEvent.change(screen.getByLabelText('决定理由'),{target:{value:'未保存理由-留存'}});fireEvent.change(screen.getByLabelText('决定'),{target:{value:'defer'}});fireEvent.click(within(screen.getByRole('group',{name:'补充材料（固定解析版本）'})).getByLabelText('补充证据.docx · 版本 1'));
 const before=reads
 if(trigger==='visible'){act(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'))});act(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});document.dispatchEvent(new Event('visibilitychange'))})}
 if(trigger==='active'){view.rerender(<ReviewsWorkspace {...props} active={false}/>);view.rerender(<ReviewsWorkspace {...props}/>)}
 if(trigger==='upload'){fireEvent.click(screen.getByRole('button',{name:'上传并解析新的 DOCX / PDF'}));fireEvent.click(screen.getByRole('button',{name:'模拟上传完成'}))}
 await waitFor(()=>expect(reads).toBeGreaterThan(before));await act(async()=>{});
 expect(screen.getByLabelText('修改计划')).toHaveProperty('value','未保存计划-留存');expect(screen.getByLabelText('人工译文')).toHaveProperty('value','未保存译文-留存');expect(screen.getByLabelText('决定理由')).toHaveProperty('value','未保存理由-留存');expect(screen.getByLabelText('决定')).toHaveProperty('value','defer');expect(within(screen.getByRole('group',{name:'补充材料（固定解析版本）'})).getByLabelText('补充证据.docx · 版本 1')).toHaveProperty('checked',true)
})

it('applies the manuscript entry only once and preserves an explicitly changed version on refresh',async()=>{
 let reads=0;vi.stubGlobal('fetch',vi.fn(async(url:string)=>{if(url.endsWith('/inputs'))reads++;return Response.json(url.endsWith('/inputs')?inputs:{items:[]})}));render(<ReviewsWorkspace projectId="p1" projectType="sci" active roundId="" initialManuscript="m1" initialRevision={1} onSelectRound={vi.fn()} onOpenTask={vi.fn()}/>);
 await waitFor(()=>expect(screen.getByLabelText('固定稿件版本')).toHaveProperty('value','v1'));fireEvent.change(screen.getByLabelText('固定稿件版本'),{target:{value:'v2'}});const before=reads;fireEvent.click(screen.getByRole('button',{name:'刷新意见记录'}));await waitFor(()=>expect(reads).toBeGreaterThan(before));await act(async()=>{});expect(screen.getByLabelText('固定稿件版本')).toHaveProperty('value','v2')
})

it('identifies repeated source numbers consistently in cards, conflicts, decisions and history',async()=>{
 const r=savedRound();r.sources.push({...r.sources[0],id:'s2',label:'Reviewer 2'});r.items.push({...reviewItem,id:'i2',source_id:'s2'});r.decisions=[{id:'decision1',item_id:'i2',item_revision:1,action:'clarify',reason:'已澄清：保留既有统计方法',created_at:taskFixture.created_at}] as never;r.versions[0].items=r.items;
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/inputs')?inputs:url.endsWith('/manuscripts/m1/versions/1')?manuscriptFixture.versions[0]:url.endsWith('/rounds')?{items:[r]}:r)));render(<ReviewsWorkspace projectId="p1" projectType="sci" active roundId="round1" onSelectRound={vi.fn()} onOpenTask={vi.fn()}/>);
 await screen.findByRole('heading',{name:/Reviewer 2 · 意见 1/});expect(screen.getByLabelText('关联冲突意见 Reviewer 2 · 意见 1')).toBeTruthy();expect(screen.getByRole('group',{name:'Reviewer 2 · 意见 1'})).toBeTruthy();expect(screen.getByText(/Reviewer 2 · 意见 1 · 已澄清并确认处理/)).toBeTruthy();expect(screen.getAllByRole('option',{name:'已澄清并确认处理'})).toHaveLength(2);expect(screen.getByText('选择“已澄清并确认处理”时，理由应写明已澄清的具体处理；尚待答复请暂缓处理。')).toBeTruthy();fireEvent.change(screen.getByLabelText('查看计划历史'),{target:{value:'1'}});expect(screen.getByRole('heading',{name:/Reviewer 2 · 意见 1/})).toBeTruthy()
})

it('describes clarify as an already provided clarification in English',async()=>{
 setLocale('en');const r=savedRound();vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/inputs')?inputs:url.endsWith('/rounds')?{items:[r]}:url.endsWith('/manuscripts/m1/versions/1')?manuscriptFixture.versions[0]:r)));render(<ReviewsWorkspace projectId="p1" projectType="sci" active roundId="round1" onSelectRound={vi.fn()} onOpenTask={vi.fn()}/>);expect(await screen.findByRole('option',{name:'Clarification provided'})).toBeTruthy();expect(screen.getByText('For “Clarification provided”, record the specific clarified handling in the reason. Defer if a reply is still pending.')).toBeTruthy()
})

it('keeps the draft base revision when the server changes, so save still uses CAS',async()=>{
 let current=savedRound();const writes:unknown[]=[];let reads=0;
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){writes.push(JSON.parse(String(init.body)));return Response.json({detail:{message:'stale review revision'}},{status:409})}if(url.endsWith('/rounds/round1'))reads++;return Response.json(url.endsWith('/inputs')?inputs:url.endsWith('/manuscripts/m1/versions/1')?manuscriptFixture.versions[0]:url.endsWith('/rounds')?{items:[current]}:current)}));render(<ReviewsWorkspace projectId="p1" projectType="sci" active roundId="round1" onSelectRound={vi.fn()} onOpenTask={vi.fn()}/>);
 await screen.findByLabelText('修改计划');fireEvent.change(screen.getByLabelText('修改计划'),{target:{value:'旧基线的本地草稿'}});current={...current,revision:2};const before=reads;fireEvent.click(screen.getByRole('button',{name:'刷新意见记录'}));await waitFor(()=>expect(reads).toBeGreaterThan(before));await screen.findByText('服务器记录已更新；未保存草稿已保留，请核对后保存。');fireEvent.click(screen.getByRole('button',{name:'保存本轮计划修改'}));await waitFor(()=>expect(writes).toHaveLength(1));expect(writes[0]).toMatchObject({expected_revision:1});expect(screen.getByLabelText('修改计划')).toHaveProperty('value','旧基线的本地草稿')
})
it('layers opinion selection and preserves the plan while switching views and rounds',async()=>{
 const r=savedRound(),r2={...savedRound(),id:'round2',title:'第二轮',round_number:2,task:{...r.task,input_version:{...r.task.input_version,round_id:'round2'}}};const selectItem=vi.fn(),changeView=vi.fn();
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/inputs')?inputs:url.endsWith('/manuscripts/m1/versions/1')?manuscriptFixture.versions[0]:url.endsWith('/rounds')?{items:[r,r2]}:url.endsWith('/round2')?r2:r)));
 const props={projectId:'p1',projectType:'sci' as const,active:true,roundId:'round1',onSelectRound:vi.fn(),onOpenTask:vi.fn(),onSelectItem:selectItem,onViewChange:changeView};const ui=render(<ReviewsWorkspace {...props} view="items"/>);
 await screen.findByRole('button',{name:/Reviewer 1 · 意见 1/});expect(screen.queryByRole('textbox',{name:'修改计划'})).toBeNull();fireEvent.click(screen.getByRole('button',{name:/Reviewer 1 · 意见 1/}));expect(selectItem).toHaveBeenCalledWith('i1');expect(changeView).toHaveBeenCalledWith('plan');
 ui.rerender(<ReviewsWorkspace {...props} view="plan" selectedItemId="i1"/>);fireEvent.change(await screen.findByRole('textbox',{name:'修改计划'}),{target:{value:'跨视图轮次保留'}});
 ui.rerender(<ReviewsWorkspace {...props} view="sources" selectedItemId="i1"/>);expect(screen.queryByRole('textbox',{name:'修改计划'})).toBeNull();
 ui.rerender(<ReviewsWorkspace {...props} roundId="round2" view="items"/>);await screen.findByRole('heading',{name:'第 2 轮 · 第二轮'});
 ui.rerender(<ReviewsWorkspace {...props} view="plan" selectedItemId="i1"/>);expect(await screen.findByRole('textbox',{name:'修改计划'})).toHaveProperty('value','跨视图轮次保留');
})
it('resets only the creation controller after a successful round creation',async()=>{
 const r=savedRound(),choose=vi.fn();vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>Response.json(url.endsWith('/inputs')?inputs:url.endsWith('/sources/preview')?{original_text:'A',segments:[{start:0,end:1,original_number:'1'}],supported:true,warnings:[]}:init?.method==='POST'?r:url.endsWith('/manuscripts/m1/versions/1')?manuscriptFixture.versions[0]:{items:[]})));
 render(<ReviewsWorkspace projectId="p1" projectType="sci" active roundId="" onSelectRound={choose} onOpenTask={vi.fn()}/>);await screen.findByRole('option',{name:'旧稿 · 版本 1'});fireEvent.change(screen.getByLabelText('轮次标题'),{target:{value:'新轮次'}});fireEvent.change(screen.getByLabelText('固定稿件版本'),{target:{value:'v1'}});fireEvent.change(screen.getByLabelText('来源身份'),{target:{value:'Reviewer 1'}});fireEvent.change(screen.getByLabelText('意见原文'),{target:{value:'A'}});fireEvent.click(screen.getByRole('button',{name:'预览并分条'}));await screen.findByRole('button',{name:'保存来源'});fireEvent.click(screen.getByRole('button',{name:'保存来源'}));fireEvent.click(screen.getByRole('button',{name:'创建本轮意见计划'}));await waitFor(()=>expect(choose).toHaveBeenCalledWith('round1'));expect(screen.queryByRole('heading',{name:'第 1 轮 · 合成审稿意见'})).toBeNull();expect(screen.getByLabelText('固定稿件版本')).toHaveProperty('value','');
})
it('keeps manuscript-specific creation drafts isolated by the exact fixed entry version',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/inputs')?inputs:{items:[]})));const props={projectId:'p1',projectType:'sci' as const,active:true,roundId:'',initialManuscript:'m1',onSelectRound:vi.fn(),onOpenTask:vi.fn(),view:'create' as const};const ui=render(<ReviewsWorkspace {...props} initialRevision={1}/>);await waitFor(()=>expect(screen.getByRole('combobox',{name:'固定稿件版本'})).toHaveProperty('value','v1'));fireEvent.change(screen.getByRole('textbox',{name:'轮次标题'}),{target:{value:'父稿v1草稿'}});
 ui.rerender(<ReviewsWorkspace {...props} initialRevision={2}/>);await waitFor(()=>expect(screen.getByRole('combobox',{name:'固定稿件版本'})).toHaveProperty('value','v2'));expect(screen.getByRole('textbox',{name:'轮次标题'})).toHaveProperty('value','');fireEvent.change(screen.getByRole('textbox',{name:'轮次标题'}),{target:{value:'父稿v2草稿'}});
 ui.rerender(<ReviewsWorkspace {...props} initialRevision={1}/>);expect(screen.getByRole('textbox',{name:'轮次标题'})).toHaveProperty('value','父稿v1草稿');expect(screen.getByRole('combobox',{name:'固定稿件版本'})).toHaveProperty('value','v1');
})
