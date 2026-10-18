import {act, cleanup, fireEvent, render, screen} from '@testing-library/react'
import {afterEach, expect, test, vi} from 'vitest'
import StatisticsResults from './StatisticsResults'
import {isTask, isWorkspace} from '../tasks/taskTypes'
import {taskFixture,workspaceFixture,usageFixture,eventsFixture} from '../tasks/taskFixtures'
import TaskDetail from '../tasks/TaskDetail'
import {correlationResult} from './correlationFixtures'
import {validStatisticsTaskResult} from './statisticsTaskContracts'
import {setLocale} from '../../shared/i18n'

vi.mock('../figures/BoxplotFigure',()=>({default:()=>null}))
vi.mock('./ConfirmedRunArtifacts',()=>({default:()=>null}))
const base='/api/v1/projects/p1/files/f1'
const selection={task_type:'descriptive_boxplot' as const,sheet_name:'Data',numeric_column:'A',group_column:null,unit:'',missing_policy:'exclude_selected_missing' as const}
const summary={n:3,mean:2,std:1,min:1,q1:1.5,median:2,q3:2.5,max:3,iqr:1,warnings:[]}
const result={id:'r1',file_id:'f1',filename:'Synthetic.xlsx',source_sha256:'a'.repeat(64),setup_revision:1,selection,check:{ready:true,row_count:3,valid_count:3,excluded_count:0,groups:[],issues:[],warnings:[]},numeric_name:'Value',group_name:null,engine:{id:'descriptive_statistics_v1',python_version:'3.11'},started_at:'2026-10-18T01:00:00Z',completed_at:'2026-10-18T01:00:01Z',overall:summary,groups:[]}
const input={kind:'statistics_compute',setup_revision:1,output_language:'zh-CN',source:null,analysis_plan_id:null,workflow_version:'statistics_compute_v1'}
const queued={...taskFixture,task_type:'statistics_compute',status:'queued',display_status:'queued',phase:'compute',input_version:input,reason_code:null,error_code:null,result_analysis_run_id:null,execution_receipt:null}
const succeeded={...queued,status:'succeeded',display_status:'succeeded',revision:4,result_analysis_run_id:'r1',execution_receipt:{schema_version:1,status:'succeeded',nodes:[],result_sha256:'b'.repeat(64)}}
const props={base,savedRevision:1,savedSelection:selection,fieldsMatch:true,disabled:false,onBusyChange:vi.fn()}
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();vi.useRealTimers();sessionStorage.clear();setLocale('zh-CN')})

test('statistics task input and exact saved artifact are validated',()=>{
 expect(isTask(queued,'p1')).toBe(true)
 expect(isTask({...queued,input_version:{...input,workflow_version:'unknown'}},'p1')).toBe(false)
 const workspace={task:succeeded,source:{file_id:'f1',filename:'Synthetic.xlsx',analysis_run_id:null,is_current:true},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null,analysis:result}}
 expect(isWorkspace(workspace,'p1','t1')).toBe(true)
 expect(isWorkspace({...workspace,artifacts:{...workspace.artifacts,analysis:{...result,id:'foreign'}}},'p1','t1')).toBe(false)
})

test('202 receipt is observed as a task and only its exact result is read',async()=>{
 vi.useFakeTimers()
 let reads=0
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST')return Response.json(queued,{status:202})
  if(url===base+'/analysis-result')return Response.json({current_revision:1,is_current:false,result:null,active_task:null,execution_verification:null})
  if(url==='/api/v1/tasks/t1')return Response.json(++reads===1?{...queued,status:'running',display_status:'computing'}:succeeded)
  if(url===base+'/analysis-runs/r1')return Response.json(result)
  throw new Error('Unexpected '+url)
 });vi.stubGlobal('fetch',fetch)
 render(<StatisticsResults {...props}/>);await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'执行描述统计'}));await act(async()=>{})
 expect(screen.getByText('统计任务正在计算；离开页面不会取消任务。')).toBeTruthy()
 expect(screen.queryByRole('table',{name:'描述统计结果'})).toBeNull()
 await act(async()=>{vi.advanceTimersByTime(2000)})
 expect(screen.getByRole('table',{name:'描述统计结果'})).toBeTruthy()
 const post=fetch.mock.calls.find(([,init])=>init?.method==='POST')!
 expect(JSON.parse(String(post[1]?.body)).idempotency_key).toBeTruthy()
 expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1)
})

test('returning to the page resumes active task without submitting a new request',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url===base+'/analysis-result'?{current_revision:1,is_current:false,result:null,active_task:succeeded,execution_verification:null}:result)))
 render(<StatisticsResults {...props}/>);await act(async()=>{})
 expect(screen.getByRole('table',{name:'描述统计结果'})).toBeTruthy()
 expect(vi.mocked(fetch).mock.calls.some(([,init])=>init?.method==='POST')).toBe(false)
})

test('lost submission receipt retains one key across remount and explicit reconciliation',async()=>{
 let posts=0
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){if(++posts===1)throw new TypeError('offline');return Response.json(queued,{status:202})}
  return Response.json(url===base+'/analysis-result'?{current_revision:1,is_current:false,result:null,active_task:null,execution_verification:null}:queued)
 });vi.stubGlobal('fetch',fetch)
 let view=render(<StatisticsResults {...props}/>);await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'执行描述统计'}));await act(async()=>{})
 view.unmount();view=render(<StatisticsResults {...props}/>);await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'核实并继续同一统计请求'}));await act(async()=>{})
 const calls=fetch.mock.calls.filter(([,init])=>init?.method==='POST')
 expect(calls).toHaveLength(2)
 expect(calls[0][1]?.body).toBe(calls[1][1]?.body)
})

test('a task for another revision never publishes or fetches its result',async()=>{
 const fetch=vi.fn(async(_url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{...succeeded,input_version:{...input,setup_revision:2}}:{current_revision:1,is_current:false,result:null,active_task:null,execution_verification:null},{status:init?.method==='POST'?202:200}))
 vi.stubGlobal('fetch',fetch);render(<StatisticsResults {...props}/>);await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'执行描述统计'}));await act(async()=>{})
 expect(screen.queryByRole('table')).toBeNull()
 expect(fetch.mock.calls.some(([url])=>url===base+'/analysis-runs/r1')).toBe(false)
})

test('a free statistical task displays its exact artifact without querying model usage',async()=>{
 const workspace={task:succeeded,source:{file_id:'f1',filename:'Synthetic.xlsx',analysis_run_id:null,is_current:true},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null,analysis:result}}
 const fetch=vi.fn(async(url:string)=>Response.json(url.includes('/events')?{task_id:'t1',items:[],next_cursor:0,has_more:false}:workspace))
 vi.stubGlobal('fetch',fetch);render(<TaskDetail projectId="p1" taskId="t1" onChanged={()=>{}}/>);await act(async()=>{})
 expect(screen.getByRole('article',{name:'此任务的统计结果'})).toBeTruthy()
 expect(screen.getByText('此统计任务在本地执行，不调用付费模型。')).toBeTruthy()
 expect(fetch.mock.calls.some(([url])=>url.includes('/model-usage'))).toBe(false)
 expect(document.body.textContent).not.toContain('b'.repeat(64))
})

test('exact result verification rejects crossed method, source, language and plan',()=>{
 const context={base,revision:2,source:correlationResult.source,plan:correlationResult.analysis_plan,selection:correlationResult.selection,language:'en' as const}
 expect(validStatisticsTaskResult(correlationResult,context,correlationResult.id)).toBe(true)
 expect(validStatisticsTaskResult(correlationResult,{...context,language:'zh-CN'},correlationResult.id)).toBe(false)
 expect(validStatisticsTaskResult(correlationResult,{...context,plan:{...context.plan,sha256:'f'.repeat(64)}},correlationResult.id)).toBe(false)
 expect(validStatisticsTaskResult(correlationResult,{...context,source:{...context.source,dataset_id:'foreign'}},correlationResult.id)).toBe(false)
 expect(validStatisticsTaskResult(correlationResult,{...context,selection:{...context.selection,method:'spearman'}},correlationResult.id)).toBe(false)
})

test('late exact result cannot replace a newer configuration',async()=>{
 let finish!:(response:Response)=>void
 const fetch=vi.fn(async(url:string)=>{
  if(url===base+'/analysis-runs/r1')return new Promise<Response>(resolve=>{finish=resolve})
  return Response.json({current_revision:1,is_current:false,result:null,active_task:succeeded,execution_verification:null})
 });vi.stubGlobal('fetch',fetch)
 const view=render(<StatisticsResults {...props}/>);await act(async()=>{})
 fetch.mockImplementation(async()=>Response.json({current_revision:2,is_current:false,result:null,active_task:null,execution_verification:null}))
 view.rerender(<StatisticsResults {...props} savedRevision={2}/>);await act(async()=>{})
 await act(async()=>finish(Response.json(result)))
 expect(screen.queryByRole('table')).toBeNull()
})

test('an older failed active task cannot erase the key of a lost submission',async()=>{
 let posts=0
 const old={...queued,id:'older-task',status:'failed',display_status:'failed',error_code:'numeric_timeout'}
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){if(++posts===1)throw new TypeError('offline');return Response.json(queued,{status:202})}
  return Response.json(url===base+'/analysis-result'?{current_revision:1,is_current:false,result:null,active_task:posts?old:null,execution_verification:null}:queued)
 });vi.stubGlobal('fetch',fetch)
 let view=render(<StatisticsResults {...props}/>);await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'执行描述统计'}));await act(async()=>{})
 view.unmount();view=render(<StatisticsResults {...props}/>);await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'核实并继续同一统计请求'}));await act(async()=>{})
 const calls=fetch.mock.calls.filter(([,init])=>init?.method==='POST')
 expect(calls).toHaveLength(2);expect(calls[0][1]?.body).toBe(calls[1][1]?.body)
})

test('retrying a failed task in its details resumes observation and reads the exact saved run',async()=>{
 vi.useFakeTimers()
 const failed={...queued,status:'failed',display_status:'failed',error_code:'task_worker_interrupted'}
 let retried=false,reads=0
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url===base+'/analysis-result')return Response.json({current_revision:1,is_current:false,result:null,active_task:failed,execution_verification:null})
  if(url==='/api/v1/tasks/t1/resume'&&init?.method==='POST'){retried=true;return Response.json({...queued,revision:4})}
  if(url==='/api/v1/tasks/t1/workspace')return Response.json({task:retried?{...queued,revision:4}:failed,source:{file_id:'f1',filename:'Synthetic.xlsx',analysis_run_id:null,is_current:true},wait:null,allowed_actions:retried?[]:['retry'],artifacts:{figure:null,explanation:null,report:null}})
  if(url==='/api/v1/tasks/t1')return Response.json(++reads===1?{...queued,revision:4}:{...succeeded,revision:5})
  if(url.includes('/events'))return Response.json({task_id:'t1',items:[],next_cursor:0,has_more:false})
  if(url===base+'/analysis-runs/r1')return Response.json(result)
  throw new Error('Unexpected '+url)
 });vi.stubGlobal('fetch',fetch)
 render(<StatisticsResults {...props}/>);await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'查看统计任务详情'}));await act(async()=>{})
 fireEvent.click(screen.getByRole('button',{name:'重试原任务'}));await act(async()=>{})
 expect(fetch.mock.calls.some(([url])=>url==='/api/v1/tasks/t1')).toBe(true)
 await act(async()=>{vi.advanceTimersByTime(2000)})
 expect(screen.getByRole('table',{name:'描述统计结果'})).toBeTruthy()
 expect(fetch.mock.calls.filter(([url])=>url===base+'/analysis-runs/r1')).toHaveLength(1)
 expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1)
})

test.each(['zh-CN','en'] as const)('expired cloud action explains a single retrieval without a renewed window in %s',async locale=>{
 setLocale(locale)
 const workspace={...workspaceFixture,task:{...taskFixture,reason_code:'observation_expired',error_code:'model_observation_expired'},wait:{...workspaceFixture.wait,kind:'remote_observation',reason_code:'observation_expired',error_code:'model_observation_expired'}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/events')?eventsFixture:url.includes('/model-usage')?usageFixture:workspace)))
 render(<TaskDetail projectId="p1" taskId="t1" onChanged={()=>{}}/>);await act(async()=>{})
 expect(screen.getByRole('button',{name:locale==='en'?'Check the original receipt once':'查询原回执一次'})).toBeTruthy()
 expect(screen.getByText(locale==='en'?'Authorize one retrieval of the original cloud receipt. This does not extend the original deadline or authorize another generation charge.':'授权单次查询原云端回执；不延长原观察期限，也不授权重新生成费用。')).toBeTruthy()
 expect(document.body.textContent).not.toContain(locale==='en'?'another 20 minutes':'重新观察最多20分钟')
})
