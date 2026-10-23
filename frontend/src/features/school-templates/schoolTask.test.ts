import {expect,it} from 'vitest'
import {isTask,isTaskPage,isWorkspace,sameInputVersion} from '../tasks/taskTypes'
import {taskFixture} from '../tasks/taskFixtures'
const input={kind:'school_template',template_version_id:'v1',parser_version:'school-template-openxml-v1',workflow_version:'school_template_v1'}
const task={...taskFixture,task_type:'school_template_parse',phase:'parse',status:'succeeded',display_status:'succeeded',retry_count:0,reason_code:null,error_code:null,input_version:input}
const source={file_id:'f1',filename:'template.docx',analysis_run_id:null,is_current:true}
it('accepts retained school parsing tasks in the unified list and workspace',()=>{
 expect(isTask(task,'p1')).toBe(true)
 expect(isTaskPage({project_id:'p1',page:1,page_size:10,total:1,items:[{task,source}]},'p1',1)).toBe(true)
 expect(isWorkspace({task,source,wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}},'p1','t1')).toBe(true)
 expect(isTask({...task,input_version:{...input,workflow_version:'invented'}},'p1')).toBe(false)
 expect(isWorkspace({task,source:{...source,file_id:null},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}},'p1','t1')).toBe(false)
 // Public contract guards versions even when no model usage exists.
 expect(sameInputVersion(input as never,{...input,template_version_id:'other'} as never)).toBe(false)
})
