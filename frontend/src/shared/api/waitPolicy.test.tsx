import {STANDARD_REQUEST_TIMEOUT_MS,RESEARCH_REQUEST_TIMEOUT_MS} from './requestTimeouts'
import {act,cleanup,render,screen} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {taskRequest} from '../../features/tasks/taskApi'
import {intakeRequest} from '../../features/research-intake/api'
import {researchRequest} from '../../features/research-results/api'
import AuthBoundary from '../../features/auth/AuthBoundary'
import {clearApiSession,setApiSession} from './client'
beforeEach(()=>{setApiSession('csrf','owner');vi.useFakeTimers()})
afterEach(()=>{cleanup();vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();clearApiSession()})
type Result={id:string}
const valid=(v:unknown):v is Result=>!!v&&typeof v==='object'&&'id'in v&&v.id==='fixed'
function responseAfter(ms:number,body:unknown={id:'fixed'}){const fetch=vi.fn((_url:string,init?:RequestInit)=>new Promise<Response>((resolve,reject)=>{const timer=window.setTimeout(()=>resolve(Response.json(body)),ms);init?.signal?.addEventListener('abort',()=>{window.clearTimeout(timer);reject(new DOMException('Aborted','AbortError'))},{once:true})}));vi.stubGlobal('fetch',fetch);return fetch}
it('uses the approved sixty- and one-hundred-twenty-minute bounded defaults',()=>{expect(STANDARD_REQUEST_TIMEOUT_MS).toBe(3600000);expect(RESEARCH_REQUEST_TIMEOUT_MS).toBe(7200000)})
it.each(['task','intake'])('accepts a twenty-second %s response under the ordinary waiting policy',async kind=>{
 responseAfter(20000);const p=(kind==='task'?taskRequest('/api/v1/projects/p/tasks',new AbortController(),valid,'Read failed'):intakeRequest<Result>('/api/v1/projects/p/research-intake')).then(value=>({value,error:null}),error=>({value:null,error}));await vi.advanceTimersByTimeAsync(20000);expect(await p).toEqual({value:{id:'fixed'},error:null})
})
it.each(['task','intake','research'])('aborts %s only at its final bounded deadline',async kind=>{
 const deadline=kind==='research'?RESEARCH_REQUEST_TIMEOUT_MS:STANDARD_REQUEST_TIMEOUT_MS,fetch=responseAfter(deadline+1000),controller=new AbortController();const p=(kind==='task'?taskRequest('/api/v1/projects/p/tasks',controller,valid,'Read failed'):kind==='intake'?intakeRequest('/api/v1/projects/p/research-intake'):researchRequest('/api/v1/projects/p/research-reports')).catch(error=>error);await vi.advanceTimersByTimeAsync(deadline-1);expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(false);await vi.advanceTimersByTimeAsync(1);expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);expect(await p).toBeInstanceOf(Error)
})
it('keeps restore visibly waiting after twenty seconds and accepts the confirmed session',async()=>{
 responseAfter(20000,{user:{id:'slow-user',email:'slow@example.test',role:'user'},csrf_token:'confirmed'});render(<AuthBoundary><p>Confirmed workspace</p></AuthBoundary>);expect(screen.getByText('连接较慢时可能需要数分钟，请保持页面打开。')).toBeDefined();await act(()=>vi.advanceTimersByTimeAsync(16000));expect(screen.queryByRole('alert')).toBeNull();expect(screen.queryByText('Confirmed workspace')).toBeNull();await act(()=>vi.advanceTimersByTimeAsync(4000));expect(screen.getByText('Confirmed workspace')).toBeDefined()
})

it.each(['task','intake','research'])('keeps the original %s request waiting past the former bound and accepts its late result',async kind=>{
 const former=kind==='research'?1200000:600000,fetch=responseAfter(former+1000);let settled=false
 const request=(kind==='task'?taskRequest('/api/v1/projects/p/tasks',new AbortController(),valid,'Read failed'):kind==='intake'?intakeRequest<Result>('/api/v1/projects/p/research-intake'):researchRequest<Result>('/api/v1/projects/p/research-reports')).then(value=>({value,error:null}),error=>({value:null,error})).finally(()=>{settled=true})
 await vi.advanceTimersByTimeAsync(former+1);expect(settled).toBe(false);expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(false);expect(fetch).toHaveBeenCalledTimes(1)
 await vi.advanceTimersByTimeAsync(999);expect(await request).toEqual({value:{id:'fixed'},error:null});expect(fetch).toHaveBeenCalledTimes(1)
})
