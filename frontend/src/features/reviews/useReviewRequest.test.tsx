import {act,cleanup,renderHook} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {useReviewRequest} from './useReviewRequest'
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals()})
const valid=(v:unknown):v is {ok:boolean}=>!!v&&typeof v==='object'&&'ok'in v
it('allows refreshing after an individual timeout without ending the whole editor session',async()=>{
 vi.useFakeTimers();let calls=0;vi.stubGlobal('fetch',vi.fn(()=>++calls===1?new Promise(()=>{}):Promise.resolve(Response.json({ok:true}))));const {result}=renderHook(useReviewRequest)
 const pending=result.current.request('/api/v1/projects/p1/reviews/revisions/r1',valid).catch(e=>e)
 await act(async()=>{await vi.advanceTimersByTimeAsync(15001)});expect(await pending).toBeInstanceOf(Error)
 await expect(result.current.request('/api/v1/projects/p1/reviews/revisions/r1',valid)).resolves.toEqual({ok:true})
})
it('aborts a stale panel read while retaining the editor session',async()=>{
 let received:AbortSignal|undefined,finish:(response:Response)=>void=()=>{};vi.stubGlobal('fetch',vi.fn((_url:string,init?:RequestInit)=>{received=init?.signal as AbortSignal;return new Promise<Response>(resolve=>{finish=resolve})}));const {result}=renderHook(useReviewRequest),controller=new AbortController()
 const pending=(result.current.request as unknown as (url:string,validator:typeof valid,body:undefined,signal:AbortSignal)=>Promise<unknown>)('/api/v1/projects/p1/reviews/progress',valid,undefined,controller.signal).catch(e=>e);controller.abort();const wasAborted=received?.aborted;finish(Response.json({ok:true}));await pending;expect(wasAborted).toBe(true);expect(result.current.available).toBe(true)
})
