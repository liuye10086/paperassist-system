import {expect,it} from 'vitest'
import { isTask,isTaskPage,isWorkspace,sameInputVersion,type InputVersion } from './taskTypes'
import {taskFixture} from './taskFixtures'
import {summaryFixture} from '../../test/fixtures/summaryFixture'
import {isProjectSummary} from '../projects/projectSummaryTypes'
const input={kind:'manuscript',manuscript_version_id:'version1',output_language:'en',workflow_version:'manuscript_fact_draft_v1'}
const task={...taskFixture,task_type:'manuscript_draft',status:'succeeded',display_status:'succeeded',phase:'write',reason_code:null,error_code:null,input_version:input}
const source={file_id:null,filename:'Frozen draft',analysis_run_id:null,is_current:true}
it('accepts manuscript publication and DOCX tasks with a frozen manuscript version',()=>{
 expect(isTask(task,'p1')).toBe(true)
 expect(isTask({...task,task_type:'manuscript_docx',phase:'export'},'p1')).toBe(true)
 expect(isTaskPage({project_id:'p1',page:1,page_size:10,total:1,items:[{task,source}]},'p1',1)).toBe(true)
 expect(isWorkspace({task,source,wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null,manuscript:{id:'m1',version_id:'version1',revision:1,download_url:null}}},'p1','t1')).toBe(true)
 const report={filename:'fact.docx',download_url:'/api/v1/projects/p1/manuscripts/m1/exports/e1/download'}
 expect(isWorkspace({task:{...task,task_type:'manuscript_docx',phase:'export'},source,wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report}},'p1','t1')).toBe(true)
 expect(isWorkspace({task:{...task,task_type:'manuscript_docx',phase:'export'},source,wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:{...report,download_url:'/api/v1/projects/p2/manuscripts/m1/exports/e1/download'}}},'p1','t1')).toBe(false)
})
it('compares manuscript inputs by frozen version identity and rejects mixed legacy input',()=>{
 expect(sameInputVersion(input as InputVersion,{...input} as InputVersion)).toBe(true)
 expect(sameInputVersion(input as InputVersion,{...input,manuscript_version_id:'other'} as InputVersion)).toBe(false)
 expect(isTask({...task,input_version:taskFixture.input_version},'p1')).toBe(false)
})
it('accepts available writing summaries while retaining existing branch restrictions',()=>{
 const fixture=summaryFixture();const summary={...fixture,future:{...fixture.future,writing:{state:'available',current_manuscript:{id:'m1',title:'Draft',current_revision:1},versions:[{id:'v1',manuscript_id:'m1',revision:1}],tasks:[]}}}
 expect(isProjectSummary(summary,'p1','sci',1,1)).toBe(true)
 expect(isProjectSummary({...summary,future:{...summary.future,writing:{...summary.future.writing,current_manuscript:{id:'m1',title:'Draft',current_revision:0}}}},'p1','sci',1,1)).toBe(false)
})
