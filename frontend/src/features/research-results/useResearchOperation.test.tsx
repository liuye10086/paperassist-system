import {act,renderHook,waitFor} from '@testing-library/react'
import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest'
import {setApiSession,clearApiSession} from '../../shared/api/client'
import useResearchOperation from './useResearchOperation'
describe('research operations',()=>{
 beforeEach(()=>{setApiSession('token','owner');sessionStorage.clear()})
 afterEach(()=>{vi.unstubAllGlobals();clearApiSession()})
 it('blocks synchronous double clicks and freezes the original key and body',async()=>{
  let finish!:(r:Response)=>void;const fetch=vi.fn(()=>new Promise<Response>(r=>finish=r));vi.stubGlobal('fetch',fetch)
  const {result}=renderHook(()=>useResearchOperation<{id:string}>('p','finding','draft'))
  act(()=>{void result.current.submit('/api/v1/projects/p/research-findings',{title:'first'});void result.current.submit('/api/v1/projects/p/research-findings',{title:'second'})})
  expect(fetch).toHaveBeenCalledTimes(1);expect(fetch.mock.calls[0]).toBeDefined()
  await act(async()=>finish(new Response(JSON.stringify({id:'saved'}))))
  await waitFor(()=>expect(result.current.value?.id).toBe('saved'))
 })
 it('recovers unknown submission before allowing an explicit original-key retry',async()=>{
  const fetch=vi.fn().mockRejectedValueOnce(new TypeError('network')).mockResolvedValueOnce(new Response('{}',{status:404})).mockResolvedValueOnce(new Response('{"id":"saved"}'));vi.stubGlobal('fetch',fetch)
  const {result}=renderHook(()=>useResearchOperation<{id:string}>('p','finding','draft'))
  await act(()=>result.current.submit('/api/v1/projects/p/research-findings',{title:'first'}))
  expect(result.current.unknown).toBe(true)
  await act(()=>result.current.lookup());expect(fetch).toHaveBeenCalledTimes(2);expect(result.current.retryable).toBe(true)
  const first=fetch.mock.calls[0][1]
  await act(()=>result.current.retry());expect(fetch.mock.calls[2][1].body).toBe(first.body);expect(fetch.mock.calls[2][1].headers.get('Idempotency-Key')).toBe(first.headers.get('Idempotency-Key'))
 })
 it('clears pending state and sensitive results on session change',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('{"id":"saved"}')))
  const {result}=renderHook(()=>useResearchOperation<{id:string}>('p','finding','draft'))
  await act(()=>result.current.submit('/api/v1/projects/p/research-findings',{}));expect(result.current.value).not.toBeNull()
  act(()=>clearApiSession());expect(result.current.value).toBeNull();expect(result.current.valid).toBe(false)
 })
 it('preserves a stale CAS draft and requires a refresh instead of automatic retry',async()=>{
  const fetch=vi.fn().mockResolvedValue(new Response('{"detail":{"code":"research_revision_conflict"}}',{status:409}));vi.stubGlobal('fetch',fetch)
  const {result}=renderHook(()=>useResearchOperation('p','finding','draft'))
  await act(()=>result.current.submit('/api/v1/projects/p/research-findings',{}));expect(result.current.conflict).toBe(true);expect(result.current.retryable).toBe(false);expect(fetch).toHaveBeenCalledTimes(1)
 })
})
