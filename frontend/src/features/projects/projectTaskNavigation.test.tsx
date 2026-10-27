import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import WorkspaceShell from './WorkspaceShell'
import useProjectSelection from './useProjectSelection'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })
const project = { id: 'p1', name: '研究', research_topic: '主题', project_type: 'sci', file_count: 0,
  created_at: '2026-10-08T00:00:00Z', updated_at: '2026-10-08T00:00:00Z', default_output_language: 'zh-CN' }
it('opens a PDF task hash link and rejects malformed destinations',async()=>{
 window.history.replaceState(null,'','/#project=p1');vi.stubGlobal('fetch',vi.fn(async()=>Response.json(project)))
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()));await waitFor(()=>expect(result.current.project?.id).toBe('p1'))
 act(()=>{window.history.replaceState(null,'','/#project=p1&section=tasks&task=pdf-task');window.dispatchEvent(new HashChangeEvent('hashchange'))})
 expect(result.current.section).toBe('tasks');expect(result.current.taskId).toBe('pdf-task')
 for(const hash of ['#project=p1&section=tasks&task=bad/id','#project=p1&section=unknown&task=other']){
  act(()=>{window.history.replaceState(null,'','/'+hash);window.dispatchEvent(new HashChangeEvent('hashchange'))})
  expect(result.current.taskId).toBe('pdf-task');expect(result.current.project?.id).toBe('p1')
 }
})
it('adds project tasks to the existing sidebar', () => {
  render(<WorkspaceShell view="project" section="tasks" projectName="研究" onNavigate={vi.fn()} onCreate={vi.fn()} onCurrentProject={vi.fn()}><div /></WorkspaceShell>)
  expect(screen.getByRole('button', { name: '项目任务' })).toBeTruthy()
})
it('restores the task deep link and clears it when a different project opens', async () => {
  window.history.replaceState(null, '', '/#project=p1&section=tasks&task=t1')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json({ ...project, id: url.endsWith('p2') ? 'p2' : 'p1' })))
  const { result } = renderHook(() => useProjectSelection(vi.fn(), vi.fn()))
  await waitFor(() => expect(result.current.project?.id).toBe('p1'))
  expect(result.current.section).toBe('tasks'); expect(result.current.taskId).toBe('t1')
  expect(window.location.hash).toBe('#project=p1&section=tasks&task=t1')
  act(() => result.current.open('p2'))
  await waitFor(() => expect(result.current.project?.id).toBe('p2'))
  expect(result.current.taskId).toBe(''); expect(window.location.hash).toBe('#project=p2')
})
it.each(['legacy-plot:', 'legacy-plot:abc/def', 'legacy-plot:b2xk=', 'legacy-other:b2xk', 'legacy-plot:A', 'legacy-plot:YR', 'legacy-plot:_w'])('rejects malformed historical deep link %s', async taskId => {
  window.history.replaceState(null, '', `/#project=p1&section=tasks&task=${encodeURIComponent(taskId)}`)
  vi.stubGlobal('fetch', vi.fn(async () => Response.json(project)))
  const { result } = renderHook(() => useProjectSelection(vi.fn(), vi.fn()))
  await waitFor(() => expect(result.current.project?.id).toBe('p1'))
  expect(result.current.taskId).toBe('')
  expect(window.location.hash).toBe('#project=p1&section=tasks')
})
it.each(['legacy-plot', 'legacy-explanation'])('restores a long canonical %s deep link and clears it on project change', async prefix => {
  const taskId = `${prefix}:${btoa('old-task/'.repeat(100)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')}`
  window.history.replaceState(null, '', `/#project=p1&section=tasks&task=${encodeURIComponent(taskId)}`)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json({ ...project, id: url.endsWith('p2') ? 'p2' : 'p1' })))
  const { result } = renderHook(() => useProjectSelection(vi.fn(), vi.fn()))
  await waitFor(() => expect(result.current.project?.id).toBe('p1'))
  expect(result.current.taskId).toBe(taskId)
  expect(window.location.hash).toContain(`task=${encodeURIComponent(taskId)}`)
  act(() => result.current.open('p2'))
  await waitFor(() => expect(result.current.project?.id).toBe('p2'))
  expect(result.current.taskId).toBe('')
})
it('preserves current selection when a malformed legacy ID is selected', async () => {
  window.history.replaceState(null, '', '/#project=p1&section=tasks&task=t1')
  vi.stubGlobal('fetch', vi.fn(async () => Response.json(project)))
  const { result } = renderHook(() => useProjectSelection(vi.fn(), vi.fn()))
  await waitFor(() => expect(result.current.project?.id).toBe('p1'))
  act(() => result.current.selectTask('legacy-plot:abc/def'))
  expect(result.current.taskId).toBe('t1')
  expect(window.location.hash).toBe('#project=p1&section=tasks&task=t1')
})

it('offers SCI writing only to SCI projects and restores its deep link', async () => {
  const shell = render(<WorkspaceShell projectType="sci" view="project" section="manuscripts" projectName="研究" onNavigate={vi.fn()} onCreate={vi.fn()} onCurrentProject={vi.fn()}><div /></WorkspaceShell>)
  expect(screen.getByRole('button', { name: 'SCI 写作' }).getAttribute('aria-current')).toBe('page')
  shell.rerender(<WorkspaceShell projectType="thesis" view="project" section="overview" projectName="研究" onNavigate={vi.fn()} onCreate={vi.fn()} onCurrentProject={vi.fn()}><div /></WorkspaceShell>)
  expect(screen.queryByRole('button', { name: 'SCI 写作' })).toBeNull()
  shell.unmount()
  window.history.replaceState(null, '', '/#project=p1&section=manuscripts')
  vi.stubGlobal('fetch', vi.fn(async () => Response.json(project)))
  const { result } = renderHook(() => useProjectSelection(vi.fn(), vi.fn()))
  await waitFor(() => expect(result.current.project?.id).toBe('p1'))
  expect(result.current.section).toBe('manuscripts')
  expect(window.location.hash).toBe('#project=p1&section=manuscripts')
})

it.each(['', '#project=p1'])('opens an owner-checked task link from %s', async initial => {
 window.history.replaceState(null,'','/'+initial)
 let finish!:(response:Response)=>void
 const fetch=vi.fn((url:string)=>url.endsWith('p2')?new Promise<Response>(resolve=>{finish=resolve}):Promise.resolve(Response.json(project)))
 vi.stubGlobal('fetch',fetch)
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()))
 if(initial)await waitFor(()=>expect(result.current.project?.id).toBe('p1'))
 act(()=>{window.history.replaceState(null,'','/#project=p2&section=tasks&task=t2');window.dispatchEvent(new HashChangeEvent('hashchange'))})
 expect(result.current.instance?.id).toBe('p2');expect(result.current.project).toBeNull();expect(result.current.loading).toBe(true)
 await act(async()=>finish(Response.json({...project,id:'p2'})))
 expect(result.current.project?.id).toBe('p2');expect(result.current.taskId).toBe('t2');expect(result.current.section).toBe('tasks')
 expect(fetch).toHaveBeenCalledWith('/api/v1/projects/p2',expect.anything())
})
it('opens literature links within and across projects and rejects ambiguous links',async()=>{
 window.history.replaceState(null,'','/#project=p1')
 const fetch=vi.fn(async(url:string)=>Response.json({...project,id:url.endsWith('p2')?'p2':'p1'}));vi.stubGlobal('fetch',fetch)
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()));await waitFor(()=>expect(result.current.project?.id).toBe('p1'))
 for(const id of ['p1','p2']){
  act(()=>{window.history.replaceState(null,'',`/#project=${id}&section=literature&search=s1`);window.dispatchEvent(new HashChangeEvent('hashchange'))})
  await waitFor(()=>expect(result.current.project?.id).toBe(id));expect(result.current.section).toBe('literature');expect(result.current.literatureSearchId).toBe('s1');expect(result.current.taskId).toBe('')
 }
 for(const hash of ['project=p3&project=p2&section=tasks&task=t3','project=p3&section=literature&search=bad/id','project=p3&section=tasks&task=t3&extra=x','project=bad/id&section=tasks&task=t3']){
  act(()=>{window.history.replaceState(null,'','/#'+hash);window.dispatchEvent(new HashChangeEvent('hashchange'))})
  expect(result.current.instance?.id).toBe('p2');expect(result.current.literatureSearchId).toBe('s1')
 }
 expect(fetch).toHaveBeenCalledTimes(2)
})
it('never publishes a denied cross-project destination',async()=>{
 window.history.replaceState(null,'','/#project=p1');vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.endsWith('p2')?Response.json({detail:'denied'},{status:403}):Response.json(project)))
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()));await waitFor(()=>expect(result.current.project?.id).toBe('p1'))
 act(()=>{window.history.replaceState(null,'','/#project=p2&section=tasks&task=t2');window.dispatchEvent(new HashChangeEvent('hashchange'))})
 await waitFor(()=>expect(result.current.error).toBeTruthy());expect(result.current.project).toBeNull()
})

it('discards the prior owner response after another project destination opens',async()=>{
 let finish!:(response:Response)=>void
 vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('p2')?new Promise<Response>(resolve=>{finish=resolve}):Promise.resolve(Response.json(project))))
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()))
 act(()=>{window.history.replaceState(null,'','/#project=p2&section=tasks&task=t2');window.dispatchEvent(new HashChangeEvent('hashchange'))})
 act(()=>{window.history.replaceState(null,'','/#project=p1&section=literature&search=s1');window.dispatchEvent(new HashChangeEvent('hashchange'))})
 await waitFor(()=>expect(result.current.project?.id).toBe('p1'))
 await act(async()=>finish(Response.json({...project,id:'p2'})))
 expect(result.current.project?.id).toBe('p1');expect(result.current.section).toBe('literature');expect(result.current.literatureSearchId).toBe('s1');expect(result.current.taskId).toBe('')
})

it.each(['journals&adaptation=a1','reviews&round=r1&reviewRun=run1&reviewDocument=d1','manuscripts&manuscript=m1&revision=2'])('owner-checks cross-project %s destinations',async target=>{
 let finish!:(response:Response)=>void
 vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(resolve=>{finish=resolve})))
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()))
 act(()=>{window.history.replaceState(null,'','/#project=p2&section='+target);window.dispatchEvent(new HashChangeEvent('hashchange'))})
 expect(result.current.instance?.id).toBe('p2');expect(result.current.project).toBeNull()
 await act(async()=>finish(Response.json({...project,id:'p2'})))
 expect(result.current.project?.id).toBe('p2');expect(result.current.section).toBe(target.split('&')[0]);expect(window.location.hash).toBe('#project=p2&section='+target)
})
it.each(['journals&adaptation=a1','reviews&round=r1','manuscripts&manuscript=m1&revision=2'])('does not publish denied %s destinations',async target=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({detail:'denied'},{status:403})))
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()))
 act(()=>{window.history.replaceState(null,'','/#project=p2&section='+target);window.dispatchEvent(new HashChangeEvent('hashchange'))})
 await waitFor(()=>expect(result.current.error).toBeTruthy());expect(result.current.project).toBeNull()
})
it.each(['journals&adaptation=bad/id','reviews&round=r1&reviewManuscript=m1&reviewRevision=2','manuscripts&manuscript=m1&revision=2&revision=3'])('rejects malformed cross-project %s destinations',target=>{
 const fetch=vi.fn();vi.stubGlobal('fetch',fetch)
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()))
 act(()=>{window.history.replaceState(null,'','/#project=p2&section='+target);window.dispatchEvent(new HashChangeEvent('hashchange'))})
 expect(result.current.instance).toBeNull();expect(fetch).not.toHaveBeenCalled()
})
