import {expect,it} from 'vitest'
import {isTask,isWorkspace,sameInputVersion} from '../tasks/taskTypes'
import {taskFixture,workspaceFixture} from '../tasks/taskFixtures'
const input={kind:'review_revision',revision_id:'revision1',round_id:'round1',base_version_id:'v1',workflow_version:'review_revision_v1'}
it('accepts only the exact fixed revision input and keeps its workspace free of invented results',()=>{
 const task={...taskFixture,task_type:'review_revision',phase:'verify',input_version:input}
 expect(isTask(task,'p1')).toBe(true)
 expect(isTask({...task,input_version:{...input,revision_id:undefined}},'p1')).toBe(false)
 expect(isTask({...task,input_version:{...input,extra:'x'}},'p1')).toBe(false)
 expect(sameInputVersion(input as never,{...input,revision_id:'other'} as never)).toBe(false)
 expect(isWorkspace({...workspaceFixture,task,source:{file_id:null,filename:'固定稿',analysis_run_id:null,is_current:true},wait:null,allowed_actions:[]},'p1','t1')).toBe(true)
})
it('accepts independent document exports and PDF sources while rejecting cross-document download URLs',()=>{
 const input_version={kind:'review_document_export',export_id:'e1',document_id:'d1',revision_id:'revision1',round_id:'round1',document_sha256:'a'.repeat(64),workflow_version:'review_document_export_v1'}
 const task={...taskFixture,task_type:'review_document_export',phase:'export',status:'succeeded',display_status:'succeeded',input_version}
 expect(isTask(task,'p1')).toBe(true)
 const workspace={...workspaceFixture,task,source:{file_id:null,filename:'逐条对照',analysis_run_id:null,is_current:true},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:{filename:'comparison.docx',download_url:'/api/v1/projects/p1/reviews/document-exports/e1/download'}}}
 expect(isWorkspace(workspace,'p1','t1')).toBe(true)
 expect(isWorkspace({...workspace,artifacts:{...workspace.artifacts,report:{...workspace.artifacts.report,download_url:'/api/v1/projects/p2/reviews/document-exports/e1/download'}}},'p1','t1')).toBe(false)
 expect(isTask({...task,task_type:'pdf_export',input_version:{kind:'pdf_export',export_id:'pdf1',source_kind:'review_document_export',source_id:'e1',source_sha256:'a'.repeat(64),workflow_version:'pdf_export_v1'}},'p1')).toBe(true)
})
