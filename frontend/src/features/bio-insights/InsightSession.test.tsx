import {act,cleanup,renderHook,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
const events=vi.hoisted(()=>new Set<()=>void>())
vi.mock('../../shared/api/client',()=>({getApiUserId:()=> 'owner',apiFetch:vi.fn(),onApiSessionChanged:(fn:()=>void)=>{events.add(fn);return()=>events.delete(fn)}}))
import {apiFetch} from '../../shared/api/client'
import {useInsightIntent} from './hooks'
afterEach(()=>{cleanup();sessionStorage.clear()})
it('aborts session changes, removes stored identity and ignores even a late fulfilled write',async()=>{let finish!:(r:Response)=>void;let signal:AbortSignal|undefined;vi.mocked(apiFetch).mockImplementation((_url,init)=>{signal=init?.signal as AbortSignal;return new Promise<Response>(r=>finish=r)});const{result}=renderHook(()=>useInsightIntent('p1','plan','v1'));act(()=>{void result.current.submit('/api/v1/projects/p1/bio-insight-plans',{name:'private draft'})});await waitFor(()=>expect(result.current.busy).toBe(true));act(()=>{for(const fn of events)fn()});expect(signal?.aborted).toBe(true);expect(result.current.valid).toBe(false);expect(Object.keys(sessionStorage).filter(k=>k.startsWith('paperassist.bio-insight.'))).toEqual([]);await act(async()=>finish(Response.json({id:'old-secret'})));expect(result.current.value).toBeNull()})
