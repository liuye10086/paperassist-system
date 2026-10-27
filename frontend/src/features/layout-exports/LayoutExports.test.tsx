import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import LayoutExports from './LayoutExports'
import {setApiSession} from '../../shared/api/client'
import {setLocale} from '../../shared/i18n'
import {execFileSync} from 'node:child_process'
import {resolve} from 'node:path'
const hash='a'.repeat(64),anchor=(n:number)=>`${hash}:${n}`
const props={projectId:'p1',sourceKind:'report' as const,sourceId:'r1',sourceSha256:hash,sourceLabel:'Analysis v1'}
const catalog={source_kind:'report',source_id:'r1',filename:'source.docx',source_sha256:hash,source_size:200,version:{id:'a1',revision:1,renderer_version:'v1'},output_language:'en',limits:{},anchors:[{id:anchor(0),position:0,type:'heading',text:'Results',heading_level:1,bookmark:null,is_caption:false},{id:anchor(1),position:1,type:'paragraph',text:'Findings',heading_level:null,bookmark:null,is_caption:false},{id:anchor(2),position:2,type:'table',text:'Table 1',heading_level:null,bookmark:null,is_caption:false},{id:anchor(3),position:3,type:'figure',text:'Figure 1',heading_level:null,bookmark:null,is_caption:false}]}
const layout={source_sha256:hash,formulas:[],references:[],headings:[],toc:null,pagination:null,landscape_anchor_ids:[]}
const row={id:'l1',project_id:'p1',source_kind:'report',source_id:'r1',source_sha256:hash,status:'queued',task_id:'lt1',created_at:'2026-10-20T00:00:00Z',layout,layout_version:'document_layout_v1',output_language:'en',request_key:'key1',can_retry:false,parent_export_id:null,filename:null,error_code:null,renderer_manifest:null,sha256:null,size_bytes:null,download_url:null}
const base='/api/v1/projects/p1/layout-exports'
beforeEach(()=>{sessionStorage.clear();setApiSession('layout-session','user1')})
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals();setLocale('zh-CN')})
function mock(history:unknown[]=[],catalogValue:unknown=catalog){const bodies:string[]=[];const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){bodies.push(String(init.body));const body=JSON.parse(String(init.body));return Response.json({...row,request_key:body.request_key,layout:body.layout??layout,parent_export_id:url.endsWith('/retry')?'l1':null})}return Response.json(url.endsWith('/catalog')?catalogValue:{items:history})});vi.stubGlobal('fetch',fetcher);return {fetcher,bodies}}
async function open(){fireEvent.click(screen.getByRole('button',{name:'排版与公式'}));return screen.findByRole('button',{name:'生成排版 DOCX'})}
it('labels original layout candidate recovery and keeps the original creation identity',async()=>{let recovered=false;vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(url.endsWith('/catalog'))return Response.json(catalog);const original={...row,status:recovered?'queued':'failed',error_code:recovered?null:'storage_quota_exceeded',can_retry:!recovered,recovery_mode:'local_candidate'};if(init?.method==='POST'){recovered=true;return Response.json({...original,status:'queued',error_code:null,can_retry:false,recovery_request_key:JSON.parse(String(init.body)).request_key})}return Response.json({items:[original]})}));render(<LayoutExports {...props}/>);await open();fireEvent.click(await screen.findByRole('button',{name:'恢复原导出候选'}));await waitFor(()=>expect(screen.getByRole('heading',{name:'排版导出 1 · 待执行'})).toBeTruthy());expect(screen.queryByRole('heading',{name:/排版导出 2/})).toBeNull()})
it('protects layout options and only blocks leave while the POST is executing',async()=>{
 let guard=()=>true,dirty=()=>false;const register=(next:()=>boolean,isDirty?:()=>boolean)=>{guard=next;dirty=isDirty??(()=>false);return ()=>{}}
 let reject!:(error:Error)=>void
 vi.stubGlobal('alert',vi.fn());vi.stubGlobal('confirm',vi.fn(()=>true))
 vi.stubGlobal('fetch',vi.fn((url:string,init?:RequestInit)=>init?.method==='POST'?new Promise<Response>((_resolve,rejectRequest)=>{reject=rejectRequest}):Promise.resolve(Response.json(url.endsWith('/catalog')?catalog:{items:[]}))))
 render(<LayoutExports {...props} registerLeaveGuard={register}/>);await open();expect(dirty()).toBe(false)
 fireEvent.click(screen.getByRole('checkbox',{name:'添加目录'}));expect(dirty()).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'生成排版 DOCX'}));expect(guard()).toBe(false);expect(window.alert).toHaveBeenCalledTimes(1)
 await act(async()=>reject(Error('Unknown')))
 expect(dirty()).toBe(true);expect(guard()).toBe(true);expect(window.confirm).toHaveBeenCalledTimes(1)
})
it('loads catalog only on opening, submits usable TOC, page, wide object, user formula and reference controls',async()=>{
 const {fetcher,bodies}=mock();render(<LayoutExports {...props}/>);expect(fetcher).not.toHaveBeenCalled();await open()
 fireEvent.click(screen.getByRole('checkbox',{name:'添加目录'}));fireEvent.change(screen.getByLabelText('目录深度'),{target:{value:'2'}})
 fireEvent.change(screen.getByLabelText('页码模式'),{target:{value:'roman_front'}});fireEvent.change(screen.getByLabelText('正文起始标题'),{target:{value:anchor(0)}})
 fireEvent.click(screen.getByRole('checkbox',{name:/横向显示.*Table 1/}));fireEvent.click(screen.getByRole('checkbox',{name:/横向显示.*Figure 1/}))
 fireEvent.click(screen.getByRole('button',{name:'添加用户公式'}));fireEvent.change(screen.getByLabelText('公式 1 表达式'),{target:{value:String.raw`\frac{x_i^2}{\sqrt{a}}+\alpha`}});fireEvent.change(screen.getByLabelText('公式 1 位置'),{target:{value:anchor(1)}})
 fireEvent.click(screen.getByRole('button',{name:'添加交叉引用'}));fireEvent.change(screen.getByLabelText('引用 1 目标'),{target:{value:'formula:eq1'}});fireEvent.change(screen.getByLabelText('引用 1 类型'),{target:{value:'page'}})
 fireEvent.click(screen.getByRole('button',{name:'生成排版 DOCX'}));await waitFor(()=>expect(bodies).toHaveLength(1))
 expect(JSON.parse(bodies[0])).toMatchObject({source_kind:'report',source_id:'r1',layout:{source_sha256:hash,toc:{depth:2},pagination:{mode:'roman_front',body_anchor_id:anchor(0)},landscape_anchor_ids:[anchor(2),anchor(3)],formulas:[{id:'eq1',anchor_id:anchor(1),expression:String.raw`\frac{x_i^2}{\sqrt{a}}+\alpha`,placement:'after'}],references:[{target_id:'formula:eq1',kind:'page'}]}})
 expect(screen.getByText('原始 DOCX 保留；排版结果独立保存。')).toBeTruthy();expect(screen.getByText('公式由用户明确输入，不从原稿推断。')).toBeTruthy()
})
it('rejects mismatched catalog SHA and never enables submission',async()=>{mock([],{...catalog,source_sha256:'b'.repeat(64)});render(<LayoutExports {...props}/>);fireEvent.click(screen.getByRole('button',{name:'排版与公式'}));await screen.findByRole('alert');expect(screen.queryByRole('button',{name:'生成排版 DOCX'})).toBeNull()})
it('resets the form on source or project changes and ignores late old catalog responses',async()=>{
 let resolve!:(v:Response)=>void;const fetcher=vi.fn(async(url:string)=>url.includes('/r1/catalog')?new Promise<Response>(r=>{resolve=r}):Response.json(url.endsWith('/catalog')?{...catalog,source_id:'r2'}:{items:[]}));vi.stubGlobal('fetch',fetcher)
 const view=render(<LayoutExports {...props}/>);fireEvent.click(screen.getByRole('button',{name:'排版与公式'}));view.rerender(<LayoutExports {...props} sourceId="r2"/>);await open();fireEvent.click(screen.getByRole('checkbox',{name:'添加目录'}));await act(async()=>resolve(Response.json(catalog)));expect((screen.getByRole('checkbox',{name:'添加目录'}) as HTMLInputElement).checked).toBe(true)
 view.rerender(<LayoutExports {...props} projectId="p2"/>);expect(screen.queryByRole('checkbox',{name:'添加目录'})).toBeNull()
})
it('keeps exact unknown POST body/key across edits and remount, and only replays on explicit confirmation',async()=>{
 const bodies:string[]=[];let accepted=false;const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){bodies.push(String(init.body));if(bodies.length===1){accepted=true;throw new TypeError('lost')}const body=JSON.parse(bodies[0]);return Response.json({...row,layout:body.layout,request_key:body.request_key})}return Response.json(url.endsWith('/catalog')?catalog:{items:accepted?[{...row,request_key:JSON.parse(bodies[0]).request_key,layout:JSON.parse(bodies[0]).layout}]:[]})});vi.stubGlobal('fetch',fetcher)
 const view=render(<LayoutExports {...props}/>);await open();fireEvent.click(screen.getByRole('checkbox',{name:'添加目录'}));fireEvent.click(screen.getByRole('button',{name:'生成排版 DOCX'}));await screen.findByRole('alert');view.unmount();render(<LayoutExports {...props}/>);fireEvent.click(screen.getByRole('button',{name:'排版与公式'}));const confirm=await screen.findByRole('button',{name:'确认上次排版请求'});await waitFor(()=>expect(confirm.hasAttribute('disabled')).toBe(false));expect(bodies).toHaveLength(1);fireEvent.click(confirm);await waitFor(()=>expect(bodies).toHaveLength(2));expect(bodies[1]).toBe(bodies[0])
})
it('isolates unknown bodies by authenticated owner and clears UI immediately on session changes',async()=>{
 mock();render(<LayoutExports {...props}/>);await open();fireEvent.click(screen.getByRole('button',{name:'添加用户公式'}));fireEvent.change(screen.getByLabelText('公式 1 表达式'),{target:{value:'private_user_expression'}});act(()=>setApiSession('other-session','user2'));expect(screen.queryByDisplayValue('private_user_expression')).toBeNull();expect(screen.getByRole('button',{name:'排版与公式'}).hasAttribute('disabled')).toBe(true)
})
it('honors authoritative can_retry, keeps successful DOCX and uses the shared layout_export PDF source',async()=>{
 const failed={...row,status:'failed',error_code:'layout_field_update_failed',can_retry:true};const done={...row,id:'done',status:'succeeded',sha256:'b'.repeat(64),size_bytes:100,filename:'layout.docx',renderer_manifest:{},download_url:`${base}/done/download`};const {fetcher}=mock([failed,done]);render(<LayoutExports {...props}/>);await open();expect(await screen.findByRole('link',{name:'下载排版 DOCX'})).toBeTruthy();expect(screen.getByRole('button',{name:'重试排版'})).toBeTruthy();await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url.includes('/pdf-exports?source_kind=layout_export&source_id=done'))).toBe(true))
})
it('displays readable English controls and errors without internal paths or Chinese chrome',async()=>{setLocale('en');mock([],{...catalog,filename:'source.docx'});render(<LayoutExports {...props}/>);fireEvent.click(screen.getByRole('button',{name:'Layout and equations'}));await screen.findByRole('button',{name:'Generate layout DOCX'});expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]|customXml|\/server\//);const form=screen.getByRole('group',{name:'Layout settings'});expect(within(form).getByLabelText('Page numbering')).toBeTruthy()})

it('locks creation after a lost retry response and replays the exact parent retry instead of creating another chain',async()=>{
 const failed={...row,status:'failed',error_code:'layout_field_update_failed',can_retry:true};const bodies:string[]=[];let accepted=false
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){bodies.push(String(init.body));expect(url).toBe(`${base}/l1/retry`);if(bodies.length===1){accepted=true;throw new TypeError('lost')}return Response.json({...row,id:'l2',parent_export_id:'l1',request_key:JSON.parse(bodies[0]).request_key})}return Response.json(url.endsWith('/catalog')?catalog:{items:[{...failed,can_retry:!accepted},...(accepted?[{...row,id:'l2',parent_export_id:'l1',request_key:JSON.parse(bodies[0]).request_key}]:[])]})});vi.stubGlobal('fetch',fetcher)
 const view=render(<LayoutExports {...props}/>);await open();fireEvent.click(await screen.findByRole('button',{name:'重试排版'}));await screen.findByRole('alert');view.unmount();render(<LayoutExports {...props}/>);await open();const confirm=await screen.findByRole('button',{name:'确认上次排版重试'});expect(screen.getByRole('button',{name:'生成排版 DOCX'}).hasAttribute('disabled')).toBe(true);fireEvent.click(confirm);await waitFor(()=>expect(bodies).toHaveLength(2));expect(bodies[1]).toBe(bodies[0]);expect(Object.keys(JSON.parse(bodies[0]))).toEqual(['request_key'])
})
it('uses can_retry=false even for a transient failed chain and confirms no POST from refresh',async()=>{
 const {fetcher}=mock([{...row,status:'failed',error_code:'layout_field_update_failed',can_retry:false}]);render(<LayoutExports {...props}/>);await open();expect(screen.queryByRole('button',{name:'重试排版'})).toBeNull();fireEvent.click(screen.getByRole('button',{name:'刷新排版状态'}));await waitFor(()=>expect(fetcher.mock.calls.length).toBeGreaterThan(2));expect(fetcher.mock.calls.every(([,init])=>init?.method!=='POST')).toBe(true)
})
it('surfaces a bounded POST timeout and preserves its exact body for explicit confirmation',async()=>{
 vi.useFakeTimers();const bodies:string[]=[];vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){bodies.push(String(init.body));return new Promise<Response>(()=>{})}return Response.json(url.endsWith('/catalog')?catalog:{items:[]})}));render(<LayoutExports {...props}/>);fireEvent.click(screen.getByRole('button',{name:'排版与公式'}));await act(async()=>{});fireEvent.click(screen.getByRole('button',{name:'生成排版 DOCX'}));await act(async()=>vi.advanceTimersByTime(15000));expect(screen.getByRole('alert').textContent).toContain('排版请求未确认');expect(screen.getByRole('button',{name:'确认上次排版请求'})).toBeTruthy();expect(bodies).toHaveLength(1)
})
it('keeps DOCX downloadable when its shared PDF fails and never treats PDF as the original source',async()=>{
 const done={...row,status:'succeeded',sha256:'b'.repeat(64),size_bytes:100,filename:'layout.docx',renderer_manifest:{},download_url:`${base}/l1/download`};const fetcher=vi.fn(async(url:string,init?:RequestInit)=>Response.json(url.includes('/pdf-exports')?init?.method==='POST'?{detail:{code:'pdf_conversion_failed'}}:{items:[]}:url.endsWith('/catalog')?catalog:{items:[done]},{status:url.includes('/pdf-exports')&&init?.method==='POST'?503:200}));vi.stubGlobal('fetch',fetcher);render(<LayoutExports {...props}/>);await open();const button=await screen.findByRole('button',{name:'生成 PDF'});await waitFor(()=>expect(button.hasAttribute('disabled')).toBe(false));fireEvent.click(button);await screen.findByRole('alert');expect(screen.getByRole('link',{name:'下载排版 DOCX'})).toBeTruthy();const post=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(JSON.parse(String(post[1]?.body))).toMatchObject({source_kind:'layout_export',source_id:'l1'})
})
it('pauses polling in closed parent details and restores without submitting',async()=>{
 vi.useFakeTimers();const {fetcher}=mock([row]);const view=render(<details><summary>Version</summary><LayoutExports {...props} initialOpen/></details>);await act(async()=>{});expect(fetcher).not.toHaveBeenCalled();view.rerender(<details open><summary>Version</summary><LayoutExports {...props} initialOpen/></details>);await act(async()=>{});expect(fetcher).toHaveBeenCalledTimes(2);view.rerender(<details><summary>Version</summary><LayoutExports {...props} initialOpen/></details>);await act(async()=>{});const count=fetcher.mock.calls.length;await act(async()=>vi.advanceTimersByTime(9000));expect(fetcher).toHaveBeenCalledTimes(count)
})
it('locates formula validation errors without echoing raw exception messages or paths',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{detail:{code:'layout_formula_invalid',message:'/secret/path',params:{formula_id:'eq1',position:5,reason:'/server/path'}}}:url.endsWith('/catalog')?catalog:{items:[]},{status:init?.method==='POST'?422:200})));render(<LayoutExports {...props}/>);await open();fireEvent.click(screen.getByRole('button',{name:'添加用户公式'}));fireEvent.change(screen.getByLabelText('公式 1 表达式'),{target:{value:String.raw`\unknown{x}`}});fireEvent.click(screen.getByRole('button',{name:'生成排版 DOCX'}));const alert=await screen.findByRole('alert');expect(alert.textContent).toContain('eq1');expect(document.body.textContent).not.toMatch(/secret|server\/path/);expect(screen.getByRole('button',{name:'生成排版 DOCX'})).toBeTruthy()
})

it.each([
 ['invalid','公式 badFormula 无效'],['wide','公式 badFormula 无效'],
 ['target','references.0.target_id'],['pagination','pagination.body_anchor_id'],['toc','toc.depth'],
])('locates %s using the real Python engine and public serializer response',async(caseName,expected)=>{
 const python=process.env.PAPERASSIST_TEST_PYTHON??resolve('..','backend','.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python')
 const payload=JSON.parse(execFileSync(python,[resolve('..','backend','tests','fixtures','layout_public_error.py'),caseName],{encoding:'utf8'}))
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?payload:url.endsWith('/catalog')?catalog:{items:[]},{status:init?.method==='POST'?422:200})))
 render(<LayoutExports {...props}/>);await open()
 fireEvent.click(screen.getByRole('button',{name:'添加用户公式'}))
 fireEvent.change(screen.getByLabelText('公式 1 标识'),{target:{value:'badFormula'}})
 fireEvent.change(screen.getByLabelText('公式 1 表达式'),{target:{value:String.raw`\unsupported{x}`}})
 fireEvent.click(screen.getByRole('button',{name:'生成排版 DOCX'}))
 expect((await screen.findByRole('alert')).textContent).toContain(expected)
 expect(document.body.textContent).not.toContain('unknown_command')
})

it.each(['zh-CN','en'] as const)('explains parser depth, matrix/cases and aligned limits in %s',async locale=>{
 setLocale(locale);mock();render(<LayoutExports {...props}/>)
 fireEvent.click(screen.getByRole('button',{name:locale==='en'?'Layout and equations':'排版与公式'}))
 await screen.findByRole('button',{name:locale==='en'?'Generate layout DOCX':'生成排版 DOCX'})
 expect(screen.getByText(locale==='en'
  ?'Nesting depth: up to 12. matrix: up to 6 rows × 6 columns; cases: up to 6 rows with exactly 2 columns; aligned: up to 8 lines.'
  :'嵌套深度最多 12 层；matrix 最多 6 行 × 6 列，cases 最多 6 行且固定 2 列；aligned 最多 8 行。')).toBeTruthy()
})

it.each(['report','collection_report','manuscript_export'] as const)('creates a new layout only for exact %s source ID, language and catalog hash',async sourceKind=>{
 const sourceId=`${sourceKind}-saved`;const bodies:string[]=[];vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){bodies.push(String(init.body));const body=JSON.parse(String(init.body));return Response.json({...row,source_kind:sourceKind,source_id:sourceId,request_key:body.request_key,layout:body.layout})}return Response.json(url.endsWith('/catalog')?{...catalog,source_kind:sourceKind,source_id:sourceId,version:sourceKind==='report'?catalog.version:{id:'v1',revision:2,...(sourceKind==='collection_report'?{export_revision:3}:{})}}:{items:[]})}));render(<LayoutExports {...props} sourceKind={sourceKind} sourceId={sourceId}/>);await open();fireEvent.click(screen.getByRole('button',{name:'生成排版 DOCX'}));await waitFor(()=>expect(bodies).toHaveLength(1));expect(JSON.parse(bodies[0])).toMatchObject({source_kind:sourceKind,source_id:sourceId,layout:{source_sha256:hash}});expect(JSON.parse(bodies[0])).not.toHaveProperty('output_language')
})
it('prevents unsupported references to inline equations and blocks empty user expressions before POST',async()=>{
 const {fetcher}=mock();render(<LayoutExports {...props}/>);await open();fireEvent.click(screen.getByRole('button',{name:'添加用户公式'}));fireEvent.change(screen.getByLabelText('公式 1 模式'),{target:{value:'inline'}});fireEvent.click(screen.getByRole('button',{name:'添加交叉引用'}));expect(within(screen.getByLabelText('引用 1 目标')).queryByRole('option',{name:'用户公式 eq1'})).toBeNull();fireEvent.click(screen.getByRole('button',{name:'生成排版 DOCX'}));await screen.findByRole('alert');expect(fetcher.mock.calls.every(([,init])=>init?.method!=='POST')).toBe(true)
})

it('opens a Python-compatible160-code-point source excerpt containing a non-BMP character',async()=>{
 mock([],{...catalog,anchors:catalog.anchors.map((a,i)=>i? a:{...a,text:'𝑥'+'a'.repeat(159)})});render(<LayoutExports {...props}/>);await open();expect(screen.getByRole('group',{name:'排版设置'})).toBeTruthy();expect(screen.queryByRole('alert')).toBeNull()
})
it('accepts full Unicode equation/prefix limits and caps overflow by code point without native UTF-16 maxLength',async()=>{
 const {bodies}=mock();render(<LayoutExports {...props}/>);await open();fireEvent.click(screen.getByRole('button',{name:'添加用户公式'}));fireEvent.click(screen.getByRole('button',{name:'添加交叉引用'}))
 const expression=screen.getByLabelText('公式 1 表达式') as HTMLTextAreaElement,prefix=screen.getByLabelText('引用 1 前缀') as HTMLInputElement
 expect(expression.hasAttribute('maxlength')).toBe(false);expect(prefix.hasAttribute('maxlength')).toBe(false)
 const fullExpression='𝑥'+'x'.repeat(1999),fullPrefix='𝑥'+'p'.repeat(99)
 fireEvent.change(expression,{target:{value:fullExpression}});fireEvent.change(prefix,{target:{value:fullPrefix}});expect(expression.value).toBe(fullExpression);expect(prefix.value).toBe(fullPrefix)
 fireEvent.change(expression,{target:{value:fullExpression+'𝑦'}});fireEvent.change(prefix,{target:{value:fullPrefix+'𝑦'}});expect(expression.value).toBe(fullExpression);expect(prefix.value).toBe(fullPrefix)
 // A supplementary character at the final legal position must never split into
 // a lone UTF-16 surrogate while the following character is discarded.
 const finalExpression='x'.repeat(1999)+'𝑥',finalPrefix='p'.repeat(99)+'𝑥'
 fireEvent.change(expression,{target:{value:finalExpression+'z'}});fireEvent.change(prefix,{target:{value:finalPrefix+'z'}});expect(expression.value).toBe(finalExpression);expect(prefix.value).toBe(finalPrefix)
 fireEvent.click(screen.getByRole('button',{name:'生成排版 DOCX'}));await waitFor(()=>expect(bodies).toHaveLength(1));expect(JSON.parse(bodies[0]).layout.formulas[0].expression).toBe(finalExpression);expect(JSON.parse(bodies[0]).layout.references[0].prefix).toBe(finalPrefix)
})
