import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ReviewSciencePanel from './ReviewSciencePanel'
import {setLocale} from '../../shared/i18n'
import {taskFixture,preparationSourceFixture} from '../tasks/taskFixtures'
const round={id:'r1',revision:2,synthetic:true,sources:[{id:'s1',label:'Reviewer 1'}],items:[{id:'i1',source_id:'s1',number:1,original_text:'Redraw this figure.'}]} as never
const context={round_id:'r1',plan_revision:2,manuscript:{id:'m1',revision:1,version_id:'v1'},expected_current_revision:1,project_type:'sci',output_language:'en',locations:[],citation_candidates:[],evidence:[],grounded_plans:[],constraints:{}}
afterEach(()=>{cleanup();setLocale('zh-CN');vi.useRealTimers();vi.unstubAllGlobals()})
it('fixes the selected historical run/config and preserves draft and retry key after unknown projection response',async()=>{
 const posts:{url:string;body:Record<string,unknown>;key:string|null}[]=[]
 const link={id:'l1',round_id:'r1',item_id:'i1',plan_revision:2,input_snapshot:{purpose:'projection',creation_kind:'projection',creation_request:{file_id:'f1',analysis_run_id:'old-run',figure_config_version_id:'old-config'}},task:{...taskFixture,task_type:'figure_projection',status:'queued',display_status:'queued',input_version:{kind:'dataset_analysis',setup_revision:1,output_language:'zh-CN',source:{...preparationSourceFixture,kind:'prepared_dataset_version',parent_dataset_id:'raw',parent_dataset_version:1,transform_version:'excel_prepare_v1'}}},result:{result_analysis_run_id:null,result_figure_id:null,result_report_id:null,execution_receipt:null,available:false},created_at:taskFixture.created_at}
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
 if(init?.method==='POST'){posts.push({url,body:JSON.parse(String(init.body)),key:new Headers(init.headers).get('Idempotency-Key')});if(posts.length===1)return new Promise<Response>(()=>{});return Response.json(link)}
 return Response.json(url.endsWith('/science')?{round_id:'r1',plan_revision:2,task_links:posts.length>=2?[link]:[],analysis_adoptions:[],pending:[]}:url.endsWith('/revision-context')?context:url.includes('/tasks?')?{project_id:'p1',items:[],total:0,page:1,page_size:10}:url.endsWith('/analysis-runs')?{items:[{id:'new-run',setup_revision:2,completed_at:'new'},{id:'old-run',setup_revision:1,completed_at:'old'}]}:url.endsWith('/figure-workbench')?{configurations:[{version:{id:'new-config',revision:2,config:{figure_kind:'line',style:{title:'New'}}},versions:[{version:{id:'old-config',revision:1,config:{figure_kind:'line',style:{title:'Old'}}}},{version:{id:'new-config',revision:2,config:{figure_kind:'line',style:{title:'New'}}}}]}]}:url.endsWith('/analysis-setup')?null:{items:[{id:'f1',filename:'confirmed.xlsx',file_type:'xlsx',parse_status:'parsed'}],total:1,page:1,page_size:10})}))
 const open=vi.fn(),props={projectId:'p1',round,active:true,disabled:false,onOpenTask:open,onChanged:vi.fn(),expanded:true}
 const ui=render(<ReviewSciencePanel {...props}/>);await screen.findByText('confirmed.xlsx')
 fireEvent.change(screen.getByLabelText('科学任务对应意见'),{target:{value:'i1'}});fireEvent.change(screen.getByLabelText('已确认分析配置的数据文件'),{target:{value:'f1'}})
 await screen.findByRole('option',{name:/old-run/});fireEvent.change(screen.getByLabelText('固定分析结果版本'),{target:{value:'old-run'}})
 await screen.findByRole('option',{name:/old-config/});fireEvent.change(screen.getByLabelText('固定图表配置版本'),{target:{value:'old-config'}})
 fireEvent.change(screen.getByLabelText('采用新分析的理由'),{target:{value:'保持草稿'}})
 expect(posts).toHaveLength(0)
 vi.useFakeTimers();fireEvent.click(screen.getByRole('button',{name:'创建关联的本地投影任务'}));await act(async()=>{await vi.advanceTimersByTimeAsync(15001)});vi.useRealTimers();expect(posts).toHaveLength(1);await screen.findByRole('alert')
 ui.rerender(<ReviewSciencePanel {...props} active={false}/>);ui.rerender(<ReviewSciencePanel {...props}/>);
 expect(screen.getByLabelText('固定分析结果版本')).toHaveProperty('value','old-run');expect(screen.getByLabelText('采用新分析的理由')).toHaveProperty('value','保持草稿')
 fireEvent.click(screen.getByRole('button',{name:'创建关联的本地投影任务'}));await waitFor(()=>expect(posts).toHaveLength(2))
 expect(posts[0]).toEqual(posts[1]);expect(posts[0].body).toEqual({plan_revision:2,item_id:'i1',file_id:'f1',analysis_run_id:'old-run',figure_config_version_id:'old-config'})
 fireEvent.click(await screen.findByRole('button',{name:'查看关联实际任务'}));expect(open).toHaveBeenCalledWith('t1')
 expect(posts.every(p=>p.url.endsWith('/projection-tasks'))).toBe(true)
 act(()=>setLocale('en'));expect(screen.getByLabelText('Fixed analysis result version')).toHaveProperty('value','old-run');expect(screen.getByRole('button',{name:'Create linked local projection task'})).toBeTruthy();expect(screen.getByText(/Local projection creates no PNG/)).toBeTruthy()
})
