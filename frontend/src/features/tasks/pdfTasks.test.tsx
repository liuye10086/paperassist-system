import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {isTask,isTaskPage,isWorkspace,sameInputVersion} from './taskTypes'
import {taskFixture} from './taskFixtures'
import TaskDetail from './TaskDetail'
const input={kind:'pdf_export',export_id:'pdf1',source_kind:'manuscript_export',source_id:'docx1',source_sha256:'a'.repeat(64),workflow_version:'pdf_export_v1'}
const task={...taskFixture,task_type:'pdf_export',phase:'export',status:'succeeded',display_status:'succeeded',input_version:input,error_code:null,reason_code:null}
const source={file_id:null,analysis_run_id:null,filename:'manuscript.docx',is_current:true}
const report={filename:'manuscript.pdf',download_url:'/api/v1/projects/p1/pdf-exports/pdf1/download'}
const workspace={task,source,wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report}}
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('accepts PDF tasks and strict source version matching in list and workspace',()=>{
 expect(isTask(task,'p1')).toBe(true);expect(isTaskPage({project_id:'p1',items:[{task,source}],total:1,page:1,page_size:10},'p1',1)).toBe(true);expect(isWorkspace(workspace,'p1','t1')).toBe(true)
 expect(isWorkspace({...workspace,allowed_actions:['retry']},'p1','t1')).toBe(false)
 expect(isWorkspace({...workspace,artifacts:{...workspace.artifacts,report:{...report,download_url:'/api/v1/projects/p2/pdf-exports/pdf1/download'}}},'p1','t1')).toBe(false)
 expect(sameInputVersion(input as never,{...input,source_id:'other'} as never)).toBe(false)
 expect(isTask({...task,input_version:{...input,source_sha256:'bad'}},'p1')).toBe(false)
})
it('shows PDF download and frozen DOCX source without generic task retry or model usage',async()=>{
 const fetcher=vi.fn(async(url:string)=>Response.json(url.endsWith('/workspace')?workspace:{task_id:'t1',items:[],next_cursor:0,has_more:false}));vi.stubGlobal('fetch',fetcher)
 render(<TaskDetail projectId="p1" taskId="t1" onChanged={()=>{}} onOpenManuscripts={()=>{}}/>);await screen.findByRole('link',{name:'下载此任务的 PDF'})
 expect(screen.getByRole('heading',{name:'PDF 导出'})).toBeTruthy();expect(screen.getByText(/已冻结的 DOCX 来源/)).toBeTruthy();expect(screen.getByRole('button',{name:'打开 SCI 写作'})).toBeTruthy();expect(screen.queryByRole('button',{name:'重试原任务'})).toBeNull();expect(fetcher.mock.calls.some(([url])=>url.includes('model-usage'))).toBe(false)
})
it('offers a dedicated new PDF child retry from a failed task workspace',async()=>{
 const failed={...task,status:'failed',display_status:'failed',error_code:'pdf_conversion_timeout'}
 const row={id:'pdf1',project_id:'p1',source_kind:'manuscript_export',source_id:'docx1',source_sha256:'a'.repeat(64),status:'failed',task_id:'t1',created_at:task.created_at,filename:null,error_code:'pdf_conversion_timeout',parent_export_id:null,renderer_manifest:null,sha256:null,size_bytes:null,download_url:null}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/workspace')?{...workspace,task:failed,artifacts:{...workspace.artifacts,report:null}}:url.includes('pdf-exports')?{items:[row]}:{task_id:'t1',items:[],next_cursor:0,has_more:false})))
 render(<TaskDetail projectId="p1" taskId="t1" onChanged={()=>{}}/>);await screen.findByRole('button',{name:'重试 PDF'});expect(screen.queryByRole('button',{name:'重试原任务'})).toBeNull()
})
