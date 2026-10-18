import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import RequirementReview from './RequirementReview'
import {isRequirementReview} from './requirementsApi'
import {isTask,isWorkspace,sameInputVersion} from '../tasks/taskTypes'
import {taskFixture} from '../tasks/taskFixtures'
import {isResearchIntent} from './recommendationApi'
import {setLocale} from '../../shared/i18n'

const research={question:'Compare external study',output_language:'zh-CN',population:'',study_design:'',observation_unit:'',observation_structure:'unknown',relationship_description:'',output_requirements:''}
const materialSource={kind:'original',file_id:'f1',filename:'outside.png',file_type:'png',source_sha256:'a'.repeat(64),size_bytes:100,original_download_url:'/api/v1/projects/p1/files/f1/download',version_id:null,version:null,sha256:'a'.repeat(64),object_download_url:null,review_status:'not_reviewed'}
const material={id:'private-e1',evidence_id:'series',version:1,previous_version_id:null,project_id:'p1',file_id:'f1',created_at:taskFixture.created_at,sha256:'b'.repeat(64),title:'External image',source_description:'Unknown',intended_use:'reference',original_data:'unavailable',user_note:'',limitations:'No raw data',source:materialSource,items:[],verification_status:'external_not_recomputed',computed_by_system:false,included_in_reports:false}
const input={kind:'analysis_plan',source:null,workflow_version:'analysis_plan_v4'} as const
const task={...taskFixture,task_type:'analysis_plan',status:'waiting_input',display_status:'waiting_input',phase:'plan',input_version:input}
const review={task,source:null,input_version:input,input_kind:'materials',evidence_versions:[material],checkpoint_id:'private-checkpoint',wait_id:'private-wait',plan_revision:1,selection:null,research_request:research,check:{rules_version:'analysis_plan_rules_v4',research_missing:['source','selection','study_design'],data_check:null,limitations:[]},resolutions:{},recommendation_ref:null,origin_recommendation_ref:null,result:null,continuation:null}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})

it('accepts material-only task/workspace without fabricating dataset and rejects cross-project materials',()=>{
 expect(isTask(task,'p1')).toBe(true)
 expect(sameInputVersion(input,input)).toBe(true)
 expect(isRequirementReview(review,'p1')).toBe(true)
 expect(isRequirementReview({...review,evidence_versions:[{...material,project_id:'other'}]},'p1')).toBe(false)
 expect(isRequirementReview({...review,selection:{task_type:'descriptive_boxplot'}},'p1')).toBe(false)
 expect(isWorkspace({task,source:{file_id:null,filename:'',analysis_run_id:null,is_current:true,material_versions:[material]},allowed_actions:['revise'],wait:{id:'private-wait',kind:'analysis_plan_input',status:'open',task_revision:task.revision,input_version:input,reason_code:null,error_code:null,created_at:task.created_at,resolved_at:null},artifacts:{figure:null,explanation:null,report:null}},'p1',task.id)).toBe(true)
})
it('supplements research through the real revise contract and never presents approval without data',async()=>{
 const fetch=vi.fn(async(url:string,_init?:RequestInit)=>url.endsWith('/decisions')?Response.json({...task,status:'queued',revision:2}):Response.json(review));vi.stubGlobal('fetch',fetch)
 render(<RequirementReview projectId="p1" taskId={task.id}/> )
 await screen.findByText('研究材料；尚无可计算数据。')
 expect(screen.queryByRole('button',{name:'确认并发布分析计划'})).toBeNull()
 expect(screen.queryByText('private-checkpoint')).toBeNull()
 fireEvent.change(screen.getByLabelText('研究设计'),{target:{value:'Observational'}})
 fireEvent.click(screen.getByRole('button',{name:'补充资料并重新检查'}))
 await waitFor(()=>expect(fetch.mock.calls.filter(([u])=>u.endsWith('/decisions'))).toHaveLength(1))
 const body=JSON.parse(String(fetch.mock.calls.find(([u])=>u.endsWith('/decisions'))![1]?.body))
 expect(body).toMatchObject({operation:'revise',selection:null,wait_id:'private-wait',checkpoint_id:'private-checkpoint',input_version:input,research_request:{study_design:'Observational'}})
 expect(fetch.mock.calls.some(([u])=>u.includes('/statistics'))).toBe(false)
})
it('ignores late reads after switching task identities',async()=>{
 let resolve!:(value:Response)=>void
 vi.stubGlobal('fetch',vi.fn((url:string)=>url.includes('/tasks/old/')?new Promise<Response>(r=>{resolve=r}):Promise.resolve(Response.json({...review,task:{...task,id:'new'}}))))
 const view=render(<RequirementReview projectId="p1" taskId="old"/> )
 view.rerender(<RequirementReview projectId="p1" taskId="new"/> )
 await screen.findByDisplayValue('Compare external study')
 await act(async()=>resolve(Response.json({...review,task:{...task,id:'old'},research_request:{...research,question:'Stale original'}})))
 expect(screen.queryByDisplayValue('Stale original')).toBeNull()
})
it('validates exact outbound Unicode evidence, field scope and supported charts',()=>{
 const intent={objective:'Estimate',material_relationship:'same table',field_roles:[{column:'A',role:'outcome'}],population_conditions:['age ≥ 18'],chart_preferences:['boxplot'],explanation_focus:[],output_language:'zh-CN',missing_information:[],conflicts:[],evidence:[{start:1,end:3,quote:'年龄'}]}
 expect(isResearchIntent(intent,['A'],'📊年龄 summary','zh-CN')).toBe(true)
 expect(isResearchIntent({...intent,evidence:[{start:0,end:2,quote:'年龄'}]},['A'],'📊年龄 summary','zh-CN')).toBe(false)
 expect(isResearchIntent(intent,['B'],'📊年龄 summary','zh-CN')).toBe(false)
 expect(isResearchIntent({...intent,chart_preferences:['cox']},['A'],'📊年龄 summary','zh-CN')).toBe(false)
})
