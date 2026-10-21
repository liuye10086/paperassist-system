import {StrictMode,useEffect} from 'react'
import {act,cleanup,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import WritingLive from './WritingLive'
import {useWritingOperation} from './useWritingOperation'
import {bundleFixture,liveRequest} from './writingLiveFixtures'
import {manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('loads previews, capabilities and request history automatically on StrictMode mount',async()=>{
 const bundle=bundleFixture();const fetcher=vi.fn(async(url:string)=>Response.json(url.endsWith('/writing-previews')?{items:[bundle],capabilities:{real_calls_enabled:true}}:{items:[liveRequest]}));vi.stubGlobal('fetch',fetcher)
 render(<StrictMode><WritingLive projectId="p1" manuscriptId="m1" version={manuscriptFixture.versions[0] as unknown as ManuscriptVersion} onPublished={vi.fn()}/></StrictMode>)
 expect(await screen.findByRole('option',{name:/b1 · full_draft/})).toBeTruthy();expect(screen.getByText('服务端真实调用门禁已配置；账户可用性尚未验证。')).toBeTruthy();expect(await screen.findByRole('button',{name:'审核此原始候选'})).toBeTruthy();expect(fetcher.mock.calls.filter(([url])=>url.endsWith('/writing-previews'))).toHaveLength(2)
})
function AutomaticRead(){const op=useWritingOperation()
 // The test models the real mount-triggered read, including StrictMode replay.
 // oxlint-disable-next-line react/set-state-in-effect, react-hooks/exhaustive-deps
 useEffect(()=>{void op.run('/lifecycle',(v):v is {ok:boolean}=>!!v&&typeof v==='object'&&'ok'in v)},[])
 return <><output>{op.busy?'busy':'idle'}</output>{op.error&&<p role="alert">{op.error}</p>}</>
}
it('ignores old aborted catch and finally while the replacement lifecycle request is pending',async()=>{
 const pending:{resolve:(r:Response)=>void;reject:(e:Error)=>void;signal:AbortSignal}[]=[]
 vi.stubGlobal('fetch',vi.fn((_url:string,init:RequestInit)=>new Promise<Response>((resolve,reject)=>pending.push({resolve,reject,signal:init.signal as AbortSignal}))))
 render(<StrictMode><AutomaticRead/></StrictMode>);await waitFor(()=>expect(pending).toHaveLength(2));expect(pending[0].signal.aborted).toBe(true);expect(pending[1].signal.aborted).toBe(false)
 await act(async()=>pending[0].reject(new DOMException('Old mount aborted','AbortError')));expect(screen.getByRole('status').textContent).toBe('busy');expect(screen.queryByRole('alert')).toBeNull()
 await act(async()=>pending[1].reject(Error('Current request failed')));expect(screen.getByRole('status').textContent).toBe('idle');expect(screen.getByRole('alert').textContent).toContain('请求未确认')
})
