import {act,cleanup,renderHook,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import useDeliveryOperation from './useDeliveryOperation'
import {clearApiSession} from '../../shared/api/client'
const base='/api/v1/projects/p1/deliveries/d1'
afterEach(()=>{cleanup();sessionStorage.clear();vi.unstubAllGlobals()})
it('requires an original-key lookup before retrying a lost freeze and retains its exact body after remount',async()=>{
 let posts=0
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{if(init?.method==='POST'){posts++;if(posts===1)throw Error('lost');return Response.json({id:'saved'})}return Response.json({detail:{code:'research_source_not_found'}},{status:404})});vi.stubGlobal('fetch',fetcher)
 const first=renderHook(()=>useDeliveryOperation<{id:string}>('p1','d1','freeze')),body={stage:'final',members:[{kind:'file',file_id:'f1'}]}
 await act(()=>first.result.current.submit('freeze',base+'/snapshots',body,base+'/snapshots/requests/{key}'));expect(first.result.current.unknown).toBe(true)
 await act(()=>first.result.current.retry());expect(posts).toBe(1);first.unmount()
 const restored=renderHook(()=>useDeliveryOperation<{id:string}>('p1','d1','freeze'));await waitFor(()=>expect(restored.result.current.unknown).toBe(true));await act(()=>restored.result.current.lookup());expect(posts).toBe(1)
 await act(()=>restored.result.current.retry());expect(posts).toBe(2)
 const calls=fetcher.mock.calls.filter(([,init])=>init?.method==='POST');expect(calls[1][1]?.body).toBe(calls[0][1]?.body);expect(JSON.parse(String(calls[1][1]?.body))).toEqual(body);expect(new Headers(calls[1][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[0][1]?.headers).get('Idempotency-Key'))
})
it('recovers the existing package task after an unknown response without creating another task',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{if(init?.method==='POST')throw Error('lost');return Response.json({task_id:'t1',task:{id:'t1'},progress:{stage:'writing_package'}})});vi.stubGlobal('fetch',fetcher)
 const h=renderHook(()=>useDeliveryOperation<{task_id:string}>('p1','d1','package:s1'));await act(()=>h.result.current.submit('package',base+'/snapshots/s1/package',{},base+'/snapshots/s1/package'));await act(()=>h.result.current.lookup());expect(h.result.current.value?.task_id).toBe('t1');expect(h.result.current.unknown).toBe(false);expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(1)
})
it('does not treat old identical acceptance text as this request receipt and replays only its original key',async()=>{
 let posts=0;const body={snapshot_sha256:'a'.repeat(64),scope:'Engineering only',kind:'accept',comment:'checked'}
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{if(init?.method==='POST'){if(++posts===1)throw Error('lost');return Response.json({id:'event1',...body})}return Response.json({items:[{id:'old-identical',...body}]})});vi.stubGlobal('fetch',fetcher)
 const h=renderHook(()=>useDeliveryOperation<{id:string}>('p1','d1','acceptance:s1'));await act(()=>h.result.current.submit('acceptance',base+'/snapshots/s1/acceptances',body,base+'/snapshots/s1/acceptances'));await act(()=>h.result.current.lookup());expect(h.result.current.unknown).toBe(true);expect(h.result.current.value).toBeNull();expect(posts).toBe(1)
 await act(()=>h.result.current.retry());expect(h.result.current.value?.id).toBe('event1');const calls=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(calls[1][1]?.body).toBe(calls[0][1]?.body);expect(new Headers(calls[1][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[0][1]?.headers).get('Idempotency-Key'))
})
it('isolates project requests and removes a pending private input after session changes',async()=>{
 const fetcher=vi.fn(async()=>{throw Error('lost')});vi.stubGlobal('fetch',fetcher)
 const one=renderHook(()=>useDeliveryOperation('p1','d1','freeze'));await act(()=>one.result.current.submit('freeze',base+'/snapshots',{change_note:'Private note'},base+'/snapshots/requests/{key}'))
 const two=renderHook(()=>useDeliveryOperation('p2','d1','freeze'));expect(two.result.current.unknown).toBe(false);act(()=>clearApiSession());expect(one.result.current.valid).toBe(false);expect(Object.values(sessionStorage).join('')).not.toContain('Private note');await act(()=>one.result.current.lookup());expect(fetcher).toHaveBeenCalledTimes(1)
})
