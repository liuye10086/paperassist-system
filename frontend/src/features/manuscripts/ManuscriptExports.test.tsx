import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptExports from './ManuscriptExports'
import {exportFixture,manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
import {setApiSession} from '../../shared/api/client'
import {taskFixture} from '../tasks/taskFixtures'
const base='/api/v1/projects/p1/manuscripts/m1/versions/1/exports'
const props={projectId:'p1',manuscriptId:'m1',version:{...manuscriptFixture.versions[0],exports:[]} as unknown as ManuscriptVersion}
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals()})
it('offers PDF only for a successful concrete DOCX export and keeps DOCX after independent PDF failure',async()=>{
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.includes('/pdf-exports'))return init?.method==='POST'?Response.json({detail:{code:'pdf_conversion_failed'}},{status:503}):Response.json({items:[]})
  return Response.json({items:[exportFixture],pdf_status:'not_requested'})
 });vi.stubGlobal('fetch',fetcher);render(<ManuscriptExports {...props}/>);await screen.findByRole('link',{name:'下载 DOCX'})
 const button=await screen.findByRole('button',{name:'生成 PDF'});await waitFor(()=>expect(button.hasAttribute('disabled')).toBe(false));fireEvent.click(button);await screen.findByRole('alert');expect(screen.getByRole('link',{name:'下载 DOCX'})).toBeTruthy()
 expect(screen.getByRole('button',{name:'排版与公式'})).toBeTruthy();expect(fetcher.mock.calls.some(([url])=>url.includes('/layout-exports'))).toBe(false);
 const post=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(JSON.parse(String(post[1]?.body))).toMatchObject({source_kind:'manuscript_export',source_id:'export1'});expect(screen.getByText(/稿件 v1/)).toBeTruthy()
})
it('restores queued exports by GET and polls their status without resubmitting',async()=>{
 vi.useFakeTimers();let ready=false
 const fetcher=vi.fn(async(_url:string,_init?:RequestInit)=>Response.json({items:[{...exportFixture,status:ready?'succeeded':'queued',download_url:ready?exportFixture.download_url:null,filename:ready?'draft.docx':null,size_bytes:ready?100:null}],pdf_status:'not_requested'}))
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
  return Response.json({items:[{...exportFixture,status:recovered?'queued':'failed',download_url:null}],pdf_status:'not_requested'})
 });vi.stubGlobal('fetch',fetcher);render(<ManuscriptExports {...props}/> )
 fireEvent.click(await screen.findByRole('button',{name:'重试 DOCX'}))
 await screen.findByText('待执行')
 const posts=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(posts).toHaveLength(1)
 expect(posts[0][0]).toBe('/api/v1/tasks/export-task/resume')
 expect(JSON.parse(String(posts[0][1]?.body))).toEqual({operation:'retry',wait_id:null,expected_task_revision:3,input_version:input})
})
it('rejects exports for a different frozen manuscript version',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{...exportFixture,version_id:'v2'}],pdf_status:'not_requested'})))
 render(<ManuscriptExports {...props}/>);await screen.findByRole('alert');expect(screen.queryByRole('link',{name:'下载 DOCX'})).toBeNull();expect(screen.queryByRole('button',{name:'生成 PDF'})).toBeNull()
})
it('uses one request key for duplicate clicks and explicit retry after an uncertain POST',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{
  if(init?.method==='POST')throw new TypeError('network')
  return Response.json({items:[],pdf_status:'not_requested'})
 });vi.stubGlobal('fetch',fetcher);render(<ManuscriptExports {...props}/>)
 fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}));fireEvent.click(screen.getByRole('button',{name:'正在提交……'}))
 await screen.findByRole('alert');fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}))
 await waitFor(()=>expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(2))
 const calls=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(calls[0][0]).toBe(base)
 expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'))
})
it('clears saved downloads and aborts requests when the authenticated session changes',async()=>{
 const fetcher=vi.fn(async()=>Response.json({items:[exportFixture],pdf_status:'not_requested'}));vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptExports {...props}/>);await screen.findByRole('link',{name:'下载 DOCX'})
 act(()=>setApiSession('another-session'));expect(screen.queryByRole('link',{name:'下载 DOCX'})).toBeNull()
 expect(screen.getByRole('alert').textContent).toContain('会话已失效')
})
