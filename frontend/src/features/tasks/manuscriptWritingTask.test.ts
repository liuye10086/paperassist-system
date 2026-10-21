import {expect,it} from 'vitest'
import {isTask,isWorkspace,sameInputVersion,type InputVersion} from './taskTypes'
import {taskFixture,workspaceFixture} from './taskFixtures'
const input={kind:'manuscript_writing',base_version_id:'v1',base_revision:1,output_language:'en',workflow_version:'manuscript_writing_v1'}
const task={...taskFixture,task_type:'manuscript_writing',phase:'write',input_version:input}
it('distinguishes the live writing workflow from v1 and rejects unknown versions',()=>{
 expect(isTask({...task,input_version:{...input,workflow_version:'manuscript_writing_v2'}},'p1')).toBe(true)
 expect(isTask({...task,input_version:{...input,workflow_version:'manuscript_writing_v3'}},'p1')).toBe(false)
})
it('accepts frozen manuscript writing task identity and rejects changed base versions',()=>{
 expect(isTask(task,'p1')).toBe(true)
 expect(isTask({...task,input_version:{...input,base_revision:0}},'p1')).toBe(false)
 expect(sameInputVersion(input as InputVersion,{...input,base_version_id:'v2'} as InputVersion)).toBe(false)
})
it('reads authorization waits without real model resume actions',()=>{
 const workspace={...workspaceFixture,task,source:{file_id:null,analysis_run_id:null,filename:'Saved draft',is_current:true},wait:{...workspaceFixture.wait,kind:'unsupported_confirmation',input_version:input},allowed_actions:[]}
 expect(isWorkspace(workspace,'p1','t1')).toBe(true)
 expect(isWorkspace({...workspace,allowed_actions:['resume']},'p1','t1')).toBe(false)
})
