import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import OcrReview from './OcrReview'
import OcrReviewWorkspace from './OcrReviewWorkspace'
import OcrReviewHistory from './OcrReviewHistory'
import TaskDetail from '../tasks/TaskDetail'
import { clearApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'

afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
const base='/api/v1/projects/p/files/f'
const source={file_id:'f',parse_id:'ocr',parse_version:2,source_sha256:'a'.repeat(64),document_sha256:'b'.repeat(64),parser_version:'ocr-v1',selected_pages:[3,8]}
const input={kind:'ocr_review',source,workflow_version:'ocr_review_v1'}
const task={id:'review-task',project_id:'p',task_type:'review_ocr',status:'waiting_confirmation',phase:'plan',display_status:'waiting_confirmation',revision:3,current_attempt:1,created_at:'2026-10-12',updated_at:'2026-10-12',reason_code:null,error_code:null,input_version:input}
const wait={id:'wait',kind:'ocr_review_confirmation',status:'open',task_revision:3,input_version:input,reason_code:null,error_code:null,created_at:'2026-10-12',resolved_at:null}
const summary={total_blocks:3,reviewed_blocks:0,unreviewed_blocks:3,accepted_blocks:0,corrected_blocks:0,unreadable_blocks:0,no_text_pages:[8]}
const parent={id:'ocr',file_id:'f',kind:'ocr_document',version:2,task_id:'parse-task',status:'succeeded',created_at:'2026-10-12',completed_at:null,parser_version:'ocr-v1',selected_pages:[3,8],summary:{counts:{pages:2,text_blocks:3,images:2,pages_without_text:1},warnings:[]},error:null,download_url:'download',pages_url:'pages',images:[{id:'img',mime:'image/jpeg',size_bytes:3,inline_preview:true,download_url:'https://untrusted.invalid/img'}]}
const polygon=[[10,10],[100,10],[100,30],[10,30]]
const page=(n:number)=>({page_number:n===1?3:8,width:1200,height:1600,rotation:0,preview_image_id:'img',source_width:600,source_height:800,source_coordinate_system:'pdf_points_bottom_left',pixel_to_source:[0.5,0,0,0,-0.5,800],transforms:[],text_status:n===1?'text':'no_text',text_blocks:n===1?['原文甲','原文乙','原文丙'].map((text,i)=>({kind:'ocr_text',id:`block-${i}`,text,score:0.9,review_status:'unreviewed',polygon,source:{page_number:3,polygon,coordinate_system:'pdf_points_bottom_left',label:'private'}})):[],warnings:[]})
function mockApi(resume=false) {
 let decisionFailure=0
 let discover=resume,createConflict=false
 let historyFailure=false,documentFailure:''|'parent'|'page'=''
 let current={task,source,wait,checkpoint_id:'checkpoint',edit_revision:0,edits:[] as {block_id:string;action:string;text?:string}[],summary,preview_download_url:'/api/v1/tasks/review-task/ocr-review/preview/download',result:null as unknown}
 const posts:{url:string;body:Record<string,unknown>;key:string|null}[]=[]
 const versions:unknown[]=[]
 const NativeURL=URL;vi.stubGlobal('URL',class extends NativeURL {static createObjectURL=vi.fn(()=> 'blob:preview');static revokeObjectURL=vi.fn()})
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST') {
   const body=JSON.parse(init.body as string);posts.push({url,body,key:new Headers(init.headers).get('Idempotency-Key')})
   if(url.endsWith('/ocr-reviews')&&createConflict){discover=true;return Response.json({detail:{code:'ocr_review_pending'}},{status:409})}
   if(url.endsWith('/resume'))current={...current,task:{...task,revision:5},wait:{...wait,task_revision:5}}
   if(url.endsWith('/decision')) {
    if(decisionFailure){const status=decisionFailure;decisionFailure=0;return Response.json({detail:{code:'ocr_review_conflict'}},{status})}
    if(body.operation==='revise') {
     const edits=body.edits as typeof current.edits
     current={...current,edits,checkpoint_id:'saved-checkpoint',edit_revision:1,task:{...task,revision:5},wait:{...wait,id:'saved-wait',task_revision:5},summary:{...summary,reviewed_blocks:edits.length,unreviewed_blocks:3-edits.length,accepted_blocks:edits.filter(e=>e.action==='accept_original').length,corrected_blocks:edits.filter(e=>e.action==='replace_text').length,unreadable_blocks:edits.filter(e=>e.action==='unreadable').length}}
    } else {
     const result={id:'published',file_id:'f',parent_parse_id:'ocr',parent_parse_version:2,version:1,created_at:'2026-10-12',task_id:'review-task',source,summary:current.summary,download_url:base+'/ocr-review-versions/published/download'}
     versions.push({...result,edits:current.edits});current={...current,result,task:{...current.task,status:'succeeded',display_status:'succeeded',revision:7},wait:null as never}
    }
   }
   return Response.json(current.task)
  }
  if(url.endsWith('/workspace'))return Response.json({task:current.task,source:{file_id:'f',filename:'scan.pdf',analysis_run_id:null,is_current:true},wait:current.wait,allowed_actions:current.task.status==='failed'?['retry']:['approve','revise'],artifacts:{figure:null,explanation:null,report:null}})
  if(url.includes('/events'))return Response.json({task_id:'review-task',items:[],next_cursor:0,has_more:false})
  if(url.includes('/ocr-review-versions/published')){if(historyFailure){historyFailure=false;return new Response(null,{status:503})}return Response.json(versions[0])}
  if(url.includes('/ocr-review-versions?'))return Response.json({items:versions,total:versions.length,page:1,page_size:5})
  if(url.includes('/ocr-reviews?'))return Response.json({items:discover?[current.task]:[]})
  if(url.endsWith('/ocr-review'))return Response.json(current)
  if(url.includes('/images/'))return new Response('jpg',{headers:{'Content-Type':'image/jpeg'}})
  if(url.includes('/pages?')){if(documentFailure==='page'){documentFailure='';return new Response(null,{status:503})}const n=Number(new URL(url,'http://localhost').searchParams.get('page'));return Response.json({items:[page(n)],total:2,page:n,page_size:1})}
  if(url.endsWith('/document-versions/ocr')){if(documentFailure==='parent'){documentFailure='';return new Response(null,{status:503})}return Response.json(parent)}
  throw new Error(`Unexpected URL ${url}`)
 });vi.stubGlobal('fetch',fetch)
 return {posts,fetch,failNextHistory:()=>{historyFailure=true},failNextDocument:(path:'parent'|'page')=>{documentFailure=path},setPublished:()=>{versions.push({id:'published',file_id:'f',parent_parse_id:'ocr',parent_parse_version:2,version:1,created_at:'2026-10-12',task_id:'review-task',source,summary:{...summary,reviewed_blocks:3,unreviewed_blocks:0,accepted_blocks:3},download_url:base+'/ocr-review-versions/published/download',edits:[0,1,2].map(i=>({block_id:`block-${i}`,action:'accept_original'}))})},failNextCreate:()=>{createConflict=true},failTask:()=>{current={...current,task:{...task,status:'failed',display_status:'failed'},wait:null as never}},failNextDecision:(status:number)=>{decisionFailure=status},setSaved:()=>{current={...current,edits:[{block_id:'block-0',action:'accept_original'}],summary:{...summary,reviewed_blocks:1,unreviewed_blocks:2,accepted_blocks:1}}}}
}
test('starts review, records three explicit actions, saves candidate then approves only the displayed saved version',async()=>{
 const user=userEvent.setup();const {posts}=mockApi()
 render(<OcrReview projectId="p" fileId="f" filename="scan.pdf" parent={parent as never} onUnavailable={()=>{}} />)
 await user.click(await screen.findByRole('button',{name:'开始人工核对'}))
 const blocks=await screen.findAllByRole('group',{name:/文字核对/})
 expect(screen.getByText('未核对 3 / 3 条')).toBeTruthy()
 await user.click(within(blocks[0]).getByRole('radio',{name:'确认原文'}))
 await user.click(within(blocks[1]).getByRole('radio',{name:'修改文字'}))
 await user.clear(within(blocks[1]).getByRole('textbox',{name:'核对文字'}));await user.type(within(blocks[1]).getByRole('textbox',{name:'核对文字'}),'修正乙')
 await user.click(within(blocks[2]).getByRole('radio',{name:'无法辨认'}))
 expect(screen.getByText('未核对 0 / 3 条')).toBeTruthy()
 expect((screen.getByRole('button',{name:'确认生成核对版本'}) as HTMLButtonElement).disabled).toBe(true)
 await user.click(screen.getByRole('button',{name:'保存核对进度'}))
 await screen.findByText('进度已保存。')
 expect(posts[1].body.edits).toEqual([{block_id:'block-0',action:'accept_original'},{block_id:'block-1',action:'replace_text',text:'修正乙'},{block_id:'block-2',action:'unreadable'}])
 expect(posts[1].key).toBeTruthy();expect(screen.getByRole('link',{name:'下载核对预览 JSON'})).toBeTruthy()
 await waitFor(()=>expect((screen.getByRole('button',{name:'确认生成核对版本'}) as HTMLButtonElement).disabled).toBe(false))
 await user.click(screen.getByRole('button',{name:'确认生成核对版本'}))
 await screen.findByText('核对版本已生成，内容只读。')
 expect(posts[2].body).toMatchObject({operation:'approve',wait_id:'saved-wait',checkpoint_id:'saved-checkpoint',expected_task_revision:5})
 expect(posts[2].body).not.toHaveProperty('edits')
 expect(screen.queryByRole('radio')).toBeNull()
 await user.click(await screen.findByRole('button',{name:'查看核对版本 v1'}))
 const history=within(screen.getByRole('region',{name:'核对历史版本'}))
 await history.findByText('修正乙');expect(history.getByRole('link',{name:'下载核对版本 JSON'})).toBeTruthy()
 expect(screen.queryByText('block-0')).toBeNull()
})
test('restores saved progress and protects unsaved edits from rereads; parent changes reset the draft',async()=>{
 const user=userEvent.setup();const {setSaved}=mockApi(true);setSaved()
 const view=render(<OcrReview projectId="p" fileId="f" filename="scan.pdf" parent={parent as never} onUnavailable={()=>{}} />)
 await user.click(await screen.findByRole('button',{name:'继续人工核对'}))
 const blocks=await screen.findAllByRole('group',{name:/文字核对/})
 expect((within(blocks[0]).getByRole('radio',{name:'确认原文'}) as HTMLInputElement).checked).toBe(true)
 await user.click(within(blocks[1]).getByRole('radio',{name:'修改文字'}));await user.type(within(blocks[1]).getByRole('textbox',{name:'核对文字'}),'本地草稿')
 await user.click(screen.getByRole('button',{name:'刷新核对状态'}))
 await waitFor(()=>expect((within(blocks[1]).getByRole('textbox',{name:'核对文字'}) as HTMLTextAreaElement).value).toContain('本地草稿'))
 await user.click(screen.getByRole('button',{name:'下一张核对页'}));await screen.findByText('此页未识别到文字，请核对原图。')
 await user.click(screen.getByRole('button',{name:'上一张核对页'}));expect((await screen.findByRole('textbox',{name:'核对文字'}) as HTMLTextAreaElement).value).toContain('本地草稿')
 view.rerender(<OcrReview projectId="p" fileId="f" filename="scan.pdf" parent={{...parent,id:'another'} as never} onUnavailable={()=>{}} />)
 expect(screen.queryByRole('textbox',{name:'核对文字'})).toBeNull()
})
test('session invalidation removes image and editing state and blocks further requests',async()=>{
 const {fetch}=mockApi(true)
 render(<OcrReviewWorkspace projectId="p" fileId="f" parseId="ocr" taskId="review-task" filename="scan.pdf" onUnavailable={()=>{}} />)
 await screen.findAllByRole('group',{name:/文字核对/})
 clearApiSession();await screen.findByText('会话已失效，请重新登录。')
 const count=fetch.mock.calls.length;expect(screen.queryByRole('radio')).toBeNull();expect(screen.queryByRole('img')).toBeNull()
 await new Promise(resolve=>setTimeout(resolve,30));expect(fetch.mock.calls.length).toBe(count)
})
test('task center opens the specific review form and translates controls without altering source text',async()=>{
 mockApi(true);setLocale('en')
 render(<TaskDetail projectId="p" taskId="review-task" onChanged={()=>{}} />)
 await screen.findAllByRole('group',{name:/Text review/})
 expect(screen.getByText('原文甲')).toBeTruthy();expect(screen.getByRole('button',{name:'Save review progress'})).toBeTruthy()
 expect(screen.queryByText('Analysis configuration v0')).toBeNull()
})

test.each(['zh-CN','en'] as const)('task center describes OCR plan events and publication in %s',async locale=>{
 const {fetch}=mockApi(true);const normal=fetch.getMockImplementation()!;setLocale(locale)
 fetch.mockImplementation((url,init)=>url.includes('/events')?Promise.resolve(Response.json({task_id:'review-task',items:[
  {seq:1,task_revision:1,event_type:'created',status:'queued',phase:'plan',reason_code:null,created_at:'2026-10-12'},
  {seq:2,task_revision:2,event_type:'waiting',status:'waiting_confirmation',phase:'plan',reason_code:null,created_at:'2026-10-12'},
  {seq:3,task_revision:3,event_type:'phase_changed',status:'running',phase:'verify',reason_code:null,created_at:'2026-10-12'},
 ],next_cursor:3,has_more:false})):normal(url,init))
 render(<TaskDetail projectId="p" taskId="review-task" onChanged={()=>{}} />)
 const history=await screen.findByRole('region',{name:locale==='en'?'Execution history':'执行记录'})
 expect(await within(history).findAllByText(locale==='en'?'Text review':'文字核对')).toHaveLength(2)
 expect(within(history).queryByText(locale==='en'?'Analysis plan':'分析计划')).toBeNull()
 expect(within(history).getByText(locale==='en'?'Generate review version':'生成核对版本')).toBeTruthy()
})
test('partial saves survive reopening and remain unpublishable until every block is explicitly handled',async()=>{
 const user=userEvent.setup();mockApi(true)
 const props={projectId:'p',fileId:'f',parseId:'ocr',taskId:'review-task',filename:'scan.pdf',onUnavailable:()=>{}}
 const view=render(<OcrReviewWorkspace {...props}/>)
 const blocks=await screen.findAllByRole('group',{name:/文字核对/})
 await user.click(within(blocks[0]).getByRole('radio',{name:'确认原文'}))
 await user.click(screen.getByRole('button',{name:'保存核对进度'}));await screen.findByText('进度已保存。')
 expect((screen.getByRole('button',{name:'确认生成核对版本'}) as HTMLButtonElement).disabled).toBe(true)
 view.unmount();render(<OcrReviewWorkspace {...props}/>)
 const restored=await screen.findAllByRole('group',{name:/文字核对/})
 expect((within(restored[0]).getByRole('radio',{name:'确认原文'}) as HTMLInputElement).checked).toBe(true)
 expect(screen.getByText('未核对 2 / 3 条')).toBeTruthy()
 await user.click(within(restored[0]).getByRole('button',{name:'恢复为未核对'}));expect(screen.getByText('未核对 3 / 3 条')).toBeTruthy()
})
test('blank replacement blocks saving and unreadable does not submit the OCR guess',async()=>{
 const user=userEvent.setup();const {posts}=mockApi(true)
 render(<OcrReviewWorkspace projectId="p" fileId="f" parseId="ocr" taskId="review-task" filename="scan.pdf" onUnavailable={()=>{}}/>)
 const block=(await screen.findAllByRole('group',{name:/文字核对/}))[0]
 await user.click(within(block).getByRole('radio',{name:'修改文字'}));await user.clear(within(block).getByRole('textbox',{name:'核对文字'}))
 expect((screen.getByRole('button',{name:'保存核对进度'}) as HTMLButtonElement).disabled).toBe(true)
 expect(screen.getByRole('alert').textContent).toContain('请填写非空修正文字或选择无法辨认')
 await user.click(within(block).getByRole('radio',{name:'无法辨认'}));await user.click(screen.getByRole('button',{name:'保存核对进度'}));await screen.findByText('进度已保存。')
 expect(posts[0].body.edits).toEqual([{block_id:'block-0',action:'unreadable'}])
})
test('conflicts keep the local draft and require explicitly reloading saved progress',async()=>{
 const user=userEvent.setup();const {failNextDecision,setSaved}=mockApi(true)
 render(<OcrReviewWorkspace projectId="p" fileId="f" parseId="ocr" taskId="review-task" filename="scan.pdf" onUnavailable={()=>{}}/>)
 const block=(await screen.findAllByRole('group',{name:/文字核对/}))[1]
 await user.click(within(block).getByRole('radio',{name:'修改文字'}));await user.type(within(block).getByRole('textbox',{name:'核对文字'}),'本地保留')
 setSaved();failNextDecision(409)
 await user.click(screen.getByRole('button',{name:'保存核对进度'}))
 await screen.findByText('核对状态已变化，请重新读取已保存进度后核对。')
 expect((screen.getByRole('textbox',{name:'核对文字'}) as HTMLTextAreaElement).value).toContain('本地保留')
 expect((screen.getByRole('button',{name:'保存核对进度'}) as HTMLButtonElement).disabled).toBe(true)
 await user.click(screen.getByRole('button',{name:'重新读取已保存进度'}))
 await waitFor(()=>expect(screen.queryByRole('textbox',{name:'核对文字'})).toBeNull())
 expect((screen.getAllByRole('radio',{name:'确认原文'})[0] as HTMLInputElement).checked).toBe(true)
})
test('an unconfirmed save retries with the same frozen body and idempotency key',async()=>{
 const user=userEvent.setup();const {failNextDecision,posts}=mockApi(true)
 render(<OcrReviewWorkspace projectId="p" fileId="f" parseId="ocr" taskId="review-task" filename="scan.pdf" onUnavailable={()=>{}}/>)
 const block=(await screen.findAllByRole('group',{name:/文字核对/}))[0]
 await user.click(within(block).getByRole('radio',{name:'确认原文'}));failNextDecision(500)
 await user.click(screen.getByRole('button',{name:'保存核对进度'}));await screen.findByText('核对提交未确认，请刷新状态后重试。')
 await user.click(screen.getByRole('button',{name:'保存核对进度'}));await screen.findByText('进度已保存。')
 expect(posts[1]).toEqual(posts[0])
})
test('failed review stays reachable from the file and retries the same task through existing resume API',async()=>{
 const user=userEvent.setup();const {failTask,setSaved,posts}=mockApi(true);setSaved();failTask()
 render(<OcrReview projectId="p" fileId="f" filename="scan.pdf" parent={parent as never} onUnavailable={()=>{}}/>)
 await user.click(await screen.findByRole('button',{name:'继续人工核对'}))
 await user.click(await screen.findByRole('button',{name:'重试原任务'}))
 await waitFor(()=>expect((screen.getByRole('button',{name:'保存核对进度'}) as HTMLButtonElement).disabled).toBe(false))
 expect(posts[0].url).toBe('/api/v1/tasks/review-task/resume')
 expect(posts[0].body).toMatchObject({operation:'retry',wait_id:null,expected_task_revision:3,input_version:input})
 expect(posts[0].body).not.toHaveProperty('edits')
 expect(screen.getByText('未核对 2 / 3 条')).toBeTruthy()
})
test('a concurrent start conflict refreshes discovery and offers the existing review instead of another creation',async()=>{
 const user=userEvent.setup();const {failNextCreate,posts}=mockApi();failNextCreate()
 render(<OcrReview projectId="p" fileId="f" filename="scan.pdf" parent={parent as never} onUnavailable={()=>{}}/>)
 await user.click(await screen.findByRole('button',{name:'开始人工核对'}))
 await user.click(await screen.findByRole('button',{name:'继续人工核对'}))
 await screen.findAllByRole('group',{name:/文字核对/})
 expect(posts).toHaveLength(1)
})
test('opening the current history version again retains the loaded read-only details',async()=>{
 const user=userEvent.setup();const {setPublished}=mockApi();setPublished()
 render(<OcrReviewHistory projectId="p" fileId="f" parseId="ocr" filename="scan.pdf" refreshKey={0} onUnavailable={()=>{}}/>)
 const open=await screen.findByRole('button',{name:'查看核对版本 v1'})
 await user.click(open);await screen.findByText('核对版本 v1 · 只读');await screen.findByRole('button',{name:'原文甲'})
 await user.click(open)
 expect(screen.getByText('核对版本 v1 · 只读')).toBeTruthy();expect(screen.getByRole('button',{name:'原文甲'})).toBeTruthy()
})
test('opening the same history version retries a failed detail request',async()=>{
 const user=userEvent.setup();const {setPublished,failNextHistory}=mockApi();setPublished();failNextHistory()
 render(<OcrReviewHistory projectId="p" fileId="f" parseId="ocr" filename="scan.pdf" refreshKey={0} onUnavailable={()=>{}}/>)
 const open=await screen.findByRole('button',{name:'查看核对版本 v1'})
 await user.click(open);await screen.findByRole('alert');await user.click(open)
 await screen.findByText('核对版本 v1 · 只读');await screen.findByRole('button',{name:'原文甲'})
})
test.each(['parent','page'] as const)('failed %s reads recover through the document retry control',async path=>{
 const user=userEvent.setup();const {failNextDocument}=mockApi(true);failNextDocument(path)
 render(<OcrReviewWorkspace projectId="p" fileId="f" parseId="ocr" taskId="review-task" filename="scan.pdf" onUnavailable={()=>{}}/>)
 await screen.findByRole('alert')
 await user.click(screen.getByRole('button',{name:'重新读取核对原图和文字'}))
 await screen.findAllByRole('group',{name:/文字核对/})
 expect(screen.queryByRole('alert')).toBeNull()
})
test('refreshing the workspace retries source content and retains local edits after a failed reread',async()=>{
 const user=userEvent.setup();const {fetch,failNextDocument}=mockApi(true)
 const unavailable=()=>{}
 render(<OcrReviewWorkspace projectId="p" fileId="f" parseId="ocr" taskId="review-task" filename="scan.pdf" onUnavailable={unavailable}/>)
 const block=(await screen.findAllByRole('group',{name:/文字核对/}))[1]
 await user.click(within(block).getByRole('radio',{name:'修改文字'}));await user.type(within(block).getByRole('textbox',{name:'核对文字'}),' 保留本地草稿')
 const reads=()=>fetch.mock.calls.filter(([url])=>url.endsWith('/document-versions/ocr')).length
 const before=reads();failNextDocument('page')
 await user.click(screen.getByRole('button',{name:'刷新核对状态'}))
 await waitFor(()=>expect(reads()).toBeGreaterThan(before));await screen.findByRole('alert')
 await user.click(screen.getByRole('button',{name:'重新读取核对原图和文字'}))
 const editor=await screen.findByRole('textbox',{name:'核对文字'}) as HTMLTextAreaElement
 expect(editor.value).toBe('原文乙 保留本地草稿')
 expect((screen.getByRole('button',{name:'确认生成核对版本'}) as HTMLButtonElement).disabled).toBe(true)
})

test('returning to OCR preview keeps the current unsaved review task and edits',async()=>{
 const user=userEvent.setup();const {posts}=mockApi(true)
 render(<OcrReview projectId="p" fileId="f" filename="scan.pdf" parent={parent as never} onUnavailable={()=>{}}><p>识别预览内容</p></OcrReview>)
 await user.click(await screen.findByRole('button',{name:'继续人工核对'}))
 const blocks=await screen.findAllByRole('group',{name:/文字核对/})
 await user.click(within(blocks[0]).getByRole('radio',{name:'确认原文'}))
 await user.click(screen.getByRole('button',{name:'返回识别预览'}))
 expect(screen.getByText('识别预览内容')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'保存核对进度'})).toBeNull()
 await user.click(screen.getByRole('button',{name:'继续人工核对'}))
 expect((within((await screen.findAllByRole('group',{name:/文字核对/}))[0]).getByRole('radio',{name:'确认原文'}) as HTMLInputElement).checked).toBe(true)
 expect(posts).toHaveLength(0)
})

test('switching parsed versions preserves unsaved OCR review edits for the original version',async()=>{
 const {default:DocumentVersions}=await import('./DocumentVersions')
 const {fetch,posts}=mockApi(true);const original=fetch.getMockImplementation()!
 const other={...parent,id:'other',kind:'docx_document',version:3,selected_pages:undefined,blocks_url:'blocks',summary:{counts:{paragraphs:0,tables:0,cells:0,images:0},warnings:[]}}
 fetch.mockImplementation(async(url:string,init?:RequestInit)=>{
  if(url.includes('/document-versions?page='))return Response.json({items:[parent,other],total:2,page:1,page_size:5,latest_version:3})
  if(url.endsWith('/document-versions/other'))return Response.json(other)
  if(url.includes('/other/blocks?'))return Response.json({items:[],total:0,page:1,page_size:20})
  return original(url,init)
 })
 const user=userEvent.setup()
 render(<DocumentVersions projectId="p" fileId="f" filename="scan.pdf" fileType="pdf" active onUnavailable={()=>{}} />)
 await user.click(await screen.findByRole('button',{name:'PDF 版本 v2 · 已完成'}))
 await user.click(await screen.findByRole('button',{name:'继续人工核对'}))
 const blocks=await screen.findAllByRole('group',{name:/文字核对/})
 await user.click(within(blocks[0]).getByRole('radio',{name:'确认原文'}))
 await user.click(screen.getByRole('button',{name:'PDF 版本 v3 · 已完成'}))
 await waitFor(()=>expect(screen.getByRole('button',{name:'PDF 版本 v2 · 已完成'}).hasAttribute('disabled')).toBe(false))
 expect(screen.queryByRole('button',{name:'保存核对进度'})).toBeNull()
 await user.click(screen.getByRole('button',{name:'PDF 版本 v2 · 已完成'}))
 expect((within((await screen.findAllByRole('group',{name:/文字核对/}))[0]).getByRole('radio',{name:'确认原文'}) as HTMLInputElement).checked).toBe(true)
 expect(posts).toHaveLength(0)
})
