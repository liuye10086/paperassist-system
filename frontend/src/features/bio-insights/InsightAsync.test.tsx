import {act,renderHook,waitFor} from '@testing-library/react'
import {beforeEach,expect,it,vi} from 'vitest'
import {apiFetch} from '../../shared/api/client'
import {useInsightIntent} from './hooks'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',onApiSessionChanged:()=>()=>{}}))
beforeEach(()=>{sessionStorage.clear();vi.mocked(apiFetch).mockReset()})
it('blocks double submit and recovers unknown via GET before explicit original identity retry',async()=>{
 vi.mocked(apiFetch).mockRejectedValueOnce(new TypeError('offline')).mockResolvedValueOnce(Response.json({detail:{code:'bio_insight_not_found'}},{status:404})).mockResolvedValueOnce(Response.json({id:'saved'}))
 const {result}=renderHook(()=>useInsightIntent<{id:string}>('p1','plan','new'))
 await act(async()=>{await Promise.all([result.current.submit('/api/v1/projects/p1/bio-insight-plans',{name:'A'}),result.current.submit('/api/v1/projects/p1/bio-insight-plans',{name:'B'})])})
 expect(apiFetch).toHaveBeenCalledTimes(1);expect(result.current.unknown).toBe(true)
 await act(()=>result.current.lookup());expect(String(vi.mocked(apiFetch).mock.calls[1][0])).toContain('bio-insight-requests/');expect(result.current.retryable).toBe(true)
 await act(()=>result.current.retry());const first=vi.mocked(apiFetch).mock.calls[0][1]!,last=vi.mocked(apiFetch).mock.calls[2][1]!;expect(last.body).toBe(first.body);expect(last.headers).toEqual(first.headers);expect(result.current.value).toEqual({id:'saved'})
})
it('retains unknown intent across remount, isolated from another project, and cancel never resubmits',async()=>{
 vi.mocked(apiFetch).mockImplementation((_url,init)=>new Promise((_resolve,reject)=>init?.signal?.addEventListener('abort',()=>reject(new DOMException('cancel','AbortError')))))
 const a=renderHook(()=>useInsightIntent('p1','run','v1'));act(()=>{void a.result.current.submit('/api/v1/projects/p1/bio-insight-runs',{plan:'v1'})});await waitFor(()=>expect(apiFetch).toHaveBeenCalledTimes(1));act(()=>a.result.current.cancel());await waitFor(()=>expect(a.result.current.unknown).toBe(true));a.unmount()
 const b=renderHook(()=>useInsightIntent('p2','run','v1'));expect(b.result.current.unknown).toBe(false);b.unmount();const restored=renderHook(()=>useInsightIntent('p1','run','v1'));await waitFor(()=>expect(restored.result.current.unknown).toBe(true));expect(apiFetch).toHaveBeenCalledTimes(1)
})
