import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,it,expect,vi} from 'vitest'
import TaskDetail from '../tasks/TaskDetail'
import {isWorkspace} from '../tasks/taskTypes'
import {eventsFixture,usageFixture,taskFixture} from '../tasks/taskFixtures'
const task={...taskFixture,id:'assist1',task_type:'literature_assistance',status:'succeeded',display_status:'succeeded',phase:'plan',reason_code:null,error_code:null,input_version:{kind:'literature_assistance',workflow_version:'literature_assistance_v1',assistance_kind:'search_plan',input_digest:'a'.repeat(64),output_language:'en'}}
// Synthetic persisted suggestion, never a real provider response.
const result={direction:'Synthetic saved direction',terms:['Synthetic term'],synonyms:[],mesh_candidates:[{term:'Synthetic MeSH',verified:false}],query:'synthetic[Title]',explanation:'Synthetic explanation'}
const workspace={task,source:{file_id:null,filename:'Synthetic source topic',analysis_run_id:null,is_current:false},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null,literature_assistance:{kind:'search_plan',result,real_calls_enabled:false}}}
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('keeps historical assistance readable with frozen input and explicitly unverified MeSH suggestions',async()=>{
 expect(isWorkspace(workspace,'p1','assist1')).toBe(true)
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/events')?{...eventsFixture,task_id:'assist1'}:url.includes('/model-usage')?usageFixture:workspace)))
 render(<TaskDetail projectId="p1" taskId="assist1" onChanged={vi.fn()}/>);
 expect(await screen.findByText('冻结的文献建议输入')).toBeTruthy()
 expect(await screen.findByText('Synthetic saved direction')).toBeTruthy()
 expect(screen.getByText('MeSH candidates (unverified)')).toBeTruthy()
 expect(screen.queryByText('分析配置 v0')).toBeNull()
 expect(screen.queryByText('此任务尚无已保存的成果。')).toBeNull()
})
