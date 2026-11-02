import {afterEach,beforeEach,it,expect,vi} from 'vitest'
import {listPdfExports,type PdfScope} from './pdfApi'
import {setApiSession,clearApiSession} from '../../shared/api/client'
import {STANDARD_REQUEST_TIMEOUT_MS,RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
beforeEach(()=>{setApiSession('csrf','owner');sessionStorage.clear();vi.useFakeTimers()});afterEach(()=>{vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();clearApiSession()})
it.each(['report','research_report'] as const)('historic PDF list uses the exact %s scope deadline',async sourceKind=>{
 const scope:PdfScope={projectId:'p1',sourceId:'docx',sourceKind},fetch=vi.fn((_url:string,_init?:RequestInit)=>new Promise<Response>(()=>{}));vi.stubGlobal('fetch',fetch);const controller=new AbortController(),pending=listPdfExports(scope,controller).catch(error=>error),deadline=sourceKind==='research_report'?RESEARCH_REQUEST_TIMEOUT_MS:STANDARD_REQUEST_TIMEOUT_MS;await vi.advanceTimersByTimeAsync(deadline-1);expect(controller.signal.aborted).toBe(false);await vi.advanceTimersByTimeAsync(1);expect(controller.signal.aborted).toBe(true);expect(await pending).toBeInstanceOf(Error);expect(fetch).toHaveBeenCalledTimes(1)
})
