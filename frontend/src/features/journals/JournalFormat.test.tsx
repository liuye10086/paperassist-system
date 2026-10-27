import {cleanup,render,screen,fireEvent,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {isRequirement} from './formatContracts'
import {clearApiSession} from '../../shared/api/client'
import JournalWorkspace from './JournalWorkspace'
import {taskFixture} from '../tasks/taskFixtures'
import {isTask,isTaskPage,isWorkspace,sameInputVersion,taskDisplayName,taskPhaseName,type InputVersion} from '../tasks/taskTypes'
const sha='a'.repeat(64)
export const formatInput={kind:'journal_format_check',check_id:'c1',target_id:'target1',guide_id:'g1',requirements_version:sha,manuscript_version_id:'v1',check_version:1,workflow_version:'journal_format_check_v1'} as const
export const formatTask={...taskFixture,task_type:'journal_format_check',phase:'verify',status:'succeeded',display_status:'succeeded',reason_code:null,error_code:null,input_version:formatInput}
const p={id:'p-old',project_id:'p1',name:'synthetic Journal',source_type:'synthetic',source_text:'original',source_url:'',official_url:'',source_status:'available',verified_on:'2026-10-23',conditions:'offline',permission:'fixture',synthetic:true,verification_level:'synthetic_material_only',created_at:'2026-10-23T00:00:00Z',fields:{}}
const rule={id:'r1',key:'word_limit',value:3000,status:'known',quote:'Maximum body words: 3000',location:'line:1',article_type:null,count_method:null,origin:'journal',note:''}
const guide={...p,id:'g1',profile_id:p.id,source_version:'2026 v1',acquired_on:'2026-10-23',article_types:['research'],requirements_version:sha,requirements:[rule],extracted_requirements:[rule],permission_status:'unknown',extract:true}
const rec={id:'rec1',created_at:p.created_at,input_snapshot:{project_id:'p1',kind:'journal_recommendation',recommendation_id:'rec1',workflow_version:'journal_recommendation_v1',research:{limit:3,title:'Fixed research',topics:[],article_type:'research'},profiles:[p],materials:[],manuscript:null,real_model_calls:false,real_network_calls:false},task:{...taskFixture,task_type:'journal_recommendation',phase:'plan',status:'succeeded',display_status:'succeeded',input_version:{kind:'journal_recommendation',recommendation_id:'rec1',workflow_version:'journal_recommendation_v1'}},result:{candidates:[{profile:p,reasons:[],matched_tag_count:0,preference_match_count:0}],pending_verification:[],excluded:[],candidate_total:1,limitations:[],real_model_calls:false,real_network_calls:false}}
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
function setup(options:{failedCheck?:boolean;failFormatLoad?:boolean}={}){const posts:{url:string;body:Record<string,unknown>}[]=[];let targets:unknown[]=[];let checks:unknown[]=[];let guides=[guide,{...guide,id:'g2',source_version:'2026 v2',requirements:[{...rule,id:'r2',value:2000,quote:'Maximum body words: 2000',origin:'unit'}]}]
vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{const path=url.split('/').at(-1)!
 if(init?.method==='POST'){const body=JSON.parse(String(init.body));posts.push({url,body});if(path==='guides'){const saved={...guide,...body,id:'g3',requirements_version:sha,synthetic:true};guides=[saved,...guides];return Response.json(saved)}
 if(path==='targets'){const target={...body,id:'target1',project_id:'p1',candidate:rec.result.candidates[0],guide,additional_guides:[guides[1]],selected_requirements:[],conflicts:[{key:'word_limit',requirements:[{...rule,id:'g1:r1',source_id:'g1'},{...rule,id:'g2:r2',value:2000,source_id:'g2'}],reason:'暂缓',deferred:true}],decisions:[],warnings:[{key:'unit_requirements',message:'单位要求需人工'}],synthetic:true,confirmed_by:'me',confirmed_at:p.created_at};targets=[target];return Response.json(target)}
 const target=targets[0];const item={id:'c1',created_at:p.created_at,task:options.failedCheck&&!url.endsWith('/retry')?{...formatTask,status:'failed',display_status:'failed',error_code:'task_failed'}:formatTask,input_snapshot:{id:'c1',kind:'journal_format_check',project_id:'p1',workflow_version:'journal_format_check_v1',target,manuscript:{id:'m1',revision:1,version_id:'v1'},check_version:1,public_check_version:2,real_model_calls:false,real_network_calls:false},result:options.failedCheck&&!url.endsWith('/retry')?null:{items:['length','sections','abstract','illustrations','references'].map((category,i)=>({id:String(i),category,key:'word_limit',status:'pending_verification',actual:null,expected:null,location:'guide',evidence:[{...rule,source_id:'g1'}],suggested_action:'补原文',future_automation:'manual',reason:'缺规则不得通过'})),adjustments:[],summary:{all_passed:false,counts:{pending_verification:5},meaning:'只读检查完成不等于合规'},public_issues:[{id:'bad-number',message:'公共数值错误不可豁免'}],synthetic:true,check_version:1,real_model_calls:false,real_network_calls:false}};checks=[item];return Response.json(item)}
 if(path==='submission-events')return Response.json({items:[],current_by_target:{}})
 if(options.failFormatLoad&&path==='guides')return Response.json({}, {status:503})
 if(path==='config')return Response.json({workflow_version:'journal_recommendation_v1',metrics_enabled:false,real_model_calls:false,real_network_calls:false,default_limit:3,max_limit:5,configuration:{status:'legacy_unbound',version_id:null,sha256:null}})
 if(url.endsWith('/manuscripts/candidates'))return Response.json({items:[]})
 if(path==='manuscripts')return Response.json({items:[{id:'m1',title:'New manuscript',versions:[{id:'v1',revision:1,status:'published',snapshot:{title:'Old manuscript'}},{id:'v2',revision:2,status:'published',snapshot:{title:'New manuscript'}}]}]})
 return Response.json({items:path==='profiles'?[p]:path==='recommendations'?[rec]:path==='guides'?guides:path==='targets'?targets:path==='checks'?checks:[]})
}));render(<JournalWorkspace projectId="p1" active/>);return posts}
it('accepts only frozen format identities and verify phase with result-free public workspace',()=>{
 expect(isTask(formatTask,'p1')).toBe(true);expect(taskPhaseName(formatTask as never)).toBe('期刊格式检查')
 expect(isTask({...formatTask,phase:'plan'},'p1')).toBe(false)
 expect(isTask({...formatTask,input_version:{...formatInput,check_version:2}},'p1')).toBe(false)
 expect(sameInputVersion(formatInput as InputVersion,{...formatInput,guide_id:'g2'} as InputVersion)).toBe(false)
 const source={file_id:null,filename:'Old manuscript',analysis_run_id:null,is_current:true}
 expect(isTaskPage({project_id:'p1',page:1,page_size:10,total:1,items:[{task:formatTask,source}]},'p1',1)).toBe(true)
 expect(isWorkspace({task:formatTask,source,wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}},'p1','t1')).toBe(true)
})
it('confirms fixed guides without a manuscript, defers conflict, then checks explicitly selected old manuscript',async()=>{
 const posts=setup();await waitFor(()=>expect(screen.getByLabelText('目标候选').closest('fieldset')?.hasAttribute('disabled')).toBe(false))
 fireEvent.change(screen.getByLabelText('目标候选'),{target:{value:'p-old'}})
 fireEvent.change(screen.getByLabelText('主指南版本'),{target:{value:'g1'}})
 fireEvent.click(screen.getByLabelText(/附加指南.*2026 v2/))
 fireEvent.change(screen.getByLabelText('冲突 word_limit 采用条款'),{target:{value:'defer'}})
 fireEvent.change(screen.getByLabelText('冲突 word_limit 理由'),{target:{value:'等待单位核对'}})
 fireEvent.click(screen.getByRole('button',{name:'确认固定目标'}));await waitFor(()=>expect(posts.length).toBe(1))
 expect(posts[0].body).toMatchObject({recommendation_id:'rec1',profile_id:'p-old',guide_id:'g1',requirements_version:sha,article_type:'research',additional_guide_ids:['g2'],resolutions:[{key:'word_limit',requirement_id:null,reason:'等待单位核对'}]})
 expect(screen.getByRole('button',{name:'检查固定稿件版本'}).hasAttribute('disabled')).toBe(true)
 fireEvent.change(screen.getByLabelText('检查稿件版本'),{target:{value:'m1:1'}});fireEvent.click(screen.getByRole('button',{name:'检查固定稿件版本'}));await waitFor(()=>expect(posts.length).toBe(2));expect(posts[1].body).toEqual({target_id:'target1',manuscript:{id:'m1',revision:1},check_version:1})
 const result=await screen.findByRole('region',{name:'当前格式检查'});for(const name of ['篇幅','章节','摘要','图表','引用'])expect(within(result).getByRole('heading',{name})).toBeTruthy()
 expect(within(result).getByText('公共数值错误不可豁免')).toBeTruthy();expect(within(result).getAllByText('缺规则不得通过')).toHaveLength(5)
})
it('offers ordinary rule controls with unknown permission and preserves exact quote and count method',async()=>{
 const posts=setup();await screen.findByRole('heading',{name:'目标确认与指南检查'})
 fireEvent.click(screen.getByText('登记作者指南新版本'));fireEvent.change(screen.getByLabelText('指南所属固定档案'),{target:{value:'p-old'}})
 fireEvent.change(screen.getByLabelText('指南名称'),{target:{value:'synthetic manual'}});fireEvent.change(screen.getByLabelText('指南来源版本'),{target:{value:'v3'}});fireEvent.change(screen.getByLabelText('指南适用文章类型'),{target:{value:'research'}});fireEvent.change(screen.getByLabelText('指南原文'),{target:{value:'Body words at most 3000'}});fireEvent.change(screen.getByLabelText('指南使用条件'),{target:{value:'offline'}});fireEvent.change(screen.getByLabelText('指南许可依据'),{target:{value:'fixture'}})
 expect((screen.getByLabelText('指南许可状态') as HTMLSelectElement).value).toBe('unknown')
 fireEvent.click(screen.getByRole('button',{name:'添加规则'}));fireEvent.change(screen.getByLabelText('规则 1 状态'),{target:{value:'known'}});fireEvent.change(screen.getByLabelText('规则 1 数值上限'),{target:{value:'3000'}});fireEvent.change(screen.getByLabelText('规则 1 原文引文'),{target:{value:'Body words at most 3000'}});fireEvent.change(screen.getByLabelText('规则 1 原文位置'),{target:{value:'line:1'}})
 fireEvent.click(screen.getByRole('button',{name:'保存作者指南新版本'}));await waitFor(()=>expect(posts.length).toBe(1));expect(posts[0].body).toMatchObject({permission_status:'unknown',requirements:[{key:'word_limit',value:3000,count_method:null,quote:'Body words at most 3000',location:'line:1',status:'known'}]});expect(screen.queryByRole('textbox',{name:/JSON/})).toBeNull()
})

it('labels running format checks without AI analysis wording',()=>{expect(taskDisplayName({...formatTask,status:'running',display_status:'analyzing'} as never)).toBe('格式检查中')})

async function fixedTarget(){await screen.findByRole('heading',{name:'目标确认与指南检查'});await waitFor(()=>expect(screen.getByLabelText('目标候选').closest('fieldset')?.hasAttribute('disabled')).toBe(false));fireEvent.change(screen.getByLabelText('目标候选'),{target:{value:'p-old'}});fireEvent.change(screen.getByLabelText('主指南版本'),{target:{value:'g1'}});fireEvent.click(screen.getByRole('button',{name:'确认固定目标'}));await screen.findByLabelText('检查稿件版本')}
it('sends full prefixed conflict choice and never silently certifies permission',async()=>{
 const posts=setup();await fixedTarget();fireEvent.click(screen.getByLabelText(/附加指南.*2026 v2/));const select=screen.getByLabelText('冲突 word_limit 采用条款');fireEvent.change(select,{target:{value:'g2:r2'}});fireEvent.click(screen.getByRole('button',{name:'确认固定目标'}));expect(posts).toHaveLength(1);expect(screen.getByRole('alert').textContent).toContain('须填写理由');fireEvent.change(screen.getByLabelText('冲突 word_limit 理由'),{target:{value:'使用本次单位来源'}});fireEvent.click(screen.getByRole('button',{name:'确认固定目标'}));await waitFor(()=>expect(posts).toHaveLength(2));expect(posts[1].body.resolutions).toEqual([{key:'word_limit',requirement_id:'g2:r2',reason:'使用本次单位来源'}]);expect(screen.getAllByText(/来源或许可尚未可用/).length).toBeGreaterThan(0)
})
it('keeps failed check retry on the same endpoint and clears frozen content on session loss',async()=>{
 const posts=setup({failedCheck:true});await fixedTarget();fireEvent.change(screen.getByLabelText('检查稿件版本'),{target:{value:'m1:1'}});fireEvent.click(screen.getByRole('button',{name:'检查固定稿件版本'}));await screen.findByRole('button',{name:'重试固定检查'});fireEvent.change(screen.getByLabelText('检查稿件版本'),{target:{value:'m1:2'}});fireEvent.click(screen.getByRole('button',{name:'重试固定检查'}));await waitFor(()=>expect(posts).toHaveLength(3));expect(posts[2]).toEqual({url:'/api/v1/projects/p1/journals/checks/c1/retry',body:{}});const result=await screen.findByRole('region',{name:'当前格式检查'});expect(result.textContent).toContain('稿件 m1 / 1');clearApiSession();await waitFor(()=>expect(screen.queryByRole('region',{name:'当前格式检查'})).toBeNull());expect(screen.getByRole('alert').textContent).toContain('会话或项目访问已变化')
})
it('keeps history disabled on a recoverable format load failure without inventing empty compliance',async()=>{
 setup({failFormatLoad:true});await screen.findByText('指南、目标或检查历史读取失败，请刷新后重试。');expect(screen.getByLabelText('目标候选').closest('fieldset')?.hasAttribute('disabled')).toBe(true);expect(screen.getByRole('button',{name:'刷新期刊资料'}).hasAttribute('disabled')).toBe(false);expect(screen.queryByText('全部通过')).toBeNull()
})
it('forks guides with request fields only and preserves unknown permission and old version identity',async()=>{
 const posts=setup();await fixedTarget();fireEvent.click(screen.getByText('登记作者指南新版本'));fireEvent.change(screen.getByLabelText('基于指南另存版本'),{target:{value:'g1'}});fireEvent.change(screen.getByLabelText('指南来源版本'),{target:{value:'v3'}});fireEvent.click(screen.getByRole('button',{name:'保存作者指南新版本'}));await waitFor(()=>expect(posts).toHaveLength(2));expect(posts[1].body).toMatchObject({previous_version_id:'g1',profile_id:'p-old',source_version:'v3',permission_status:'unknown'});for(const key of ['id','project_id','created_at','requirements_version','extracted_requirements','synthetic','verification_level'])expect(posts[1].body).not.toHaveProperty(key);const fixed=screen.getByRole('region',{name:'目标确认历史'});expect(fixed.textContent).toContain('2026 v1');expect(fixed.textContent).not.toContain('v3')
})

it('rejects malformed finite rule values and missing evidence rather than displaying them as known',()=>{expect(isRequirement({...rule,value:{foo:3000}})).toBe(false);expect(isRequirement({...rule,value:null})).toBe(false);expect(isRequirement({...rule,quote:''})).toBe(false);expect(isRequirement({...rule,status:'unknown',value:null})).toBe(true)})
