import {afterEach,beforeEach,it,expect,vi} from 'vitest'
import {listPdfExports,submitPdfExport,hasUnconfirmedPdfRequest,type PdfScope} from './pdfApi'
import {setApiSession,clearApiSession} from '../../shared/api/client'
import {STANDARD_REQUEST_TIMEOUT_MS,RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
beforeEach(()=>{setApiSession('csrf','owner');sessionStorage.clear();vi.useFakeTimers()});afterEach(()=>{vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();clearApiSession()})
for(const method of ['list','submit'] as const)it.each(['report','research_report'] as const)(`${method} PDF uses the exact %s scope deadline`,async sourceKind=>{
 const scope:PdfScope={projectId:'p1',sourceId:'docx',sourceKind},fetch=vi.fn((_url:string,_init?:RequestInit)=>new Promise<Response>(()=>{}));vi.stubGlobal('fetch',fetch);const controller=new AbortController(),pending=(method==='list'?listPdfExports(scope,controller):submitPdfExport(scope,controller)).catch(error=>error),deadline=sourceKind==='research_report'?RESEARCH_REQUEST_TIMEOUT_MS:STANDARD_REQUEST_TIMEOUT_MS;await vi.advanceTimersByTimeAsync(deadline-1);expect(controller.signal.aborted).toBe(false);await vi.advanceTimersByTimeAsync(1);expect(controller.signal.aborted).toBe(true);expect(await pending).toBeInstanceOf(Error);expect(fetch).toHaveBeenCalledTimes(1);if(method==='submit')expect(hasUnconfirmedPdfRequest(scope)).toBe(true)
})

it('cancels observation immediately after the old research bound while retaining the original PDF request key',async()=>{
 const scope:PdfScope={projectId:'p1',sourceId:'docx',sourceKind:'research_report'},controller=new AbortController()
 const fetch=vi.fn((_url:string,init?:RequestInit)=>new Promise<Response>((_resolve,reject)=>{init?.signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true})}));vi.stubGlobal('fetch',fetch)
 const request=submitPdfExport(scope,controller).catch(error=>error),body=fetch.mock.calls[0][1]?.body,retained=JSON.stringify(sessionStorage)
 await vi.advanceTimersByTimeAsync(1200001);expect(controller.signal.aborted).toBe(false);expect(hasUnconfirmedPdfRequest(scope)).toBe(true);expect(fetch).toHaveBeenCalledTimes(1)
 const before=Date.now();controller.abort();expect(controller.signal.aborted).toBe(true);expect(await request).toMatchObject({name:'AbortError'});expect(Date.now()).toBe(before)
 expect(hasUnconfirmedPdfRequest(scope)).toBe(true);expect(JSON.stringify(sessionStorage)).toBe(retained);expect(fetch.mock.calls[0][1]?.body).toBe(body);expect(JSON.parse(String(body)).request_key).toBeTruthy()
 await vi.advanceTimersByTimeAsync(RESEARCH_REQUEST_TIMEOUT_MS);expect(fetch).toHaveBeenCalledTimes(1);expect(JSON.stringify(sessionStorage)).toBe(retained)
})
