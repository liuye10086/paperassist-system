import {act,cleanup,renderHook,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import useProjectSelection from './useProjectSelection'
afterEach(()=>{cleanup();vi.unstubAllGlobals();window.history.replaceState(null,'','/')})
it('retains a same-project historical delivery destination across sections and drops it when opening another project',async()=>{
 window.history.replaceState(null,'','/#project=p1&section=overview&view=deliveries&delivery=d1&snapshot=s1')
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json({id:url.endsWith('p2')?'p2':'p1',name:'Study',research_topic:'Topic',project_type:'research',file_count:0,created_at:'2026-11-02T00:00:00Z',updated_at:'2026-11-02T00:00:00Z'})))
 const h=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()));await waitFor(()=>expect(h.result.current.project?.id).toBe('p1'))
 act(()=>h.result.current.changeSection('files'));expect(h.result.current.deliverySnapshotId).toBe('s1')
 act(()=>h.result.current.changeOverviewView('deliveries'));expect(window.location.hash).toBe('#project=p1&section=overview&view=deliveries&delivery=d1&snapshot=s1')
 act(()=>h.result.current.selectDelivery('d1','s2'));expect(window.location.hash).toContain('&snapshot=s2')
 act(()=>h.result.current.open('p2'));await waitFor(()=>expect(h.result.current.project?.id).toBe('p2'));expect(h.result.current.deliveryId).toBeUndefined();expect(h.result.current.deliverySnapshotId).toBeUndefined()
})
