import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ReviewSciencePanel from './ReviewSciencePanel'
import RevisionPanel from './RevisionPanel'
import {taskFixture,preparationSourceFixture} from '../tasks/taskFixtures'
import {setLocale} from '../../shared/i18n'
const round={id:'r1',revision:2,synthetic:true,sources:[{id:'s1',label:'Reviewer'}],items:[{id:'i1',source_id:'s1',number:1,original_text:'Redraw the figure.'}]} as never
const source={id:'new',kind:'figure',label:'Saved B plot',sha256:'a'.repeat(64),content:{title:'B',caption:'Actual saved caption.'}}
const adoption={id:'fa1',round_id:'r1',item_id:'i1',plan_revision:2,input_snapshot:{},source,supersedes_figure_id:'old',affected_locations:[{kind:'figure',id:'old'}],created_at:taskFixture.created_at}
const context={round_id:'r1',plan_revision:2,manuscript:{id:'m1',revision:1,version_id:'v1'},expected_current_revision:3,project_type:'sci',output_language:'en',locations:[{kind:'figure',id:'old',section_id:'main',section_title:'Results',text:'Old plot caption.'}],citation_candidates:[],evidence:[],grounded_plans:[],constraints:{},figure_adoptions:[adoption]}
afterEach(()=>{cleanup();setLocale('zh-CN');vi.unstubAllGlobals()})
it('explicitly saves a successful plot adoption with fixed old figure and parent CAS without adopting manuscript',async()=>{
 const posts:{url:string;body:Record<string,unknown>}[]=[]
 const link={id:'plot-link',round_id:'r1',item_id:'i1',plan_revision:2,input_snapshot:{purpose:'plot'},task:{...taskFixture,task_type:'figure_workbench',input_version:{kind:'dataset_analysis',setup_revision:1,output_language:'en',source:{...preparationSourceFixture,kind:'prepared_dataset_version',parent_dataset_id:'raw',parent_dataset_version:1,transform_version:'excel_prepare_v1'}},status:'succeeded',display_status:'succeeded',result_figure_id:'new'},result:{result_analysis_run_id:null,result_figure_id:'new',result_report_id:null,execution_receipt:null,available:true},created_at:taskFixture.created_at}
 const legacy={...link,id:'legacy-link',task:{...taskFixture,status:'succeeded',display_status:'succeeded',result_figure_id:'legacy-fixed-number'},result:{...link.result,result_figure_id:'legacy-fixed-number'}}
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){posts.push({url,body:JSON.parse(String(init.body))});return Response.json(adoption)}return Response.json(url.endsWith('/science')?{round_id:'r1',plan_revision:2,task_links:[link,legacy],analysis_adoptions:[],figure_adoptions:[],pending:[]}:url.endsWith('/revision-context')?context:url.includes('/tasks?')?{project_id:'p1',items:[],total:0,page:1,page_size:10}:{items:[],total:0,page:1,page_size:10})}))
 render(<ReviewSciencePanel expanded projectId="p1" round={round} active disabled={false} onOpenTask={vi.fn()} onChanged={vi.fn()}/>);
 await screen.findByLabelText('采用的成功绘图任务');fireEvent.change(screen.getByLabelText('科学任务对应意见'),{target:{value:'i1'}})
 expect(Array.from(screen.getByLabelText('采用的成功绘图任务').querySelectorAll('option')).some(o=>o.value==='legacy-link')).toBe(false)
 fireEvent.change(screen.getByLabelText('采用的成功绘图任务'),{target:{value:'plot-link'}});fireEvent.change(screen.getByLabelText('明确替代的固定旧图'),{target:{value:'old'}});fireEvent.change(screen.getByLabelText('采用新图的理由'),{target:{value:'Use saved B pixels.'}})
 fireEvent.click(screen.getByRole('button',{name:'保存新图采用关系'}));await waitFor(()=>expect(posts).toHaveLength(1))
 expect(posts[0].url).toContain('/figure-adoptions');expect(posts[0].body).toMatchObject({plan_revision:2,expected_current_revision:3,item_id:'i1',task_link_id:'plot-link',supersedes_figure_id:'old',reason:'Use saved B pixels.'})
 expect(screen.getByText(/新图已固定/)).toBeTruthy()
})
it('requires explicit revision selection and preserves chosen figure when view changes',async()=>{
 const posts:Record<string,unknown>[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){posts.push(JSON.parse(String(init.body)));return Response.json({...context,actual_changes:[],unexecuted:[],public_issues:[],constraint_issues:[],can_adopt:false,preview_sha256:'b'.repeat(64),synthetic:true})}return Response.json(url.endsWith('/revision-context')?context:{items:[]})}))
 const props={projectId:'p1',round,active:true,disabled:false,onOpenTask:vi.fn()};const ui=render(<RevisionPanel {...props}/>);fireEvent.click(screen.getByRole('button',{name:'执行本批修改'}));await screen.findByRole('checkbox',{name:/本批采用新图/})
 const button=screen.getByRole('button',{name:'预览实际差异与检查'});expect(button).toHaveProperty('disabled',true)
 fireEvent.click(screen.getByRole('checkbox',{name:/本批采用新图/}));ui.rerender(<RevisionPanel {...props} active={false}/>);ui.rerender(<RevisionPanel {...props}/>);expect(screen.getByRole('checkbox',{name:/本批采用新图/})).toHaveProperty('checked',true)
 fireEvent.click(button);await waitFor(()=>expect(posts).toHaveLength(1));expect(posts[0]).toMatchObject({figure_adoption_ids:['fa1'],operations:[],expected_current_revision:3})
})
