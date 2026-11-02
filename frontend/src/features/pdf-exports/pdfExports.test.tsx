import {act,cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import PdfExportHistory from './PdfExportHistory'
import {validPdfExport} from './pdfApi'
import {setApiSession} from '../../shared/api/client'
import {setLocale} from '../../shared/i18n'
import {STANDARD_REQUEST_TIMEOUT_MS,RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
const hash='a'.repeat(64)
const props={projectId:'p1',sourceKind:'report' as const,sourceId:'report1',sourceSha256:hash,sourceLabel:'分析配置 v2'}
const base='/api/v1/projects/p1/pdf-exports'
const row={id:'pdf1',project_id:'p1',source_kind:'report',source_id:'report1',status:'queued',task_id:'pdf-task',created_at:'2026-10-20T00:00:00Z',filename:null,error_code:null,source_sha256:hash,parent_export_id:null,renderer_manifest:null,sha256:null,size_bytes:null,download_url:null}
beforeEach(()=>{sessionStorage.clear();setApiSession('pdf-test-session')})
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals();setLocale('zh-CN');sessionStorage.clear()})
it.each(['report','research_report'] as const)('bounds PDF download using its known %s source scope',async sourceKind=>{
 let signal!:AbortSignal
 const saved={...row,source_kind:sourceKind,status:'succeeded',filename:'fixed.pdf',sha256:'b'.repeat(64),size_bytes:100,renderer_manifest:{id:'renderer'},download_url:`${base}/pdf1/download`}
 vi.stubGlobal('fetch',vi.fn((url:string,init?:RequestInit)=>url.endsWith('/download')?(signal=init!.signal as AbortSignal,new Promise<Response>(()=>{})):Promise.resolve(Response.json({items:[saved]}))))
 render(<PdfExportHistory {...props} sourceKind={sourceKind}/>);const link=await screen.findByRole('link',{name:'下载 PDF'});vi.useFakeTimers();fireEvent.click(link);const deadline=sourceKind==='research_report'?RESEARCH_REQUEST_TIMEOUT_MS:STANDARD_REQUEST_TIMEOUT_MS;await act(()=>vi.advanceTimersByTimeAsync(deadline-1));expect(signal.aborted).toBe(false);await act(()=>vi.advanceTimersByTimeAsync(1));expect(signal.aborted).toBe(true);expect(screen.getByRole('alert').textContent).toContain('超时')
})
it('validates exact project, DOCX identity, hash and PDF download path',()=>{
 const done={...row,status:'succeeded',filename:'saved.pdf',sha256:'b'.repeat(64),size_bytes:100,renderer_manifest:{id:'renderer'},download_url:`${base}/pdf1/download`}
 expect(validPdfExport(done,props)).toBe(true)
 for(const changed of [{project_id:'p2'},{source_id:'other'},{source_kind:'collection_report'},{source_sha256:'b'.repeat(64)},{download_url:'https://evil.test/file'},{download_url:`${base}/pdf1/../pdf2/download`},{download_url:`${base}/pdf2/download`},{sha256:null}])expect(validPdfExport({...done,...changed},props)).toBe(false)
})
it('stops polling while inactive and rejects late cross-source results',async()=>{
 vi.useFakeTimers();const fetcher=vi.fn(async()=>Response.json({items:[row]}));vi.stubGlobal('fetch',fetcher)
 const view=render(<PdfExportHistory {...props}/>);await act(async()=>{});view.rerender(<PdfExportHistory {...props} active={false}/>);const count=fetcher.mock.calls.length
 await act(async()=>vi.advanceTimersByTime(9000));expect(fetcher).toHaveBeenCalledTimes(count)
 view.rerender(<PdfExportHistory {...props} sourceId="other"/>);await act(async()=>{});expect(screen.getByRole('alert')).toBeTruthy();expect(screen.queryByText('待执行')).toBeNull()
})
it('pauses history polling in closed or hidden workspace sections and resumes on reopen',async()=>{
 vi.useFakeTimers();const fetcher=vi.fn(async()=>Response.json({items:[row]}));vi.stubGlobal('fetch',fetcher)
 const view=render(<details><summary>Saved version</summary><PdfExportHistory {...props}/></details>);await act(async()=>{});expect(fetcher).not.toHaveBeenCalled()
 view.rerender(<details open><summary>Saved version</summary><PdfExportHistory {...props}/></details>);await act(async()=>{});expect(fetcher).toHaveBeenCalledTimes(1)
 view.rerender(<details open hidden><summary>Saved version</summary><PdfExportHistory {...props}/></details>);await act(async()=>{});await act(async()=>vi.advanceTimersByTime(9000));expect(fetcher).toHaveBeenCalledTimes(1)
 view.rerender(<details open><summary>Saved version</summary><PdfExportHistory {...props}/></details>);await act(async()=>{});expect(fetcher).toHaveBeenCalledTimes(2)
})

it('retains history without PDF generation, confirmation or retry actions',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{...row,status:'failed',error_code:'pdf_conversion_timeout'}]})));render(<PdfExportHistory {...props}/>);await screen.findByText('执行失败');
 expect(screen.queryAllByRole('button',{name:/生成 PDF|新建 PDF|重试 PDF|确认上次 PDF|恢复原导出/})).toHaveLength(0);
})

it('clears historical files and disables refresh after authentication changes',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{...row,status:'failed',error_code:'pdf_input_invalid'}]})));render(<PdfExportHistory {...props}/>);await screen.findByText('执行失败');act(()=>setApiSession('new'));expect(screen.queryByText('执行失败')).toBeNull();expect(screen.getByRole('button',{name:'刷新 PDF 状态'}).hasAttribute('disabled')).toBe(true)
})
