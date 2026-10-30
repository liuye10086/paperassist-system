import {act,cleanup,render,screen,waitFor,within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {afterEach,expect,it,vi} from 'vitest'
import SchoolTemplates from './SchoolTemplates'
import SchoolRuleSuggestions from './SchoolRuleSuggestions'

const hash='a'.repeat(64),bundle='b'.repeat(64),artifact='c'.repeat(64)
const note={id:'n1',text:'英文使用 Times New Roman。',source:{part:'word/document.xml',path:'/p[4]',text:'英文使用 Times New Roman。'}}
const analysis={rules:[],chapters:[{id:'c1',title:'绪论',level:1}],sections:[],notes:[note],missing:[],unsupported:[],identity_fields:[{id:'private',text:'姓名：秘密姓名'}],conflicts:[]}
const profile={revision:0,school:'示例学校',department:'',major:'',degree_type:'',education_level:'',applicable_version:'',bound_confirmation_id:null}
function suggestion(id='sg1',status='conflict'){
 return {schema_version:1,id,template_version_id:'v1',analysis_sha256:hash,bundle_sha256:bundle,artifact_sha256:id==='sg1'?artifact:'d'.repeat(64),task:{id:`task-${id}`,project_id:'p1',status:'succeeded'},result:{candidates:[{id:'candidate1',target_id:'styles.Normal.font_latin',value:'Times New Roman',note_alias:'N1',start:0,end:23,quote:note.text,status,reason:'原文字体与属性不同',normalized_value:'Times New Roman',source_verified:true,human_confirmed:false,current_value:'宋体',source:note.source}]},model_calls:[{id:'mc1',status:'succeeded',model:'gpt-6.1-sol',provider_provenance:'synthetic_fixture',estimated_cost_micro_usd:100}]}
}
function setup(options:{confirmed?:boolean;status?:string;items?:ReturnType<typeof suggestion>[]}={}){
 let confirmation:unknown=options.confirmed?{id:'cf-old',chapters:analysis.chapters}:null
 const views=options.items??[suggestion('sg1',options.status)]
 const fetch=vi.fn(async(url:string,_init?:RequestInit)=>{
  if(url.endsWith('/thesis-profile'))return Response.json(profile)
  if(url.includes('/files?'))return Response.json({items:[],total:0,page:1,page_size:50})
  if(url.endsWith('/rule-suggestion-preview'))return Response.json({schema_version:1,template_version_id:'v1',analysis_sha256:hash,notes:[{...note,alias:'N1',sha256:'e'.repeat(64)}],material:{notes:[{alias:'N1',text:note.text}],capabilities:[{id:'styles.Normal.font_latin',kind:'font',current_value:'宋体'}],capability_catalog_version:'school-rule-capabilities-v1'},bundle_sha256:bundle,policy:{model:'gpt-6.1-sol',price:{input_micro_usd_per_million_tokens:1000000}},input_token_allowance:2000,reserved_micro_usd:1000,real_calls_enabled:false})
  if(url.endsWith('/rule-suggestions'))return Response.json({items:views})
  if(url.includes('/school-rule-suggestions/'))return Response.json(views.find(item=>url.endsWith('/'+item.id)))
  if(url.endsWith('/fork'))return Response.json({id:'v2',task:{id:'fork-task',status:'queued'}},{status:202})
  if(url.endsWith('/confirm')){confirmation={id:'cf1'};return Response.json(confirmation)}
  return Response.json({items:[{id:'v1',name:'学校论文模板',school:'示例学校',version_label:'2026',task:{id:'t1',status:'succeeded'},analysis,analysis_sha256:hash,confirmation,sources:[]}]})
 })
 vi.stubGlobal('fetch',fetch)
 return {fetch}
}
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('excludes known identity source notes from selectable sending while preserving ordinary signature requirements',async()=>{
 const secret={id:'identity-note',text:'作者签名：示例签名',source:{part:'word/document.xml',path:'/w:document/w:body/w:p[3]',text:'作者签名：示例签名'}}
 const ordinary={id:'ordinary-note',text:'签名须人工填写。',source:{part:'supplement_text',path:'/lines/1',text:'签名须人工填写。'}}
 const item={id:'v1',name:'模板',school:'学校',version_label:'',created_at:'2026-10-28',task:{id:'parse',status:'succeeded'},analysis:{...analysis,notes:[secret,ordinary]},analysis_sha256:hash,confirmation:null,sources:[],rule_suggestion_note_eligibility:{eligible_note_ids:['ordinary-note'],blocked_notes:[{note_id:'identity-note',reason_code:'identity_source' as const}]}}
 const fetch=vi.fn(async(_url:string,_init?:RequestInit)=>Response.json({items:[]}));vi.stubGlobal('fetch',fetch)
 const callbacks={onSelection:vi.fn(),onPendingChange:vi.fn(),onFork:async()=>{},onUnavailable:vi.fn()};const user=userEvent.setup()
 const view=render(<SchoolRuleSuggestions projectId="p1" item={{...item,rule_suggestion_note_eligibility:undefined}} active busy={false} {...callbacks}/> )
 await user.click(await screen.findByRole('checkbox',{name:secret.text}))
 view.rerender(<SchoolRuleSuggestions projectId="p1" item={item} active busy={false} {...callbacks}/> )
 await waitFor(()=>expect(screen.getByRole('checkbox',{name:ordinary.text})).toBeTruthy())
 const identity=screen.queryByRole('checkbox',{name:secret.text})
 expect(identity===null||(identity as HTMLInputElement).disabled).toBe(true)
 expect((screen.getByRole('checkbox',{name:ordinary.text}) as HTMLInputElement).disabled).toBe(false)
 expect(screen.getByText(/已识别的身份字段来源.*单独补充/)).toBeTruthy()
 await user.click(screen.getByRole('checkbox',{name:ordinary.text}));await user.click(screen.getByRole('button',{name:'预览建议发送内容'}))
 await waitFor(()=>expect(fetch.mock.calls.some(([url])=>url.endsWith('/rule-suggestion-preview'))).toBe(true))
 const sent=fetch.mock.calls.find(([url])=>url.endsWith('/rule-suggestion-preview'))!
 expect(JSON.parse(String(sent[1]?.body))).toMatchObject({note_ids:['ordinary-note']})
})
async function choose(user:ReturnType<typeof userEvent.setup>,id:string){await screen.findByRole('option',{name:new RegExp(id)});await user.selectOptions(screen.getByLabelText('纳入确认的建议产物'),id)}

it('requires explicit note selection and previews only frozen selected note identifiers',async()=>{
 const {fetch}=setup();const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active navigation={{view:'confirm',templateId:'v1'}}/>)
 const check=await screen.findByRole('checkbox',{name:/英文使用 Times New Roman/})
 expect((check as HTMLInputElement).checked).toBe(false)
 expect((screen.getByRole('button',{name:'预览建议发送内容'}) as HTMLButtonElement).disabled).toBe(true)
 await user.click(check);await user.click(screen.getByRole('button',{name:'预览建议发送内容'}))
 await screen.findByText('真实模型调用已关闭')
 const call=fetch.mock.calls.find(([url])=>url.endsWith('/rule-suggestion-preview'))!
 expect(JSON.parse(String(call[1]?.body))).toEqual({analysis_sha256:hash,note_ids:['n1']})
 expect(String(call[1]?.body)).not.toContain('秘密姓名')
 expect(screen.getByText('/p[4]')).toBeTruthy()
 expect((screen.getByRole('button',{name:'确认发送并生成建议'}) as HTMLButtonElement).disabled).toBe(true)
})

it('does not preselect or accept a suggestion and keeps the legacy confirmation body unchanged',async()=>{
 const {fetch}=setup();const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active navigation={{view:'confirm',templateId:'v1'}}/>)
 const selection=await screen.findByLabelText('纳入确认的建议产物')
 expect((selection as HTMLSelectElement).value).toBe('')
 await user.click(screen.getByRole('button',{name:'确认模板规则'}))
 await waitFor(()=>expect(fetch.mock.calls.some(([url])=>url.endsWith('/confirm'))).toBe(true))
 const call=fetch.mock.calls.find(([url])=>url.endsWith('/confirm'))!
 expect(JSON.parse(String(call[1]?.body))).toEqual({analysis_sha256:hash,decisions:[],chapters:analysis.chapters})
})

it('requires all explicit decisions and reasons and submits the selected artifact exact SHA via V2',async()=>{
 const {fetch}=setup();const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active navigation={{view:'confirm',templateId:'v1'}}/>)
 await choose(user,'sg1')
 const decision=await screen.findByLabelText('建议处置 1')
 expect((decision as HTMLSelectElement).value).toBe('')
 expect((screen.getByRole('button',{name:'确认模板规则'}) as HTMLButtonElement).disabled).toBe(true)
 await user.selectOptions(decision,'accept')
 expect((screen.getByRole('button',{name:'确认模板规则'}) as HTMLButtonElement).disabled).toBe(true)
 await user.type(screen.getByLabelText('处置理由 1'),'核对原文后采用英文规范')
 await user.click(screen.getByRole('button',{name:'确认模板规则'}))
 await waitFor(()=>expect(fetch.mock.calls.some(([url])=>url.endsWith('/confirm'))).toBe(true))
 const call=fetch.mock.calls.find(([url])=>url.endsWith('/confirm'))!
 expect(JSON.parse(String(call[1]?.body))).toEqual({schema_version:2,analysis_sha256:hash,decisions:[],chapters:analysis.chapters,suggestion_id:'sg1',suggestion_artifact_sha256:artifact,suggestion_decisions:[{candidate_id:'candidate1',action:'accept',reason:'核对原文后采用英文规范'}]})
})

it('invalidates an earlier complete selection when switching artifacts or editing a reason',async()=>{
 setup({items:[suggestion(),suggestion('sg2')]});const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active navigation={{view:'confirm',templateId:'v1'}}/>)
 await choose(user,'sg1');const selection=screen.getByLabelText('纳入确认的建议产物')
 await user.selectOptions(await screen.findByLabelText('建议处置 1'),'reject');await user.type(screen.getByLabelText('处置理由 1'),'保留原属性')
 expect((screen.getByRole('button',{name:'确认模板规则'}) as HTMLButtonElement).disabled).toBe(false)
 await user.clear(screen.getByLabelText('处置理由 1'))
 expect((screen.getByRole('button',{name:'确认模板规则'}) as HTMLButtonElement).disabled).toBe(true)
 await user.type(screen.getByLabelText('处置理由 1'),'保留原属性');await user.selectOptions(selection,'sg2')
 await waitFor(()=>expect((screen.getByLabelText('建议处置 1') as HTMLSelectElement).value).toBe(''))
 expect((screen.getByLabelText('处置理由 1') as HTMLTextAreaElement).value).toBe('')
 expect((screen.getByRole('button',{name:'确认模板规则'}) as HTMLButtonElement).disabled).toBe(true)
})

it.each(['unknown','unsupported'])('never allows accept for %s candidates',async status=>{
 setup({status});const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active navigation={{view:'confirm',templateId:'v1'}}/>)
 await choose(user,'sg1')
 const decision=await screen.findByLabelText('建议处置 1')
 expect(within(decision).queryByRole('option',{name:'接受建议值'})).toBeNull()
 expect(within(decision).getByRole('option',{name:'拒绝并保留原属性'})).toBeTruthy()
 expect(within(decision).getByRole('option',{name:'暂缓'})).toBeTruthy()
})

it('retains hidden suggestion drafts and registers their leave guard',async()=>{
 setup();const dirty=new Set<()=>boolean>();const register=(_guard:()=>boolean,check?:()=>boolean)=>{if(check)dirty.add(check);return()=>{if(check)dirty.delete(check)}}
 const user=userEvent.setup();const view=render(<SchoolTemplates projectId="p1" active navigation={{view:'confirm',templateId:'v1'}} registerLeaveGuard={register}/>)
 await choose(user,'sg1');await user.selectOptions(await screen.findByLabelText('建议处置 1'),'defer');await user.type(screen.getByLabelText('处置理由 1'),'待学校核对')
 expect([...dirty].some(check=>check())).toBe(true)
 view.rerender(<SchoolTemplates projectId="p1" active={false} navigation={{view:'list',templateId:''}} registerLeaveGuard={register}/>)
 await act(async()=>{})
 view.rerender(<SchoolTemplates projectId="p1" active navigation={{view:'confirm',templateId:'v1'}} registerLeaveGuard={register}/>)
 expect((screen.getByLabelText('处置理由 1') as HTMLTextAreaElement).value).toBe('待学校核对')
 expect((screen.getByLabelText('建议处置 1') as HTMLSelectElement).value).toBe('defer')
})

it('forks a confirmed template using its frozen original without requesting another upload',async()=>{
 const {fetch}=setup({confirmed:true});const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active navigation={{view:'confirm',templateId:'v1'}}/>)
 await user.click(await screen.findByRole('button',{name:'基于冻结原件创建修订版'}))
 await waitFor(()=>expect(fetch.mock.calls.some(([url])=>url.endsWith('/fork'))).toBe(true))
 const call=fetch.mock.calls.find(([url])=>url.endsWith('/fork'))!
 expect(JSON.parse(String(call[1]?.body))).toEqual({})
 expect(fetch.mock.calls.some(([url,init])=>url.endsWith('/school-templates')&&init?.method==='POST')).toBe(false)
})

it('invalidates a decision when a refreshed artifact SHA changes without rendering state updates',async()=>{
 const views=[suggestion()];setup({items:views});const errors=vi.spyOn(console,'error').mockImplementation(()=>{})
 const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active navigation={{view:'confirm',templateId:'v1'}}/>)
 await choose(user,'sg1');await user.selectOptions(await screen.findByLabelText('建议处置 1'),'reject');await user.type(screen.getByLabelText('处置理由 1'),'保留原属性')
 views[0]={...suggestion(),artifact_sha256:'f'.repeat(64)}
 await user.click(screen.getByRole('button',{name:'刷新建议列表'}))
 await waitFor(()=>expect((screen.getByLabelText('处置理由 1') as HTMLTextAreaElement).value).toBe(''))
 expect((screen.getByRole('button',{name:'确认模板规则'}) as HTMLButtonElement).disabled).toBe(true)
 expect(errors.mock.calls).toEqual([])
 errors.mockRestore()
})

it('can refresh saved suggestions on a confirmed template while its decisions stay frozen',async()=>{
 const {fetch}=setup({confirmed:true});const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active navigation={{view:'confirm',templateId:'v1'}}/>)
 await screen.findByRole('option',{name:/sg1/});const before=fetch.mock.calls.filter(([url])=>url.endsWith('/rule-suggestions')).length
 await user.click(screen.getByRole('button',{name:'刷新建议列表'}))
 await waitFor(()=>expect(fetch.mock.calls.filter(([url])=>url.endsWith('/rule-suggestions')).length).toBeGreaterThan(before))
 expect((screen.getByLabelText('纳入确认的建议产物') as HTMLSelectElement).disabled).toBe(true)
})
