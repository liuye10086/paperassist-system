import {it,expect} from 'vitest'
import {isTask,isTaskPage,isWorkspace,sameInputVersion} from '../tasks/taskTypes'
import {literatureTask} from './fixtures'
import {validAssistance} from './assistanceApi'
// Synthetic authorization wait: never invokes a provider.
export const assistanceTask={...literatureTask,id:'assist1',task_type:'literature_assistance',phase:'plan',reason_code:'literature_model_authorization_required',input_version:{kind:'literature_assistance',workflow_version:'literature_assistance_v1',assistance_kind:'search_plan',input_digest:'b'.repeat(64),output_language:'en'}}
it('accepts frozen assistance tasks and authorization wait without granting a model action',()=>{
 expect(isTask(assistanceTask,'p1')).toBe(true)
 const workspace={task:assistanceTask,source:{file_id:null,filename:'Synthetic topic',analysis_run_id:null,is_current:true},wait:{id:'w1',kind:'literature_model_authorization',status:'open',task_revision:3,input_version:assistanceTask.input_version,reason_code:assistanceTask.reason_code,error_code:null,created_at:assistanceTask.updated_at,resolved_at:null},allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}}
 expect(isWorkspace(workspace,'p1','assist1')).toBe(true)
 expect(isWorkspace({...workspace,allowed_actions:['approve']},'p1','assist1')).toBe(false)
 expect(isTask({...assistanceTask,input_version:{...assistanceTask.input_version,input_digest:'fake'}},'p1')).toBe(false)
 if(isTask(assistanceTask,'p1'))expect(sameInputVersion(assistanceTask.input_version,{...assistanceTask.input_version,input_digest:'c'.repeat(64)} as typeof assistanceTask.input_version)).toBe(false)
})

it.each([['search_plan','plan','verify'],['evidence_review','verify','plan']] as const)('binds %s assistance strictly to %s across POST, list, details and workspace', (kind,phase,wrongPhase)=>{
 const task={...assistanceTask,phase,input_version:{...assistanceTask.input_version,assistance_kind:kind}}
 const detail={task,kind,input_version:task.input_version,result:null,real_calls_enabled:false}
 const source={file_id:null,filename:'Synthetic source',analysis_run_id:null,is_current:true}
 expect(isTask(task,'p1')).toBe(true)
 expect(isTask({...task,phase:wrongPhase},'p1')).toBe(false)
 expect(isTaskPage({project_id:'p1',page:1,page_size:10,total:1,items:[{task,source}]},'p1',1)).toBe(true)
 expect(validAssistance(detail,'p1')).toBe(true)
 expect(validAssistance({...detail,task:{...task,phase:wrongPhase}},'p1')).toBe(false)
 expect(isWorkspace({task,source,wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}},'p1','assist1')).toBe(true)
})
