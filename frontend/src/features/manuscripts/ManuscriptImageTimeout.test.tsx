import {STANDARD_REQUEST_TIMEOUT_MS,RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import {act,cleanup,render,screen} from '@testing-library/react'
import {afterEach,beforeEach,it,expect,vi} from 'vitest'
import ManuscriptImage from './ManuscriptImage'
beforeEach(()=>{vi.useFakeTimers();vi.stubGlobal('URL',class extends URL{static createObjectURL=vi.fn(()=> 'blob:fixed-image');static revokeObjectURL=vi.fn()})})
afterEach(()=>{cleanup();vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals()})
function slowImage(delay=20000){const fetch=vi.fn((_url:string,init?:RequestInit)=>new Promise<Response>((resolve,reject)=>{const timer=window.setTimeout(()=>resolve(new Response('synthetic',{headers:{'Content-Type':'image/png'}})),delay);init?.signal?.addEventListener('abort',()=>{window.clearTimeout(timer);reject(new DOMException('Aborted','AbortError'))},{once:true})}));vi.stubGlobal('fetch',fetch);return fetch}
it('keeps research image verification visible and renders an authenticated image after twenty seconds',async()=>{
 const fetch=slowImage();render(<ManuscriptImage url="/api/v1/projects/p1/research-figures/f/members/m/download" title="Research image" timeoutMs={RESEARCH_REQUEST_TIMEOUT_MS}/>);expect(screen.getByRole('status').textContent).toContain('核验固定来源');await act(()=>vi.advanceTimersByTimeAsync(20000));expect(screen.getByRole('img',{name:'Research image'}).getAttribute('src')).toBe('blob:fixed-image');expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(false)
})
it('uses the sixty-minute default deadline for ordinary manuscript images',async()=>{
 const fetch=slowImage(STANDARD_REQUEST_TIMEOUT_MS+100000);render(<ManuscriptImage url="/api/v1/projects/p1/files/f/download" title="Legacy image"/>);await act(()=>vi.advanceTimersByTimeAsync(STANDARD_REQUEST_TIMEOUT_MS));expect(screen.getByRole('alert').textContent).toContain('图片读取失败');expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true)
})
it('aborts a research image when its configured bound expires or its component unmounts',async()=>{
 const fetch=slowImage();const first=render(<ManuscriptImage url="/api/v1/projects/p1/research-figures/a/members/m/download" title="Bounded image" timeoutMs={17000}/>);await act(()=>vi.advanceTimersByTimeAsync(16999));expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(false);await act(()=>vi.advanceTimersByTimeAsync(1));expect(screen.getByRole('alert')).toBeDefined();expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);first.unmount();const second=render(<ManuscriptImage url="/api/v1/projects/p1/research-figures/b/members/m/download" title="Cancelled image" timeoutMs={RESEARCH_REQUEST_TIMEOUT_MS}/>);second.unmount();expect(fetch.mock.calls[1][1]?.signal?.aborted).toBe(true)
})
