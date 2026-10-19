import {act,cleanup,render,screen,waitFor,renderHook} from '@testing-library/react'
import {afterEach,it,expect,vi} from 'vitest'
import TaskDetail from '../tasks/TaskDetail'
import {literatureWorkspace} from './fixtures'
import useProjectSelection from '../projects/useProjectSelection'
afterEach(()=>{cleanup();vi.unstubAllGlobals();window.history.replaceState(null,'','/')})
it('shows source topic and links literature task results back to literature',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/workspace')?literatureWorkspace:{task_id:'search1',items:[],next_cursor:0,has_more:false})))
 render(<TaskDetail projectId="p1" taskId="search1" onChanged={vi.fn()}/>)
 expect(await screen.findByText('来源研究主题')).toBeTruthy()
 expect(screen.getByRole('link',{name:'查看文献与候选'}).getAttribute('href')).toBe('#project=p1&section=literature&search=search1')
 expect(screen.queryByText(/分析配置 v/)).toBeNull()
 expect(screen.getByText(/NCBI 配置尚未就绪/)).toBeTruthy()
})
it('restores a literature page deep link',async()=>{
 window.history.replaceState(null,'','/#project=p1&section=literature&search=search1')
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({id:'p1',name:'Synthetic project',research_topic:'Synthetic topic',project_type:'thesis',file_count:0,created_at:'2026-10-08T01:00:00Z',updated_at:'2026-10-08T01:00:00Z',default_output_language:'en'})))
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()));await waitFor(()=>expect(result.current.project).toBeTruthy());expect(result.current.section).toBe('literature');expect(window.location.hash).toContain('section=literature')
})
it('updates and clears the selected literature search in the workspace URL',async()=>{
 window.history.replaceState(null,'','/#project=p1&section=literature&search=search1')
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({id:'p1',name:'Synthetic project',research_topic:'Synthetic topic',project_type:'sci',file_count:0,created_at:'2026-10-08T01:00:00Z',updated_at:'2026-10-08T01:00:00Z',default_output_language:'zh-CN'})))
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()));await waitFor(()=>expect(result.current.project).toBeTruthy())
 act(()=>result.current.selectLiterature(''));expect(result.current.section).toBe('literature');expect(window.location.hash).toBe('#project=p1&section=literature')
})
