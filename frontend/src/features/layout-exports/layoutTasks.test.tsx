import TaskEvents from '../tasks/TaskEvents'
import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {isTask,isTaskPage,isWorkspace,sameInputVersion} from '../tasks/taskTypes'
import {taskFixture} from '../tasks/taskFixtures'
import TaskDetail from '../tasks/TaskDetail'
import {validPdfExport} from '../pdf-exports/pdfApi'
const input={kind:'layout_docx',export_id:'l1',source_kind:'report',source_id:'r1',source_sha256:'a'.repeat(64),workflow_version:'layout_docx_v1'}
const task={...taskFixture,task_type:'layout_docx',phase:'export',status:'succeeded',display_status:'succeeded',input_version:input,error_code:null,reason_code:null}
const source={file_id:null,analysis_run_id:null,filename:'source.docx',is_current:true}
const report={filename:'layout.docx',download_url:'/api/v1/projects/p1/layout-exports/l1/download'}
const workspace={task,source,wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report}}
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('validates layout tasks, strict versions and artifact paths, and layout PDF sources',()=>{
 expect(isTask(task,'p1')).toBe(true);expect(isTaskPage({project_id:'p1',items:[{task,source}],total:1,page:1,page_size:10},'p1',1)).toBe(true);expect(isWorkspace(workspace,'p1','t1')).toBe(true)
 expect(isWorkspace({...workspace,allowed_actions:['retry']},'p1','t1')).toBe(false);expect(isTask({...task,input_version:{...input,source_kind:'layout_export'}},'p1')).toBe(false);expect(isTask({...task,input_version:{...input,extra:1}},'p1')).toBe(false)
 expect(isWorkspace({...workspace,artifacts:{...workspace.artifacts,report:{...report,download_url:'/api/v1/projects/p2/layout-exports/l1/download'}}},'p1','t1')).toBe(false);expect(sameInputVersion(input as never,{...input,source_id:'other'} as never)).toBe(false)
 const pdfInput={...input,kind:'pdf_export',workflow_version:'pdf_export_v1',source_kind:'layout_export'};expect(isTask({...task,task_type:'pdf_export',input_version:pdfInput},'p1')).toBe(true)
 expect(validPdfExport({id:'p1',project_id:'p1',source_kind:'layout_export',source_id:'l1',source_sha256:'b'.repeat(64),status:'queued',task_id:'pt',created_at:task.created_at,filename:null,error_code:null,parent_export_id:null,renderer_manifest:null,sha256:null,size_bytes:null,download_url:null},{projectId:'p1',sourceKind:'layout_export' as never,sourceId:'l1'})).toBe(true)
})
it('shows layout downloads and frozen source without generic retry or model usage',async()=>{
 const fetcher=vi.fn(async(url:string)=>Response.json(url.endsWith('/workspace')?workspace:{task_id:'t1',items:[],next_cursor:0,has_more:false}));vi.stubGlobal('fetch',fetcher);render(<TaskDetail projectId="p1" taskId="t1" onChanged={()=>{}}/>);await screen.findByRole('link',{name:'下载此任务的 Word'});expect(screen.getByRole('heading',{name:'排版 DOCX 导出',level:3})).toBeTruthy();expect(screen.queryByRole('button',{name:'重试原任务'})).toBeNull();expect(fetcher.mock.calls.some(([url])=>url.includes('model-usage'))).toBe(false)
})

it('offers only the dedicated layout retry for failed local tasks',async()=>{
 const failed={...task,status:'failed',display_status:'failed',error_code:'layout_field_update_failed'};const row={id:'l1',project_id:'p1',source_kind:'report',source_id:'r1',source_sha256:'a'.repeat(64),status:'failed',task_id:'t1',created_at:task.created_at,layout:{source_sha256:'a'.repeat(64),formulas:[],references:[],headings:[],toc:null,pagination:null,landscape_anchor_ids:[]},layout_version:'document_layout_v1',output_language:'en',request_key:'key',can_retry:true,parent_export_id:null,filename:null,error_code:'layout_field_update_failed',renderer_manifest:null,sha256:null,size_bytes:null,download_url:null}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/workspace')?{...workspace,task:failed,artifacts:{...workspace.artifacts,report:null}}:url.includes('/layout-exports?')?{items:[row]}:url.endsWith('/catalog')?{}:{task_id:'t1',items:[],next_cursor:0,has_more:false})));render(<TaskDetail projectId="p1" taskId="t1" onChanged={()=>{}}/>);await screen.findByRole('button',{name:'重试排版'});expect(screen.queryByRole('button',{name:'重试原任务'})).toBeNull()
})

it('directs an exhausted local layout task to its independent export retry',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({task_id:'t1',items:[{seq:1,task_revision:1,event_type:'failed',status:'failed',phase:'export',reason_code:null,error_code:'layout_field_update_failed',error_category:'temporary',retry_count:3,retry_delay_seconds:null,created_at:task.created_at}],next_cursor:1,has_more:false})));render(<TaskEvents taskId="t1" taskType="layout_docx" live={false} refreshKey={0}/>);await screen.findByText('自动恢复已用尽，请在排版与公式中查看末端导出的重试权限。');expect(document.body.textContent).not.toContain('手动继续原任务')
})
