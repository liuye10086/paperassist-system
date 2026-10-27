import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptWriting from './ManuscriptWriting'
import {manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
import {liveRequest,unsubmittedRequest} from './writingLiveFixtures'
import {taskFixture} from '../tasks/taskFixtures'
import {setApiSession} from '../../shared/api/client'
const props={projectId:'p1',manuscriptId:'m1',version:manuscriptFixture.versions[0] as unknown as ManuscriptVersion,onPublished:vi.fn()}
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals()})
it('uses only explicit user keywords and retains idempotency across uncertain retries without enabling real calls',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{if(init?.method==='POST')throw Error('network');return Response.json({items:[]})});vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptWriting {...props}/>);await screen.findByText('暂无写作任务。')
 fireEvent.change(screen.getByLabelText('关键词（每行一项，可留空）'),{target:{value:'user keyword'}})
 fireEvent.change(screen.getByLabelText('用户提供的致谢（可留空）'),{target:{value:'user thanks'}})
 fireEvent.click(screen.getByRole('button',{name:'发起完整七部分写作'}));await screen.findByRole('alert')
 fireEvent.click(screen.getByRole('button',{name:'发起完整七部分写作'}));await waitFor(()=>expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(2))
 const posts=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(new Headers(posts[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(posts[1][1]?.headers).get('Idempotency-Key'))
 expect(JSON.parse(String(posts[0][1]?.body))).toMatchObject({base_revision:1,mode:'full_draft',keywords:['user keyword'],acknowledgements:'user thanks'})
})
it('invalidates task candidates on session changes',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})));render(<ManuscriptWriting {...props}/>);await screen.findByText('暂无写作任务。');act(()=>setApiSession('expired-writing'));expect(screen.getByRole('alert').textContent).toContain('会话已失效');expect(screen.getByRole('button',{name:'发起完整七部分写作'}).matches(':disabled')).toBe(true)
})

const sections=['title','abstract','introduction','results','discussion','materials_and_methods','references'].map(id=>({id,paragraphs:[{id:`${id}:1`,text:`Saved ${id}`,origin:'model_generated',source_ids:[],citations:[],numeric_bindings:[]}]}))
const complete={...manuscriptFixture.versions[0].snapshot,sections,keywords:['explicit keyword'],acknowledgements:'',writing_provenance:{provider_provenance:'synthetic_fixture',verification_status:'not_verified'}}
const writing={id:'w1',project_id:'p1',manuscript_id:'m1',base_revision:1,input:{base_revision:1,mode:'full_draft',target_section:null,instructions:'',keywords:['explicit keyword'],acknowledgements:''},task:{...taskFixture,id:'w1',project_id:'p1',task_type:'manuscript_writing',phase:'write',status:'succeeded',display_status:'succeeded',input_version:{kind:'manuscript_writing',base_version_id:'v1',base_revision:1,output_language:'en',workflow_version:'manuscript_writing_v1'}},candidate:complete,published_revision:null,real_calls_enabled:false,preservation_check:{non_target_sections_preserved:true}}
it('preserves independent full-draft and chapter requirements when switching chapters',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})))
 render(<ManuscriptWriting {...props} version={{...props.version,snapshot:complete} as unknown as ManuscriptVersion}/>)
 await screen.findByText('暂无写作任务。')
 fireEvent.change(screen.getByLabelText('自由写作要求'),{target:{value:'Full instructions'}})
 fireEvent.change(screen.getByLabelText('写作方式'),{target:{value:'rewrite_section'}})
 fireEvent.change(screen.getByLabelText('自由写作要求'),{target:{value:'Discussion instructions'}})
 fireEvent.change(screen.getByLabelText('目标章节'),{target:{value:'abstract'}})
 expect(screen.getByLabelText('自由写作要求')).toHaveProperty('value','')
 fireEvent.change(screen.getByLabelText('自由写作要求'),{target:{value:'Abstract instructions'}})
 fireEvent.change(screen.getByLabelText('目标章节'),{target:{value:'discussion'}})
 expect(screen.getByLabelText('自由写作要求')).toHaveProperty('value','Discussion instructions')
 fireEvent.change(screen.getByLabelText('写作方式'),{target:{value:'full_draft'}})
 expect(screen.getByLabelText('自由写作要求')).toHaveProperty('value','Full instructions')
})
it('previews candidate without publishing, then explicitly creates an immutable version',async()=>{
 const result={...manuscriptFixture,current_revision:2,versions:[...manuscriptFixture.versions,{...manuscriptFixture.versions[0],id:'v2',revision:2,parent_version_id:'v1',snapshot:complete,exports:[]}]}
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?result:{items:[writing]}));vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptWriting {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'预览写作候选'}));await screen.findByText('Saved abstract')
 expect(fetcher.mock.calls.every(([,i])=>!i?.method)).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'确认发布为不可变新版本'}));await waitFor(()=>expect(props.onPublished).toHaveBeenCalledWith(result))
 const post=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(post[0]).toContain('/writing-requests/w1/publish');expect(JSON.parse(String(post[1]?.body))).toEqual({expected_revision:1})
})
it('opens the fixed original through its task navigation without discarding the writing candidate',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[writing]})))
 const original=vi.fn();render(<ManuscriptWriting {...props} onShowOriginal={original}/>)
 fireEvent.click(await screen.findByRole('button',{name:'预览写作候选'}));await screen.findByText('Saved abstract')
 fireEvent.click(screen.getByRole('button',{name:'查看冻结原稿'}))
 expect(original).toHaveBeenCalledTimes(1)
 expect(screen.getByRole('region',{name:'待研究人员审核的写作候选'})).toBeTruthy()
})
it('blocks publication when a non-target section was modified despite server preservation claim',async()=>{
 const rewrite={...writing,input:{...writing.input,mode:'rewrite_section',target_section:'discussion'},candidate:{...complete,sections:sections.map(s=>s.id==='abstract'?{...s,paragraphs:[{...s.paragraphs[0],text:'Tampered abstract'}]}:s)}}
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[rewrite]})))
 render(<ManuscriptWriting {...props} version={{...props.version,snapshot:complete} as unknown as ManuscriptVersion}/>);fireEvent.click(await screen.findByRole('button',{name:'预览写作候选'}));await screen.findByText('非目标章节保留校验未通过，禁止发布。');expect(screen.getByRole('button',{name:'确认发布为不可变新版本'}).matches(':disabled')).toBe(true)
})
it('ignores an old project response after switching projects and rejects foreign candidates',async()=>{
 let finish:(r:Response)=>void=()=>{};vi.stubGlobal('fetch',vi.fn((url:string)=>url.includes('/p1/')?new Promise<Response>(resolve=>{finish=resolve}):Promise.resolve(Response.json({items:[writing]}))))
 const view=render(<ManuscriptWriting {...props}/>);view.rerender(<ManuscriptWriting {...props} projectId="p2"/>);await act(async()=>finish(Response.json({items:[writing]})));await screen.findByRole('alert');expect(screen.queryByRole('button',{name:'预览写作候选'})).toBeNull()
})

it('reports a timed-out writing request and keeps it retryable',async()=>{
 vi.useFakeTimers();vi.stubGlobal('fetch',vi.fn(async(_url:string,init?:RequestInit)=>init?.method==='POST'?new Promise<Response>(()=>{}):Response.json({items:[]})))
 render(<ManuscriptWriting {...props}/>);await act(async()=>{})
 fireEvent.change(screen.getByLabelText('关键词（每行一项，可留空）'),{target:{value:'explicit keyword'}});fireEvent.click(screen.getByRole('button',{name:'发起完整七部分写作'}));await act(async()=>{vi.advanceTimersByTime(15001)})
 expect(screen.getByRole('alert').textContent).toContain('未确认');vi.useRealTimers()
})
it('accepts unchanged non-target sections regardless of JSON object property order',async()=>{
 const rewritten={...writing,input:{...writing.input,mode:'rewrite_section',target_section:'discussion'},candidate:{...complete,sections:sections.map(s=>({paragraphs:s.paragraphs,id:s.id}))}}
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[rewritten]})));render(<ManuscriptWriting {...props} version={{...props.version,snapshot:complete} as unknown as ManuscriptVersion}/>);fireEvent.click(await screen.findByRole('button',{name:'预览写作候选'}));expect(screen.getByText('非目标章节保留校验通过。')).toBeTruthy()
})

it('permits empty keywords and never invents acknowledgements',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{if(init?.method==='POST')throw Error('network');return Response.json({items:[]})});vi.stubGlobal('fetch',fetcher);render(<ManuscriptWriting {...props}/>);fireEvent.click(screen.getByRole('button',{name:'发起完整七部分写作'}));await screen.findByRole('alert');const post=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(JSON.parse(String(post[1]?.body))).toMatchObject({keywords:[],acknowledgements:''})
})
it('preserves saved keywords and acknowledgements when rewriting a section',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{if(init?.method==='POST')throw Error('network');return Response.json({items:[]})});vi.stubGlobal('fetch',fetcher);render(<ManuscriptWriting {...props} version={{...props.version,snapshot:{...complete,keywords:['Frozen keyword'],acknowledgements:'Frozen thanks'}} as unknown as ManuscriptVersion}/>);fireEvent.change(screen.getByLabelText('写作方式'),{target:{value:'rewrite_section'}});fireEvent.change(screen.getByLabelText('自由写作要求'),{target:{value:'Improve discussion clarity'}});fireEvent.click(screen.getByRole('button',{name:'发起章节重写'}));await screen.findByRole('alert');const post=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(JSON.parse(String(post[1]?.body))).toMatchObject({mode:'rewrite_section',target_section:'discussion',keywords:['Frozen keyword'],acknowledgements:'Frozen thanks'})
})
it('rejects a candidate whose task belongs to another project',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{...writing,task:{...writing.task,project_id:'p2'}}]})));render(<ManuscriptWriting {...props}/>);await screen.findByRole('alert');expect(screen.queryByRole('button',{name:'预览写作候选'})).toBeNull()
})

it('retains the publish idempotency key when the first publication response is lost',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{if(init?.method==='POST')throw Error('lost publication response');return Response.json({items:[writing]})});vi.stubGlobal('fetch',fetcher);render(<ManuscriptWriting {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'预览写作候选'}));fireEvent.click(screen.getByRole('button',{name:'确认发布为不可变新版本'}));await screen.findByRole('alert');fireEvent.click(screen.getByRole('button',{name:'确认发布为不可变新版本'}));await waitFor(()=>expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(2));const posts=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(new Headers(posts[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(posts[1][1]?.headers).get('Idempotency-Key'))
})
it('polls an existing queued request into a preview without posting it again',async()=>{
 vi.useFakeTimers();let ready=false;const fetcher=vi.fn(async()=>Response.json({items:[{...writing,task:{...writing.task,status:ready?'succeeded':'queued',display_status:ready?'succeeded':'queued'},candidate:ready?complete:null,preservation_check:ready?writing.preservation_check:null}]}));vi.stubGlobal('fetch',fetcher);render(<ManuscriptWriting {...props}/>);await act(async()=>{});expect(screen.getByRole('status').textContent).toBe('待执行');ready=true;await act(async()=>{vi.advanceTimersByTime(3000)});fireEvent.click(screen.getByRole('button',{name:'预览写作候选'}));expect(screen.getByText('Saved abstract')).toBeTruthy();expect(fetcher.mock.calls.length).toBe(2)
})
it('requires a complete published base before offering a section rewrite',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})));render(<ManuscriptWriting {...props}/>);expect(screen.queryByRole('option',{name:'指定章节重写'})).toBeNull();expect(screen.getByText('旧两章事实稿须先生成并发布完整初稿，再指定章节重写。')).toBeTruthy()
})
it('uses a new request key for another deliberate submission after confirmed acknowledgement',async()=>{
 const pending={...writing,candidate:null,preservation_check:null,task:{...writing.task,status:'queued',display_status:'queued'},input:{...writing.input,keywords:[]}};const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?pending:{items:[]}));vi.stubGlobal('fetch',fetcher);render(<ManuscriptWriting {...props}/>);fireEvent.click(screen.getByRole('button',{name:'发起完整七部分写作'}));await waitFor(()=>expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(1));await screen.findByText('任务尚无可预览候选；请查看任务状态。');fireEvent.click(screen.getByRole('button',{name:'发起完整七部分写作'}));await waitFor(()=>expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(2));const posts=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(new Headers(posts[0][1]?.headers).get('Idempotency-Key')).not.toBe(new Headers(posts[1][1]?.headers).get('Idempotency-Key'))
})
it('distinguishes budget confirmation from an unavailable real model authorization',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{...writing,candidate:null,preservation_check:null,task:{...writing.task,status:'waiting_confirmation',display_status:'waiting_confirmation',reason_code:'budget_exceeded',error_code:'model_budget_exceeded'}}]})));render(<ManuscriptWriting {...props}/>);await screen.findByText('预算不足，任务等待确认；请查看任务中的预算说明。');expect(screen.queryByText('等待模型授权；本环境不会发起真实调用。')).toBeNull()
})

it.each(['reserved','released'] as const)('preserves the legacy and v2 list alongside %s not-submitted calls',async status=>{
 const current={...liveRequest,id:'current',task:{...liveRequest.task,id:'current'}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/writing-previews')?{items:[],capabilities:{real_calls_enabled:false}}:{items:[writing,current,unsubmittedRequest(status)]})))
 render(<ManuscriptWriting {...props}/>);expect(await screen.findByRole('button',{name:'预览写作候选'})).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'受控写作与人工审核'}));await waitFor(()=>expect(screen.getAllByRole('button',{name:'审核此原始候选'})).toHaveLength(2));expect(screen.queryByRole('alert')).toBeNull()
})
