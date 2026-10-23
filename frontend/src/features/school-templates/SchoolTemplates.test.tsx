import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import SchoolTemplates from './SchoolTemplates'
import { clearApiSession } from '../../shared/api/client'
const profile = { revision:0,school:'示例学校',department:'',major:'',degree_type:'',education_level:'',applicable_version:'',bound_confirmation_id:null }
const analysis = {rules:[{id:'r1',label:'正文字体',value:'宋体',source:{part:'word/document.xml',path:'/p[2]',text:'正文宋体'}}],chapters:[{id:'c1',title:'绪论',level:1}],sections:[],notes:[],missing:['发布日期未注明'],unsupported:['文字规则仅引用'],identity_fields:[{label:'作者签名',required:true}],conflicts:[{id:'x1',label:'字号冲突',options:[{id:'o1',value:'小四',source:{part:'word/document.xml',path:'/p[4]',text:'小四'}},{id:'o2',value:'五号'}]}]}
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
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
