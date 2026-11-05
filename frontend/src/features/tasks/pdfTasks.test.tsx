import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
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
it('keeps historical PDF task identity and source without PDF download or Word relabeling',async()=>{
 const fetcher=vi.fn(async(url:string)=>Response.json(url.endsWith('/workspace')?workspace:{task_id:'t1',items:[],next_cursor:0,has_more:false}));vi.stubGlobal('fetch',fetcher)
 render(<TaskDetail projectId="p1" taskId="t1" onChanged={()=>{}} onOpenManuscripts={()=>{}}/>);await screen.findByRole('heading',{name:'PDF 导出'})
 expect(screen.queryByRole('link',{name:/下载此任务的 PDF|下载此任务的 Word/})).toBeNull()
 expect(screen.getByRole('heading',{name:'PDF 导出'})).toBeTruthy();expect(screen.getByText(/已冻结的 DOCX 来源/)).toBeTruthy();expect(screen.getByRole('button',{name:'返回稿件写作'})).toBeTruthy();expect(screen.queryByRole('button',{name:'重试原任务'})).toBeNull();expect(fetcher.mock.calls.some(([url])=>url.includes('model-usage'))).toBe(false)
})
it('keeps failed PDF tasks readable without mounting historical PDF panels or fetching PDF exports',async()=>{
 const failed={...task,status:'failed',display_status:'failed',error_code:'pdf_conversion_timeout'}
 const row={id:'pdf1',project_id:'p1',source_kind:'manuscript_export',source_id:'docx1',source_sha256:'a'.repeat(64),status:'failed',task_id:'t1',created_at:task.created_at,filename:null,error_code:'pdf_conversion_timeout',parent_export_id:null,renderer_manifest:null,sha256:null,size_bytes:null,download_url:null}
 const saved={...row,id:'pdf2',status:'succeeded',task_id:'historical-pdf-task',filename:'saved.pdf',error_code:null,sha256:'b'.repeat(64),size_bytes:100,renderer_manifest:{id:'historical-renderer'},download_url:'/api/v1/projects/p1/pdf-exports/pdf2/download'}
 const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/workspace')?{...workspace,task:failed,artifacts:{...workspace.artifacts,report:null}}:url.includes('pdf-exports')?{items:[row,saved]}:{task_id:'t1',items:[],next_cursor:0,has_more:false}));vi.stubGlobal('fetch',fetcher)
 render(<TaskDetail projectId="p1" taskId="t1" onChanged={()=>{}}/>);
 await screen.findByRole('heading',{name:'PDF 导出'})
 expect(screen.queryByRole('link',{name:'下载 PDF'})).toBeNull()
 expect(screen.queryByRole('link',{name:'查看 PDF 任务'})).toBeNull()
 expect(screen.getAllByText('历史 PDF 转换超时；Word 仍可下载。').length).toBeGreaterThan(0)
 expect(screen.queryAllByRole('button',{name:/重试原任务|重试 PDF|生成 PDF|新建 PDF|确认上次 PDF/})).toHaveLength(0)
 expect(fetcher.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false)
 expect(fetcher.mock.calls.some(([url])=>url.includes('/pdf-exports'))).toBe(false)
})

it.each(['docx','pdf','nested'])('reads the exact delivery snapshot before recovering a %s package',async format=>{
 const deliveryInput={kind:'delivery_package',schema_version:1,workflow_version:'delivery_package_v1',source_sha256:'a'.repeat(64),output_language:'zh-CN',real_model_calls:false,real_network_calls:false},deliveryTask={...taskFixture,task_type:'delivery_package',status:'failed',display_status:'failed',phase:'export',input_version:deliveryInput,error_code:'task_failed',reason_code:null}
 const member={id:'member1',selection:{kind:'research_report_member',version_id:'report1',member_id:'member1'},format:format==='nested'?'zip':format,source_metadata:format==='nested'?{inner_members:[{name:'figure.pdf'}]}:{}},snapshot={id:'s1',members:[member]}
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{...deliveryTask,status:'queued',display_status:'queued',revision:4}:url.endsWith('/workspace')?{...workspace,task:deliveryTask,allowed_actions:['retry'],artifacts:{figure:null,explanation:null,report:null}}:url.endsWith('/progress')?{project_id:'p1',task_id:'t1',task_type:'delivery_package',status:'failed',delivery_id:'d1',snapshot_id:'s1',progress:null}:url.endsWith('/snapshots/s1')?snapshot:{task_id:'t1',items:[],next_cursor:0,has_more:false}));vi.stubGlobal('fetch',fetch)
 render(<TaskDetail projectId="p1" taskId="t1" onChanged={()=>{}} view="actions"/>);await waitFor(()=>expect(fetch.mock.calls.some(([url])=>url==='/api/v1/projects/p1/deliveries/d1/snapshots/s1')).toBe(true))
 if(format==='docx'){fireEvent.click(await screen.findByRole('button',{name:'重试原任务'}));await waitFor(()=>expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true));expect(JSON.parse(String(fetch.mock.calls.find(([,init])=>init?.method==='POST')![1]?.body))).toEqual({operation:'retry',wait_id:null,expected_task_revision:3,input_version:deliveryInput})}
 else{await screen.findByText('此历史交付包含 PDF，仅保留状态与原请求查询。');expect(screen.queryByRole('button',{name:'重试原任务'})).toBeNull();expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false)}
})
