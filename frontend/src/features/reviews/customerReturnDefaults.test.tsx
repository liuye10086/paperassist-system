import {useState} from 'react'
import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,describe,expect,it,vi} from 'vitest'
import ReviewsWorkspace,{type ManuscriptPlace} from './ReviewsWorkspace'
import ReturnContinuationPanel from './ReturnContinuationPanel'
import {validContinuation,type ManuscriptInput,type NextRoundInput} from './continuationTypes'
import type {LeaveGuard,RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {taskFixture} from '../tasks/taskFixtures'
import {manuscriptFixture} from '../manuscripts/manuscriptFixtures'
import {setLocale,translateForLocale} from '../../shared/i18n'
import {clearApiSession,setApiSession} from '../../shared/api/client'

// Synthetic UI contract fixtures for the customer return flow (wireframe 16, B04-6).
vi.mock('../files/BatchUpload',()=>({default:({onChanged,trackedItems}:{onChanged:(fileIds?:string[])=>void;trackedItems?:{ids:string[];register:(ids:string[])=>void}})=>
 <><button type="button" onClick={()=>onChanged(['fdoc'])}>模拟上传完成</button>
 <button type="button" onClick={()=>trackedItems?.register(['client-return'])}>模拟已接收尚未解析</button>
 <button type="button" onClick={()=>onChanged(trackedItems?.ids.includes('client-return')?['fdoc']:[])}>模拟重读已解析批次</button></>}))
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN');sessionStorage.clear();clearApiSession()})

const task={...taskFixture,task_type:'review_round_plan',phase:'verify',status:'succeeded',display_status:'succeeded',reason_code:null,error_code:null,
 input_version:{kind:'review_round_plan',round_id:'round1',base_version_id:'v1',workflow_version:'review_round_plan_v1'}}
const makeRound=(project_type:'sci'|'thesis')=>({id:'round1',project_id:'p1',title:'合成第一轮',project_type,round_number:1,revision:1,synthetic:false,
 manuscript:{id:'m1',revision:1,version_id:'v1',title:'合成送审稿'},sources:[],items:[],materials:[],
 constraints:{school_confirmation_id:null,journal_target_id:null},versions:[],decisions:[],task,wait:null,created_at:taskFixture.created_at,
 real_model_calls:false,real_network_calls:false,continuation:null,next_round_ids:[]})
const oldDocument={file_id:'fold',filename:'合成旧上传.docx',document_version_id:'parse-old',version:3,kind:'docx_document'}
const newDocument={file_id:'fdoc',filename:'合成导师返回.docx',document_version_id:'parse1',version:1,kind:'docx_document'}
const makeInputs=(project_type:'sci'|'thesis',documents:unknown[])=>({project_type,manuscripts:[{id:'m1',title:'合成稿',current_revision:3,versions:[
 {id:'v1',revision:1,status:'published',title:'合成送审稿'},{id:'v2',revision:2,status:'published',title:'合成修改稿'},{id:'v3',revision:3,status:'published',title:'合成返回稿'}]}],
 documents,journal_targets:[],school_confirmations:[]})
const savedAt='2026-11-18T06:20:45Z'
const minute=(locale:string)=>new Date(savedAt).toLocaleString(locale,{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})
const continuation={previous_round_id:'round1',manuscript_id:'m1',expected_current_revision:3,
 eligible_inputs:[
  {id:'m1',revision:2,version_id:'v2',title:'合成修改稿',exports:[]},
  {id:'m1',revision:1,version_id:'v1',title:'合成送审稿',saved_at:savedAt,exports:[{id:'exp-blind',status:'succeeded',review_mode:'blind',created_at:savedAt},{id:'exp1',status:'succeeded',review_mode:'identified',created_at:savedAt}]},
 ],
 successful_revisions:[{id:'run2',output:{version_id:'v2'}}],returns:[]}
const registered={id:'return1',previous_round_id:'round1',revision_id:null,synthetic:false,manuscript_id:'m1',base_version_id:'v1',base_revision:1,
 source:{file_id:'fdoc',document_version_id:'parse1'},original_download_url:'/api/v1/projects/p1/files/fdoc/download',
 input_sections:[{id:'input1',title:'方法',paragraphs:['合成改文'],candidate_chapter_ids:['methods'],match_method:'title',suggested_chapter_id:'methods'}],
 target_chapters:[{id:'methods',title:'方法'}],mappings:[{input_section_id:'input1',chapter_id:'methods'}],
 differences:[{kind:'text',location:'方法',message:'支持文本变化',before:'旧合成文本',after:'合成改文'}],issues:[],
 can_adopt:true,preview_sha256:'c'.repeat(64),output:null,created_at:taskFixture.created_at}
type Write={url:string;body:Record<string,unknown>;key:string|null}
function mockApi(project_type:'sci'|'thesis',handler:(url:string,init:RequestInit|undefined)=>unknown=()=>undefined){
 const writes:Write[]=[];const state={uploaded:false}
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST')writes.push({url,body:init.body?JSON.parse(String(init.body)):{},key:new Headers(init.headers).get('Idempotency-Key')})
  const custom=handler(url,init);if(custom!==undefined)return Response.json(custom)
  if(url.endsWith('/inputs'))return Response.json(makeInputs(project_type,state.uploaded?[oldDocument,newDocument]:[oldDocument]))
  if(url.endsWith('/rounds'))return Response.json({items:[makeRound(project_type)]})
  if(url.endsWith('/rounds/round1'))return Response.json(makeRound(project_type))
  if(url.endsWith('/manuscripts/m1/versions/1'))return Response.json(manuscriptFixture.versions[0])
  if(url.endsWith('/continuation-context'))return Response.json(continuation)
  if(url.endsWith('/progress'))return Response.json({items:[],current:null,journal_current_by_target:{}})
  return Response.json({items:[]})
 }))
 return {writes,state}
}
function guards(){
 const active=new Set<{guard:LeaveGuard;dirty?:()=>boolean}>()
 const register:RegisterLeaveGuard=(guard,dirty)=>{const entry={guard,dirty};active.add(entry);return()=>{active.delete(entry)}}
 return {register,dirty:()=>[...active].some(entry=>entry.dirty?.())}
}
function Customer({projectType,register,onOpenManuscript}:{projectType:'sci'|'thesis';register?:RegisterLeaveGuard;onOpenManuscript?:(m:ManuscriptInput,place:ManuscriptPlace)=>void}){
 const [state,setState]=useState<{roundId:string;next?:NextRoundInput}>({roundId:'round1'})
 return <ReviewsWorkspace projectId="p1" projectType={projectType} active view={state.roundId?'continuation':'create'} roundId={state.roundId}
  initialManuscript={state.next?.manuscript.id} initialRevision={state.next?.manuscript.revision}
  initialPreviousRound={state.next?.previous_round_id} initialReturn={state.next?.user_return_id}
  registerLeaveGuard={register} onSelectRound={(id,selection)=>setState({roundId:id,next:selection?.continuation})}
  onOpenTask={vi.fn()} customer onOpenManuscript={onOpenManuscript}/>
}
const panelName=(projectType:'sci'|'thesis')=>projectType==='thesis'?'导师返回的 Word':'返回的 Word'
const panel=()=>screen.getByRole('region',{name:/返回的 Word|Returned Word file|Word file returned/})
// B04 task 13: words the customer must never see on the return page.
const technical={'zh-CN':/公共|清洁|DOCX|父稿|固定导出|回传记录 \d|绑定/,en:/[Pp]ublic|[Cc]lean|DOCX|[Pp]arent|[Ff]ixed export|[Bb]inding/}
function expectCustomerText(locale:'zh-CN'|'en'){
 expect(panel().textContent).not.toMatch(technical[locale])
 expect(panel().querySelector('details, [aria-expanded], a[href^="#"]')).toBeNull()
}

describe.each(['sci','thesis'] as const)('customer return defaults (%s)',projectType=>{
 it('keeps a Word uploaded for supplemental evidence out of the returned-file default',async()=>{
  const {state}=mockApi(projectType)
  const props={projectId:'p1',projectType,roundId:'round1',active:true,customer:true,onSelectRound:vi.fn(),onOpenTask:vi.fn(),onOpenManuscript:vi.fn()}
  const ui=render(<ReviewsWorkspace {...props} view="supplements"/>)
  await screen.findByRole('button',{name:'查看原稿'})
  state.uploaded=true
  fireEvent.click(screen.getByRole('button',{name:'模拟上传完成'}))
  ui.rerender(<ReviewsWorkspace {...props} view="continuation"/>)
  const section=await screen.findByRole('region',{name:panelName(projectType)})
  await waitFor(()=>expect(section.textContent).toContain('（已带入）'))
  expect(within(section).queryByText(/合成导师返回\.docx · 已带入/)).toBeNull()
  expect(await within(section).findByRole('option',{name:newDocument.filename})).toBeTruthy()
  expect(within(section).getByRole('option',{name:newDocument.filename})).toHaveProperty('selected',false)
 })
 it('carries the sent draft and the just-uploaded Word, checks differences in one click and starts the next round without reselecting',async()=>{
  let output:unknown=null
  const {writes,state}=mockApi(projectType,(url,init)=>{
   if(url.endsWith('/rounds/round1/returns')&&init?.method==='POST')return registered
   if(url.endsWith('/returns/return1')&&!init?.method)return {...registered,output}
   if(url.endsWith('/return1/adopt')){output={manuscript_id:'m1',version_id:'v3',revision:3,parent_version_id:'v1',task_id:'producer1',status:'published'};return {...registered,output}}
  })
  render(<Customer projectType={projectType}/>)
  await screen.findByRole('region',{name:panelName(projectType)})
  await waitFor(()=>expect(panel().textContent).toContain(`送审稿 · 第 1 版 · ${minute('zh-CN')}（已带入）`))
  expect(panel().textContent).not.toContain('合成旧上传.docx · 已带入')
  state.uploaded=true
  fireEvent.click(screen.getByRole('button',{name:'模拟上传完成'}))
  await within(panel()).findByText(/合成导师返回\.docx · 已带入/)
  expect(panel().querySelectorAll('select')).toHaveLength(0)
  const check=within(panel()).getByRole('button',{name:'核对差异'})
  expect(check).toHaveProperty('disabled',false)
  fireEvent.click(check)
  await within(panel()).findByText('旧合成文本')
  const posts=writes.filter(w=>w.url.endsWith('/rounds/round1/returns'))
  expect(posts).toHaveLength(1)
  expect(posts[0].body).toEqual({manuscript:{id:'m1',revision:1,version_id:'v1'},revision_id:null,file_id:'fdoc',document_version_id:'parse1',base_export_id:'exp1',synthetic:false})
  // B05 task 8: a digest of the whole selection, so a changed revision run or original Word gets a new key.
  expect(posts[0].key).toMatch(/^return:round1:[0-9a-f]{64}$/)
  expect(posts[0].key!.length).toBeLessThanOrEqual(128)
  expect(writes.some(w=>w.url.endsWith('/preview'))).toBe(false)
  expect(within(panel()).queryByRole('button',{name:'重新核对差异'})).toBeNull()
  fireEvent.click(within(panel()).getByRole('button',{name:'采用返回稿'}))
  const next=await within(panel()).findByRole('button',{name:'用返回稿开始下一轮'})
  await waitFor(()=>expect(next).toHaveProperty('disabled',false))
  fireEvent.click(next)
  await waitFor(()=>expect(screen.getByLabelText('固定稿件版本')).toHaveProperty('value','v3'))
  expect(screen.getByLabelText('固定稿件版本')).toHaveProperty('disabled',true)
  expect(screen.getByLabelText('上一轮意见')).toHaveProperty('value','round1')
  expect(screen.getByLabelText('上一轮意见')).toHaveProperty('disabled',true)
  if(projectType==='thesis')expect(screen.getByLabelText('固定稿件的学校确认')).toHaveProperty('disabled',true)
  expect(writes.filter(w=>w.url.endsWith('/rounds/round1/returns'))).toHaveLength(1)
 })

 it('reopens the latest open return on remount without registering it again',async()=>{
  const {writes}=mockApi(projectType,url=>{
   if(url.endsWith('/continuation-context'))return {...continuation,returns:[registered]}
   if(url.endsWith('/returns/return1'))return registered
  })
  const view=()=><ReturnContinuationPanel projectId="p1" round={makeRound(projectType) as never} documents={[newDocument] as never}
   active expanded customer onPrepareNext={vi.fn()} onOpenTask={vi.fn()}/>
  const first=render(view())
  await screen.findByText('旧合成文本')
  first.unmount()
  render(view())
  await screen.findByText('旧合成文本')
  expect(writes.filter(w=>w.url.endsWith('/returns'))).toHaveLength(0)
  expect(screen.queryByRole('button',{name:'重新核对差异'})).toBeNull()
 })

 it('treats carried defaults as clean and only a manual draft change as unsaved',async()=>{
  const {state}=mockApi(projectType)
  state.uploaded=true
  const guard=guards()
  render(<Customer projectType={projectType} register={guard.register}/>)
  await waitFor(()=>expect(panel().textContent).toContain('（已带入）'))
  fireEvent.click(screen.getByRole('button',{name:'模拟上传完成'}))
  await within(panel()).findByText(/合成导师返回\.docx · 已带入/)
  expect(guard.dirty()).toBe(false)
  fireEvent.click(within(panel()).getByRole('button',{name:'换一版'}))
  const select=within(panel()).getByLabelText('换一版送审稿')
  const options=within(select).getAllByRole('option').filter(o=>(o as HTMLOptionElement).value).map(o=>o.textContent)
  expect(options[0]).toBe('合成修改稿 · 第 2 版 · 系统修改稿')
  expect(options[1]).toBe(`合成送审稿 · 第 1 版 · ${minute('zh-CN')}`)
  expect(guard.dirty()).toBe(false)
  fireEvent.change(select,{target:{value:'v2'}})
  expect(guard.dirty()).toBe(true)
 })

 it.each(['zh-CN','en'] as const)('uses customer words through the first, checked and adopted states (%s)',async locale=>{
  setLocale(locale)
  let output:unknown=null
  const opened:[ManuscriptInput,unknown][]=[]
  const {state}=mockApi(projectType,(url,init)=>{
   if(url.endsWith('/rounds/round1/returns')&&init?.method==='POST')return registered
   if(url.endsWith('/returns/return1')&&!init?.method)return {...registered,output}
   if(url.endsWith('/return1/adopt')){output={manuscript_id:'m1',version_id:'v3',revision:3,parent_version_id:'v1',task_id:'producer1',status:'published'};return {...registered,output}}
  })
  render(<Customer projectType={projectType} onOpenManuscript={(m,place)=>opened.push([m,place])}/>)
  const zh=locale==='zh-CN'
  const heading=await screen.findByRole('heading',{name:zh?panelName(projectType):projectType==='thesis'?'Word file returned by your supervisor':'Returned Word file'})
  expect(panel().contains(heading)).toBe(true)
  if(projectType==='thesis')expect(panel().textContent).toContain(zh?'导师或评阅人返回':'Returned by your supervisor or reviewer')
  else expect(panel().textContent).not.toMatch(/导师|supervisor/)
  const steps=within(panel()).getByRole('list',{name:zh?'返回稿步骤':'Return steps'})
  expect(within(steps).getAllByRole('listitem').map(item=>item.textContent)).toEqual(zh
   ? ['上传返回的 Word','核对差异','采用返回稿','用返回稿开始下一轮']
   : ['Upload the returned Word file','Check differences','Adopt the returned manuscript','Start the next round from it'])
  await waitFor(()=>expect(panel().textContent).toContain(zh?`第 1 版 · ${minute('zh-CN')}（已带入）`:`Version 1 · ${minute('en')} (filled in)`))
  expectCustomerText(locale)
  state.uploaded=true
  fireEvent.click(screen.getByRole('button',{name:'模拟上传完成'}))
  fireEvent.click(await within(panel()).findByRole('button',{name:zh?'核对差异':'Check differences'}))
  await within(panel()).findByText('旧合成文本')
  expectCustomerText(locale)
  expect(within(panel()).getByRole('link',{name:zh?'下载返回的 Word':'Download the returned Word file'}).getAttribute('href')).toBe(registered.original_download_url)
  fireEvent.click(within(panel()).getByRole('button',{name:zh?'查看送审稿':'Open the submitted manuscript'}))
  expect(opened).toEqual([[{id:'m1',revision:1,version_id:'v1'},{roundNumber:1}]])
  fireEvent.click(within(panel()).getByRole('button',{name:zh?'采用返回稿':'Adopt the returned manuscript'}))
  await within(panel()).findByText(zh?'返回稿已保存为第 3 版':'The returned manuscript was saved as version 3')
  expect(within(panel()).getByRole('button',{name:zh?'用返回稿开始下一轮':'Start the next round from it'})).toBeTruthy()
  expect(within(panel()).getByRole('button',{name:zh?'开始下一轮（不使用返回稿）':'Start the next round without the returned manuscript'})).toBeTruthy()
  expectCustomerText(locale)
 })
})

it('accepts older continuation responses without the new time and type fields, and historical blind exports',()=>{
 const base=JSON.parse(JSON.stringify(continuation)) as typeof continuation
 const withoutNewFields={...base,eligible_inputs:base.eligible_inputs.map(({id,revision,version_id,title,exports})=>({id,revision,version_id,title,exports:exports.map(e=>({id:e.id,status:e.status}))}))}
 expect(validContinuation(withoutNewFields,'p1','round1')).toBe(true)
 expect(validContinuation(base,'p1','round1')).toBe(true)
 const change=(patch:Record<string,unknown>,exportPatch:Record<string,unknown>={})=>({...base,eligible_inputs:[{...base.eligible_inputs[1],...patch,exports:[{id:'e1',status:'succeeded',...exportPatch}]}]})
 expect(validContinuation(change({},{review_mode:'blind'}),'p1','round1')).toBe(true)
 expect(validContinuation(change({},{review_mode:'identified'}),'p1','round1')).toBe(true)
 expect(validContinuation(change({},{review_mode:'anonymous'}),'p1','round1')).toBe(false)
 expect(validContinuation(change({},{created_at:5}),'p1','round1')).toBe(false)
 expect(validContinuation(change({saved_at:null},{created_at:null}),'p1','round1')).toBe(true)
 expect(validContinuation(change({saved_at:5}),'p1','round1')).toBe(false)
})

// B05 task 8: refresh keeps the carried Word, the key follows the selection, and options use customer words.
describe.each(['sci','thesis'] as const)('customer return after a refresh (%s)',projectType=>{
 it('remembers the registered return upload if parsing finishes after reload',async()=>{
  setApiSession('csrf','customer-a')
  const {state}=mockApi(projectType)
  const ui=render(<Customer projectType={projectType}/>)
  await waitFor(()=>expect(panel().textContent).toContain('（已带入）'))
  fireEvent.click(screen.getByRole('button',{name:'模拟已接收尚未解析'}))
  ui.unmount()
  state.uploaded=true
  render(<Customer projectType={projectType}/>)
  fireEvent.click(await screen.findByRole('button',{name:'模拟重读已解析批次'}))
  await within(await screen.findByRole('region',{name:panelName(projectType)})).findByText(/合成导师返回\.docx · 已带入/)
 })
 it('keeps the just-uploaded Word after a remount, per account and round',async()=>{
  setApiSession('csrf','customer-a')
  const {state}=mockApi(projectType)
  const first=render(<Customer projectType={projectType}/>)
  await waitFor(()=>expect(panel().textContent).toContain('（已带入）'))
  state.uploaded=true
  fireEvent.click(screen.getByRole('button',{name:'模拟上传完成'}))
  await within(panel()).findByText(/合成导师返回\.docx · 已带入/)
  first.unmount()
  const second=render(<Customer projectType={projectType}/>)
  await within(await screen.findByRole('region',{name:panelName(projectType)})).findByText(/合成导师返回\.docx · 已带入/)
  expect(panel().querySelectorAll('select')).toHaveLength(0)
  second.unmount()
  setApiSession('csrf','customer-b')
  render(<Customer projectType={projectType}/>)
  await waitFor(()=>expect(panel().textContent).toContain('（已带入）'))
  expect(panel().textContent).not.toContain('合成导师返回.docx · 已带入')
  expect(within(panel()).getByLabelText(panelName(projectType))).toBeTruthy()
 })

 it('keeps a manual choice for its own round only and falls back when the file is gone',async()=>{
  mockApi(projectType,url=>url.includes('/rounds/round2/continuation-context')?{...continuation,previous_round_id:'round2'}:undefined)
  const view=(round:string,documents:unknown[])=><ReturnContinuationPanel projectId="p1" projectType={projectType}
   round={{...makeRound(projectType),id:round} as never} documents={documents as never} active expanded customer onPrepareNext={vi.fn()} onOpenTask={vi.fn()}/>
  const first=render(view('round1',[oldDocument,newDocument]))
  const select=await within(await screen.findByRole('region',{name:panelName(projectType)})).findByLabelText(panelName(projectType))
  fireEvent.change(select,{target:{value:'parse1'}})
  first.unmount()
  const again=render(view('round1',[oldDocument,newDocument]))
  expect(await within(panel()).findByLabelText(panelName(projectType))).toHaveProperty('value','parse1')
  again.unmount()
  const gone=render(view('round1',[oldDocument]))
  expect(await within(panel()).findByLabelText(panelName(projectType))).toHaveProperty('value','')
  gone.unmount()
  render(view('round2',[oldDocument,newDocument]))
  expect(await within(panel()).findByLabelText(panelName(projectType))).toHaveProperty('value','')
 })
})

it('uses the same key for a repeated check and a new key for another original Word',async()=>{
 const twoExports={...continuation,eligible_inputs:[continuation.eligible_inputs[0],{...continuation.eligible_inputs[1],
  exports:[{id:'exp2',status:'succeeded',review_mode:'identified',created_at:'2026-11-19T06:20:45Z'},{id:'exp1',status:'succeeded',review_mode:'identified',created_at:savedAt}]}]}
 const {writes,state}=mockApi('sci',(url,init)=>{
  if(url.endsWith('/continuation-context'))return twoExports
  if(url.endsWith('/rounds/round1/returns')&&init?.method==='POST')return registered
 })
 state.uploaded=true
 render(<Customer projectType="sci"/>)
 fireEvent.click(await screen.findByRole('button',{name:'模拟上传完成'}))
 const word=await within(panel()).findByLabelText('对应的 Word（可选）')
 const options=within(word).getAllByRole('option').map(option=>option.textContent)
 expect(options.slice(1)).toEqual([
  `Word 文件（生成于 ${new Date('2026-11-19T06:20:45Z').toLocaleString('zh-CN')}）`,`Word 文件（生成于 ${new Date(savedAt).toLocaleString('zh-CN')}）`])
 expect(panel().textContent).not.toMatch(/署名稿导出|版本 \d/)
 const check=await within(panel()).findByRole('button',{name:'核对差异'})
 await waitFor(()=>expect(check).toHaveProperty('disabled',false))
 fireEvent.click(check)
 await waitFor(()=>expect(writes.filter(w=>w.url.endsWith('/returns'))).toHaveLength(1))
 fireEvent.click(within(panel()).getByRole('button',{name:'核对差异'}))
 await waitFor(()=>expect(writes.filter(w=>w.url.endsWith('/returns'))).toHaveLength(2))
 fireEvent.change(within(panel()).getByLabelText('对应的 Word（可选）'),{target:{value:'exp1'}})
 fireEvent.click(within(panel()).getByRole('button',{name:'核对差异'}))
 await waitFor(()=>expect(writes.filter(w=>w.url.endsWith('/returns'))).toHaveLength(3))
 const posts=writes.filter(w=>w.url.endsWith('/returns'))
 expect(posts[0].body.base_export_id).toBe('exp2')
 expect(posts[1].key).toBe(posts[0].key)
 expect(posts[2].body.base_export_id).toBe('exp1')
 expect(posts[2].key).not.toBe(posts[0].key)
 for(const post of posts)expect(post.key).toMatch(/^return:round1:[0-9a-f]{64}$/)
 for(const post of posts)expect(post.key!.length).toBeLessThanOrEqual(128)
})

it('lists one option per returned file and submits its latest parsed version',async()=>{
 const reparsed={...newDocument,document_version_id:'parse2',version:2}
 const twin={file_id:'ftwin',filename:'合成导师返回.docx',document_version_id:'parse-twin',version:1,kind:'docx_document'}
 const {writes}=mockApi('sci',(url,init)=>{
  if(url.endsWith('/inputs'))return makeInputs('sci',[reparsed,newDocument,twin,oldDocument])
  if(url.endsWith('/rounds/round1/returns')&&init?.method==='POST')return registered
 })
 render(<Customer projectType="sci"/>)
 const select=await within(await screen.findByRole('region',{name:'返回的 Word'})).findByLabelText('返回的 Word')
 await waitFor(()=>expect(within(select).getAllByRole('option')).toHaveLength(4))
 expect(within(select).getAllByRole('option').map(option=>option.textContent).slice(1)).toEqual([
  '合成导师返回.docx · 第 1 次上传','合成导师返回.docx · 第 2 次上传','合成旧上传.docx'])
 fireEvent.change(select,{target:{value:'parse2'}})
 fireEvent.click(within(panel()).getByRole('button',{name:'核对差异'}))
 await waitFor(()=>expect(writes.filter(w=>w.url.endsWith('/returns'))).toHaveLength(1))
 expect(writes[0].body.document_version_id).toBe('parse2')
})

it('restores the chosen file to its latest parse when it was reparsed after saving the choice',async()=>{
 setApiSession('csrf','customer-a')
 const {writes}=mockApi('thesis',(url,init)=>url.endsWith('/returns')&&init?.method==='POST'?registered:undefined)
 const view=(documents:typeof newDocument[])=><ReturnContinuationPanel projectId="p1" projectType="thesis"
  round={makeRound('thesis') as never} documents={documents as never} active expanded customer
  onPrepareNext={vi.fn()} onOpenTask={vi.fn()}/>
 const first=render(view([oldDocument,newDocument]))
 const selector=()=>within(panel()).getByLabelText('导师返回的 Word') as HTMLSelectElement
 await waitFor(()=>expect(selector().matches(':disabled')).toBe(false))
 fireEvent.change(selector(),{target:{value:'parse1'}})
 first.unmount()
 render(view([oldDocument,{...newDocument,document_version_id:'parse2',version:2},newDocument]))
 await waitFor(()=>expect(selector().matches(':disabled')).toBe(false))
 expect.soft(selector().value).toBe('parse2')
 expect(within(selector()).getAllByRole('option').filter(option=>option.textContent===newDocument.filename)).toHaveLength(1)
 fireEvent.click(within(panel()).getByRole('button',{name:'核对差异'}))
 await waitFor(()=>expect(writes).toHaveLength(1))
 expect(writes[0].body).toMatchObject({file_id:newDocument.file_id,document_version_id:'parse2'})
})

it('carries the latest available returned file even when an earlier file has more parsed versions',async()=>{
 mockApi('sci')
 render(<ReturnContinuationPanel projectId="p1" projectType="sci" round={makeRound('sci') as never}
  documents={[oldDocument,newDocument] as never} recentFileIds={['fold','fdoc']} active expanded customer
  onPrepareNext={vi.fn()} onOpenTask={vi.fn()}/>)
 await waitFor(()=>expect(panel().textContent).toContain('送审稿 · 第 1 版'))
 expect(within(panel()).queryByText(/合成旧上传\.docx · 已带入/)).toBeNull()
 expect(within(panel()).getByText(/合成导师返回\.docx · 已带入/)).toBeTruthy()
})
it.each(['zh-CN','en'] as const)('explains saved %s return checks to customers while keeping the original staff checks and adoption decision',async savedLocale=>{
 const body='正文改变；改变段落不继承原支持绑定。'
 const checks=[
  ['nonbody_changed','error','固定导出的封面、目录、图题、书目或人工附加内容变化；保留原件并须人工核对。'],
  ['export_nonbody_retained','warning','已核对固定导出中未变的封面、目录、图表说明和人工附加内容；保留在原导出与回传原件，未当作新增研究正文。'],
  ['citation_changed','error','无固定导出可核对页眉页脚、脚注或尾注。'],
  ['bound_claim_changed','error','已绑定论述发生变化，不能继承原支持；请先重新核实。'],
 ]
 const record={...registered,can_adopt:false,preview_sha256:null,
  differences:[{...registered.differences[0],kind:'text_changed',message:translateForLocale(body,savedLocale)}],
  issues:checks.map(([code,severity,message])=>({code,severity,message:translateForLocale(message,savedLocale),location:'methods'}))}
 const {writes}=mockApi('thesis',url=>url.endsWith('/continuation-context')?{...continuation,returns:[record]}:url.endsWith('/returns/return1')?record:undefined)
 const view=(customer:boolean)=><ReturnContinuationPanel projectId="p1" projectType="thesis" round={makeRound('thesis') as never}
  documents={[newDocument] as never} active expanded customer={customer} onPrepareNext={vi.fn()} onOpenTask={vi.fn()}/>
 const page=render(view(true))
 await screen.findByText('旧合成文本')
 expect(screen.getByRole('heading',{name:'正文有改动。请重新核对改动段落的依据。'})).toBeTruthy()
 for(const text of ['错误 · 送审 Word 的封面','警告 · 两份 Word 中未改动的封面','缺少可供对照的送审 Word','论述已改动'])expect(page.container.textContent).toContain(text)
 expect(screen.getByRole('button',{name:'采用返回稿'})).toHaveProperty('disabled',true)
 act(()=>setLocale('en'))
 for(const text of ['Check the evidence for each changed paragraph','Keep both files and review the changes','These sections do not count as new manuscript text','There is no submitted Word file','The claim has changed'])expect(page.container.textContent).toContain(text)
 expect(page.container.textContent).not.toMatch(/fixed export|support bindings|bound claim/i)
 page.rerender(view(false))
 for(const text of [body,...checks.map(c=>c[2])])expect(page.container.textContent).toContain(translateForLocale(text,'en'))
 act(()=>setLocale('zh-CN'))
 for(const text of [body,...checks.map(c=>c[2])])expect(page.container.textContent).toContain(text)
 expect(writes).toHaveLength(0)
})
