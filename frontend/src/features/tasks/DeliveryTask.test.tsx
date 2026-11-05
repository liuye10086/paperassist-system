import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import TaskDetail from './TaskDetail'
import {taskFixture} from './taskFixtures'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('shows existing-member packaging and restores the original failed task through the normal exact-input resume entry',async()=>{
 const input={kind:'delivery_package',schema_version:1,workflow_version:'delivery_package_v1',source_sha256:'a'.repeat(64),output_language:'zh-CN',real_model_calls:false,real_network_calls:false},task={...taskFixture,task_type:'delivery_package',input_version:input,status:'failed',phase:'export',display_status:'failed'},workspace={task,source:{file_id:null,filename:'Frozen delivery',analysis_run_id:null,is_current:true},wait:null,allowed_actions:['retry'],artifacts:{figure:null,explanation:null,report:null,research_results:{kind:'delivery_package',source_sha256:input.source_sha256,figure_version_id:null,report_version_id:null,candidate_id:null}}}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{...task,status:'queued',display_status:'queued',revision:4}:url.endsWith('/progress')?{project_id:'p1',task_id:'t1',task_type:'delivery_package',status:'failed',delivery_id:'d1',snapshot_id:'s1',progress:null}:url.endsWith('/snapshots/s1')?{id:'s1',members:[{id:'word',format:'docx',selection:{kind:'manuscript_export'},source_metadata:{}}]}:url.includes('/events')?{task_id:'t1',items:[],next_cursor:0,has_more:false}:workspace));vi.stubGlobal('fetch',fetcher)
 render(<TaskDetail projectId="p1" taskId="t1" onChanged={vi.fn()}/>);const retry=await screen.findByRole('button',{name:'重试原任务'});expect(screen.getByText('仅恢复原快照封包；复用已有成果，不重新分析、绘图或生成文档。')).toBeTruthy()
 fireEvent.click(retry);await waitFor(()=>expect(fetcher.mock.calls.some(([,i])=>i?.method==='POST')).toBe(true));const [url,init]=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!
 expect(url).toBe('/api/v1/tasks/t1/resume');expect(JSON.parse(String(init?.body))).toEqual({operation:'retry',wait_id:null,expected_task_revision:task.revision,input_version:input});expect(fetcher.mock.calls.some(([u])=>u.includes('/model-usage'))).toBe(false)
})
