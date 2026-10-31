import {afterEach,expect,it,vi} from 'vitest'
import {apiFetch} from '../../shared/api/client'
import {insightRequest} from './api'
import {STANDARD_REQUEST_TIMEOUT_MS,RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn()}))
afterEach(()=>vi.useRealTimers())
it.each([false,true])('accepts a 20-second slow response with bounded standard/fullsource=%s',async full=>{vi.useFakeTimers();vi.mocked(apiFetch).mockImplementation(()=>new Promise(resolve=>setTimeout(()=>resolve(Response.json({ok:true})),20000)));const p=insightRequest('/api',undefined,full);await vi.advanceTimersByTimeAsync(20000);await expect(p).resolves.toEqual({ok:true})})
it.each([[false,STANDARD_REQUEST_TIMEOUT_MS],[true,RESEARCH_REQUEST_TIMEOUT_MS]] as const)('aborts precisely at the final bounded deadline (%s)',async(full,deadline)=>{vi.useFakeTimers();let signal:AbortSignal|undefined;vi.mocked(apiFetch).mockImplementation((_url,init)=>{signal=init?.signal as AbortSignal;return new Promise(()=>{})});const p=insightRequest('/api',undefined,full);const failure=expect(p).rejects.toThrow();await vi.advanceTimersByTimeAsync(deadline-1);expect(signal?.aborted).toBe(false);await vi.advanceTimersByTimeAsync(1);expect(signal?.aborted).toBe(true);await failure;expect(apiFetch).toHaveBeenCalled()})
