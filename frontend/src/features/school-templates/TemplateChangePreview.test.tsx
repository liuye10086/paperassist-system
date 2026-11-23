import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import SchoolTemplates from './SchoolTemplates'
import TemplateChangePreview from './TemplateChangePreview'
import { setLocale } from '../../shared/i18n'
import { findTechnicalText } from '../../test/technicalText'
import { isBindingPreview } from './contracts'

// B04 task 6: changing an adopted template first shows what the change affects (interface design section 4).
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
const ids={template:'2b4d6f8a-0c1e-4a3b-9d5f-7e9a1c3b5d70',confirmation:'6c8e0a2b-4d6f-4b1a-8c3e-5f7a9b1d3e84',other:'a1c3e5f7-9b2d-4c6e-8a0b-1d3f5a7c9e26',file:'f0a2c4e6-8b1d-4f3a-9c5e-7b9d1f3a5c48',manuscript:'8e0a2c4e-6f8b-4d1a-9b3c-5e7f9a1c3d62'}
const sha='7c5a3e1b9d7f5a3c1e9b7d5f3a1c9e7b5d3f1a9c7e5b3d1f9a7c5e3b1d9f7a5c'
const systemIds=[...Object.values(ids),sha]
const profile={school:'示例学校',department:'',major:'',degree_type:'',education_level:'',applicable_version:''}
const analysis={
 rules:[{id:'body.font_size_pt',label:'body.font_size_pt',value:14,source:{part:'word/document.xml',path:'/w:document/w:body/w:p[4]',text:'正文四号宋体'}}],
 chapters:[{id:'c1',title:'绪论',level:1},{id:'c3',title:'研究设计',level:1}],sections:[],notes:[],missing:[],unsupported:[],identity_fields:[],
 conflicts:[{id:'conflict-1',rule_id:'body.font_size_pt',label:'body.font_size_pt',options:[{id:'openxml',value:14,source:{part:'word/document.xml',path:'/w:document/w:body/w:p[4]',text:'正文四号宋体'}},{id:'text-1',value:12,source:{part:'supplement_text',path:'supplement_text',text:'正文小四'}}]}]}
const previewResponse={
 current:{confirmation_id:ids.other,template_name:'旧学校模板',confirmed_at:'2026-10-08T03:00:00Z'},
 next:{confirmation_id:null,template_name:'学校论文模板',confirmed_at:null},
 chapters:[
  {title:'研究设计',change:'title_changed',detail_key:'chapter.title_changed',detail_params:{from:'研究方法',to:'研究设计'}},
  {title:'附录',change:'added',detail_key:'chapter.added',detail_params:{}},
  {title:'文献综述',change:'removed',detail_key:'chapter.removed',detail_params:{}},
  {title:'绪论',change:'level_changed',detail_key:'chapter.level_changed',detail_params:{from:2,to:1}},
  {title:'结论',change:'order_changed',detail_key:'chapter.order_changed',detail_params:{from:4,to:5}},
 ],
 outputs:[
  {kind:'word_format',rule_id:'body.font_size_pt',detail_key:'format.rule',detail_params:{from:12,to:14}},
  {kind:'word_format',detail_key:'format.unknown_internal_key',detail_params:{from:'x_1',to:'y_2'}},
 ],
 manuscripts:[{manuscript_id:ids.manuscript,title:'硕士学位论文',revision:3,keeps_template:true,next_action:'migrate'}]}
type Reply=Response|(()=>Response|Promise<Response>)
function server(options:{bound?:string|null;confirmed?:boolean;preview?:Reply[];bind?:Reply[];lineRule?:string}={}){
 let bound=options.bound===undefined?ids.other:options.bound,revision=3,confirmation:null|{id:string}=options.confirmed?{id:ids.confirmation}:null
 const previews=[...options.preview??[]],binds=[...options.bind??[]]
 const calls:{method:string;path:string;body:unknown}[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  const path=url.replace('/api/v1/projects/p1/',''),method=init?.method??'GET'
  calls.push({method,path,body:init?.body?JSON.parse(String(init.body)):null})
  if(path==='thesis-profile')return Response.json({...profile,revision,bound_confirmation_id:bound})
  if(path.startsWith('files?'))return Response.json({items:[],page:1,total:0,page_size:50})
  if(path==='thesis-template-binding/preview'){const next=previews.shift();if(next)return typeof next==='function'?next():next;return Response.json(options.confirmed?{...previewResponse,next:{confirmation_id:ids.confirmation,template_name:'学校论文模板',confirmed_at:'2026-11-01T02:00:00Z'}}:previewResponse)}
  if(path.endsWith('/confirm')){confirmation={id:ids.confirmation};return Response.json(confirmation,{status:201})}
  if(path==='thesis-template-binding'){const next=binds.shift();if(next)return typeof next==='function'?next():next;bound=ids.confirmation;revision++;return Response.json({...profile,revision,bound_confirmation_id:bound})}
  const template={id:ids.template,name:'学校论文模板',school:'示例学校',version_label:'2026',task:{id:'t1',status:'succeeded'},analysis,analysis_sha256:sha,confirmation,sources:[{id:'s1',role:'template',file_id:ids.file,filename:'学校.docx',download_url:''}]}
  if(options.lineRule){
   const rules=[{id:'body.line_spacing',value:'480'},{id:'body.line_rule',value:options.lineRule}]
   return Response.json({items:[{...template,analysis:{...analysis,rules}}]})
  }
  return Response.json({items:[template]})
 }))
 return {calls,posts:()=>calls.filter(call=>call.method!=='GET').map(call=>call.path),setRevision:(value:number)=>{revision=value},setBound:(value:string)=>{bound=value;revision++}}
}
function renderCustomer(){
 const onNavigate=vi.fn(),onAdopted=vi.fn(),onOpenMigration=vi.fn()
 const view=render(<SchoolTemplates projectId="p1" active customerView navigation={{view:'detail',templateId:ids.template}} onNavigate={onNavigate} onAdopted={onAdopted} onOpenMigration={onOpenMigration}/>)
 return {view,onNavigate,onAdopted,onOpenMigration}
}
async function openPreview(user:ReturnType<typeof userEvent.setup>,choose=true){
 if(choose)await user.click(await screen.findByRole('radio',{name:/四号/}))
 await user.click(await screen.findByRole('button',{name:'改用这份模板'}))
 return screen.findByRole('heading',{name:'改用后会影响这些章节和格式'})
}
const confirmBody={analysis_sha256:sha,decisions:[{conflict_id:'conflict-1',option_id:'openxml'}],chapters:[{id:'c1',title:'绪论',level:1},{id:'c3',title:'研究设计',level:1}]}

it.each([
 ['exact','atLeast','固定 18 磅','至少 24 磅'],
 ['auto','auto','1.5 倍','2 倍'],
])('shows the Word line rule only in the template change preview (%s → %s)',async(fromRule,toRule,fromLabel,toLabel)=>{
 const outputs=[{kind:'word_format',rule_id:'body.line_spacing',detail_key:'format.rule',detail_params:{from:'360',to:'480'}}]
 if(fromRule!==toRule)outputs.push({kind:'word_format',rule_id:'body.line_rule',detail_key:'format.rule',detail_params:{from:fromRule,to:toRule}})
 server({lineRule:toRule,preview:[Response.json({...previewResponse,outputs})]})
 const user=userEvent.setup();renderCustomer()
 await screen.findByRole('radio',{name:/四号/})
 const target=document.getElementById('template-'+ids.template)!
 expect(target.textContent).not.toContain(toLabel)
 await openPreview(user)
 expect(await screen.findByText(`正文行距：${fromLabel} → ${toLabel}`)).toBeTruthy()
})

it('previews a template change and lists chapter, format and manuscript effects without technical text',async()=>{
 const api=server();const user=userEvent.setup();const {view}=renderCustomer()
 await openPreview(user)
 expect(api.posts()).toEqual(['thesis-template-binding/preview'])
 expect(api.calls.find(call=>call.path==='thesis-template-binding/preview')!.body).toEqual({...confirmBody,template_version_id:ids.template,expected_revision:3})
 const text=view.container.textContent??''
 expect(text).toContain('当前：旧学校模板（');expect(text).toContain('采用） → 新：学校论文模板')
 for(const line of ['章节改名：研究方法 → 研究设计','新增章节：附录','删除章节：文献综述','绪论：标题级别由 2 级改为 1 级','结论：位置由第 4 项调整为第 5 项','正文字号：小四 → 四号','其他 Word 格式有变化'])expect(text).toContain(line)
 expect(screen.getByText('已下载的 Word 保持原样；第 3 版要按新模板导出，需要先把稿件迁移到新模板。')).toBeTruthy()
 expect(text).toContain('硕士学位论文')
 for(const name of ['迁移到新模板','保持当前模板','改用这份模板'])expect(screen.getByRole('button',{name})).toBeTruthy()
 for(const banned of ['仍按原模板','以后再次导出','绑定','unknown_internal_key','x_1','body.font_size_pt','chapter.'])expect(text).not.toContain(banned)
 expect(view.container.querySelectorAll('details,summary,[aria-expanded]')).toHaveLength(0)
 expect(findTechnicalText(view.container,{systemIds})).toEqual([])
})
it('does not preview the first adoption',async()=>{
 const api=server({bound:null});const user=userEvent.setup();renderCustomer()
 await user.click(await screen.findByRole('radio',{name:/四号/}));await user.click(screen.getByRole('button',{name:'采用这份模板'}))
 await screen.findByText('已采用 学校论文模板。')
 expect(api.posts()).toEqual([`school-templates/${ids.template}/confirm`,'thesis-template-binding'])
})
it('keeps the current template without confirming or binding and returns to the template list',async()=>{
 const api=server();const user=userEvent.setup();const {onNavigate,onAdopted}=renderCustomer()
 await openPreview(user);await user.click(screen.getByRole('button',{name:'保持当前模板'}))
 expect(api.posts()).toEqual(['thesis-template-binding/preview'])
 expect(onNavigate).toHaveBeenLastCalledWith({view:'list',templateId:''});expect(onAdopted).not.toHaveBeenCalled()
})
it('changes the template from the preview with one confirmation and one binding',async()=>{
 const api=server();const user=userEvent.setup();const {onAdopted,onOpenMigration}=renderCustomer()
 await openPreview(user);await user.click(screen.getByRole('button',{name:'改用这份模板'}))
 await screen.findByText('已采用 学校论文模板。')
 expect(api.posts()).toEqual(['thesis-template-binding/preview',`school-templates/${ids.template}/confirm`,'thesis-template-binding'])
 expect(api.calls.find(call=>call.path.endsWith('/confirm'))!.body).toEqual(confirmBody)
 expect(onAdopted).toHaveBeenCalledWith(ids.confirmation);expect(onOpenMigration).not.toHaveBeenCalled()
})
it('changes the template first and then opens the migration with the manuscript, revision and new confirmation',async()=>{
 const api=server();const user=userEvent.setup();const {onOpenMigration,onAdopted}=renderCustomer()
 await openPreview(user);await user.click(screen.getByRole('button',{name:'迁移到新模板'}))
 await waitFor(()=>expect(onOpenMigration).toHaveBeenCalledWith(ids.manuscript,3,ids.confirmation))
 expect(api.posts()).toEqual(['thesis-template-binding/preview',`school-templates/${ids.template}/confirm`,'thesis-template-binding'])
 expect(onAdopted).toHaveBeenCalledWith(ids.confirmation)
 expect(onAdopted.mock.invocationCallOrder[0]).toBeLessThan(onOpenMigration.mock.invocationCallOrder[0])
})
it('retries only the binding after a failed change from the preview and then opens the migration',async()=>{
 const api=server({bind:[Response.json({detail:{code:'internal_error'}},{status:500})]});const user=userEvent.setup();const {onOpenMigration}=renderCustomer()
 await openPreview(user);await user.click(screen.getByRole('button',{name:'迁移到新模板'}))
 await screen.findByText('规则已确认，但还没有改用。');expect(onOpenMigration).not.toHaveBeenCalled()
 await user.click(screen.getByRole('button',{name:'重试改用'}))
 await waitFor(()=>expect(onOpenMigration).toHaveBeenCalledWith(ids.manuscript,3,ids.confirmation))
 expect(api.posts()).toEqual(['thesis-template-binding/preview',`school-templates/${ids.template}/confirm`,'thesis-template-binding','thesis-template-binding'])
})
it('opens the intended migration once after reading back a committed binding with a lost response',async()=>{
 const api=server({bind:[()=>{api.setBound(ids.confirmation);throw new TypeError('Disconnected')}]})
 const user=userEvent.setup();const {onAdopted,onOpenMigration}=renderCustomer()
 await openPreview(user);await user.click(screen.getByRole('button',{name:'迁移到新模板'}))
 await waitFor(()=>expect(onOpenMigration).toHaveBeenCalledExactlyOnceWith(ids.manuscript,3,ids.confirmation))
 expect(onAdopted).toHaveBeenCalledExactlyOnceWith(ids.confirmation)
 expect(onAdopted.mock.invocationCallOrder[0]).toBeLessThan(onOpenMigration.mock.invocationCallOrder[0])
 expect(api.posts()).toEqual(['thesis-template-binding/preview',`school-templates/${ids.template}/confirm`,'thesis-template-binding'])
})
it('previews an already confirmed target with only its version and the profile revision',async()=>{
 const api=server({confirmed:true});const user=userEvent.setup();renderCustomer()
 await openPreview(user,false)
 expect(api.calls.find(call=>call.path==='thesis-template-binding/preview')!.body).toEqual({template_version_id:ids.template,expected_revision:3})
 await user.click(screen.getByRole('button',{name:'改用这份模板'}));await screen.findByText('已采用 学校论文模板。')
 expect(api.posts()).toEqual(['thesis-template-binding/preview','thesis-template-binding'])
})
it('asks to reopen the template when the preview reports a revision conflict and rereads the profile',async()=>{
 const api=server({preview:[()=>{api.setRevision(4);return Response.json({detail:{code:'task_revision_conflict'}},{status:409})}]});const user=userEvent.setup();renderCustomer()
 await user.click(await screen.findByRole('radio',{name:/四号/}));await user.click(screen.getByRole('button',{name:'改用这份模板'}))
 expect((await screen.findByRole('alert')).textContent).toBe('学校模板资料已更新，请重新打开这份模板。')
 const index=api.calls.findIndex(call=>call.path==='thesis-template-binding/preview')
 expect(api.calls.slice(index+1).some(call=>call.method==='GET'&&call.path==='thesis-profile')).toBe(true)
 expect(screen.queryByRole('heading',{name:'改用后会影响这些章节和格式'})).toBeNull()
 expect(api.posts()).toEqual(['thesis-template-binding/preview'])
})
it('shows the preview in English without internal values',async()=>{
 server();setLocale('en');const user=userEvent.setup();const {view}=renderCustomer()
 await user.click(await screen.findByRole('radio',{name:/Size four/}));await user.click(await screen.findByRole('button',{name:'Change to this template'}))
 await screen.findByRole('heading',{name:'The change affects these chapters and formats'})
 const text=view.container.textContent??''
 expect(text).toContain('Downloaded Word files stay as they are. To export version 3 with the new template, migrate the manuscript to the new template first.')
 expect(text).toContain('Body text font size: Small four (12 pt) → Size four (14 pt)')
 expect(text).toContain('Chapter renamed: 研究方法 → 研究设计')
 for(const name of ['Migrate to the new template','Keep the current template'])expect(screen.getByRole('button',{name})).toBeTruthy()
 expect(findTechnicalText(view.container,{systemIds})).toEqual([])
})
it('names header, footer and page number differences with the keys the backend sends',()=>{
 const outputs=[
  {kind:'word_format' as const,detail_key:'format.headers_footers',detail_params:{from:[[['default','学校论文']]],to:[[['default','学位论文']]]}},
  {kind:'word_format' as const,detail_key:'format.page_numbers',detail_params:{from:[{format:'decimal',start:'1',mode:'continue'}],to:[{format:'upperRoman',start:'1',mode:'restart'}]}},
  {kind:'word_format' as const,detail_key:'format.front_matter',detail_params:{from:false,to:true}},
  {kind:'word_format' as const,detail_key:'format.format_profile',detail_params:{from:null,to:'bsu-gs501-academic-masters-2026'}},
 ]
 const {container}=render(<TemplateChangePreview preview={{...previewResponse,chapters:[],manuscripts:[],outputs}} busy={false} bindFailed={false} onKeep={vi.fn()} onChange={vi.fn()} onRetry={vi.fn()}/>)
 const text=container.textContent??''
 for(const line of ['页眉页脚有变化','页码设置有变化','封面等前置规则：未设置 → 已设置','排版方案：按模板原样式 → 北体 GS501 学术型硕士排版'])expect(text).toContain(line)
 for(const banned of ['其他 Word 格式有变化','upperRoman','decimal','bsu-gs501'])expect(text).not.toContain(banned)
 expect(findTechnicalText(container,{systemIds})).toEqual([])
})
it('rejects malformed preview responses',()=>{
 expect(isBindingPreview(previewResponse)).toBe(true)
 expect(isBindingPreview({...previewResponse,current:null})).toBe(true)
 expect(isBindingPreview({...previewResponse,chapters:[{title:'x',change:'renamed',detail_key:'x',detail_params:{}}]})).toBe(false)
 expect(isBindingPreview({...previewResponse,manuscripts:[{manuscript_id:ids.manuscript,title:'x',revision:'3',keeps_template:true,next_action:'migrate'}]})).toBe(false)
 expect(isBindingPreview({...previewResponse,next:null})).toBe(false)
})
