import {expect,test} from 'vitest'
import {isTask,isTaskPage,isWorkspace,sameInputVersion,type InputVersion} from './taskTypes'
import {taskFixture,sourceFixture} from './taskFixtures'
import {correlationResult} from '../analysis/correlationFixtures'
test.each(['figure_projection','figure_workbench','figure_explanation'])('%s uses immutable dataset source in task UI',task_type=>{
 const task={...taskFixture,task_type,input_version:{kind:'dataset_analysis',setup_revision:2,output_language:'zh-CN',source:correlationResult.source}}
 expect(isTask(task,'p1')).toBe(true)
 expect(isTask({...task,input_version:taskFixture.input_version},'p1')).toBe(false)
})
test('a completed figure explanation shows the bound source package without a generated figure id',()=>{
 const task={...taskFixture,task_type:'figure_explanation',status:'succeeded',display_status:'succeeded',phase:'interpret',
  reason_code:null,error_code:null,result_explanation_id:'explanation-1',
  input_version:{kind:'dataset_analysis',setup_revision:2,output_language:'en',source:correlationResult.source}}
 const source={...sourceFixture,file_id:correlationResult.source.file_id,dataset_source:correlationResult.source}
 const prefix=`/api/v1/projects/p1/files/${source.file_id}/analysis-runs/r1`
 const packageUrl=`${prefix}/figure-workbench/figures/fixed-figure/package`
 function workspace(download_url:string){
  return {task,source,wait:null,allowed_actions:[],artifacts:{
   figure:{title:'Fixed figure',caption:'Original figure caption',download_url},
   explanation:{sections:[{key:'purpose',title:'Purpose',text:'Describe the fixed result.'}],limitations:[]},report:null}}
 }
 expect(isWorkspace(workspace(packageUrl),'p1','t1')).toBe(true)
 for (const invalid of [`${packageUrl}?x=1`,`${packageUrl}#anchor`,`${prefix}/figure-workbench/figures/%2F/package`,
  packageUrl.replace('/r1/', '/r2/'),packageUrl.replace('/p1/', '/p2/')]) {
  expect(isWorkspace(workspace(invalid),'p1','t1')).toBe(false)
 }
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
