import {afterEach,expect,it,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import {BioMemberImage} from './BioSpatialShared'
import {useBioRead} from './spatialHooks'
import {setLocale} from '../../shared/i18n'
import {BioFigureComposer} from './BioFigureDetail'
import {processedFixture} from './spatialFixtures'
const sessions=vi.hoisted(()=>new Set<()=>void>())
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:(fn:()=>void)=>{sessions.add(fn);return()=>sessions.delete(fn)}}))
afterEach(()=>{cleanup();vi.clearAllMocks();vi.unstubAllGlobals();sessions.clear();setLocale('zh-CN')})
it('revokes private image URLs and removes the image when the session is lost',async()=>{const create=vi.fn(()=> 'blob:private'),revoke=vi.fn();vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:create,revokeObjectURL:revoke}));vi.mocked(apiFetch).mockResolvedValue(new Response(new Blob(['PNG'],{type:'image/png'})));const {unmount}=render(<BioMemberImage projectId="p1" member={{id:'m1',key:'qc',format:'png',sha256:'a'.repeat(64),size_bytes:3,download_url:'/api/v1/projects/p1/bio-figures/f1/members/m1/download'}}/>);await screen.findByRole('img');act(()=>sessions.forEach(fn=>fn()));expect(screen.queryByRole('img')).toBeNull();expect(revoke).toHaveBeenCalledWith('blob:private');unmount();expect(revoke).toHaveBeenCalledTimes(1)})
function Reader({id}:{id:string}){const r=useBioRead<{id:string}>('/api/v1/projects/'+id+'/bio-analysis-runs/run1');return <output>{r.value?.id??'loading'}</output>}
it('aborts stale requests and prevents a previous project response from replacing the current result',async()=>{let resolveOld:(value:Response)=>void=()=>{};vi.mocked(apiFetch).mockImplementation((url)=>String(url).includes('/p1/')?new Promise<Response>(resolve=>{resolveOld=resolve}):Promise.resolve(Response.json({id:'p2result'})));const {rerender}=render(<Reader id="p1"/>);rerender(<Reader id="p2"/>);await screen.findByText('p2result');expect(vi.mocked(apiFetch).mock.calls[0][1]?.signal?.aborted).toBe(true);await act(async()=>resolveOld(Response.json({id:'p1private'})));expect(screen.getByRole('status').textContent).toBe('p2result')})
it('translates figure editing in place without changing its saved output language',async()=>{
 render(<BioFigureComposer projectId="p1" result={processedFixture} onNavigate={()=>{}}/>)
 fireEvent.change(screen.getByLabelText('图片语言'), {target:{value:'zh-CN'}})
 act(()=>setLocale('en'))
 expect(await screen.findByRole('heading',{name:'Individual figure settings'})).toBeTruthy()
 expect(screen.getByLabelText('Figure language')).toHaveProperty('value','zh-CN')
 expect(screen.getByLabelText('Width (pixels)')).toHaveProperty('value','1800')
 expect(screen.getByLabelText('Height (pixels)')).toHaveProperty('value','1500')
 expect(screen.getByRole('option',{name:'Quality control plot'})).toBeTruthy()
 expect(screen.getByRole('option',{name:'Blue–green gradient'})).toBeTruthy()
 expect(document.body.textContent?.replace('简体中文','')).not.toMatch(/[\u3400-\u9fff]/)
})
