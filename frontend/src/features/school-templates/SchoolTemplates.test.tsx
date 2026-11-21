import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import SchoolTemplates from './SchoolTemplates'
import CustomerThesisWorkflow from '../customer/CustomerThesisWorkflow'
import { buildReturn } from '../customer/returnToken'
import { clearApiSession } from '../../shared/api/client'
import {useState} from 'react'
import type {SchoolTemplateNavigation} from '../projects/manuscriptViews'
import {setLocale} from '../../shared/i18n'
import {findTechnicalText} from '../../test/technicalText'
import parsedSources from './fixtures/t2-template-rule-sources.json'
const profile = { revision:0,school:'示例学校',department:'',major:'',degree_type:'',education_level:'',applicable_version:'',bound_confirmation_id:null }
const analysis = {rules:[{id:'r1',label:'正文字体',value:'宋体',source:{part:'word/document.xml',path:'/p[2]',text:'正文宋体'}}],chapters:[{id:'c1',title:'绪论',level:1}],sections:[],notes:[],missing:['发布日期未注明'],unsupported:['文字规则仅引用'],identity_fields:[{label:'作者签名',required:true}],conflicts:[{id:'x1',label:'字号冲突',options:[{id:'o1',value:'小四',source:{part:'word/document.xml',path:'/p[4]',text:'小四'}},{id:'o2',value:'五号'}]}]}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
function server(){
 let confirmation:null|{id:string}=null;let bound:string|null=null;let queued=false
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/thesis-profile'))return Response.json({...profile,bound_confirmation_id:bound})
  if(url.includes('/files?'))return Response.json({items:[{id:'f1',filename:'学校.docx',file_type:'docx',parse_status:'parsed'}],page:1,total:1,page_size:50})
  if(url.endsWith('/confirm')){confirmation={id:'cf1'};return Response.json(confirmation)}
  if(url.endsWith('/thesis-template-binding')){bound='cf1';return Response.json({...profile,bound_confirmation_id:bound,revision:1})}
  const item={id:'v1',name:'学校论文模板',school:'示例学校',version_label:'未注明',task:{id:'t1',status:queued?'queued':'succeeded'},analysis:queued?null:analysis,analysis_sha256:'a'.repeat(64),confirmation,sources:[{id:'s1',role:'template',file_id:'f1',filename:'学校.docx',download_url:'/api/v1/projects/p1/files/f1/download'}]}
  if(init?.method==='POST'){queued=true;return Response.json({...item,analysis:null,task:{status:'queued'}},{status:202})}
  return Response.json({items:[item]})
 });vi.stubGlobal('fetch',fetch);return {fetch,complete:()=>{queued=false}}
}
it('guards front matter drafts across hidden views and replays unknown confirmation with the same key',async()=>{
 const {fetch}=server();const keys:string[]=[];const bodies:unknown[]=[];let first=true
 const sources=[{id:'p1',source:{part:'word/document.xml',path:'/p[1]',text:'培养类型：示例值'},section_id:'s1',suggested_label:'培养类型',style:{font_size_pt:18},style_sources:{}}]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/confirm')){keys.push(new Headers(init?.headers).get('Idempotency-Key')!);bodies.push(JSON.parse(String(init?.body)));if(first){first=false;throw new TypeError('network')}}
  const response=await fetch(url,init)
  if(url.endsWith('/school-templates')&&!init?.method){const data=await response.json();data.items[0].front_matter_sources=sources;data.items[0].analysis.sections=[{id:'s1',source:{},page:{},page_number:{},headers:[],footers:[]}];return Response.json(data)}
  return response
 }))
 const checks=new Set<()=>boolean>(),register=(_guard:()=>boolean,dirty?:()=>boolean)=>{if(dirty)checks.add(dirty);return()=>{if(dirty)checks.delete(dirty)}}
 const user=userEvent.setup();const view=render(<SchoolTemplates projectId="p1" active registerLeaveGuard={register}/>);await screen.findByText('正文字体')
 await user.click(screen.getByLabelText('使用来源绑定的前置规则'));await user.selectOptions(screen.getByLabelText('新增字段来源'),'p1');await user.click(screen.getByRole('button',{name:'添加前置字段'}))
 await user.type(screen.getByLabelText('字段标签 1'),'草稿');expect([...checks].some(check=>check())).toBe(true)
 view.rerender(<SchoolTemplates projectId="p1" active={false} registerLeaveGuard={register}/>);view.rerender(<SchoolTemplates projectId="p1" active registerLeaveGuard={register}/>)
 act(()=>setLocale('en'));expect((screen.getByLabelText('Field label 1') as HTMLInputElement).value).toBe('培养类型草稿');act(()=>setLocale('zh-CN'))
 await user.selectOptions(screen.getByLabelText('字号冲突'),'o1');await user.click(screen.getByRole('button',{name:'确认模板规则'}));await screen.findByRole('alert');await user.click(screen.getByRole('button',{name:'确认模板规则'}));await screen.findByRole('button',{name:'绑定此确认版本'})
 expect(keys).toHaveLength(2);expect(keys[0]).toBe(keys[1]);expect(bodies[0]).toEqual(bodies[1]);expect(bodies[0]).toMatchObject({front_matter:{fields:[{label:'培养类型草稿',source_id:'p1'}]}})
})
function LayeredSchool(){
 const [navigation,onNavigate]=useState<SchoolTemplateNavigation>({view:'list',templateId:''})
 const [active,setActive]=useState(true)
 return <><button onClick={()=>setActive(value=>!value)}>toggle section</button><SchoolTemplates projectId="p1" active={active} navigation={navigation} onNavigate={onNavigate}/></>
}
it('keeps applicability and confirmation drafts across list, task and inactive views',async()=>{
 server();const user=userEvent.setup();render(<LayeredSchool/>);
 await user.click(await screen.findByRole('button',{name:'学校资料'}))
 await screen.findByDisplayValue('示例学校');await user.type(screen.getByLabelText('院系'),'药学院草稿')
 await user.click(screen.getByRole('button',{name:'模板列表'}));
 expect(screen.queryByRole('textbox',{name:'院系'})).toBeNull()
 await user.click(await screen.findByRole('button',{name:'查看模板 学校论文模板'}))
 await user.click(screen.getByRole('button',{name:'规则确认'}))
 await user.clear(screen.getByLabelText('章节标题 1'));await user.type(screen.getByLabelText('章节标题 1'),'草稿引言')
 await user.selectOptions(screen.getByLabelText('字号冲突'),'o1')
 await user.click(screen.getByRole('button',{name:'toggle section'}));await user.click(screen.getByRole('button',{name:'toggle section'}))
 expect((screen.getByLabelText('章节标题 1') as HTMLInputElement).value).toBe('草稿引言')
 await user.click(screen.getByRole('button',{name:'模板列表'}));await user.click(screen.getByRole('button',{name:'学校资料'}))
 expect((screen.getByLabelText('院系') as HTMLInputElement).value).toBe('药学院草稿')
 await user.click(screen.getByRole('button',{name:'模板列表'}));await user.click(screen.getByRole('button',{name:'查看模板 学校论文模板'}));await user.click(screen.getByRole('button',{name:'规则确认'}))
 expect((screen.getByLabelText('章节标题 1') as HTMLInputElement).value).toBe('草稿引言')
 expect((screen.getByLabelText('字号冲突') as HTMLSelectElement).value).toBe('o1')
})
it('guards hidden confirmation drafts and releases the pending guard after a failed request',async()=>{
 const {fetch}=server();let reject!:(reason:Error)=>void
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>url.endsWith('/confirm')?new Promise<Response>((_,fail)=>{reject=fail}):fetch(url,init)))
 const guards=new Set<()=>boolean>();const dirty=new Set<()=>boolean>()
 const register=(guard:()=>boolean,check?:()=>boolean)=>{guards.add(guard);if(check)dirty.add(check);return()=>{guards.delete(guard);if(check)dirty.delete(check)}}
 const ask=vi.fn(()=>false),alert=vi.fn();vi.stubGlobal('confirm',ask);vi.stubGlobal('alert',alert)
 const user=userEvent.setup();const view=render(<SchoolTemplates projectId="p1" active navigation={{view:'confirm',templateId:'v1'}} registerLeaveGuard={register}/>);
 await screen.findByDisplayValue('绪论');await user.selectOptions(screen.getByLabelText('字号冲突'),'o1')
 expect([...dirty].some(check=>check())).toBe(true);ask.mockReturnValue(true)
 await user.click(screen.getByRole('button',{name:'确认模板规则'}))
 expect([...guards].every(guard=>guard())).toBe(false);expect(alert).toHaveBeenCalled()
 await act(async()=>reject(new TypeError('network')));await screen.findByRole('alert');alert.mockClear();ask.mockClear();ask.mockReturnValue(false)
 view.rerender(<SchoolTemplates projectId="p1" active={false} navigation={{view:'list',templateId:''}} registerLeaveGuard={register}/>);
 expect([...guards].every(guard=>guard())).toBe(false);expect(ask).toHaveBeenCalled();expect(alert).not.toHaveBeenCalled()
})
it('requires conflict decisions, preserves chapter edits, explicitly binds and restores',async()=>{
 const {fetch}=server();const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active />)
 await screen.findByText('正文字体');expect((screen.getByRole('button',{name:'确认模板规则'}) as HTMLButtonElement).disabled).toBe(true)
 expect(screen.getByRole('link',{name:/下载原文件/}).getAttribute('href')).toBe('/api/v1/projects/p1/files/f1/download')
 await user.selectOptions(screen.getByLabelText('字号冲突'),'o1');await user.clear(screen.getByLabelText('章节标题 1'));await user.type(screen.getByLabelText('章节标题 1'),'引言')
 await user.click(screen.getByRole('button',{name:'确认模板规则'}));await screen.findByRole('button',{name:'绑定此确认版本'})
 const call=fetch.mock.calls.find(x=>String(x[0]).endsWith('/confirm'))!
 expect(JSON.parse(String(call[1]?.body))).toEqual({analysis_sha256:'a'.repeat(64),decisions:[{conflict_id:'x1',option_id:'o1'}],chapters:[{id:'c1',title:'引言',level:1}]})
 expect(new Headers(call[1]?.headers).get('Idempotency-Key')).toBeTruthy()
 await user.click(screen.getByRole('button',{name:'绑定此确认版本'}));await screen.findByText('当前绑定版本')
 await user.click(screen.getByRole('button',{name:'刷新学校模板'}));await screen.findByText('当前绑定版本')
})
it('saves the GS501 formatting choice only when offered for the verified original',async()=>{
 const {fetch}=server()
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  const response=await fetch(url,init)
  if(url.endsWith('/school-templates')&&!init?.method){
   const data=await response.json();data.items[0].available_format_profile='bsu-gs501-academic-masters-2026';return Response.json(data)
  }
  return response
 }))
 const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active customerView/>)
 const choice=await screen.findByRole('checkbox',{name:'采用北体 GS501 学术型硕士排版'}) as HTMLInputElement
 expect(choice.checked).toBe(false)
 // Customers choose conflicts on cards and adopt in one step (B04 task 5).
 await user.click(choice);await user.click(screen.getByRole('radio',{name:/小四/}))
 await user.click(screen.getByRole('button',{name:'采用这份模板'}))
 await waitFor(()=>{
  const call=fetch.mock.calls.find(([url])=>url.endsWith('/confirm'))
  expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({format_profile:'bsu-gs501-academic-masters-2026'})
 })
})
it('saves applicability and submits a retained source, then displays task completion',async()=>{
 const {fetch,complete}=server();const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active />);await screen.findByText('正文字体')
 await user.selectOptions(screen.getByLabelText('模板 DOCX 原件'),'f1');await user.click(screen.getByRole('button',{name:'提交模板解析'}));await screen.findByText('待执行')
 expect(fetch.mock.calls.some(x=>String(x[0]).endsWith('/thesis-profile')&&x[1]?.method==='PUT')).toBe(true)
 complete();await user.click(screen.getByRole('button',{name:'刷新学校模板'}));await screen.findByText('正文字体')
})
it('clears sensitive content on session changes',async()=>{
 server();render(<SchoolTemplates projectId="p1" active />);await screen.findByText('正文字体');act(()=>clearApiSession());expect(screen.queryByText('正文字体')).toBeNull()
})


it('uploads through file-batches, selects the retained original, and submits the parsing task',async()=>{
 const service=server();const baseFetch=service.fetch;let stored=false
 let batch={id:'b1',project_id:'p1',created_at:'2026-10-21T00:00:00Z',revision:1,items:[{id:'i1',ordinal:0,filename:'新模板.docx',size_bytes:1,status:'pending',file_id:null as string|null,task:null,error:null}]}
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.includes('/file-batches')){
   if(url.includes('/items/')){stored=true;batch={...batch,revision:2,items:[{...batch.items[0],status:'parsed',file_id:'f2'}]};return Response.json(batch.items[0])}
   if(url.endsWith('/b1'))return Response.json(batch)
   if(init?.method==='POST'){const body=JSON.parse(String(init.body));batch={...batch,items:[{...batch.items[0],id:body.items[0].client_id}]};return Response.json(batch)}
   if(url.includes('/items/')){stored=true;batch={...batch,revision:2,items:[{...batch.items[0],status:'parsed',file_id:'f2'}]};return Response.json(batch.items[0])}
   return Response.json({items:stored?[batch]:[],total:stored?1:0,page:1,page_size:5})
  }
  if(url.includes('/files?')&&stored)return Response.json({items:[{id:'f2',filename:'新模板.docx',file_type:'docx',parse_status:'parsed'}],total:1,page:1,page_size:50})
  return baseFetch(url,init)
 }))
 const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active/>);await screen.findByText('正文字体')
 await user.click(screen.getByRole('button',{name:'上传学校论文模板'}));await user.upload(screen.getByLabelText('批量选择 Excel / Word / PDF / 图片 文件'),new File(['x'],'新模板.docx'))
 await user.click(screen.getByRole('button',{name:'开始上传'}));await screen.findAllByRole('option',{name:'新模板.docx'})
 await user.selectOptions(screen.getByLabelText('模板 DOCX 原件'),'f2');await user.click(screen.getByRole('button',{name:'提交模板解析'}));await screen.findByText('待执行')
 const submission=baseFetch.mock.calls.find(call=>String(call[0]).endsWith('/school-templates')&&call[1]?.method==='POST')!
 expect(JSON.parse(String(submission[1]?.body)).template_file_id).toBe('f2')
})
it('retains the confirmation idempotency key after an unknown response',async()=>{
 const {fetch}=server();let attempts=0;const keys:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(url.endsWith('/confirm')){keys.push(new Headers(init?.headers).get('Idempotency-Key')!);if(++attempts===1)throw new TypeError('network')}return fetch(url,init)}))
 const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active/>);await screen.findByText('正文字体');await user.selectOptions(screen.getByLabelText('字号冲突'),'o1')
 await user.click(screen.getByRole('button',{name:'确认模板规则'}));await screen.findByRole('alert');await user.click(screen.getByRole('button',{name:'确认模板规则'}));await screen.findByRole('button',{name:'绑定此确认版本'})
 expect(keys).toHaveLength(2);expect(keys[0]).toBe(keys[1])
})
it('does not display a late response from the previously selected project',async()=>{
 const {fetch}=server();let resolve!:(response:Response)=>void
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>url.includes('/p1/school-templates')?new Promise<Response>(done=>{resolve=done}):url.includes('/p2/school-templates')?Response.json({items:[]}):fetch(url,init)))
 const view=render(<SchoolTemplates projectId="p1" active/>);await screen.findByLabelText('学校')
 view.rerender(<SchoolTemplates projectId="p2" active/>);await act(async()=>{resolve(Response.json({items:[{id:'old',name:'旧项目保密模板'}]}))})
 expect(screen.queryByText('旧项目保密模板')).toBeNull()
})
it('preserves unsaved applicability while refreshing server state',async()=>{
 server();const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active/>);await screen.findByText('正文字体')
 await user.type(screen.getByLabelText('院系'),'测试学院');await user.click(screen.getByRole('button',{name:'刷新学校模板'}));await screen.findByText('正文字体');expect((screen.getByLabelText('院系') as HTMLInputElement).value).toBe('测试学院')
})
it('blocks confirmation until at least one applicable chapter exists',async()=>{
 server();const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active/>);await screen.findByText('正文字体');await user.selectOptions(screen.getByLabelText('字号冲突'),'o1');await user.click(screen.getByRole('button',{name:'移除此章节'}))
 expect((screen.getByRole('button',{name:'确认模板规则'}) as HTMLButtonElement).disabled).toBe(true)
})
it('restores frozen conflict decisions and resolved rules from a confirmed version',async()=>{
 const {fetch}=server();vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  const response=await fetch(url,init);if(url.endsWith('/school-templates')&&!init?.method){const data=await response.json();data.items[0].confirmation={id:'cf1',decisions:[{conflict_id:'x1',option_id:'o1'}],chapters:[{id:'c1',title:'已确认引言',level:1}],rules:[{id:'r1',label:'已确认字号',value:'小四',source:{part:'word/document.xml',path:'/p[4]',text:'小四'}}]};return Response.json(data)}return response
 }))
 render(<SchoolTemplates projectId="p1" active/>);await screen.findByText('已确认字号');expect((screen.getByLabelText('字号冲突') as HTMLSelectElement).value).toBe('o1');expect((screen.getByLabelText('章节标题 1') as HTMLInputElement).value).toBe('已确认引言')
})
it('loads safely under the application StrictMode lifecycle',async()=>{
 server();const {StrictMode}=await import('react');render(<StrictMode><SchoolTemplates projectId="p1" active/></StrictMode>);await screen.findByText('正文字体')
})
it('reports malformed template responses without breaking the workspace',async()=>{
 const {fetch}=server();vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>url.endsWith('/school-templates')?Response.json({items:[{id:'bad',analysis:{rules:null}}]}):fetch(url,init)))
 render(<SchoolTemplates projectId="p1" active/>);await screen.findByRole('alert');expect(screen.getByRole('button',{name:'刷新学校模板'})).toBeTruthy()
})
it('keeps a dirty draft on its original revision and blocks overwriting a newer remote profile',async()=>{
 const {fetch}=server();let remoteRevision=0;let remoteDepartment='';const writes:Record<string,unknown>[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/thesis-profile')){
   if(init?.method==='PUT'){const body=JSON.parse(String(init.body));writes.push(body);if(body.expected_revision!==remoteRevision)return Response.json({detail:{code:'revision_conflict'}},{status:409});remoteDepartment=body.department;remoteRevision++;}
   return Response.json({...profile,revision:remoteRevision,department:remoteDepartment})
  }return fetch(url,init)
 }))
 const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active/>);await screen.findByText('正文字体');await user.type(screen.getByLabelText('院系'),'本地草稿')
 remoteRevision=2;remoteDepartment='其他页面保存的院系';await user.click(screen.getByRole('button',{name:'刷新学校模板'}))
 await screen.findByText('学校资料已在其他页面更新；草稿仍基于旧版本。请核对最新资料后重新填写。')
 expect((screen.getByLabelText('院系') as HTMLInputElement).value).toBe('本地草稿')
 expect((screen.getByRole('button',{name:'保存学校资料'}) as HTMLButtonElement).disabled).toBe(true)
 await user.click(screen.getByRole('button',{name:'保存学校资料'}));expect(writes).toHaveLength(0);expect(remoteDepartment).toBe('其他页面保存的院系')
 await user.click(screen.getByRole('button',{name:'使用最新学校资料'}));expect((screen.getByLabelText('院系') as HTMLInputElement).value).toBe('其他页面保存的院系')
 await user.type(screen.getByLabelText('院系'),'（核对后）');await user.click(screen.getByRole('button',{name:'保存学校资料'}));await screen.findByRole('button',{name:'保存学校资料'});expect(writes[0].expected_revision).toBe(2)
})
it('refreshes a clean profile draft to the latest server revision',async()=>{
 const {fetch}=server();let revision=0
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>url.endsWith('/thesis-profile')?Response.json({...profile,revision,department:revision?'远端院系':''}):fetch(url,init)))
 const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active/>);await screen.findByText('正文字体');revision=2;await user.click(screen.getByRole('button',{name:'刷新学校模板'}))
 await waitFor(()=>expect((screen.getByLabelText('院系') as HTMLInputElement).value).toBe('远端院系'))
 expect(screen.queryByText('学校资料已在其他页面更新；草稿仍基于旧版本。请核对最新资料后重新填写。')).toBeNull()
})

it('collapses lengthy rule and quoted-note lists while keeping conflict controls accessible',async()=>{
 server();const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active/>);await screen.findByText('正文字体')
 const rules=screen.getByText('模板规则（1 项）').closest('details')!;const notes=screen.getByText('内嵌说明与引用（0 项）').closest('details')!
 expect(rules.open).toBe(false);expect(notes.open).toBe(false);expect(screen.getByLabelText('字号冲突').closest('details')).toBeNull()
 await user.click(screen.getByText('模板规则（1 项）'));expect(rules.open).toBe(true)
})
it('requires an explicit choice for a new version even when the earlier text rule can be reused',async()=>{
 const original=server().fetch;let confirmed:unknown
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/confirm'))confirmed=JSON.parse(String(init?.body))
  const response=await original(url,init)
  if(url.endsWith('/school-templates')&&!init?.method){const value=await response.json();value.items[0].previous_version_id='v0';value.items[0].text_decision_options=[{id:'latin_font',label:'正文英文字体',source_text:'英文采用Times New Roman',text_value:'Times New Roman',attribute_value:{font_latin:'宋体'},source_sha256:'c'.repeat(64),suggested_choice:'text',changed:false,choices:['text','attributes']}];return Response.json(value)}
  return response
 }))
 const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active/>);await screen.findByText('正文字体')
 await user.selectOptions(screen.getByLabelText('字号冲突'),'o1')
 expect((screen.getByRole('button',{name:'确认模板规则'}) as HTMLButtonElement).disabled).toBe(true)
 await user.selectOptions(screen.getByLabelText('正文英文字体'),'text')
 await user.click(screen.getByRole('button',{name:'确认模板规则'}));await screen.findByRole('button',{name:'绑定此确认版本'})
 expect(confirmed).toMatchObject({text_decisions:[{id:'latin_font',choice:'text',source_sha256:'c'.repeat(64)}]})
})

it('registers a new template with its explicitly selected previous version without replacing the old one',async()=>{
 const original=server().fetch;let created:unknown
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/school-templates')&&init?.method==='POST')created=JSON.parse(String(init.body))
  const response=await original(url,init)
  if(url.endsWith('/school-templates')&&!init?.method){const value=await response.json();value.items[0].confirmation={id:'cf1',chapters:analysis.chapters,decisions:[{conflict_id:'x1',option_id:'o1'}]};return Response.json(value)}
  return response
 }))
 const user=userEvent.setup();render(<SchoolTemplates projectId="p1" active/>);await screen.findByText('正文字体')
 await user.selectOptions(screen.getByLabelText('更新自模板版本（可选）'),'v1');await user.selectOptions(screen.getByLabelText('模板 DOCX 原件'),'f1')
 await user.click(screen.getByRole('button',{name:'提交模板解析'}));await waitFor(()=>expect(created).toMatchObject({previous_version_id:'v1'}))
})

// B04 task 5: customers adopt a template in one step, see conflict sources in plain words, no folds or paths.
const ids={template:'4d1f6a2b-8c3e-4f5a-9b7d-2e6c1a0f8b31',confirmation:'7a2c9e41-5b6d-4e8f-a1c3-9d0b2f4e6a57',other:'c3e5a7b9-1d2f-4a6b-8c0e-5f7a9b1d3e62',file:'e8b0d2f4-6a1c-4e3b-9d5f-7a0c2e4b6d81',supplement:'1b3d5f7a-9c2e-4a6b-8d0f-3e5a7c9b1d24',version:'5f7a9b1d-3e5a-4c7b-9d1f-2a4c6e8b0d35',previous:'9e1a3c5b-7d9f-4b2a-8c4e-6f8a0b2c4d57'}
const sha='3f9a1c7e5b2d8f40a6c4e2b8d0f6a3c1e9b7d5f3a1c8e6b4d2f0a9c7e5b3d1f8'
const systemIds=[...Object.values(ids),sha]
const customerAnalysis={
 rules:[{id:'body.font_size_pt',label:'body.font_size_pt',value:12,source:{part:'word/document.xml',path:'/w:document/w:body/w:p[4]',text:'正文小四号宋体'}},{id:'heading1.font_east_asia',label:'heading1.font_east_asia',value:'黑体',source:{part:'word/styles.xml',path:'/w:styles/w:style[3]',text:''}}],
 chapters:[{id:'c1',title:'绪论',level:1,source:{part:'word/document.xml',path:'/w:document/w:body/w:p[9]',text:'第一章 绪论'}}],
 sections:[{id:'section-1',page:{margin_top_cm:2.5},source:{part:'word/document.xml',path:'/w:document/w:body/w:sectPr'},different_first_page:true,different_odd_even_pages:false,page_number:{format:'upperRoman',start:'1',mode:'restart'},headers:[{type:'default',part:'word/header1.xml',text:'学位论文',fields:[' PAGE \\* MERGEFORMAT '],linked_to_previous:false,source:{part:'word/header1.xml',path:'/w:hdr/w:p[1]',text:'学位论文'}}],footers:[],break_type:null}],
 notes:[{id:'supplement:text',text:'正文四号',source:{part:'supplement_text',path:'supplement_text',text:'正文四号'}}],missing:[],unsupported:[],identity_fields:[],
 conflicts:[
  {id:'conflict-1',rule_id:'body.font_size_pt',label:'body.font_size_pt',message:'实际属性与文字规范或多处文字表述不同，需确认适用要求。',options:[{id:'openxml',value:12,source:{part:'word/document.xml',path:'/w:document/w:body/w:p[4]',text:'正文小四号宋体'}},{id:'text-2',value:10.5,source:{part:'学校补充规范.docx',path:`document-version:${ids.version}:e1`,text:'正文：五号字'}}]},
  {id:'conflict-2',rule_id:'abstract.word_count',label:'摘要字数',options:[{id:'text-1',value:'300-500字',source:{part:'supplement_text',path:'supplement_text',text:'摘要300-500字'}},{id:'text-2',value:'约400字',source:{part:'学校补充规范.docx',path:`document-version:${ids.version}:e2`,text:'摘要字数400字左右'}}]},
 ]}
type Reply=Response|((init?:RequestInit)=>Response|Promise<Response>)
function customerServer(options:{bound?:string|null;previous?:string;confirmed?:boolean;bind?:Reply[];confirm?:Reply[];textOptions?:boolean}={}){
 let bound=options.bound??null,revision=3,confirmation:null|{id:string}=options.confirmed?{id:ids.confirmation}:null
 const confirms=[...options.confirm??[]],binds=[...options.bind??[]]
 const calls:{method:string;path:string;key:string|null;body:unknown}[]=[]
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  const path=url.replace('/api/v1/projects/p1/',''),method=init?.method??'GET'
  calls.push({method,path,key:new Headers(init?.headers).get('Idempotency-Key'),body:init?.body?JSON.parse(String(init.body)):null})
  if(path==='thesis-profile')return Response.json({...profile,revision,bound_confirmation_id:bound})
  if(path.startsWith('files?'))return Response.json({items:[],page:1,total:0,page_size:50})
  if(path==='thesis-template-binding/preview')return Response.json({current:{confirmation_id:ids.other,template_name:'旧学校模板',confirmed_at:null},next:{confirmation_id:null,template_name:'学校论文模板',confirmed_at:null},chapters:[],outputs:[],manuscripts:[]})
  if(path.endsWith('/confirm')){const next=confirms.shift();if(next)return typeof next==='function'?next():next;confirmation={id:ids.confirmation};return Response.json({...confirmation,chapters:customerAnalysis.chapters},{status:201})}
  if(path==='thesis-template-binding'){const next=binds.shift();if(next)return typeof next==='function'?next(init):next;bound=ids.confirmation;revision++;return Response.json({...profile,revision,bound_confirmation_id:bound})}
  const item={id:ids.template,name:'学校论文模板',school:'示例学校',version_label:'2026',previous_version_id:options.previous??null,task:{id:'t1',status:'succeeded'},analysis:customerAnalysis,analysis_sha256:sha,confirmation,
   text_decision_options:options.textOptions?[
    {id:'latin_font',label:'英文及数字字体',source_text:'英文一律采用Times New Roman',text_value:'Times New Roman',attribute_value:{'body.font_latin':'宋体'},source_sha256:sha,suggested_choice:null,changed:false,choices:['text','attributes']},
    {id:'heading1_line_spacing',label:'一级标题行距',source_text:'一级标题采用1.5倍行距',text_value:'1.5',attribute_value:{'heading1.line_spacing':360},source_sha256:sha,suggested_choice:null,changed:true,choices:['text','attributes']},
   ]:[],
   supplement_text:'正文四号',sources:[{id:'s1',role:'template',file_id:ids.file,filename:'学校.docx',download_url:''},{id:'s2',role:'supplement',file_id:ids.supplement,filename:'学校补充规范.docx',download_url:''}]}
  return Response.json({items:[item]})
 });vi.stubGlobal('fetch',fetch)
 return {calls,posts:()=>calls.filter(call=>call.method!=='GET').map(call=>call.path),setRevision:(value:number)=>{revision=value},setBound:(value:string)=>{bound=value;revision++}}
}
function renderCustomer(extra:Partial<Parameters<typeof SchoolTemplates>[0]>={}){
 const onAdopted=vi.fn(),onChanged=vi.fn()
 const view=render(<SchoolTemplates projectId="p1" active customerView navigation={{view:'binding',templateId:ids.template}} onNavigate={vi.fn()} onAdopted={onAdopted} onChanged={onChanged} {...extra}/>)
 return {view,onAdopted,onChanged}
}
async function chooseAll(user:ReturnType<typeof userEvent.setup>){
 await user.click(await screen.findByRole('radio',{name:/小四/}));await user.click(screen.getByRole('radio',{name:/300-500字/}))
}
const conflictQuestion='学校模板和补充说明的正文字号不同。请选择这篇论文采用的字号。'
// Selected output of inspect_school_template(T2) and merge_template_notes with one authored margin note.
function serveParsedSources(rules=parsedSources.rules) {
 const {fetch}=server()
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  const response=await fetch(url,init)
  if(!url.endsWith('/school-templates')||init?.method)return response
  const {items}=await response.json()
  return Response.json({items:[{...items[0],id:ids.template,analysis:{...analysis,...parsedSources,rules}}]})
 }))
}
it.each(['zh-CN','en'] as const)('localizes the stored GS501 level-four heading rule titles in %s',async(locale)=>{
 setLocale(locale)
 const fields=[
  ['font_east_asia','中文字体','四级标题 · 中文字体','Level 4 heading · Chinese font'],
  ['font_latin','西文字体','四级标题 · 英文字体','Level 4 heading · Latin font'],
  ['font_size_pt','字号（pt）','四级标题 · 字号','Level 4 heading · Font size'],
  ['alignment','对齐','四级标题 · 对齐方式','Level 4 heading · Alignment'],
  ['line_spacing','行距原始值','四级标题 · 行距','Level 4 heading · Line spacing'],
  ['line_rule','行距方式','四级标题 · 行距方式','Level 4 heading · Line spacing rule'],
 ]
 serveParsedSources(fields.map(([property,raw])=>({...parsedSources.rules[0],id:'heading4.'+property,label:'heading4 '+raw})))
 renderCustomer()
 const section=(await screen.findByRole('heading',{name:locale==='en'?'Template rules':'模板规则'})).closest('section')!
 expect(Array.from(section.querySelectorAll('li > strong'),node=>node.textContent)).toEqual(fields.map(row=>row[locale==='en'?3:2]))
})
it.each(['zh-CN','en'] as const)('shows T2 parsed format sources and authored quotations separately in %s',async(locale)=>{
 setLocale(locale);serveParsedSources()
 const {view}=renderCustomer()
 const heading=await screen.findByRole('heading',{name:locale==='en'?'Template rules':'模板规则'})
 const rules=heading.closest('section')!.textContent!
 const card=screen.getByRole('group',{name:locale==='en'?/Top margin/:/上边距/})
 for(const area of [rules,card.textContent,view.container.textContent]){
  expect(area).not.toMatch(/rPr\.|pPr\.|(?:top|w)=\d+ twips|(?:header|footer)Reference:/)
 }
 const expected=locale==='en'
  ? ['Level 1 heading Chinese font','宋体','Level 1 heading font size','Size three (16 pt)','Section 1','Page width','21 cm','Top margin','2.5 cm','1.15 lines','School template']
  : ['一级标题中文字体','宋体','一级标题字号','三号','第 1 节','页面宽度','21 厘米','上边距','2.5 厘米','1.15 倍','学校模板']
 for(const value of expected)expect(rules).toContain(value)
 expect(rules).toContain(parsedSources.rules.find(rule=>rule.id==='body.font_size_pt')!.example_source!.text)
 const options=within(card).getAllByRole('radio')
 expect(options[0].closest('label')?.textContent).toContain(locale==='en'?'2.5 cm':'2.5 厘米')
 expect(options[1].closest('label')?.textContent).toContain(parsedSources.notes[0].text)
 expect(options[1].closest('label')?.textContent).toContain(locale==='en'?'Supplementary note text':'补充说明文字')
})
it('retains the diagnostic source and location in the staff T2 template view',async()=>{
 serveParsedSources()
 render(<SchoolTemplates projectId="p1" active/>)
 await screen.findByText('w=11906 twips')
 expect(screen.getAllByText('样式 heading 1：rPr.sz.val=32').length).toBeGreaterThan(0)
 expect(screen.getAllByText(/word\/styles\.xml · \/w:styles\/w:style/).length).toBeGreaterThan(0)
})
it('opens the old binding address as one customer view with a single adopt button and plain conflict cards',async()=>{
 customerServer();const user=userEvent.setup();const {view}=renderCustomer()
 const adopt=await screen.findByRole('button',{name:'采用这份模板'}) as HTMLButtonElement
 expect(screen.queryByRole('navigation',{name:'模板详情视图'})).toBeNull()
 for(const name of ['模板详情','解析规则','规则确认','项目绑定','确认模板规则','绑定此确认版本'])expect(screen.queryByRole('button',{name})).toBeNull()
 expect(screen.getAllByRole('button').filter(button=>button.className.includes('button-primary'))).toEqual([adopt])
 expect(adopt.disabled).toBe(true);expect(screen.getByText('还有 2 处需要选择')).toBeTruthy()
 const prompt=screen.getByRole('group',{name:conflictQuestion})
 expect(prompt.textContent).toContain('学校模板');expect(prompt.textContent).toContain('补充规范《学校补充规范.docx》');expect(prompt.textContent).toContain('正文：五号字');expect(prompt.textContent).toContain('五号')
 expect(screen.getByRole('group',{name:'补充说明中的摘要字数要求不同。请选择这篇论文采用的字数。'}).textContent).toContain('补充说明文字')
 await user.click(screen.getByRole('radio',{name:/小四/}));expect(screen.getByText('还有 1 处需要选择')).toBeTruthy()
 await user.click(screen.getByRole('radio',{name:/300-500字/}));expect(screen.queryByText(/还有 \d+ 处需要选择/)).toBeNull();expect(adopt.disabled).toBe(false)
 // Order: conflict cards, chapters, front matter, then the main button.
 const order=[prompt,screen.getByLabelText('章节标题 1'),screen.getByLabelText('使用学校模板中的前置规则'),adopt]
 for(let i=1;i<order.length;i++)expect(order[i-1].compareDocumentPosition(order[i])&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
 expect(view.container.querySelectorAll('details,summary,[aria-expanded]')).toHaveLength(0)
 const text=view.container.textContent??''
 for(const raw of ['word/','/w:','document-version:','supplement_text','body.font_size_pt','heading1','upperRoman','MERGEFORMAT','查看来源'])expect(text).not.toContain(raw)
 expect(text).toContain('正文小四号宋体');expect(text).toContain('一级标题中文字体');expect(text).toContain('大写罗马数字')
 expect(findTechnicalText(view.container,{systemIds})).toEqual([])
})
it('confirms then binds with one click, reports the adoption and offers the next step',async()=>{
 const server=customerServer();const user=userEvent.setup();const onContinue=vi.fn();const {onAdopted,onChanged}=renderCustomer({onContinue})
 await chooseAll(user);await user.click(screen.getByRole('button',{name:'采用这份模板'}))
 await screen.findByText('已采用 学校论文模板。')
 expect(server.posts()).toEqual([`school-templates/${ids.template}/confirm`,'thesis-template-binding'])
 const confirm=server.calls.find(call=>call.path.endsWith('/confirm'))!
 expect(confirm.key).toBeTruthy();expect(confirm.body).toEqual({analysis_sha256:sha,decisions:[{conflict_id:'conflict-1',option_id:'openxml'},{conflict_id:'conflict-2',option_id:'text-1'}],chapters:[{id:'c1',title:'绪论',level:1}]})
 expect(server.calls.find(call=>call.path==='thesis-template-binding')!.body).toEqual({confirmation_id:ids.confirmation,expected_revision:3})
 expect(onAdopted).toHaveBeenCalledTimes(1);expect(onAdopted).toHaveBeenCalledWith(ids.confirmation);expect(onChanged).toHaveBeenCalled()
 await user.click(screen.getByRole('button',{name:'继续 写作资料与引用'}));expect(onContinue).toHaveBeenCalledTimes(1)
 expect(screen.queryByRole('button',{name:'采用这份模板'})).toBeNull()
})
it('retries only the binding after a failed bind and never re-sends the confirmation',async()=>{
 const server=customerServer({bind:[Response.json({detail:{code:'internal_error'}},{status:500})]});const user=userEvent.setup();const {onAdopted}=renderCustomer()
 await chooseAll(user);await user.click(screen.getByRole('button',{name:'采用这份模板'}))
 await screen.findByText('规则已确认，但模板还没有采用。');expect(onAdopted).not.toHaveBeenCalled()
 await user.click(screen.getByRole('button',{name:'重试采用'}));await screen.findByText('已采用 学校论文模板。')
 expect(server.posts()).toEqual([`school-templates/${ids.template}/confirm`,'thesis-template-binding','thesis-template-binding'])
 expect(onAdopted).toHaveBeenCalledWith(ids.confirmation)
})
it('rereads the profile after a bind revision conflict and binds again without confirming twice',async()=>{
 const server=customerServer({bind:[()=>{server.setRevision(5);return Response.json({detail:{code:'task_revision_conflict',message:'学校资料已更新，请刷新。'}},{status:409})}]})
 const user=userEvent.setup();renderCustomer()
 await chooseAll(user);await user.click(screen.getByRole('button',{name:'采用这份模板'}));await screen.findByText('已采用 学校论文模板。')
 const after=server.calls.slice(server.calls.findIndex(call=>call.path==='thesis-template-binding'))
 expect(after.slice(0,3).map(call=>`${call.method} ${call.path}`)).toEqual(['POST thesis-template-binding','GET thesis-profile','POST thesis-template-binding'])
 expect(after[2].body).toEqual({confirmation_id:ids.confirmation,expected_revision:5})
 expect(server.posts().filter(path=>path.endsWith('/confirm'))).toHaveLength(1)
})
function chapterReturnWorkflow(){
 const origin='customer-project=p1&step=manuscripts&view=materials&focus=chapters'
 const params=new URLSearchParams({view:'detail',template:ids.template,...buildReturn(new URLSearchParams(origin),'chapter',{returnChapter:'章节与复核'})})
 const follow=vi.fn()
 render(<CustomerThesisWorkflow project={{id:'p1',name:'毕业论文',project_type:'thesis',research_topic:'研究设计',file_count:1,created_at:'2026-11-20',updated_at:'2026-11-20'}}
   step="school" params={params} headingRef={null} registerLeaveGuard={()=>()=>{}} onUnavailable={vi.fn()} onNavigate={vi.fn()} onUpdateRoute={vi.fn()} onStartReview={vi.fn()} onFollowReturn={follow}/>)
 return {follow,origin:'#'+origin}
}
it('returns to chapters after a slow successful binding retry',async()=>{
 let signal:AbortSignal|null|undefined
 const server=customerServer({confirmed:true,bind:[Response.json({detail:{code:'internal_error'}},{status:500}),init=>new Promise((resolve,reject)=>{
  signal=init?.signal
  signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true})
  setTimeout(()=>{server.setBound(ids.confirmation);resolve(Response.json({...profile,revision:4,bound_confirmation_id:ids.confirmation}))},20000)
 })]})
 const {follow,origin}=chapterReturnWorkflow()
 fireEvent.click(await screen.findByRole('button',{name:'完成并返回 章节与复核'}))
 const retry=await screen.findByRole('button',{name:'重试采用'})
 vi.useFakeTimers()
 try{
  await act(async()=>{fireEvent.click(retry);await vi.advanceTimersByTimeAsync(15001)})
  expect(signal?.aborted).toBe(false)
  await act(async()=>{await vi.advanceTimersByTimeAsync(5000)})
  expect(follow).toHaveBeenCalledExactlyOnceWith(origin,true)
  expect(server.posts()).toEqual(['thesis-template-binding','thesis-template-binding'])
 }finally{vi.useRealTimers()}
})
it.each(['disconnected','invalid receipt'] as const)('recovers the chapter trip with one binding after a committed %s response',async failure=>{
 const server=customerServer({bind:[()=>{server.setBound(ids.confirmation);if(failure==='disconnected')throw new TypeError('Disconnected');return Response.json({})}]})
 const {follow,origin}=chapterReturnWorkflow()
 await chooseAll(userEvent.setup());fireEvent.click(screen.getByRole('button',{name:'完成并返回 章节与复核'}))
 await waitFor(()=>expect(follow).toHaveBeenCalledExactlyOnceWith(origin,true))
 expect(server.posts()).toEqual([`school-templates/${ids.template}/confirm`,'thesis-template-binding'])
})
it('checks again before an explicit retry when the first lost response completes later',async()=>{
 const server=customerServer({confirmed:true,bind:[()=>{throw new TypeError('Disconnected')}]})
 const {follow,origin}=chapterReturnWorkflow()
 fireEvent.click(await screen.findByRole('button',{name:'完成并返回 章节与复核'}))
 const retry=await screen.findByRole('button',{name:'重试采用'})
 expect(follow).not.toHaveBeenCalled()
 server.setBound(ids.confirmation)
 fireEvent.click(retry)
 await waitFor(()=>expect(follow).toHaveBeenCalledExactlyOnceWith(origin,true))
 expect(server.posts()).toEqual(['thesis-template-binding'])
})
it.each(['disconnected','conflict'] as const)('preserves another binding discovered after a %s response',async failure=>{
 const server=customerServer({confirmed:true,bind:[()=>{server.setBound(ids.other);if(failure==='disconnected')throw new TypeError('Disconnected');return Response.json({detail:{code:'task_revision_conflict'}},{status:409})}]})
 const {follow}=chapterReturnWorkflow()
 fireEvent.click(await screen.findByRole('button',{name:'完成并返回 章节与复核'}))
 await screen.findByText('学校模板资料已更新，请重新打开这份模板。')
 expect(follow).not.toHaveBeenCalled()
 expect(server.posts()).toEqual(['thesis-template-binding'])
})
it.each(['disconnect','request timeout'] as const)('offers a read-only binding check after %s when the profile cannot be read',async failure=>{
 let offline=false
 const server=customerServer({confirmed:true,bind:[()=>{offline=true;if(failure==='disconnect')throw new TypeError('Disconnected');return new Response(null,{status:408})}]})
 const original=fetch
 const failedReads=vi.fn()
 vi.stubGlobal('fetch',vi.fn((url:string,init?:RequestInit)=>{
  if(offline&&url.endsWith('/thesis-profile')){failedReads();return Promise.reject(new TypeError('Disconnected'))}
  return original(url,init)
 }))
 const {follow,origin}=chapterReturnWorkflow()
 fireEvent.click(await screen.findByRole('button',{name:'完成并返回 章节与复核'}))
 const check=await screen.findByRole('button',{name:'查看采用结果'})
 expect(follow).not.toHaveBeenCalled()
 expect(failedReads).toHaveBeenCalledTimes(1)
 offline=false;server.setBound(ids.confirmation)
 fireEvent.click(check)
 await waitFor(()=>expect(follow).toHaveBeenCalledExactlyOnceWith(origin,true))
 expect(server.posts()).toEqual(['thesis-template-binding'])
})
it('resends an unknown confirmation with the same key and ignores repeated clicks',async()=>{
 const server=customerServer({confirm:[()=>{throw new TypeError('network')}]});const user=userEvent.setup();renderCustomer()
 await chooseAll(user);await user.click(screen.getByRole('button',{name:'采用这份模板'}));await screen.findByRole('alert')
 await user.tripleClick(screen.getByRole('button',{name:'采用这份模板'}));await screen.findByText('已采用 学校论文模板。')
 const confirms=server.calls.filter(call=>call.path.endsWith('/confirm'))
 expect(confirms).toHaveLength(2);expect(confirms[0].key).toBe(confirms[1].key)
 expect(server.posts().filter(path=>path==='thesis-template-binding')).toHaveLength(1)
})
it('binds an already confirmed template directly and offers to finish and return to the chapter',async()=>{
 const server=customerServer({confirmed:true});const user=userEvent.setup();const {onAdopted}=renderCustomer({returnPlace:'第 3 章 研究设计'})
 await user.click(await screen.findByRole('button',{name:'完成并返回 第 3 章 研究设计'}))
 await waitFor(()=>expect(onAdopted).toHaveBeenCalledWith(ids.confirmation))
 expect(server.posts()).toEqual(['thesis-template-binding'])
})
it('uses change wording when another template is already adopted',async()=>{
 customerServer({bound:ids.other,bind:[Response.json({detail:{code:'internal_error'}},{status:500})]});const user=userEvent.setup();const {view}=renderCustomer()
 await chooseAll(user);await user.click(screen.getByRole('button',{name:'改用这份模板'}))
 // B04 task 6: the change goes through the read-only preview first.
 await screen.findByRole('heading',{name:'改用后会影响这些章节和格式'});await user.click(screen.getByRole('button',{name:'改用这份模板'}))
 await screen.findByText('规则已确认，但还没有改用。');expect(screen.getByRole('button',{name:'重试改用'})).toBeTruthy()
 expect(view.container.textContent).not.toContain('绑定')
})
it('shows supplement text, original style attributes and a missing previous version without folds or IDs',async()=>{
 customerServer({previous:ids.previous,textOptions:true});const {view}=renderCustomer()
 await screen.findByRole('button',{name:'采用这份模板'})
 expect(screen.getByText(/原模板版本不可用/)).toBeTruthy();expect(screen.getByRole('heading',{name:'补充规范文本'})).toBeTruthy()
 expect(screen.getByText(/正文英文字体：宋体/)).toBeTruthy();expect(screen.getByText('还有 4 处需要选择')).toBeTruthy()
 expect(view.container.querySelectorAll('details,summary')).toHaveLength(0)
 expect(view.container.textContent).not.toContain('绑定不会自动迁移历史稿')
 expect(findTechnicalText(view.container,{systemIds})).toEqual([])
})
it('translates both fixed rule labels and instructions while retaining the source text in English',async()=>{
 setLocale('en')
 customerServer({textOptions:true})
 renderCustomer()
 const group=within(await screen.findByRole('group',{name:'Written requirement choices'}))
 const labels=group.getAllByRole('combobox').map(select=>select.closest('label')?.firstChild?.textContent)
 expect(labels).toEqual(['Font for English text and numbers','Level 1 heading line spacing'])
 expect(group.getByText('The source or style changed. Check it again.')).toBeTruthy()
 expect(group.getByText('英文一律采用Times New Roman')).toBeTruthy()
 expect(group.getByText('一级标题采用1.5倍行距')).toBeTruthy()
 expect(group.getByRole('option',{name:'Use the written requirement · 1.5'})).toBeTruthy()
})
it('keeps source paths and the staff confirmation and binding steps for analysts',async()=>{
 const {fetch}=server();vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  const response=await fetch(url,init);if(url.endsWith('/school-templates')&&!init?.method){const data=await response.json();data.items[0].analysis.conflicts[0].rule_id='body.font_size_pt';return Response.json(data)}return response
 }))
 const view=render(<SchoolTemplates projectId="p1" active/>);await screen.findByText('正文字体')
 expect(view.container.textContent).toContain('word/document.xml · /p[4]');expect(screen.getByRole('button',{name:'确认模板规则'})).toBeTruthy()
 expect(screen.queryByRole('button',{name:'采用这份模板'})).toBeNull();expect(screen.getByLabelText('字号冲突').tagName).toBe('SELECT')
})
