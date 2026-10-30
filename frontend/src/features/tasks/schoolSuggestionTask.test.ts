import {expect,it} from 'vitest'
import {isTask,isWorkspace} from './taskTypes'
import {taskFixture} from './taskFixtures'
it('accepts the independent school suggestion task and its typed advice artifact',()=>{
 const task={...taskFixture,task_type:'school_rule_suggestion',phase:'interpret',input_version:{kind:'school_rule_suggestion',suggestion_id:'r1',template_version_id:'s1',analysis_sha256:'a'.repeat(64),bundle_sha256:'b'.repeat(64),workflow_version:'school_rule_suggestion_v1'}}
 expect(isTask(task,'p1','t1')).toBe(true)
 expect(isWorkspace({task,source:{file_id:'f1',filename:'Frozen school',analysis_run_id:null,is_current:true},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null,school_rule_suggestion:{id:'r1'}}},'p1','t1')).toBe(true)
})
