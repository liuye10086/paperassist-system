import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptWriting from './ManuscriptWriting'
import {manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
import {setApiSession} from '../../shared/api/client'
import {webcrypto} from 'node:crypto'
import {authFixture,bundleFixture,liveRequest,unsubmittedRequest} from './writingLiveFixtures'
import WritingLive from './WritingLive'
import {ManuscriptDraftProvider} from './ManuscriptDraftProvider'
const props={projectId:'p1',manuscriptId:'m1',version:manuscriptFixture.versions[0] as unknown as ManuscriptVersion,onPublished:vi.fn()}
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it.each(['受控写作关键词（每行一项）','受控写作致谢'])('keeps cached %s dirty after switching to a section rewrite',async label=>{
 const guards=new Map<()=>boolean,()=>boolean>();const register=(guard:()=>boolean,dirty?:()=>boolean)=>{guards.set(guard,dirty??(()=>false));return ()=>{guards.delete(guard)}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/writing-previews')?{items:[],capabilities:{real_calls_enabled:false}}:{items:[]})))
 render(<ManuscriptDraftProvider register={register}><WritingLive {...props} version={{...props.version,snapshot:{...props.version.snapshot,sections:[]}}}/></ManuscriptDraftProvider>)
 await waitFor(()=>expect(screen.getByLabelText('受控写作方式').matches(':disabled')).toBe(false))
 expect([...guards.values()].some(dirty=>dirty())).toBe(false)
 fireEvent.change(screen.getByLabelText(label),{target:{value:'Keep full draft field'}})
 fireEvent.change(screen.getByLabelText('受控写作方式'),{target:{value:'rewrite_section'}})
 expect([...guards.values()].some(dirty=>dirty())).toBe(true)
 fireEvent.change(screen.getByLabelText('受控写作方式'),{target:{value:'full_draft'}})
 expect(screen.getByLabelText(label)).toHaveProperty('value','Keep full draft field')
})
it('opens controlled writing without authorizing or executing, and invalidates it on a session change',async()=>{
 const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/manuscripts')?{items:[manuscriptFixture]}:url.endsWith('/writing-previews')?{items:[],capabilities:{real_calls_enabled:false,credential_status:'missing'}}:{items:[]}));vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptWriting {...props}/>);fireEvent.click(screen.getByRole('button',{name:'受控写作与人工审核'}))
 await screen.findByText('尚未授权',{selector:'p'})
 expect(screen.getByRole('button',{name:'提交已授权写作'}).matches(':disabled')).toBe(true)
 expect(fetcher.mock.calls.every(c=>c.length===1||!(c[1] as RequestInit)?.method)).toBe(true)
 act(()=>setApiSession('changed-live-session'))
 await waitFor(()=>expect(screen.getByRole('button',{name:'受控写作与人工审核'}).matches(':disabled')).toBe(true))
 const count=fetcher.mock.calls.length;fireEvent.click(screen.getByRole('button',{name:'受控写作与人工审核'}));expect(screen.queryByRole('region',{name:'受控写作工作区'})).toBeNull();expect(fetcher.mock.calls).toHaveLength(count)
})
it('executes only the explicitly matched authorized bundle and keeps failed unknown submissions visible without retry',async()=>{
 vi.stubGlobal('crypto',webcrypto);const bundle=bundleFixture(),authorization=authFixture([bundle,bundleFixture('b2'),bundleFixture('b3'),bundleFixture('b4')]);const failed={...liveRequest,candidate:null,task:{...liveRequest.task,status:'waiting_confirmation',display_status:'waiting_confirmation',reason_code:'submission_unknown'},model_calls:[{id:'call1',model:'gpt-5.4-2026-03-05',status:'submission_unknown',provider_provenance:'openai_live',bundle_id:'b1',authorization_id:'auth1',logical_task_id:'task-1',estimated_cost_micro_usd:null}]}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>Response.json(url.endsWith('/manuscripts')?{items:[manuscriptFixture]}:url.endsWith('/writing-previews')?{items:[bundle],capabilities:{real_calls_enabled:true}}:url.endsWith('/writing-authorizations')?{items:[authorization]}:init?.method==='POST'?failed:{items:[]}));vi.stubGlobal('fetch',fetcher)
 render(<WritingLive {...props}/>);await screen.findByRole('option',{name:/b1 · 完整七部分初稿/});await waitFor(()=>expect(screen.getByLabelText('选择已冻结预览').matches(':disabled')).toBe(false));fireEvent.change(screen.getByLabelText('选择已冻结预览'),{target:{value:'b1'}});await screen.findByText('完整 wire 字节与 SHA 已核对。');fireEvent.click(screen.getByRole('button',{name:'读取同项目稿件与授权'}));await screen.findByRole('option',{name:'auth1 · 有效'});fireEvent.change(screen.getByLabelText('明确选择已有授权'),{target:{value:'auth1'}});fireEvent.change(screen.getByLabelText('授权逻辑任务'),{target:{value:'task-1'}});expect(screen.getByRole('button',{name:'提交已授权写作'}).matches(':disabled')).toBe(true);fireEvent.click(screen.getByLabelText('我确认执行当前精确 SHA；失败或未知不会自动重发。'));fireEvent.click(screen.getByRole('button',{name:'提交已授权写作'}));await screen.findByText('实际费用未知；仍占预留额度，不自动重发。');expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1);const body=JSON.parse(String(fetcher.mock.calls.find(([,init])=>init?.method==='POST')![1]?.body));expect(body).toEqual({schema_version:2,bundle_id:'b1',bundle_sha256:bundle.bundle_sha256,authorization_id:'auth1',logical_task_id:'task-1'});expect(screen.getByRole('button',{name:'提交已授权写作'}).matches(':disabled')).toBe(true)
})

it.each(['reserved','released'] as const)('shows a %s call as not submitted without an executed provider receipt',async status=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/writing-previews')?{items:[],capabilities:{real_calls_enabled:false}}:{items:[unsubmittedRequest(status)]})))
 render(<WritingLive {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'审核此原始候选'}));expect(screen.getByText(/尚未提交；没有供应商回执。/)).toBeTruthy();expect(screen.queryByText(/真实 provider 回执|离线模拟回执/)).toBeNull();expect(screen.getByText(status==='released'?'调用已释放，无执行回执。':'尚未提交；预留额度等待执行或释放。')).toBeTruthy()
})
