import {expect,it} from 'vitest'
import {isTask,isTaskPage,isWorkspace,sameInputVersion,type InputVersion} from '../tasks/taskTypes'
import {taskFixture} from '../tasks/taskFixtures'
export const journalInput={kind:'journal_recommendation',recommendation_id:'j1',workflow_version:'journal_recommendation_v1'} as const
export const journalTask={...taskFixture,task_type:'journal_recommendation',phase:'plan',status:'succeeded',display_status:'succeeded',reason_code:null,error_code:null,input_version:journalInput}
it('accepts only finite journal task contracts and frozen identities',()=>{
 const source={file_id:null,analysis_run_id:null,filename:'Research',is_current:true}
 expect(isTask(journalTask,'p1')).toBe(true)
 expect(isTaskPage({project_id:'p1',page:1,page_size:10,total:1,items:[{task:journalTask,source}]},'p1',1)).toBe(true)
 const workspace={task:journalTask,source,wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}}
 expect(isWorkspace(workspace,'p1','t1')).toBe(true)
 expect(isWorkspace({...workspace,allowed_actions:['resume']},'p1','t1')).toBe(false)
 expect(isTask({...journalTask,input_version:{...journalInput,workflow_version:'unknown'}},'p1')).toBe(false)
 expect(sameInputVersion(journalInput,{...journalInput,recommendation_id:'j2'} as InputVersion)).toBe(false)
})
