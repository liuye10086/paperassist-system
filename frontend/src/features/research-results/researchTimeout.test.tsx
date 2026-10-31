import {STANDARD_REQUEST_TIMEOUT_MS,RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import {act,cleanup,renderHook} from '@testing-library/react'
import {afterEach,beforeEach,it,expect,vi} from 'vitest'
import {researchRequest,useResearchRead} from './api'
import {intakeRequest} from '../research-intake/api'
import {setApiSession,clearApiSession} from '../../shared/api/client'
beforeEach(()=>{setApiSession('csrf','owner');vi.useFakeTimers()})
afterEach(()=>{cleanup();vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();clearApiSession()})
function slowFetch(delay:number){const fetch=vi.fn((_url:string,init?:RequestInit)=>new Promise<Response>((resolve,reject)=>{const timer=window.setTimeout(()=>resolve(Response.json({id:'fixed'})),delay);init?.signal?.addEventListener('abort',()=>{window.clearTimeout(timer);reject(new DOMException('Aborted','AbortError'))},{once:true})}));vi.stubGlobal('fetch',fetch);return fetch}
it('allows a research source verification response after twenty seconds',async()=>{
 const fetch=slowFetch(20000);const request=researchRequest<{id:string}>('/api/v1/projects/p1/research-reports').then(value=>({value,error:null}),error=>({value:null,error}))
 await vi.advanceTimersByTimeAsync(20000);expect(await request).toEqual({value:{id:'fixed'},error:null});expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(false)
})
it('keeps hook loading while fixed-source verification is slow and accepts its late result',async()=>{
 slowFetch(20000);const{result}=renderHook(()=>useResearchRead<{id:string}>('/api/v1/projects/p1/research-figures',true));await act(()=>vi.advanceTimersByTimeAsync(16000));expect(result.current.loading).toBe(true);expect(result.current.error).toBe('');await act(()=>vi.advanceTimersByTimeAsync(4000));expect(result.current.data?.id).toBe('fixed')
})
it('aborts research requests at the bounded one-hundred-twenty-minute limit',async()=>{
 const fetch=slowFetch(RESEARCH_REQUEST_TIMEOUT_MS+100000),request=researchRequest('/api/v1/projects/p1/research-reports').catch(error=>error);await vi.advanceTimersByTimeAsync(RESEARCH_REQUEST_TIMEOUT_MS-1);expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(false);await vi.advanceTimersByTimeAsync(1);expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);expect(await request).toBeInstanceOf(Error)
})
it('cancels slow reads on unmount and session changes',async()=>{
 const fetch=slowFetch(20000);const first=renderHook(()=>useResearchRead('/api/v1/projects/p1/research-reports',true));first.unmount();expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);const second=renderHook(()=>useResearchRead('/api/v1/projects/p1/research-figures',true));act(()=>clearApiSession());expect(fetch.mock.calls[1][1]?.signal?.aborted).toBe(true);expect(second.result.current.valid).toBe(false)
})
it('uses the user-approved sixty-minute intake default',async()=>{
 const fetch=slowFetch(STANDARD_REQUEST_TIMEOUT_MS+100000),request=intakeRequest('/api/v1/projects/p1/research-intake').catch(error=>error);await vi.advanceTimersByTimeAsync(STANDARD_REQUEST_TIMEOUT_MS);expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);expect(await request).toBeInstanceOf(Error)
})
