import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptExports from './ManuscriptExports'
import PresentationExportDetails from './PresentationExportDetails'
import {exportFixture,manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
import {setApiSession} from '../../shared/api/client'
import {taskFixture} from '../tasks/taskFixtures'
const base='/api/v1/projects/p1/manuscripts/m1/versions/1/exports'
const props={projectId:'p1',manuscriptId:'m1',version:{...manuscriptFixture.versions[0],exports:[]} as unknown as ManuscriptVersion}
afterEach(()=>{cleanup();sessionStorage.clear();vi.useRealTimers();vi.unstubAllGlobals()})
it('keeps successful Word exports without PDF history or requests',async()=>{
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.includes('/pdf-exports'))return init?.method==='POST'?Response.json({detail:{code:'pdf_conversion_failed'}},{status:503}):Response.json({items:[]})
  return Response.json({items:[exportFixture]})
 });vi.stubGlobal('fetch',fetcher);render(<ManuscriptExports {...props}/>);await screen.findByRole('link',{name:'下载 DOCX'})
 expect(screen.queryByRole('button',{name:'生成 PDF'})).toBeNull();expect(screen.getByRole('link',{name:'下载 DOCX'})).toBeTruthy()
 expect(screen.getByRole('button',{name:'排版与公式'})).toBeTruthy();expect(fetcher.mock.calls.some(([url])=>url.includes('/layout-exports'))).toBe(false)
 expect(fetcher.mock.calls.some(([,i])=>i?.method==='POST')).toBe(false)
 expect(fetcher.mock.calls.some(([url])=>url.includes('/pdf-exports'))).toBe(false);expect(screen.queryByRole('region',{name:/PDF/})).toBeNull()
})
it('restores queued exports by GET and polls their status without resubmitting',async()=>{
 vi.useFakeTimers();let ready=false
 const fetcher=vi.fn(async(_url:string,_init?:RequestInit)=>Response.json({items:[{...exportFixture,status:ready?'succeeded':'queued',download_url:ready?exportFixture.download_url:null,filename:ready?'draft.docx':null,size_bytes:ready?100:null}]}))
 vi.stubGlobal('fetch',fetcher);render(<ManuscriptExports {...props}/>);await act(async()=>{})
 expect(screen.getByRole('status').textContent).toBe('待执行');ready=true
 await act(async()=>vi.advanceTimersByTime(3000));expect(screen.getByRole('link',{name:'下载 DOCX'})).toBeTruthy()
 expect(fetcher.mock.calls.every(([,init])=>!init?.method)).toBe(true)
})
it('keeps publication success independent from DOCX failure and retries a failed export through bounded recovery',async()=>{
 let recovered=false
 const input={kind:'manuscript',manuscript_version_id:'v1',output_language:'en',workflow_version:'manuscript_fact_draft_v1'}
 const task={...taskFixture,id:'export-task',task_type:'manuscript_docx',status:'failed',display_status:'failed',phase:'export',input_version:input,error_code:'task_failed',reason_code:null}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/workspace'))return Response.json({task,source:{file_id:null,filename:'Draft',analysis_run_id:null,is_current:true},wait:null,allowed_actions:['retry'],artifacts:{figure:null,explanation:null,report:null}})
  if(init?.method==='POST'){recovered=true;return Response.json({...task,status:'queued',display_status:'queued',revision:4})}
  return Response.json({items:[{...exportFixture,status:recovered?'queued':'failed',download_url:null}]})
 });vi.stubGlobal('fetch',fetcher);render(<ManuscriptExports {...props}/> )
 fireEvent.click(await screen.findByRole('button',{name:'重试 DOCX'}))
 await screen.findByText('待执行')
 const posts=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(posts).toHaveLength(1)
 expect(posts[0][0]).toBe('/api/v1/tasks/export-task/resume')
 expect(JSON.parse(String(posts[0][1]?.body))).toEqual({operation:'retry',wait_id:null,expected_task_revision:3,input_version:input})
})
it('rejects exports for a different frozen manuscript version',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{...exportFixture,version_id:'v2'}]})))
 render(<ManuscriptExports {...props}/>);await screen.findByRole('alert');expect(screen.queryByRole('link',{name:'下载 DOCX'})).toBeNull();expect(screen.queryByRole('button',{name:'生成 PDF'})).toBeNull()
})
it('uses one request key for duplicate clicks and explicit retry after an uncertain POST',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{
  if(init?.method==='POST')throw new TypeError('network')
  return Response.json({items:[]})
 });vi.stubGlobal('fetch',fetcher);render(<ManuscriptExports {...props}/>)
 fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}));fireEvent.click(screen.getByRole('button',{name:'正在提交……'}))
 await screen.findByRole('alert');fireEvent.click(screen.getByRole('button',{name:'用原请求重试 Word'}))
 await waitFor(()=>expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(2))
 const calls=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(calls[0][0]).toBe(base)
 expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'))
})

it('retains a lost export response across reload and replays only the original request explicitly',async()=>{
 let posts=0
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){posts++;if(posts===1)throw Error('response lost');return Response.json(exportFixture)}
  return Response.json({items:posts>1?[exportFixture]:[]})
 });vi.stubGlobal('fetch',fetcher)
 const first=render(<ManuscriptExports {...props}/>);fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}))
 await screen.findByRole('alert');first.unmount();render(<ManuscriptExports {...props}/>)
 await screen.findByText('Word 提交结果待核对，原请求和固定输入已保留。')
 expect((screen.getByRole('button',{name:'生成 DOCX'}) as HTMLButtonElement).disabled).toBe(true)
 expect(screen.queryByText('当前版本尚未生成 Word。')).toBeNull();expect(posts).toBe(1)
 fireEvent.click(screen.getByRole('button',{name:'刷新 DOCX 状态'}));await waitFor(()=>expect(fetcher.mock.calls.filter(([,i])=>!i?.method).length).toBeGreaterThan(1));expect(posts).toBe(1)
 fireEvent.click(screen.getByRole('button',{name:'用原请求重试 Word'}));await screen.findByRole('link',{name:'下载 DOCX'})
 const writes=fetcher.mock.calls.filter(([,init])=>init?.method==='POST')
 expect(writes).toHaveLength(2);expect(writes[0][0]).toBe(writes[1][0]);expect(writes[0][1]?.body).toBe(writes[1][1]?.body)
 expect(new Headers(writes[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(writes[1][1]?.headers).get('Idempotency-Key'))
})

it.each([408,409])('keeps an uncertain or conflicting %s export fixed after reload',async(status)=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>init?.method==='POST'?Response.json({detail:{code:'task_idempotency_conflict'}},{status}):Response.json({items:[]}));vi.stubGlobal('fetch',fetcher)
 const first=render(<ManuscriptExports {...props}/>);fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}));await screen.findByRole('alert')
 first.unmount();render(<ManuscriptExports {...props}/>);await screen.findByText('Word 提交结果待核对，原请求和固定输入已保留。')
 expect((screen.getByRole('button',{name:'生成 DOCX'}) as HTMLButtonElement).disabled).toBe(true)
 expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(1)
})
it('releases a stale resume intent after the same task advances and fails again',async()=>{
 let posts=0
 const input={kind:'manuscript',manuscript_version_id:'v1',output_language:'en',workflow_version:'manuscript_fact_draft_v1'}
 const task={...taskFixture,id:'export-task',task_type:'manuscript_docx',status:'failed',display_status:'failed',phase:'export',input_version:input,error_code:'task_failed',reason_code:null}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/workspace'))return Response.json({task:{...task,revision:posts?4:3},source:{file_id:null,filename:'Draft',analysis_run_id:null,is_current:true},wait:null,allowed_actions:['retry'],artifacts:{figure:null,explanation:null,report:null}})
  if(init?.method==='POST'){posts++;if(posts===1)throw Error('accepted then failed, response lost');return Response.json({...task,status:'queued',display_status:'queued',revision:5})}
  return Response.json({items:[{...exportFixture,status:posts>1?'queued':'failed',download_url:null}]})
 });vi.stubGlobal('fetch',fetcher)
 const first=render(<ManuscriptExports {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'重试 DOCX'}));await screen.findByText('Word 提交结果待核对，原请求和固定输入已保留。');first.unmount()
 render(<ManuscriptExports {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'用原请求重试 Word'}))
 await waitFor(()=>expect(screen.queryByText('Word 提交结果待核对，原请求和固定输入已保留。')).toBeNull());expect(posts).toBe(1)
 fireEvent.click(await screen.findByRole('button',{name:'重试 DOCX'}));await waitFor(()=>expect(posts).toBe(2))
 const writes=fetcher.mock.calls.filter(([,i])=>i?.method==='POST')
 expect(JSON.parse(String(writes[0][1]?.body)).expected_task_revision).toBe(3)
 expect(JSON.parse(String(writes[1][1]?.body)).expected_task_revision).toBe(4)
 expect(new Headers(writes[0][1]?.headers).get('Idempotency-Key')).not.toBe(new Headers(writes[1][1]?.headers).get('Idempotency-Key'))
})
it('clears saved downloads and aborts requests when the authenticated session changes',async()=>{
 const fetcher=vi.fn(async()=>Response.json({items:[exportFixture]}));vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptExports {...props}/>);await screen.findByRole('link',{name:'下载 DOCX'})
 act(()=>setApiSession('another-session'));expect(screen.queryByRole('link',{name:'下载 DOCX'})).toBeNull()
 expect(screen.getByRole('alert').textContent).toContain('会话已失效')
})

it('shows successful Word before manual generation and identifies an empty fixed version',async()=>{
 const fetcher=vi.fn(async(_url:string,_init?:RequestInit)=>Response.json({items:[exportFixture]}));vi.stubGlobal('fetch',fetcher);const view=render(<ManuscriptExports {...props}/>)
 const download=await screen.findByRole('link',{name:'下载 DOCX'});const generate=screen.getByRole('button',{name:'生成 DOCX'});expect(download.compareDocumentPosition(generate)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();expect(screen.getByText('事实稿 Word · 版本 1')).toBeTruthy();expect(fetcher.mock.calls.every(([,init])=>!init?.method)).toBe(true)
 view.unmount();fetcher.mockImplementation(async()=>Response.json({items:[]}));render(<ManuscriptExports {...props}/>);expect(await screen.findByText('当前版本尚未生成 Word。')).toBeTruthy()
})

it.each(['queued','running','failed'] as const)('does not call a %s export absent',async status=>{
 const item={...exportFixture,status,download_url:null,filename:null,size_bytes:null};vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[item]})))
 render(<ManuscriptExports {...props}/>);await screen.findByText(({queued:'待执行',running:'运行中',failed:'执行失败'} as const)[status])
 expect(screen.queryByText('当前版本尚未生成 Word。')).toBeNull();expect(screen.queryByRole('link',{name:'下载 DOCX'})).toBeNull()
 if(status==='queued'||status==='running')expect(screen.getByText('Word 正在生成，请等待任务完成。')).toBeTruthy()
})

it('does not claim Word is absent on a failed read or invalid succeeded record',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{...exportFixture,download_url:null}]})))
 render(<ManuscriptExports {...props}/>);await screen.findByRole('alert');expect(screen.queryByText('当前版本尚未生成 Word。')).toBeNull();expect(screen.queryByRole('link',{name:'下载 DOCX'})).toBeNull()
})
it('removes the empty-state claim when the session becomes invalid',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})));render(<ManuscriptExports {...props}/>);await screen.findByText('当前版本尚未生成 Word。')
 act(()=>setApiSession('new-session'));expect(screen.queryByText('当前版本尚未生成 Word。')).toBeNull()
})

// B03 task 6: an adopted current version gets its Word generated once, with a deterministic key.
type StoredExport=typeof exportFixture
function wordServer(options:{fail?:boolean;initial?:StoredExport[]}={}){
 const state={items:[...(options.initial??[])] as StoredExport[],keys:[] as string[]}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url===base&&init?.method==='POST'){
   const key=new Headers(init.headers).get('Idempotency-Key')!;state.keys.push(key)
   if(options.fail)return Response.json({detail:{code:'internal_error'}},{status:500})
   const found=state.items.find(item=>item.id===`export-${key}`)
   if(found)return Response.json(found)
   const created={...exportFixture,id:`export-${key}`,status:'queued',download_url:null,filename:null,size_bytes:null,sha256:null} as unknown as StoredExport
   state.items.unshift(created);return Response.json(created,{status:201})
  }
  if(url===base)return Response.json({items:state.items})
  return Response.json({items:[]})
 })
 return {state,fetcher}
}
const adopted={...props.version,parent_version_id:'v0',snapshot:{...props.version.snapshot,review_provenance:{round_id:'r1'}}} as unknown as ManuscriptVersion
const posts=(fetcher:ReturnType<typeof vi.fn>)=>fetcher.mock.calls.filter(([,init])=>(init as RequestInit|undefined)?.method==='POST')
it('generates Word once for an adopted published version with no exports, keyed by the version',async()=>{
 const {state,fetcher}=wordServer();vi.stubGlobal('fetch',fetcher)
 const onAutoStarted=vi.fn()
 const view=render(<ManuscriptExports {...props} version={adopted} customerSci autoStart onAutoStarted={onAutoStarted}/>)
 await waitFor(()=>expect(posts(fetcher)).toHaveLength(1))
 const [url,init]=posts(fetcher)[0];expect(url).toBe(base);expect(init?.body).toBe('{}')
 expect(new Headers(init?.headers).get('Idempotency-Key')).toBe('auto-word-v1')
 expect(await screen.findByText('正在准备这一版的 Word……')).toBeTruthy()
 expect(onAutoStarted).toHaveBeenCalledOnce()
 view.unmount();render(<ManuscriptExports {...props} version={adopted} customerSci autoStart/>)
 await screen.findByText('正在准备这一版的 Word……')
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20))})
 expect(posts(fetcher)).toHaveLength(1);expect(state.items).toHaveLength(1)
})
it('waits for a pending adopted version to be published before generating its Word once',async()=>{
 const {fetcher}=wordServer();vi.stubGlobal('fetch',fetcher)
 const pending={...adopted,status:'pending'} as ManuscriptVersion
 const view=render(<ManuscriptExports {...props} version={pending} customerSci autoStart/>)
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20))})
 expect(posts(fetcher)).toHaveLength(0)
 view.rerender(<ManuscriptExports {...props} version={adopted} customerSci autoStart/>)
 await waitFor(()=>expect(posts(fetcher)).toHaveLength(1))
 view.rerender(<ManuscriptExports {...props} version={{...adopted}} customerSci autoStart/>)
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20))})
 expect(posts(fetcher)).toHaveLength(1)
})
it('keeps two open windows to one Word record for the same adopted version',async()=>{
 const {state,fetcher}=wordServer();vi.stubGlobal('fetch',fetcher)
 render(<><ManuscriptExports {...props} version={adopted} customerSci autoStart/><ManuscriptExports {...props} version={adopted} customerSci autoStart/></>)
 await waitFor(()=>expect(state.keys.length).toBeGreaterThan(0))
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20))})
 expect(new Set(state.keys)).toEqual(new Set(['auto-word-v1']));expect(state.items).toHaveLength(1)
})
it.each(['failed','succeeded'] as const)('does not generate Word by itself when a %s export already exists',async status=>{
 const existing={...exportFixture,status,...(status==='failed'?{download_url:null,filename:null,size_bytes:null,error_code:'task_failed'}:{})} as unknown as StoredExport
 const {fetcher}=wordServer({initial:[existing]});vi.stubGlobal('fetch',fetcher)
 const {container}=render(<ManuscriptExports {...props} version={adopted} customerSci autoStart/>)
 await screen.findByText(status==='failed'?'这一版 Word 没有生成成功。':'已完成')
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20))})
 expect(posts(fetcher)).toHaveLength(0)
 if(status==='failed')expect(screen.getByRole('button',{name:'重试'})).toBeTruthy()
 else expect(screen.getByRole('link',{name:'下载这份 Word'})).toBeTruthy()
 expect(container.textContent).not.toMatch(/DOCX/)
})
it('does not submit again by itself after the automatic Word request fails with an unknown result',async()=>{
 const {fetcher}=wordServer({fail:true});vi.stubGlobal('fetch',fetcher)
 const view=render(<ManuscriptExports {...props} version={adopted} customerSci autoStart/>)
 expect(await screen.findByText('暂时无法确定这次提交是否成功。请先查看提交结果。')).toBeTruthy()
 expect(screen.getByRole('button',{name:'查看提交结果'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'刷新 Word 状态'}))
 view.unmount();render(<ManuscriptExports {...props} version={adopted} customerSci autoStart/>)
 await screen.findByText('暂时无法确定这次提交是否成功。请先查看提交结果。')
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20))})
 expect(posts(fetcher)).toHaveLength(1)
})
it('does not generate Word by itself without autoStart and uses a fresh key for a manual customer request',async()=>{
 const {fetcher}=wordServer({initial:[exportFixture]});vi.stubGlobal('fetch',fetcher)
 const {container}=render(<ManuscriptExports {...props} version={adopted} customerSci/>)
 expect((await screen.findByRole('link',{name:'下载这份 Word'})).getAttribute('href')).toBe(exportFixture.download_url)
 expect(screen.getByRole('region',{name:'Word'})).toBeTruthy()
 expect(screen.getByRole('button',{name:'刷新 Word 状态'})).toBeTruthy()
 expect(posts(fetcher)).toHaveLength(0)
 fireEvent.click(screen.getByRole('button',{name:'重新生成 Word'}))
 await waitFor(()=>expect(posts(fetcher)).toHaveLength(1))
 expect(new Headers(posts(fetcher)[0][1]?.headers).get('Idempotency-Key')).not.toMatch(/^auto-word-/)
 expect(container.textContent).not.toMatch(/DOCX/)
})
it('lists earlier Word files of the customer version with minute-level version labels',async()=>{
 const older={...exportFixture,id:'export0',created_at:'2026-10-19T02:05:00Z',download_url:'/api/v1/projects/p1/manuscripts/m1/exports/export0/download'}
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[exportFixture,older]})))
 render(<ManuscriptExports {...props} version={adopted} customerSci/>)
 const earlier=await screen.findByRole('region',{name:'之前生成的 Word'})
 expect(earlier.textContent).toMatch(/第 1 版 · /)
 expect(within(earlier).getByRole('link',{name:'下载这份 Word'}).getAttribute('href')).toBe(older.download_url)
 expect(screen.getAllByRole('link',{name:'下载这份 Word'})).toHaveLength(2)
})
it('reports a failed customer Word read in Word terms',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>{throw new TypeError('network')}))
 render(<ManuscriptExports {...props} version={adopted} customerSci/>)
 expect((await screen.findByRole('alert')).textContent).toBe('Word 状态读取失败，请刷新。')
})

// B04 task 10 (wireframe 15, B04-5): the thesis customer Word page has one Word kind. Each row shows the time the
// manuscript version was saved and, separately, when this Word was generated; the newest successful Word is current
// and earlier ones move aside. A historical blind export (blind review removed 2026-11-19) is a read-only label and
// download only, and never counts as the current Word.
const minuteText=(iso:string)=>new Date(iso).toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})
const thesisChapters=[{id:'chapter-result',title:'第三章 实验结果',level:1,purpose:'results',output_language:'zh-CN',result_group_ids:[]}]
const thesisProfile={revision:2,school:'测试学校',department:'',major:'',degree_type:'硕士',education_level:'研究生',applicable_version:'2026',bound_confirmation_id:'confirm1'}
const thesisVersion={...props.version,created_at:'2026-11-19T07:40:00Z',snapshot:{...props.version.snapshot,output_language:'zh-CN',thesis_context:{schema_version:1,profile:thesisProfile,template_version_id:'template1',confirmation_id:'confirm1',confirmation_sha256:'a'.repeat(64),confirmation:{id:'confirm1',chapters:thesisChapters.map(({id,title,level})=>({id,title,level}))},source_files:[],chapters:thesisChapters}}} as unknown as ManuscriptVersion
const wordExport=(id:string,created_at:string,extra:Record<string,unknown>={})=>({...exportFixture,id,task_id:`task-${id}`,created_at,filename:'毕业论文.docx',download_url:`/api/v1/projects/p1/manuscripts/m1/exports/${id}/download`,...extra})
const identifiedPresentation={binding:{presentation_version_id:'p-staff',language_view:'zh-CN',review_mode:'identified'},checks:[],quality:{scientific_semantic:'pending',word_wps:'pending',real_compliance:'pending'}}
const legacyBlindPresentation={binding:{presentation_version_id:'p-old',language_view:'zh-CN',review_mode:'blind'},checks:[{code:'blind:images',status:'pending',message:'Images require blind review'}],quality:{scientific_semantic:'pending',word_wps:'pending',real_compliance:'pending'},blind:{known_identity_check:'passed',remaining:[],images:'pending_manual_review',exceptions:[],anonymity_verified:false}}
const heading=(row:HTMLElement)=>row.querySelector('strong')!.textContent
const exportRows=(root:HTMLElement)=>[...root.querySelectorAll<HTMLElement>(':scope > .manuscript-export')]
function captureDownload(){
 const names:string[]=[]
 vi.stubGlobal('URL',class extends URL{static createObjectURL=()=>'blob:word';static revokeObjectURL=vi.fn()})
 const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(function(this:HTMLAnchorElement){if(this.download)names.push(this.download)})
 return {names,restore:()=>click.mockRestore()}
}

it('offers one Word action on the thesis customer page without signed or blind choices or configuration wording',async()=>{
 const staffOutput=wordExport('export-staff','2026-11-19T08:15:00Z',{presentation:identifiedPresentation})
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[staffOutput]})))
 const {container}=render(<ManuscriptExports {...props} version={thesisVersion} customerThesis/>)
 await screen.findByRole('link',{name:'下载这份 Word'})
 expect(container.querySelectorAll('[aria-pressed]')).toHaveLength(0)
 // “检查能否生成 Word” (B05 task 11) only checks the school options; it is not a second Word action.
 expect(screen.getAllByRole('button').filter(b=>/^(重新|再次)?生成 Word$/.test(b.textContent??'')).map(b=>b.textContent)).toEqual(['重新生成 Word'])
 expect(screen.getByRole('button',{name:'检查能否生成 Word'})).toBeTruthy()
 for(const text of ['署名稿','盲审','输出配置','配置版本','独立盲审派生稿','已绑定保存配置','关联语言稿件'])expect(container.textContent).not.toContain(text)
 expect(container.querySelectorAll('details')).toHaveLength(0)
})

it('labels each thesis Word with the version time and its generation time and moves the old Word aside after regenerating',async()=>{
 const older=wordExport('export-old','2026-11-19T08:15:00Z')
 const created=wordExport('export-new','2026-11-19T10:05:00Z')
 const state={items:[older] as unknown[]}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url===base&&init?.method==='POST'){state.items=[created,...state.items];return Response.json(created,{status:201})}
  if(url===base)return Response.json({items:state.items})
  if(url.endsWith('/download'))return new Response(new Blob(['DOCX']))
  return new Response(null,{status:404})
 })
 vi.stubGlobal('fetch',fetcher)
 const download=captureDownload()
 try{
  render(<ManuscriptExports {...props} version={thesisVersion} customerThesis/>)
  const region=screen.getByRole('region',{name:'Word'})
  await within(region).findByRole('link',{name:'下载这份 Word'})
  const [first]=exportRows(region)
  expect(heading(first)).toBe(`第 1 版 · ${minuteText(thesisVersion.created_at)}当前（生成于 ${minuteText(older.created_at)}）`)
  expect(first.querySelector('time')?.getAttribute('dateTime')).toBe(thesisVersion.created_at)
  expect(screen.queryByRole('region',{name:'之前生成的 Word'})).toBeNull()
  fireEvent.click(screen.getByRole('button',{name:'重新生成 Word'}))
  const earlier=await screen.findByRole('region',{name:'之前生成的 Word'})
  const [current]=exportRows(region)
  expect(heading(current)).toBe(`第 1 版 · ${minuteText(thesisVersion.created_at)}当前（生成于 ${minuteText(created.created_at)}）`)
  expect(within(current).getByRole('link',{name:'下载这份 Word'}).getAttribute('href')).toBe(created.download_url)
  const [moved]=exportRows(earlier)
  expect(heading(moved)).toBe(`第 1 版 · ${minuteText(thesisVersion.created_at)}（生成于 ${minuteText(older.created_at)}）`)
  expect(within(earlier).getByRole('link',{name:'下载这份 Word'}).getAttribute('href')).toBe(older.download_url)
  fireEvent.click(within(current).getByRole('link',{name:'下载这份 Word'}))
  await waitFor(()=>expect(download.names).toEqual(['毕业论文.docx']))
 }finally{download.restore()}
})

it('lists a historical blind export read-only beside the current Word without making it current',async()=>{
 const identified=wordExport('export-signed','2026-11-19T08:15:00Z')
 const blind=wordExport('export-blind','2026-11-19T09:30:00Z',{filename:'毕业论文盲审稿.docx',presentation:legacyBlindPresentation})
 const failedBlind=wordExport('export-blind-failed','2026-11-19T09:45:00Z',{status:'failed',error_code:'export_failed',filename:null,download_url:null,sha256:null,size_bytes:null,presentation:legacyBlindPresentation})
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.endsWith('/download')?new Response(new Blob(['DOCX'])):Response.json({items:[failedBlind,blind,identified]})))
 const download=captureDownload()
 try{
  const {container}=render(<ManuscriptExports {...props} version={thesisVersion} customerThesis/>)
  const region=screen.getByRole('region',{name:'Word'})
  const earlier=await screen.findByRole('region',{name:'之前生成的 Word'})
  const top=exportRows(region)
  expect(top).toHaveLength(1)
  expect(heading(top[0])).toContain('当前')
  expect(top[0].textContent).not.toContain('历史盲审稿')
  expect(within(top[0]).getByRole('link',{name:'下载这份 Word'}).getAttribute('href')).toBe(identified.download_url)
  const rows=exportRows(earlier)
  expect(rows).toHaveLength(2)
  for(const row of rows){expect(row.textContent).toContain('历史盲审稿');expect(heading(row)).not.toContain('当前')}
  expect(within(earlier).getByRole('link',{name:'下载这份 Word'}).getAttribute('href')).toBe(blind.download_url)
  expect(screen.queryByRole('button',{name:'重试'})).toBeNull()
  for(const text of ['Images require blind review','盲审自动检查回执','独立盲审派生稿'])expect(container.textContent).not.toContain(text)
  expect(screen.queryByText('当前版本尚未生成 Word。')).toBeNull()
  fireEvent.click(within(earlier).getByRole('link',{name:'下载这份 Word'}))
  await waitFor(()=>expect(download.names).toEqual(['毕业论文盲审稿.docx']))
 }finally{download.restore()}
})

it('does not treat a lone historical blind export as the Word of this version',async()=>{
 const blind=wordExport('export-blind','2026-11-19T09:30:00Z',{filename:'毕业论文盲审稿.docx',presentation:legacyBlindPresentation})
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[blind]})))
 render(<ManuscriptExports {...props} version={thesisVersion} customerThesis/>)
 expect(await screen.findByText('当前版本尚未生成 Word。')).toBeTruthy()
 expect(screen.getByRole('button',{name:'生成 Word'})).toBeTruthy()
 const earlier=screen.getByRole('region',{name:'之前生成的 Word'})
 expect(earlier.textContent).toContain('历史盲审稿')
 expect(exportRows(screen.getByRole('region',{name:'Word'}))).toHaveLength(0)
})

it('keeps the revised thesis Word list on the same version and generation times',async()=>{
 const older=wordExport('export-old','2026-11-19T08:15:00Z',{filename:'毕业论文修订稿.docx'})
 const newer=wordExport('export-new','2026-11-19T10:05:00Z',{filename:'毕业论文修订稿.docx'})
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[newer,older]})))
 render(<ManuscriptExports {...props} version={thesisVersion} customerThesis revisedResult/>)
 const earlier=await screen.findByRole('region',{name:'之前生成的 Word'})
 const [current]=exportRows(screen.getByRole('region',{name:'Word'}))
 expect(heading(current)).toBe(`第 1 版 · ${minuteText(thesisVersion.created_at)}当前（生成于 ${minuteText(newer.created_at)}）`)
 expect(heading(exportRows(earlier)[0])).toBe(`第 1 版 · ${minuteText(thesisVersion.created_at)}（生成于 ${minuteText(older.created_at)}）`)
})

it('shows the customer notice when a replayed thesis Word request is refused because blind review was removed',async()=>{
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>url===base&&init?.method==='POST'
  ?Response.json({detail:{code:'blind_review_removed',message:'blind review removed'}},{status:422})
  :Response.json({items:[]}))
 vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptExports {...props} version={thesisVersion} customerThesis/>)
 await screen.findByText('当前版本尚未生成 Word。')
 fireEvent.click(screen.getByRole('button',{name:'生成 Word'}))
 expect((await screen.findByRole('alert')).textContent).toBe('盲审已移出产品范围，请交第三方处理。')
})

it('keeps saved configuration and linked language wording out of customer export details',()=>{
 const linked={...identifiedPresentation,binding:{...identifiedPresentation.binding,peer_version_id:'v2'}}
 const {container,rerender}=render(<PresentationExportDetails customerView value={linked as never}/>)
 for(const text of ['已绑定保存配置','关联语言稿件','历史盲审稿','署名'])expect(container.textContent).not.toContain(text)
 expect(container.querySelectorAll('details')).toHaveLength(0)
 rerender(<PresentationExportDetails customerView value={legacyBlindPresentation as never}/>)
 expect(container.textContent).toContain('历史盲审稿')
 rerender(<PresentationExportDetails value={linked as never}/>)
 expect(container.textContent).toContain('本次输出已绑定保存配置与稿件版本。')
 expect(container.textContent).toContain('关联语言稿件')
})

// B04 task 11: thesis customers are told about an old template and pointed to the migration; automatic Word is preflighted.
const sealedOptions={manual_fields:{author:'合成作者',student_id:'',department:'',major:'',class_name:'',supervisor:'',submission_date:''},manual_chapters:[],english_title:'Reviewed title',keywords:[],include_toc:true,toc_depth:3}
const sealedVersion={...thesisVersion,snapshot:{...thesisVersion.snapshot,writing_provenance:{provider_provenance:'synthetic_fixture',verification_status:'not_verified',language_review_id:'language-review-1',school_export_options:sealedOptions}}} as unknown as ManuscriptVersion
const schoolPlan=(canExport:boolean)=>({schema_version:1,rules_version:'school-export-v1',confirmation_id:'confirm1',confirmation_sha256:'a'.repeat(64),analysis_sha256:'b'.repeat(64),snapshot_sha256:'c'.repeat(64),options:{},styles:{},sections:[],chapters:[],requirements:[],toc:{enabled:true,depth:3},label_map:{figures:{},tables:{}},
 report:{rules_version:'school-export-v1',can_export:canExport,scientifically_verified:false,issues:canExport?[]:[{id:'school:required-content:chapter-result',kind:'content',severity:'error',location:'chapter-result',message:'正文待用户提供。',source_evidence:[]}]}})
const profileUrl='/api/v1/projects/p1/thesis-profile'
function conflictServer(bound:string){
 return vi.fn(async(url:string,init?:RequestInit)=>{
  if(url===profileUrl)return Response.json({...thesisProfile,bound_confirmation_id:bound})
  if(url===base&&init?.method==='POST')return Response.json({detail:{code:'task_source_conflict'}},{status:409})
  if(url===base)return Response.json({items:[]})
  return new Response(null,{status:404})
 })
}
it('tells the thesis customer an old version uses the previous template and opens its migration',async()=>{
 const fetcher=conflictServer('confirm2');vi.stubGlobal('fetch',fetcher);const onOpenMigration=vi.fn()
 const {container}=render(<ManuscriptExports {...props} version={thesisVersion} customerThesis onOpenMigration={onOpenMigration}/>)
 await screen.findByText('当前版本尚未生成 Word。')
 fireEvent.click(screen.getByRole('button',{name:'生成 Word'}))
 expect(await screen.findByText('这一版用的是之前的学校模板。已下载的 Word 保持原样；要按新模板导出，需要先把稿件迁移到新模板。')).toBeTruthy()
 expect(fetcher.mock.calls.some(([url])=>url===profileUrl)).toBe(true)
 expect(container.textContent).not.toMatch(/仍按原模板|以后再次导出/)
 fireEvent.click(screen.getByRole('button',{name:'迁移到新模板'}))
 expect(onOpenMigration).toHaveBeenCalledWith('m1',1,'confirm2')
})
it('keeps the general error for other thesis source changes and for staff',async()=>{
 vi.stubGlobal('fetch',conflictServer('confirm1'));const onOpenMigration=vi.fn()
 const view=render(<ManuscriptExports {...props} version={thesisVersion} customerThesis onOpenMigration={onOpenMigration}/>)
 await screen.findByText('当前版本尚未生成 Word。')
 fireEvent.click(screen.getByRole('button',{name:'生成 Word'}))
 await screen.findByRole('alert')
 expect(screen.queryByRole('button',{name:'迁移到新模板'})).toBeNull()
 expect(screen.queryByText(/之前的学校模板/)).toBeNull()
 view.unmount();sessionStorage.clear()
 const staff=conflictServer('confirm2');vi.stubGlobal('fetch',staff)
 render(<ManuscriptExports {...props} version={thesisVersion} onOpenMigration={onOpenMigration}/>)
 await screen.findByText('当前版本尚未生成 Word。')
 fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}))
 await screen.findByRole('alert')
 expect(screen.queryByRole('button',{name:'迁移到新模板'})).toBeNull()
 expect(staff.mock.calls.some(([url])=>url===profileUrl)).toBe(false)
})
function preflightServer(canExport:boolean){
 const items:unknown[]=[]
 return vi.fn(async(url:string,init?:RequestInit)=>{
  if(url===`${base}/preview`)return Response.json({schema_version:1,school:schoolPlan(canExport)})
  if(url===base&&init?.method==='POST'){const created=wordExport('export-auto','2026-11-19T10:05:00Z',{status:'queued',download_url:null,filename:null});items.unshift(created);return Response.json(created,{status:201})}
  if(url===base)return Response.json({items})
  return new Response(null,{status:404})
 })
}
const previewCalls=(fetcher:ReturnType<typeof vi.fn>)=>fetcher.mock.calls.filter(([url])=>url===`${base}/preview`)
const exportPosts=(fetcher:ReturnType<typeof vi.fn>)=>fetcher.mock.calls.filter(([url,init])=>url===base&&(init as RequestInit|undefined)?.method==='POST')
it('checks the school layout before the automatic thesis Word and does not submit or recheck when it cannot export',async()=>{
 const fetcher=preflightServer(false);vi.stubGlobal('fetch',fetcher)
 const view=render(<ManuscriptExports {...props} version={sealedVersion} customerThesis autoStart/>)
 expect(await screen.findByText('有必须修改的项，暂时不能生成 Word。')).toBeTruthy()
 expect(previewCalls(fetcher)).toHaveLength(1);expect(previewCalls(fetcher)[0][1]?.body).toBe('{}')
 const title=screen.getByRole('heading',{name:'封面与目录'})
 await waitFor(()=>expect(document.activeElement).toBe(title))
 expect((screen.getByRole('button',{name:'生成 Word'}) as HTMLButtonElement).disabled).toBe(true)
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20))})
 expect(exportPosts(fetcher)).toHaveLength(0)
 view.unmount();render(<ManuscriptExports {...props} version={sealedVersion} customerThesis autoStart/>)
 await screen.findByText('当前版本尚未生成 Word。')
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20))})
 expect(previewCalls(fetcher)).toHaveLength(1);expect(exportPosts(fetcher)).toHaveLength(0)
})
it('generates the automatic thesis Word exactly once after the school layout check allows it',async()=>{
 const fetcher=preflightServer(true);vi.stubGlobal('fetch',fetcher);const onAutoStarted=vi.fn()
 const view=render(<ManuscriptExports {...props} version={sealedVersion} customerThesis autoStart onAutoStarted={onAutoStarted}/>)
 await waitFor(()=>expect(exportPosts(fetcher)).toHaveLength(1))
 const [,init]=exportPosts(fetcher)[0]
 expect(init?.body).toBe('{}');expect(new Headers(init?.headers).get('Idempotency-Key')).toBe('auto-word-v1')
 expect(previewCalls(fetcher)).toHaveLength(1);expect(onAutoStarted).toHaveBeenCalledOnce()
 view.unmount();render(<ManuscriptExports {...props} version={sealedVersion} customerThesis autoStart/>)
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20))})
 expect(exportPosts(fetcher)).toHaveLength(1);expect(previewCalls(fetcher)).toHaveLength(1)
})
