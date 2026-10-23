import {expect,it} from 'vitest'
import {isTask,isWorkspace,sameInputVersion,type InputVersion} from './taskTypes'
import {taskFixture,workspaceFixture} from './taskFixtures'
const input={kind:'review_round_plan',round_id:'round1',base_version_id:'v1',workflow_version:'review_round_plan_v1'}
const task={...taskFixture,task_type:'review_round_plan',phase:'verify',input_version:input}
it('recognizes fixed review plans and rejects altered or extra frozen inputs',()=>{expect(isTask(task,'p1')).toBe(true);expect(isTask({...task,phase:'write'},'p1')).toBe(false);expect(isTask({...task,input_version:{...input,extra:true}},'p1')).toBe(false);expect(sameInputVersion(input as InputVersion,{...input,round_id:'round2'} as InputVersion)).toBe(false)})
it('allows only matching review waits and local safe actions',()=>{const w={...workspaceFixture,task,source:{file_id:null,analysis_run_id:null,filename:'意见计划',is_current:true},wait:{...workspaceFixture.wait,kind:'review_round_confirmation',input_version:input}};expect(isWorkspace(w,'p1','t1')).toBe(true);expect(isWorkspace({...w,wait:{...w.wait,kind:'budget_confirmation'}},'p1','t1')).toBe(false);expect(isWorkspace({...w,allowed_actions:['approve']},'p1','t1')).toBe(false)})
