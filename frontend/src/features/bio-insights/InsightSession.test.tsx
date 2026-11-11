import {act,cleanup,renderHook,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
const {events,session}=vi.hoisted(()=>({events:new Set<()=>void>(),session:{owner:null as string|null}}))
vi.mock('../../shared/api/client',()=>({getApiUserId:()=>session.owner,apiFetch:vi.fn(),onApiSessionChanged:(fn:()=>void)=>{events.add(fn);return()=>events.delete(fn)}}))
import {apiFetch} from '../../shared/api/client'
import {useInsightDraft,useInsightIntent} from './hooks'
afterEach(()=>{cleanup();sessionStorage.clear()})
it('restores the signed-in owner draft and queries its pending request without resubmission',async()=>{
  const draftKey='paperassist.bio-insight.draft:owner:p1:plan:v1'
  const otherDraftKey='paperassist.bio-insight.draft:other-owner:p1:plan:v1'
  sessionStorage.setItem(draftKey,JSON.stringify({name:'frozen local plan draft'}))
  sessionStorage.setItem(otherDraftKey,JSON.stringify({name:'another account'}))
  sessionStorage.setItem('paperassist.bio-insight.request:owner:p1:plan:v1',JSON.stringify({
    key:'prior-request',url:'/api/v1/projects/p1/bio-insight-plans',body:{name:'frozen local plan draft'},
  }))
  session.owner='owner'
  for(const listener of events)listener()
  expect(sessionStorage.getItem(otherDraftKey)).toBeNull()
  vi.mocked(apiFetch).mockClear().mockResolvedValue(Response.json({id:'saved-fixed-version'}))
  const {result}=renderHook(()=>({draft:useInsightDraft('p1','plan:v1',()=>({name:''}))[0],request:useInsightIntent('p1','plan','v1')}))
  expect(result.current.draft.name).toBe('frozen local plan draft')
  await waitFor(()=>expect(result.current.request.unknown).toBe(true))
  expect(apiFetch).not.toHaveBeenCalled()
  await act(async()=>result.current.request.lookup())
  expect(vi.mocked(apiFetch).mock.calls[0][0]).toBe('/api/v1/projects/p1/bio-insight-requests/prior-request?kind=plan')
  expect(vi.mocked(apiFetch).mock.calls[0][1]?.method).toBeUndefined()
  expect(result.current.request.value).toEqual({id:'saved-fixed-version'})
})
it('aborts session changes, removes stored identity and ignores even a late fulfilled write',async()=>{let finish!:(r:Response)=>void;let signal:AbortSignal|undefined;vi.mocked(apiFetch).mockImplementation((_url,init)=>{signal=init?.signal as AbortSignal;return new Promise<Response>(r=>finish=r)});const{result}=renderHook(()=>useInsightIntent('p1','plan','v1'));act(()=>{void result.current.submit('/api/v1/projects/p1/bio-insight-plans',{name:'private draft'})});await waitFor(()=>expect(result.current.busy).toBe(true));act(()=>{for(const fn of events)fn()});expect(signal?.aborted).toBe(true);expect(result.current.valid).toBe(false);expect(Object.keys(sessionStorage).filter(k=>k.startsWith('paperassist.bio-insight.'))).toEqual([]);await act(async()=>finish(Response.json({id:'old-secret'})));expect(result.current.value).toBeNull()})
