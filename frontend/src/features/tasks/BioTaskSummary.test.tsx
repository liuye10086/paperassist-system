import {act,cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import TaskDetail from './TaskDetail'
import ProjectTasks from './ProjectTasks'
import {processedFixture,runFixture} from '../bioinformatics/spatialFixtures'
import {pageFixture} from './taskFixtures'
import {setLocale} from '../../shared/i18n'
const task={...runFixture.task,status:'cancelled',display_status:'cancelled',task_type:'bio_figure',input_version:{schema_version:1,kind:'bio_figure',figure_version_id:'figure1',processed_source:processedFixture.source,workflow_version:'bio_figure_v1',output_language:'en'}}
const source={file_id:null,filename:'生信单图',analysis_run_id:null,is_current:true}
const workspace={task,source,wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}}
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.useRealTimers();setLocale('zh-CN')})
it('shows fixed bio inputs and preserves figure links without Excel configuration fallback',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(workspace)))
 render(<TaskDetail projectId="p1" taskId={task.id} onChanged={vi.fn()} view="overview"/>)
 await screen.findAllByText('生信单图')
 expect(screen.queryByText(/历史 Excel 配置/)).toBeNull()
 expect(screen.queryByText('分析配置 v0')).toBeNull()
 expect(screen.queryByText('当前分析配置')).toBeNull()
 expect(screen.getByText('固定处理结果与绘图参数')).toBeTruthy()
 expect(screen.getByRole('link',{name:'打开固定单图版本'}).getAttribute('href')).toContain('figure=figure1')
 act(()=>setLocale('en'))
 expect(screen.getByText('Fixed processed results and figure settings')).toBeTruthy()
})
it('does not continue workspace or event polling after cancellation',async()=>{
 vi.useFakeTimers()
 const fetch=vi.fn(async(url:string)=>Response.json(url.includes('/events')?{task_id:task.id,items:[],next_cursor:0,has_more:false}:workspace))
 vi.stubGlobal('fetch',fetch)
 render(<TaskDetail projectId="p1" taskId={task.id} onChanged={vi.fn()} view="events"/>)
 await act(async()=>{})
 expect(fetch.mock.calls.some(([url])=>url.includes('/events'))).toBe(true)
 const initial=fetch.mock.calls.length
 await act(async()=>{vi.advanceTimersByTime(15000)})
 expect(fetch).toHaveBeenCalledTimes(initial)
})
it('uses the fixed bio input summary in the project task list too',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...pageFixture,items:[{task,source}]})))
 render(<ProjectTasks projectId="p1" active selectedTaskId="" onSelectTask={vi.fn()}/>)
 await screen.findByRole('button',{name:'查看生信单图任务'})
 expect(screen.queryByText('分析配置 v0')).toBeNull()
 expect(screen.queryByText('当前分析配置')).toBeNull()
 expect(screen.getByText('固定处理结果与绘图参数')).toBeTruthy()
})
