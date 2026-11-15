import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {clearApiSession,setApiSession} from '../../shared/api/client'
import BioReaderReport from './BioReaderReport'
import BioReaderReportWorkspace from './BioReaderReportWorkspace'
import TaskDetail from '../tasks/TaskDetail'
import {parseNavigation} from '../projects/projectNavigation'
import type {AnalysisNavigation} from '../projects/analysisViews'
import {taskFixture,workspaceFixture} from '../tasks/taskFixtures'
import {fixedContext,fixedExports} from './testFixtures'

const base='/api/v1/projects/p1',contexts=base+'/bio-reader-reports',narratives=base+'/research-report-narratives'
const selection={kind:'processed',processed_version_id:'data1',annotation_version_id:null} as const
const projection={schema_version:1,title:'Single-cell analysis report',language:'en',finding_version_id:'finding1',
 figure_version_ids:[],root_id:null,expected_revision:0,reader_narrative_id:null}
const sha='a'.repeat(64),binding='b'.repeat(64)
const memberUrl=contexts+'/context1/reports/formal1/members/docx/download'
const props={projectId:'p1',selection,title:'单细胞分析报告',figures:[{id:'fig1',title:'First plot'},{id:'fig2',title:'Second plot'}]}
const members=[{id:'member1',key:'report',role:'docx',format:'docx',sha256:sha,size_bytes:12,download_url:memberUrl}]
const result={narrative:{abstract:'Saved exact interpretation',design_and_data:'Design',quality_control:'Quality',methods_summary:'Methods',
 key_findings:'Findings',limitations:'Limitations',reader_cautions:'Cautions'},figures:[]}
const success={id:'narr1',task:{id:'task1',status:'succeeded'},binding_sha256:binding,bundle_sha256:sha,artifact_sha256:sha,result}

beforeEach(()=>{setApiSession('csrf','account');sessionStorage.clear()})
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession();sessionStorage.clear()})

function mockServer({unknown=false,saved=false}: {unknown?:boolean;saved?:boolean}={}) {
 let fixed:Record<string,unknown>|undefined,exported=saved,attempts=0
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url===contexts+'/prepare'){
   const body=JSON.parse(String(init?.body))
   fixed={id:'context1',...body,report:{...projection,title:body.title,language:body.language},
    source:{source_kind:'bio_report_context',source_id:'context1',sha256:sha,selection:body.selection}}
   if(unknown&&++attempts===1)throw new TypeError('lost response')
   return Response.json(fixed)
  }
  if(url===contexts+'/context1'||url.startsWith(contexts+'/requests/'))return Response.json(fixed)
  if(url===contexts+'/context1/reports?page=1')return Response.json({items:exported?[{
   id:'formal1',task_id:'export1',task:{id:'export1',project_id:'p1',task_type:'research_report',status:'succeeded'},members,
  }]:[],total:Number(exported),page:1,page_size:20})
  if(url===narratives+'/preview')return Response.json({bundle_sha256:sha,binding_sha256:binding,model:'fixture-model',
   reserved_micro_usd:2000,fact_count:0,figures:[],real_calls_enabled:true})
  if(url===narratives||url===narratives+'/narr1')return Response.json(success)
  if(url===base+'/research-reports'){exported=true;return Response.json({id:'formal1'})}
  return Response.json({}, {status:404})
 })
 vi.stubGlobal('fetch',fetch)
 return fetch
}

function click(name:string){fireEvent.click(screen.getByRole('button',{name}))}

it('keeps ordered native figures in the context and requires consent before exporting the report',async()=>{
 const fetch=mockServer()
 render(<BioReaderReport {...props}/>)
 fireEvent.change(screen.getByLabelText('报告语言'),{target:{value:'en'}})
 fireEvent.click(screen.getByLabelText('First plot'))
 fireEvent.click(screen.getByLabelText('Second plot'))
 fireEvent.click(screen.getAllByRole('button',{name:'上移'})[1])
 click('准备详细报告')
 const inspect=await screen.findByRole('button',{name:'生成详细解读'})
 await waitFor(()=>expect(inspect).toHaveProperty('disabled',false))
 fireEvent.click(inspect)
 const confirm=await screen.findByRole('button',{name:'确认材料并生成解读'})
 expect(confirm).toHaveProperty('disabled',true)
 expect(fetch.mock.calls.filter(([url])=>url===narratives)).toHaveLength(0)
 expect(screen.getByRole('button',{name:'生成固定报告与成果包'})).toHaveProperty('disabled',true)
 fireEvent.click(screen.getByRole('checkbox',{name:'我同意发送上述材料以生成详细解读'}))
 fireEvent.click(confirm)
 await screen.findByText('Saved exact interpretation')
 click('生成固定报告与成果包')
 expect((await screen.findByRole('link',{name:/下载.*docx/})).getAttribute('href')).toBe(memberUrl)
 const posts=fetch.mock.calls.filter(([,init])=>init?.method==='POST')
 expect(posts.map(([url])=>url)).toEqual([contexts+'/prepare',narratives+'/preview',narratives,base+'/research-reports'])
 expect(JSON.parse(String(posts[0][1]?.body))).toMatchObject({language:'en',selection:{...selection,figure_version_ids:['fig2','fig1']}})
 expect(JSON.parse(String(posts[1][1]?.body))).toMatchObject({figure_version_ids:[],finding_version_id:'finding1'})
 expect(JSON.parse(String(posts[3][1]?.body))).toMatchObject({figure_version_ids:[],reader_narrative_id:'narr1'})
})

it('recovers the original prepare key after reload and reads the saved files without submitting another narrative',async()=>{
 const fetch=mockServer({unknown:true,saved:true})
 const first=render(<BioReaderReport {...props}/>)
 click('准备详细报告')
 await screen.findByRole('button',{name:'查询原请求结果'})
 first.unmount()
 render(<BioReaderReport {...props}/>)
 fireEvent.click(await screen.findByRole('button',{name:'查询原请求结果'}))
 expect((await screen.findByRole('link',{name:/下载.*docx/})).getAttribute('href')).toBe(memberUrl)
 const prepare=fetch.mock.calls[0]
 const key=new Headers(prepare[1]?.headers).get('Idempotency-Key')
 expect(fetch.mock.calls.some(([url])=>url===contexts+'/requests/'+key)).toBe(true)
 expect(JSON.parse(String(prepare[1]?.body)).selection).toEqual({...selection,figure_version_ids:[]})
 expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1)
 expect(screen.queryByRole('button',{name:'生成详细解读'})).toBeNull()
})

it('cancels the wait for preparation while keeping the original server request recoverable',async()=>{
 let requestKey=''
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url===contexts+'/prepare'){
   requestKey=new Headers(init?.headers).get('Idempotency-Key')!
   return new Promise<Response>((_,reject)=>init?.signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))))
  }
  if(url===contexts+'/requests/'+requestKey)return Response.json(fixedContext({
   title:props.title,language:'zh-CN',selection:{...selection,figure_version_ids:[]},
  }))
  return Response.json(fixedExports())
 })
 vi.stubGlobal('fetch',fetch)
 render(<BioReaderReport {...props}/>)
 click('准备详细报告')
 click('取消等待')
 click('查询原请求结果')
 await screen.findByRole('link',{name:'打开正式报告'})
 expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1)
})

it('isolates saved results when the report language changes or another project opens the same source',async()=>{
 const fetch=mockServer({saved:true})
 const view=render(<BioReaderReport {...props}/>)
 click('准备详细报告')
 await screen.findByRole('link',{name:/下载.*docx/})
 fireEvent.change(screen.getByLabelText('报告语言'),{target:{value:'en'}})
 expect(screen.queryByRole('link',{name:/下载.*docx/})).toBeNull()
 view.rerender(<BioReaderReport {...props} projectId="p2"/>)
 await waitFor(()=>expect(screen.getByRole('button',{name:'准备详细报告'})).toHaveProperty('disabled',false))
 expect(screen.getByLabelText('报告语言')).toHaveProperty('value','zh-CN')
 expect(fetch.mock.calls.filter(([url])=>url.includes('p2'))).toHaveLength(0)
})

const returnNavigation={view:'bio-reader-report',fileId:'',reportContextId:'context1',processedId:'data1',
 tab:'spatial',entry:{requirementVersionId:'req1',scopeItemId:'customer.delivery.word'},intent:'report'} satisfies AnalysisNavigation
const context=fixedContext({title:'Selected annotated report',language:'en',
 selection:{...selection,annotation_version_id:'ann-old',figure_version_ids:['fig2','fig1']}})

it('reopens original report language, figure order and file while keeping edited materials in a draft',async()=>{
 const restored=fixedContext({title:'Saved English report',language:'en',selection:{...selection,figure_version_ids:['fig2','fig1']}})
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(fixedExports())))
 const view=<BioReaderReport {...props} restored={restored}/>
 const first=render(view)
 await screen.findByRole('link',{name:/下载.*docx/})
 click('编辑报告选材草稿')
 fireEvent.change(screen.getByLabelText('报告语言'),{target:{value:'zh-CN'}})
 fireEvent.click(screen.getAllByRole('button',{name:'下移'})[0])
 first.unmount()
 render(view)
 await screen.findByRole('link',{name:/下载.*docx/})
 expect(screen.getByLabelText('报告语言')).toHaveProperty('value','en')
 expect(screen.getAllByRole('listitem').filter(item=>item.textContent?.includes('plot')).map(item=>item.textContent?.slice(0,10))).toEqual(['Second plo','First plot'])
 click('编辑报告选材草稿')
 expect(screen.getByLabelText('报告语言')).toHaveProperty('value','zh-CN')
})

it.each(['ora','gsea_prerank','figure','candidate'])('uses only a fixed Bulk enrichment as the report shortcut (%s)',async(kind)=>{
 const base=fixedContext({title:'Bulk report',language:'en',selection:{kind:'bulk',delivery:{
  comparison_version_id:'main1',result_version_ids:['attachment1'],language:'en',facts_digest:sha,selections:[],sensitivity:null,evidence:[],
 }}})
 const fixed={...base,source:{...base.source,supporting_sources:[{kind:'bulk',delivery:base.selection.kind==='bulk'&&base.selection.delivery,
  facts:{enrichments:['ora','gsea_prerank'].includes(kind)?[{kind,version_id:'attachment1'}]:[]}}]}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/reports?page=1')?fixedExports():fixed)))
 render(<BioReaderReportWorkspace projectId="p1" navigation={{view:'bio-reader-report',fileId:'',reportContextId:'context1',resultVersionId:'attachment1'}}/>)
 if(['ora','gsea_prerank'].includes(kind)){
  expect((await screen.findByRole('link',{name:'返回原分析选材'})).getAttribute('href')).toContain('resultVersionId=attachment1')
 }else{
  expect((await screen.findByRole('alert')).textContent).toContain('固定来源身份不匹配')
  expect(screen.queryByRole('link',{name:'返回原分析选材'})).toBeNull()
 }
})

it('preserves submitted demand and Bulk enrichment source during a round trip through the interpretation task',async()=>{
 const base=fixedContext({title:'Bulk report',language:'en',selection:{kind:'bulk',delivery:{
  comparison_version_id:'main1',result_version_ids:['ora1'],language:'en',facts_digest:sha,selections:[],sensitivity:null,evidence:[],
 }}})
 const fixed={...base,source:{...base.source,supporting_sources:[{kind:'bulk',delivery:base.selection.kind==='bulk'&&base.selection.delivery,
  facts:{enrichments:[{kind:'ora',version_id:'ora1'}]}}]}}
 const task={...taskFixture,id:'task1',task_type:'reader_report_narrative',status:'succeeded',display_status:'succeeded',phase:'interpret',
  reason_code:null,error_code:null,input_version:{kind:'reader_report_narrative',workflow_version:'reader_report_narrative_v1',
   narrative_id:'narr1',binding_sha256:binding,bundle_sha256:sha}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
  if(url.endsWith('/task1/workspace'))return Response.json({...workspaceFixture,task,wait:null,allowed_actions:[],
   source:{file_id:null,filename:'Selected report',analysis_run_id:null,is_current:true},
   artifacts:{...workspaceFixture.artifacts,bio_reader_report_context_id:'context1'}})
  if(url===narratives+'/narr1')return Response.json(success)
  return Response.json(url.endsWith('/reports?page=1')?{items:[],total:0,page:1,page_size:20}:fixed)
 }))
 const navigation={...returnNavigation,processedId:undefined,tab:undefined,resultVersionId:'ora1',reportTaskId:'task1'}
 const start=render(<BioReaderReportWorkspace projectId="p1" navigation={navigation}/>)
 const taskLink=await screen.findByRole('link',{name:'查看任务'})
 const taskRoute=parseNavigation(taskLink.getAttribute('href')!)!
 expect(taskRoute.taskDetailView).toBe('result')
 start.unmount()
 const detail=render(<TaskDetail projectId="p1" taskId="task1" onChanged={()=>{}} view="result"
  taskReportReturn={taskRoute.taskReportReturn}/>)
 const back=await screen.findByRole('link',{name:'返回分析报告'})
 const returned=parseNavigation(back.getAttribute('href')!)!.analysisNavigation
 expect(returned).toMatchObject({entry:navigation.entry,intent:'report',resultVersionId:'ora1',reportTaskId:'task1'})
 detail.unmount()
 render(<BioReaderReportWorkspace projectId="p1" navigation={returned}/>)
 expect((await screen.findByRole('link',{name:'返回原分析选材'})).getAttribute('href')).toContain('resultVersionId=ora1')
})

it('opens exact saved files and returns the confirmed requirement and fixed annotation to the source',async()=>{
 const fetch=vi.fn(async(url:string)=>Response.json(url.endsWith('/reports?page=1')?fixedExports():context))
 vi.stubGlobal('fetch',fetch)
 render(<BioReaderReportWorkspace projectId="p1" navigation={returnNavigation}/>)
 const link=await screen.findByRole('link',{name:'返回原分析选材'})
 const href=link.getAttribute('href')!
 expect(Object.fromEntries(new URLSearchParams(href.slice(1)))).toMatchObject({
  view:'bio-result',processed:'data1',tab:'spatial',reportContext:'context1',requirement:'req1',scope:'customer.delivery.word',intent:'report',
 })
 expect((await screen.findByRole('link',{name:/下载.*docx/})).getAttribute('href')).toBe(memberUrl)
 const formal=screen.getByRole('link',{name:'打开正式报告'}).getAttribute('href')!
 expect(new URLSearchParams(formal.slice(1)).get('reportReturn')).toContain('requirement=req1')
 const exportTask=parseNavigation(screen.getByRole('link',{name:'查看任务'}).getAttribute('href')!)
 expect(exportTask?.taskReportReturn).toMatchObject({reportContextId:'context1',processedId:'data1',entry:returnNavigation.entry})
 expect(fetch.mock.calls.map(([url])=>url)).toEqual([contexts+'/context1',contexts+'/context1/reports?page=1'])
})

it('shows a source or project mismatch without starting a replacement selection',async()=>{
 const fetch=vi.fn(async(url:string)=>url.includes('/other/')?Response.json({}, {status:404}):Response.json(context))
 vi.stubGlobal('fetch',fetch)
 const view=render(<BioReaderReportWorkspace projectId="p1" navigation={{...returnNavigation,processedId:'wrong'}}/>)
 expect((await screen.findByRole('alert')).textContent).toContain('固定来源身份不匹配')
 view.rerender(<BioReaderReportWorkspace projectId="other" navigation={returnNavigation}/>)
 await screen.findByRole('alert')
 expect(screen.queryByRole('button',{name:'准备详细报告'})).toBeNull()
 expect(fetch.mock.calls.map(([url])=>url)).toEqual([contexts+'/context1','/api/v1/projects/other/bio-reader-reports/context1'])
})

it.each(['context1','unrelated'])('restores a task only when the server binds it to the selected context (%s)',async(taskContext)=>{
 const task={...taskFixture,id:'task1',task_type:'reader_report_narrative',status:'succeeded',display_status:'succeeded',phase:'interpret',
  reason_code:null,error_code:null,input_version:{kind:'reader_report_narrative',workflow_version:'reader_report_narrative_v1',
   narrative_id:'narr1',binding_sha256:binding,bundle_sha256:sha}}
 const fetch=vi.fn(async(url:string)=>{
  if(url.endsWith('/task1/workspace'))return Response.json({...workspaceFixture,task,wait:null,allowed_actions:[],
   source:{file_id:null,filename:'Selected report',analysis_run_id:null,is_current:true},
   artifacts:{...workspaceFixture.artifacts,bio_reader_report_context_id:taskContext}})
  if(url===narratives+'/narr1')return Response.json(success)
  return Response.json(url.endsWith('/reports?page=1')?{items:[],total:0,page:1,page_size:20}:context)
 })
 vi.stubGlobal('fetch',fetch)
 render(<BioReaderReportWorkspace projectId="p1" navigation={{...returnNavigation,reportTaskId:'task1'}}/>)
 if(taskContext==='context1'){
  await screen.findByText('Saved exact interpretation')
  expect(fetch.mock.calls.some(([url])=>url===narratives+'/narr1')).toBe(true)
 }else{
  expect((await screen.findByRole('alert')).textContent).toContain('固定来源身份不匹配')
  expect(fetch.mock.calls.some(([url])=>url.startsWith(narratives))).toBe(false)
 }
})
