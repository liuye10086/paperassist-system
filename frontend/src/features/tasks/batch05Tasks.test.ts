import {expect,test} from 'vitest'
import {isTask,isTaskPage,isWorkspace,sameInputVersion,type InputVersion} from './taskTypes'
import {taskFixture,sourceFixture} from './taskFixtures'
import {correlationResult} from '../analysis/correlationFixtures'
test.each(['figure_projection','figure_workbench','figure_explanation'])('%s uses immutable dataset source in task UI',task_type=>{
 const task={...taskFixture,task_type,input_version:{kind:'dataset_analysis',setup_revision:2,output_language:'zh-CN',source:correlationResult.source}}
 expect(isTask(task,'p1')).toBe(true)
 expect(isTask({...task,input_version:taskFixture.input_version},'p1')).toBe(false)
})
test('collection task keeps distinct input contract, nullable single run and safe download route',()=>{
 const input={kind:'report_collection',collection_version_id:'cv1',export_revision:2,output_language:'en',workflow_version:'collection_word_report_v1'}
 const task={...taskFixture,task_type:'collection_word_report',phase:'export',input_version:input}
 const source={...sourceFixture,analysis_run_id:null,dataset_source:correlationResult.source}
 expect(isTaskPage({project_id:'p1',page:1,page_size:10,total:1,items:[{task,source}]},'p1',1)).toBe(true)
 expect(isTask({...task,input_version:{...input,setup_revision:1}},'p1')).toBe(false)
 expect(sameInputVersion(input as InputVersion,{...input,export_revision:3} as InputVersion)).toBe(false)
 expect(isWorkspace({task,source,wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:{filename:'report.docx',download_url:'/api/v1/projects/p1/report-collections/c1/reports/report1/download'}}},'p1','t1')).toBe(true)
})
