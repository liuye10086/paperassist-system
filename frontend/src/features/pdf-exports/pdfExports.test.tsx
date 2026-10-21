import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import PdfExports from './PdfExports'
import {canRetryPdf,validPdfExport,type PdfExport} from './pdfApi'
import {setApiSession} from '../../shared/api/client'
import {setLocale} from '../../shared/i18n'
const hash='a'.repeat(64)
const props={projectId:'p1',sourceKind:'report' as const,sourceId:'report1',sourceSha256:hash,sourceLabel:'分析配置 v2'}
const base='/api/v1/projects/p1/pdf-exports'
const row={id:'pdf1',project_id:'p1',source_kind:'report',source_id:'report1',status:'queued',task_id:'pdf-task',created_at:'2026-10-20T00:00:00Z',filename:null,error_code:null,source_sha256:hash,parent_export_id:null,renderer_manifest:null,sha256:null,size_bytes:null,download_url:null}
beforeEach(()=>{sessionStorage.clear();setApiSession('pdf-test-session')})
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals();setLocale('zh-CN');sessionStorage.clear()})
it.each(['succeeded','failed'])('confirms a lost accepted POST using its original key before offering a new export after GET reads %s',async status=>{
 const terminal={...row,status,...(status==='succeeded'?{filename:'saved.pdf',sha256:'b'.repeat(64),size_bytes:100,renderer_manifest:{id:'renderer'},download_url:`${base}/pdf1/download`}:{error_code:'pdf_conversion_timeout'})}
 let accepted=false;const submittedKeys:string[]=[]
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){
   submittedKeys.push(JSON.parse(String(init.body)).request_key)
   if(submittedKeys.length===1){accepted=true;throw new TypeError('response lost after acceptance')}
   return Response.json(submittedKeys.length===2?terminal:{...terminal,id:'pdf2',task_id:'pdf-task2',download_url:status==='succeeded'?`${base}/pdf2/download`:null})
  }
  return Response.json({items:accepted?submittedKeys.length>=3?[terminal,{...terminal,id:'pdf2',task_id:'pdf-task2',download_url:status==='succeeded'?`${base}/pdf2/download`:null}]:[terminal]:[]})
 });vi.stubGlobal('fetch',fetcher)
 const first=render(<PdfExports {...props}/>);const generate=screen.getByRole('button',{name:'生成 PDF'});await waitFor(()=>expect(generate.hasAttribute('disabled')).toBe(false));fireEvent.click(generate);await screen.findByRole('alert');await screen.findByText(status==='succeeded'?'已完成':'执行失败')
 expect(screen.queryByRole('button',{name:'新建 PDF 导出'})).toBeNull();expect(screen.getByRole('button',{name:'确认上次 PDF 请求'})).toBeTruthy();first.unmount()
 render(<PdfExports {...props}/>);const confirm=screen.getByRole('button',{name:'确认上次 PDF 请求'});await waitFor(()=>expect(confirm.hasAttribute('disabled')).toBe(false));fireEvent.click(confirm)
 const create=await screen.findByRole('button',{name:'新建 PDF 导出'});await waitFor(()=>expect(create.hasAttribute('disabled')).toBe(false));expect(submittedKeys).toHaveLength(2);expect(submittedKeys[1]).toBe(submittedKeys[0]);fireEvent.click(create)
 await waitFor(()=>expect(submittedKeys).toHaveLength(3));expect(submittedKeys[2]).not.toBe(submittedKeys[0]);await screen.findByText('PDF 导出 2')
})
it('validates exact project, DOCX identity, hash and PDF download path',()=>{
 const done={...row,status:'succeeded',filename:'saved.pdf',sha256:'b'.repeat(64),size_bytes:100,renderer_manifest:{id:'renderer'},download_url:`${base}/pdf1/download`}
 expect(validPdfExport(done,props)).toBe(true)
 for(const changed of [{project_id:'p2'},{source_id:'other'},{source_kind:'collection_report'},{source_sha256:'b'.repeat(64)},{download_url:'https://evil.test/file'},{download_url:`${base}/pdf1/../pdf2/download`},{download_url:`${base}/pdf2/download`},{sha256:null}])expect(validPdfExport({...done,...changed},props)).toBe(false)
})
it('submits only the saved DOCX ID and polls without more POSTs',async()=>{
 vi.useFakeTimers();let requested=false,done=false
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){requested=true;return Response.json(row)}
  return Response.json({items:requested?[{...row,status:done?'succeeded':'running',...(done?{filename:'saved.pdf',sha256:'b'.repeat(64),size_bytes:100,renderer_manifest:{id:'renderer'},download_url:`${base}/pdf1/download`}:{})}]:[]})
 });vi.stubGlobal('fetch',fetcher);render(<PdfExports {...props}/>);await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'生成 PDF'}));await act(async()=>{});expect(screen.getByText('运行中')).toBeTruthy()
 done=true;await act(async()=>vi.advanceTimersByTime(3000));expect(screen.getByRole('link',{name:'下载 PDF'})).toBeTruthy()
 const posts=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(posts).toHaveLength(1);expect(JSON.parse(String(posts[0][1]?.body))).toMatchObject({source_kind:'report',source_id:'report1'})
 const count=fetcher.mock.calls.length;await act(async()=>vi.advanceTimersByTime(9000));expect(fetcher).toHaveBeenCalledTimes(count)
 expect(screen.getByText(/分析配置 v2/)).toBeTruthy()
})
it('retains failed history and retries using the PDF endpoint into a new child task',async()=>{
 const failed={...row,status:'failed',error_code:'pdf_conversion_timeout'}
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{...row,id:'pdf2',task_id:'task2',parent_export_id:'pdf1'}:{items:[failed]}));vi.stubGlobal('fetch',fetcher)
 render(<PdfExports {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'重试 PDF'}));await screen.findByText('待执行')
 expect(screen.getByText('执行失败')).toBeTruthy();const post=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(post[0]).toBe(`${base}/pdf1/retry`);expect(Object.keys(JSON.parse(String(post[1]?.body)))).toEqual(['request_key'])
})
it('allows at most three child retries and blocks nonretryable, branched or incomplete history',()=>{
 const chain=Array.from({length:4},(_,i)=>({...row,id:`pdf${i}`,status:'failed',error_code:'pdf_conversion_failed',parent_export_id:i?`pdf${i-1}`:null})) as PdfExport[]
 expect(canRetryPdf(chain[3],chain)).toBe(false);expect(canRetryPdf(chain[2],chain.slice(0,3))).toBe(true);expect(canRetryPdf(chain[0],chain)).toBe(false)
 expect(canRetryPdf({...chain[0],error_code:'pdf_input_invalid'},[chain[0]])).toBe(false);expect(canRetryPdf(chain[2],[chain[2]])).toBe(false)
})
it('translates public conversion errors in English without exposing server exceptions',async()=>{
 setLocale('en');vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{...row,status:'failed',error_code:'pdf_conversion_timeout',message:'secret /server/path'}]})))
 render(<PdfExports {...props} sourceLabel="Analysis v2"/>);await screen.findByRole('button',{name:'Retry PDF'});expect(document.body.textContent).toContain('PDF conversion timed out.');expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]|secret|server\/path/)
})
it('preserves an uncertain request key across refresh and remount',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{if(init?.method==='POST')throw new TypeError('network');return Response.json({items:[]})});vi.stubGlobal('fetch',fetcher)
 const view=render(<PdfExports {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'生成 PDF'}));await screen.findByRole('alert');view.unmount()
 render(<PdfExports {...props}/>);const button=await screen.findByRole('button',{name:'确认上次 PDF 请求'});await waitFor(()=>expect(button.hasAttribute('disabled')).toBe(false));fireEvent.click(button)
 await waitFor(()=>expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(2));const posts=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(JSON.parse(String(posts[0][1]?.body)).request_key).toBe(JSON.parse(String(posts[1][1]?.body)).request_key)
})
it('retains an uncertain request key when the app restores authentication after reload',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{if(init?.method==='POST')throw new TypeError('network');return Response.json({items:[]})});vi.stubGlobal('fetch',fetcher)
 const first=render(<PdfExports {...props}/>);const button=screen.getByRole('button',{name:'生成 PDF'});await waitFor(()=>expect(button.hasAttribute('disabled')).toBe(false));fireEvent.click(button);await screen.findByRole('alert');first.unmount()
 act(()=>setApiSession('restored-session'))
 render(<PdfExports {...props}/>);const again=screen.getByRole('button',{name:'确认上次 PDF 请求'});await waitFor(()=>expect(again.hasAttribute('disabled')).toBe(false));fireEvent.click(again)
 await waitFor(()=>expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(2));const posts=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(JSON.parse(String(posts[0][1]?.body)).request_key).toBe(JSON.parse(String(posts[1][1]?.body)).request_key)
})
it('creates a fresh export of the same DOCX with a new key after each confirmed operation',async()=>{
 const rows:unknown[]=[{...row,status:'failed',error_code:'pdf_renderer_mismatch'}];let serial=1
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){const id=`pdf${++serial}`;const saved={...row,id,status:'succeeded',filename:'saved.pdf',sha256:'b'.repeat(64),size_bytes:100,renderer_manifest:{id:'renderer'},download_url:`${base}/${id}/download`};rows.unshift(saved);return Response.json(saved)}
  return Response.json({items:rows})
 });vi.stubGlobal('fetch',fetcher);render(<PdfExports {...props}/>);const button=await screen.findByRole('button',{name:'新建 PDF 导出'});fireEvent.click(button);await screen.findByRole('link',{name:'下载 PDF'})
 await waitFor(()=>expect(button.hasAttribute('disabled')).toBe(false));fireEvent.click(button);await waitFor(()=>expect(screen.getAllByRole('link',{name:'下载 PDF'})).toHaveLength(2))
 const posts=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(posts).toHaveLength(2);expect(JSON.parse(String(posts[0][1]?.body)).request_key).not.toBe(JSON.parse(String(posts[1][1]?.body)).request_key);expect(screen.getByText('执行失败')).toBeTruthy()
})
it('stops polling while inactive and rejects late cross-source results',async()=>{
 vi.useFakeTimers();const fetcher=vi.fn(async()=>Response.json({items:[row]}));vi.stubGlobal('fetch',fetcher)
 const view=render(<PdfExports {...props}/>);await act(async()=>{});view.rerender(<PdfExports {...props} active={false}/>);const count=fetcher.mock.calls.length
 await act(async()=>vi.advanceTimersByTime(9000));expect(fetcher).toHaveBeenCalledTimes(count)
 view.rerender(<PdfExports {...props} sourceId="other"/>);await act(async()=>{});expect(screen.getByRole('alert')).toBeTruthy();expect(screen.queryByText('待执行')).toBeNull()
})
it('clears history and disables submission after a session change',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{...row,status:'failed',error_code:'pdf_input_invalid'}]})));render(<PdfExports {...props}/>);await screen.findByText('执行失败')
 act(()=>setApiSession('new'));expect(screen.queryByText('执行失败')).toBeNull();expect(screen.getByRole('button',{name:'生成 PDF'}).hasAttribute('disabled')).toBe(true)
})
it('pauses history polling in closed or hidden workspace sections and resumes on reopen',async()=>{
 vi.useFakeTimers();const fetcher=vi.fn(async()=>Response.json({items:[row]}));vi.stubGlobal('fetch',fetcher)
 const view=render(<details><summary>Saved version</summary><PdfExports {...props}/></details>);await act(async()=>{});expect(fetcher).not.toHaveBeenCalled()
 view.rerender(<details open><summary>Saved version</summary><PdfExports {...props}/></details>);await act(async()=>{});expect(fetcher).toHaveBeenCalledTimes(1)
 view.rerender(<details open hidden><summary>Saved version</summary><PdfExports {...props}/></details>);await act(async()=>{});await act(async()=>vi.advanceTimersByTime(9000));expect(fetcher).toHaveBeenCalledTimes(1)
 view.rerender(<details open><summary>Saved version</summary><PdfExports {...props}/></details>);await act(async()=>{});expect(fetcher).toHaveBeenCalledTimes(2)
})
