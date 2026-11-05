import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptExports from './ManuscriptExports'
import {exportFixture,manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
import {setApiSession} from '../../shared/api/client'
import {taskFixture} from '../tasks/taskFixtures'
const base='/api/v1/projects/p1/manuscripts/m1/versions/1/exports'
const props={projectId:'p1',manuscriptId:'m1',version:{...manuscriptFixture.versions[0],exports:[]} as unknown as ManuscriptVersion}
afterEach(()=>{cleanup();sessionStorage.clear();vi.useRealTimers();vi.unstubAllGlobals()})
it('keeps successful Word exports without PDF history or requests',async()=>{
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.includes('/pdf-exports'))return init?.method==='POST'?Response.json({detail:{code:'pdf_conversion_failed'}},{status:503}):Response.json({items:[]})
  return Response.json({items:[exportFixture]})
 });vi.stubGlobal('fetch',fetcher);render(<ManuscriptExports {...props}/>);await screen.findByRole('link',{name:'下载 DOCX'})
 expect(screen.queryByRole('button',{name:'生成 PDF'})).toBeNull();expect(screen.getByRole('link',{name:'下载 DOCX'})).toBeTruthy()
 expect(screen.getByRole('button',{name:'排版与公式'})).toBeTruthy();expect(fetcher.mock.calls.some(([url])=>url.includes('/layout-exports'))).toBe(false)
 expect(fetcher.mock.calls.some(([,i])=>i?.method==='POST')).toBe(false)
 expect(fetcher.mock.calls.some(([url])=>url.includes('/pdf-exports'))).toBe(false);expect(screen.queryByRole('region',{name:/PDF/})).toBeNull()
})
it('restores queued exports by GET and polls their status without resubmitting',async()=>{
 vi.useFakeTimers();let ready=false
 const fetcher=vi.fn(async(_url:string,_init?:RequestInit)=>Response.json({items:[{...exportFixture,status:ready?'succeeded':'queued',download_url:ready?exportFixture.download_url:null,filename:ready?'draft.docx':null,size_bytes:ready?100:null}]}))
 vi.stubGlobal('fetch',fetcher);render(<ManuscriptExports {...props}/>);await act(async()=>{})
 expect(screen.getByRole('status').textContent).toBe('待执行');ready=true
 await act(async()=>vi.advanceTimersByTime(3000));expect(screen.getByRole('link',{name:'下载 DOCX'})).toBeTruthy()
 expect(fetcher.mock.calls.every(([,init])=>!init?.method)).toBe(true)
})
it('keeps publication success independent from DOCX failure and retries a failed export through bounded recovery',async()=>{
 let recovered=false
 const input={kind:'manuscript',manuscript_version_id:'v1',output_language:'en',workflow_version:'manuscript_fact_draft_v1'}
 const task={...taskFixture,id:'export-task',task_type:'manuscript_docx',status:'failed',display_status:'failed',phase:'export',input_version:input,error_code:'task_failed',reason_code:null}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/workspace'))return Response.json({task,source:{file_id:null,filename:'Draft',analysis_run_id:null,is_current:true},wait:null,allowed_actions:['retry'],artifacts:{figure:null,explanation:null,report:null}})
  if(init?.method==='POST'){recovered=true;return Response.json({...task,status:'queued',display_status:'queued',revision:4})}
  return Response.json({items:[{...exportFixture,status:recovered?'queued':'failed',download_url:null}]})
 });vi.stubGlobal('fetch',fetcher);render(<ManuscriptExports {...props}/> )
 fireEvent.click(await screen.findByRole('button',{name:'重试 DOCX'}))
 await screen.findByText('待执行')
 const posts=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(posts).toHaveLength(1)
 expect(posts[0][0]).toBe('/api/v1/tasks/export-task/resume')
 expect(JSON.parse(String(posts[0][1]?.body))).toEqual({operation:'retry',wait_id:null,expected_task_revision:3,input_version:input})
})
it('rejects exports for a different frozen manuscript version',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{...exportFixture,version_id:'v2'}]})))
 render(<ManuscriptExports {...props}/>);await screen.findByRole('alert');expect(screen.queryByRole('link',{name:'下载 DOCX'})).toBeNull();expect(screen.queryByRole('button',{name:'生成 PDF'})).toBeNull()
})
it('uses one request key for duplicate clicks and explicit retry after an uncertain POST',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{
  if(init?.method==='POST')throw new TypeError('network')
  return Response.json({items:[]})
 });vi.stubGlobal('fetch',fetcher);render(<ManuscriptExports {...props}/>)
 fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}));fireEvent.click(screen.getByRole('button',{name:'正在提交……'}))
 await screen.findByRole('alert');fireEvent.click(screen.getByRole('button',{name:'用原请求重试 Word'}))
 await waitFor(()=>expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(2))
 const calls=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(calls[0][0]).toBe(base)
 expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'))
})

it('retains a lost export response across reload and replays only the original request explicitly',async()=>{
 let posts=0
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){posts++;if(posts===1)throw Error('response lost');return Response.json(exportFixture)}
  return Response.json({items:posts>1?[exportFixture]:[]})
 });vi.stubGlobal('fetch',fetcher)
 const first=render(<ManuscriptExports {...props}/>);fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}))
 await screen.findByRole('alert');first.unmount();render(<ManuscriptExports {...props}/>)
 await screen.findByText('Word 提交结果待核对，原请求和固定输入已保留。')
 expect((screen.getByRole('button',{name:'生成 DOCX'}) as HTMLButtonElement).disabled).toBe(true)
 expect(screen.queryByText('当前版本尚未生成 Word。')).toBeNull();expect(posts).toBe(1)
 fireEvent.click(screen.getByRole('button',{name:'刷新 DOCX 状态'}));await waitFor(()=>expect(fetcher.mock.calls.filter(([,i])=>!i?.method).length).toBeGreaterThan(1));expect(posts).toBe(1)
 fireEvent.click(screen.getByRole('button',{name:'用原请求重试 Word'}));await screen.findByRole('link',{name:'下载 DOCX'})
 const writes=fetcher.mock.calls.filter(([,init])=>init?.method==='POST')
 expect(writes).toHaveLength(2);expect(writes[0][0]).toBe(writes[1][0]);expect(writes[0][1]?.body).toBe(writes[1][1]?.body)
 expect(new Headers(writes[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(writes[1][1]?.headers).get('Idempotency-Key'))
})

it.each([408,409])('keeps an uncertain or conflicting %s export fixed after reload',async(status)=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>init?.method==='POST'?Response.json({detail:{code:'task_idempotency_conflict'}},{status}):Response.json({items:[]}));vi.stubGlobal('fetch',fetcher)
 const first=render(<ManuscriptExports {...props}/>);fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}));await screen.findByRole('alert')
 first.unmount();render(<ManuscriptExports {...props}/>);await screen.findByText('Word 提交结果待核对，原请求和固定输入已保留。')
 expect((screen.getByRole('button',{name:'生成 DOCX'}) as HTMLButtonElement).disabled).toBe(true)
 expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(1)
})
it('releases a stale resume intent after the same task advances and fails again',async()=>{
 let posts=0
 const input={kind:'manuscript',manuscript_version_id:'v1',output_language:'en',workflow_version:'manuscript_fact_draft_v1'}
 const task={...taskFixture,id:'export-task',task_type:'manuscript_docx',status:'failed',display_status:'failed',phase:'export',input_version:input,error_code:'task_failed',reason_code:null}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/workspace'))return Response.json({task:{...task,revision:posts?4:3},source:{file_id:null,filename:'Draft',analysis_run_id:null,is_current:true},wait:null,allowed_actions:['retry'],artifacts:{figure:null,explanation:null,report:null}})
  if(init?.method==='POST'){posts++;if(posts===1)throw Error('accepted then failed, response lost');return Response.json({...task,status:'queued',display_status:'queued',revision:5})}
  return Response.json({items:[{...exportFixture,status:posts>1?'queued':'failed',download_url:null}]})
 });vi.stubGlobal('fetch',fetcher)
 const first=render(<ManuscriptExports {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'重试 DOCX'}));await screen.findByText('Word 提交结果待核对，原请求和固定输入已保留。');first.unmount()
 render(<ManuscriptExports {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'用原请求重试 Word'}))
 await waitFor(()=>expect(screen.queryByText('Word 提交结果待核对，原请求和固定输入已保留。')).toBeNull());expect(posts).toBe(1)
 fireEvent.click(await screen.findByRole('button',{name:'重试 DOCX'}));await waitFor(()=>expect(posts).toBe(2))
 const writes=fetcher.mock.calls.filter(([,i])=>i?.method==='POST')
 expect(JSON.parse(String(writes[0][1]?.body)).expected_task_revision).toBe(3)
 expect(JSON.parse(String(writes[1][1]?.body)).expected_task_revision).toBe(4)
 expect(new Headers(writes[0][1]?.headers).get('Idempotency-Key')).not.toBe(new Headers(writes[1][1]?.headers).get('Idempotency-Key'))
})
it('clears saved downloads and aborts requests when the authenticated session changes',async()=>{
 const fetcher=vi.fn(async()=>Response.json({items:[exportFixture]}));vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptExports {...props}/>);await screen.findByRole('link',{name:'下载 DOCX'})
 act(()=>setApiSession('another-session'));expect(screen.queryByRole('link',{name:'下载 DOCX'})).toBeNull()
 expect(screen.getByRole('alert').textContent).toContain('会话已失效')
})

it('shows successful Word before manual generation and identifies an empty fixed version',async()=>{
 const fetcher=vi.fn(async(_url:string,_init?:RequestInit)=>Response.json({items:[exportFixture]}));vi.stubGlobal('fetch',fetcher);const view=render(<ManuscriptExports {...props}/>)
 const download=await screen.findByRole('link',{name:'下载 DOCX'});const generate=screen.getByRole('button',{name:'生成 DOCX'});expect(download.compareDocumentPosition(generate)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();expect(screen.getByText('事实稿 Word · 版本 1')).toBeTruthy();expect(fetcher.mock.calls.every(([,init])=>!init?.method)).toBe(true)
 view.unmount();fetcher.mockImplementation(async()=>Response.json({items:[]}));render(<ManuscriptExports {...props}/>);expect(await screen.findByText('当前版本尚未生成 Word。')).toBeTruthy()
})

it.each(['queued','running','failed'] as const)('does not call a %s export absent',async status=>{
 const item={...exportFixture,status,download_url:null,filename:null,size_bytes:null};vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[item]})))
 render(<ManuscriptExports {...props}/>);await screen.findByText(({queued:'待执行',running:'运行中',failed:'执行失败'} as const)[status])
 expect(screen.queryByText('当前版本尚未生成 Word。')).toBeNull();expect(screen.queryByRole('link',{name:'下载 DOCX'})).toBeNull()
 if(status==='queued'||status==='running')expect(screen.getByText('Word 正在生成，请等待任务完成。')).toBeTruthy()
})

it('does not claim Word is absent on a failed read or invalid succeeded record',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{...exportFixture,download_url:null}]})))
 render(<ManuscriptExports {...props}/>);await screen.findByRole('alert');expect(screen.queryByText('当前版本尚未生成 Word。')).toBeNull();expect(screen.queryByRole('link',{name:'下载 DOCX'})).toBeNull()
})
it('removes the empty-state claim when the session becomes invalid',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})));render(<ManuscriptExports {...props}/>);await screen.findByText('当前版本尚未生成 Word。')
 act(()=>setApiSession('new-session'));expect(screen.queryByText('当前版本尚未生成 Word。')).toBeNull()
})
