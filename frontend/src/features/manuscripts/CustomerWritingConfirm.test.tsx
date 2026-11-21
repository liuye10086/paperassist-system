// B03 task 5 (D5): one confirmation for customer writing. The authorization contract is unchanged (DESIGN 8.2):
// local wireDigest must match bundle_sha256, the grant is bound to exactly one [{bundle_id,bundle_sha256}],
// the execution body is the one WritingLive has always sent, and an unknown result is never resent automatically.
import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {webcrypto} from 'node:crypto'
import WritingLive from './WritingLive'
import {setLocale,translate} from '../../shared/i18n'
import {narrowScreenStyles} from '../../test/narrowScreenStyles'
import {manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion,Snapshot} from './manuscriptTypes'
import {bundleFixture,hash,liveRequest,rawSnapshot,reviewContext} from './writingLiveFixtures'
import type {Authorization,Bundle,LiveRequest,PreviewInput} from './writingLiveTypes'
import {findTechnicalText} from '../../test/technicalText'
import type {SciSettings} from '../customer/sciProjectSettings'

const projectId='p1',manuscriptId='m1'
const base=`/api/v1/projects/${projectId}/manuscripts/${manuscriptId}`
const authUrl=`/api/v1/projects/${projectId}/writing-authorizations`
const bundleIds=['3f2a9c41-7b6d-4e58-9a10-2c3d4e5f6a7b','4a3b2c1d-0e9f-4a8b-8c7d-6e5f4a3b2c1d']
const authIds=['8d7c6b5a-4f3e-4d2c-9b1a-0f9e8d7c6b5a','9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b']
const requestIds=['1b2c3d4e-5f60-4718-8293-a4b5c6d7e8f9','2c3d4e5f-6071-4829-93a4-b5c6d7e8f901']
const callIds=['5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d','6b7c8d9e-0f1a-4b2c-9d3e-4f5a6b7c8d9e']
const sci:SciSettings={article_type:'research',keywords:['serum marker'],main_results:'Higher serum marker',figure_plan:[],target_journal:{choice:'undecided',name:null}} as unknown as SciSettings
const version=manuscriptFixture.versions[0] as unknown as ManuscriptVersion
const props={projectId,manuscriptId,version,onPublished:vi.fn(),customerSci:sci}

type Server={previews:Bundle[];auths:Authorization[];requests:LiveRequest[];enabled:boolean;capabilities?:Record<string,unknown>;reserved?:number;tamper?:boolean;fail?:(url:string)=>boolean;requestStatus?:{status:string;reason_code:string|null;error_code:string|null};noCalls?:boolean}
const posts=(fetcher:ReturnType<typeof vi.fn>,suffix:string)=>fetcher.mock.calls.filter(([url,init])=>(init as RequestInit|undefined)?.method==='POST'&&String(url).endsWith(suffix))
const body=(call:unknown[])=>JSON.parse(String((call[1] as RequestInit).body)) as Record<string,unknown>

function makeBundle(input:PreviewInput,index:number,server:Server):Bundle{
 const fixture=bundleFixture(bundleIds[index]),wire=JSON.stringify({model:'gpt-5.4-2026-03-05',input:JSON.stringify({instructions:'Write from the frozen research materials.',sources:input.selected_source_ids.map((_,index)=>({alias:'s'+(index+1)})),evidence:[]})})
 const savedInput=input.schema_version===4?{...input,validation_source_ids:input.validation_source_ids??[]}:input
 return {...fixture,request_json:savedInput,wire_json:wire,bundle_sha256:server.tamper?hash('changed'):hash(wire),wire_sha256:server.tamper?hash('changed'):hash(wire),wire_bytes:new TextEncoder().encode(wire).length,reserved_micro_usd:server.reserved??190000}
}
function makeAuth(tasks:Authorization['manifest']['tasks'],index:number):Authorization{
 return {id:authIds[index],project_id:projectId,status:'active',revision:1,manifest_sha256:hash('manifest'+index),manifest:{tasks,max_posts:6,max_corrections:2,cap_micro_usd:12000000,logical_task_cap_micro_usd:3000000,materials:[]},occupied_posts:0,occupied_micro_usd:0,logical_task_usage:[]}
}
function makeRequest(call:{bundle_id:string;authorization_id:string;logical_task_id:string},input:PreviewInput,index:number,status={status:'queued',reason_code:null as string|null,error_code:null as string|null},candidate:Snapshot|null=null,noCalls=false):LiveRequest{
 const id=requestIds[index],execution={bundle_id:call.bundle_id,authorization_id:call.authorization_id,logical_task_id:call.logical_task_id}
 // Like the server: a request always names its execution group; model calls exist only once the worker reserved budget.
 return {...liveRequest,id,input,base_revision:1,candidate,execution,task:{...liveRequest.task,id,status:status.status,display_status:status.status,reason_code:status.reason_code,error_code:status.error_code} as LiveRequest['task'],model_calls:noCalls?[]:[{id:callIds[index],model:'gpt-5.4-2026-03-05',status:'reserved',provider_provenance:'not_submitted',estimated_cost_micro_usd:null,...call}]}
}
function serve(server:Server){
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){
   if(server.fail?.(url))throw new TypeError('Synthetic network interruption')
   const sent=JSON.parse(String(init.body))
   if(url===`${base}/writing-previews`){const created=makeBundle(sent,server.previews.length,server);server.previews.unshift(created);return Response.json(created)}
   if(url===authUrl){const created=makeAuth(sent.tasks,server.auths.length);server.auths.unshift(created);return Response.json(created)}
   if(url===`${base}/writing-requests`){const input=server.previews.find(b=>b.id===sent.bundle_id)!.request_json;const created=makeRequest(sent,input,server.requests.length,server.requestStatus,null,server.noCalls);server.requests.unshift(created);return Response.json(created)}
   return Response.json({})
  }
  if(url===`${base}/writing-previews`)return Response.json({items:server.previews,capabilities:{real_calls_enabled:server.enabled,...server.capabilities}})
  if(url===`${base}/writing-requests`)return Response.json({items:server.requests})
  if(url===authUrl)return Response.json({items:server.auths})
  if(url.endsWith('/review-context'))return Response.json({...reviewContext,request_id:server.requests[0].id,reviews:[]})
  if(url.includes('/writing-previews/'))return Response.json(server.previews[0])
  return Response.json({items:[]})
 })
 vi.stubGlobal('fetch',fetcher)
 return fetcher
}
const generate=()=>screen.getByRole('button',{name:/^(生成正文初稿|再次生成正文)$/})
const confirmBox=()=>screen.getByLabelText('我确认用以上材料生成正文，接受本次写作费用和外部保存范围。')
async function ready(){await waitFor(()=>expect(screen.getByText('本次将使用以下材料生成正文')).toBeTruthy());await waitFor(()=>expect(confirmBox().matches(':disabled')).toBe(false))}

beforeEach(()=>{vi.stubGlobal('crypto',webcrypto)})
afterEach(()=>{cleanup();sessionStorage.clear();vi.useRealTimers();vi.unstubAllGlobals()})

it('prepares one writing preview on entry and reuses a preview with the same request afterwards',async()=>{
 const server:Server={previews:[],auths:[],requests:[],enabled:true}
 let fetcher=serve(server)
 const first=render(<WritingLive {...props}/>)
 await ready()
 expect(posts(fetcher,'/writing-previews')).toHaveLength(1)
 expect(server.previews[0].request_json.validation_source_ids).toEqual([])
 expect(body(posts(fetcher,'/writing-previews')[0])).toMatchObject({schema_version:4,document_kind:'sci',article_type:'research',keywords:['serum marker']})
 first.unmount()
 fetcher=serve(server)
 render(<WritingLive {...props}/>)
 await ready()
 expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
})

it('keeps the button disabled until the materials are checked and the customer confirms',async()=>{
 serve({previews:[],auths:[],requests:[],enabled:true})
 render(<WritingLive {...props}/>)
 await ready()
 expect(generate().matches(':disabled')).toBe(true)
 fireEvent.click(confirmBox())
 expect(generate().matches(':disabled')).toBe(false)
 fireEvent.click(confirmBox())
 expect(generate().matches(':disabled')).toBe(true)
})

it('gives the generation action the primary style and full width on narrow screens',async()=>{
 serve({previews:[],auths:[],requests:[],enabled:true})
 render(<WritingLive {...props}/>);await ready()
 const button=generate()
 expect(button.classList.contains('button-primary')).toBe(true)
 const styles=narrowScreenStyles(button,'manuscripts/manuscripts.css')
 expect(styles.some(style=>style.width==='100%')).toBe(true)
})

it('shows the approved English writing and overwrite confirmations',async()=>{
 serve({previews:[],auths:[],requests:[],enabled:true,capabilities:{provider:'OpenAI',storage_scope:'OpenAI stores background responses; selected material is transmitted externally.'}})
 render(<WritingLive {...props}/>);await ready()
 try{
  act(()=>setLocale('en'))
  expect(screen.getByRole('button',{name:'Generate draft text'})).toBeTruthy()
  expect(screen.getByRole('checkbox',{name:'I confirm generating the text from the materials above and accept the writing charge and external storage scope for this run.'})).toBeTruthy()
  expect(screen.getByText(/^These materials will be sent to OpenAI; the generated result is stored by the provider \(.+\)\.$/)).toBeTruthy()
  expect(translate('再次生成正文')).toBe('Generate again')
  expect(translate('这一版已经生成过正文。再次生成会产生新的写作费用，之前的生成结果仍可查看。')).toBe('This version already has generated text. Generating again incurs a new writing charge; the earlier result stays available.')
  expect(translate('保存后，这份稿件会按新材料更新为第 {next} 版。第 {revision} 版已生成的正文和核对结果不会带到新版本，需要重新生成正文并重新核对，重新生成会再次产生写作费用。',{next:3,revision:2})).toBe('After saving, this manuscript will be updated to version 3 with the new materials. The text and checks generated for version 2 will not carry over: you will need to generate the text again and recheck it, and generating again incurs a new writing charge.')
  expect(translate('第 {revision} 版、已下载的 Word 和已开始的返修保持原样，可以在历史中查看。',{revision:2})).toBe('Version 2, downloaded Word files and revision rounds already started stay unchanged and remain available in the history.')
 }finally{act(()=>setLocale('zh-CN'))}
})

it('creates one exact authorization and then sends the unchanged writing request',async()=>{
 const server:Server={previews:[],auths:[],requests:[],enabled:true}
 const fetcher=serve(server)
 render(<WritingLive {...props}/>)
 await ready()
 fireEvent.click(confirmBox());fireEvent.click(generate())
 await waitFor(()=>expect(posts(fetcher,'/writing-requests')).toHaveLength(1))
 const bundle=server.previews[0]
 const authPosts=posts(fetcher,'/writing-authorizations')
 expect(authPosts).toHaveLength(1)
 expect(body(authPosts[0])).toEqual({schema_version:2,confirmed:true,tasks:[{logical_task_id:'task-1',bundles:[{bundle_id:bundle.id,bundle_sha256:bundle.bundle_sha256}]}]})
 expect(body(posts(fetcher,'/writing-requests')[0])).toEqual({schema_version:2,bundle_id:bundle.id,bundle_sha256:bundle.bundle_sha256,authorization_id:authIds[0],logical_task_id:'task-1'})
 const order=fetcher.mock.calls.filter(([,init])=>init?.method==='POST').map(([url])=>String(url).split('/').at(-1))
 expect(order).toEqual(['writing-previews','writing-authorizations','writing-requests'])
})

it('reuses an unused exact authorization and sends only the writing request',async()=>{
 const server:Server={previews:[],auths:[],requests:[],enabled:true}
 let fetcher=serve(server)
 const first=render(<WritingLive {...props}/>);await ready();first.unmount()
 const bundle=server.previews[0]
 server.auths=[makeAuth([{logical_task_id:'task-1',bundles:[{bundle_id:bundle.id,bundle_sha256:bundle.bundle_sha256}]}],0)]
 fetcher=serve(server)
 render(<WritingLive {...props}/>);await ready()
 fireEvent.click(confirmBox());fireEvent.click(generate())
 await waitFor(()=>expect(posts(fetcher,'/writing-requests')).toHaveLength(1))
 expect(posts(fetcher,'/writing-authorizations')).toHaveLength(0)
 expect(body(posts(fetcher,'/writing-requests')[0])).toMatchObject({authorization_id:authIds[0],logical_task_id:'task-1'})
})

it('sends neither POST when the local digest does not match the frozen preview',async()=>{
 const fetcher=serve({previews:[],auths:[],requests:[],enabled:true,tamper:true})
 render(<WritingLive {...props}/>)
 await screen.findByText('材料已变化，请重新预览本次写作材料。')
 fireEvent.click(confirmBox());fireEvent.click(generate())
 await act(async()=>{await Promise.resolve()})
 expect(posts(fetcher,'/writing-authorizations')).toHaveLength(0)
 expect(posts(fetcher,'/writing-requests')).toHaveLength(0)
 expect(generate().matches(':disabled')).toBe(true)
})

it('asks to check the result after an unknown writing request and never resends it after reload',async()=>{
 const server:Server={previews:[],auths:[],requests:[],enabled:true,fail:url=>url.endsWith('/writing-requests')}
 let fetcher=serve(server)
 const first=render(<WritingLive {...props}/>)
 await ready()
 fireEvent.click(confirmBox());fireEvent.click(generate())
 await screen.findByText('暂时无法确定这次提交是否成功。请先查看提交结果。')
 expect(screen.getByRole('button',{name:'查看提交结果'})).toBeTruthy()
 expect(generate().matches(':disabled')).toBe(true)
 expect(posts(fetcher,'/writing-requests')).toHaveLength(1)
 first.unmount()
 fetcher=serve({...server,fail:undefined})
 render(<WritingLive {...props}/>)
 await screen.findByText('暂时无法确定这次提交是否成功。请先查看提交结果。')
 await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url===`${base}/writing-requests`)).toBe(true))
 expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
 expect(generate().matches(':disabled')).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'查看提交结果'}))
 await act(async()=>{await Promise.resolve()})
 expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
})

it.each([
 {status:'queued',reason_code:null,error_code:null},
 {status:'waiting_confirmation',reason_code:'budget_exceeded',error_code:null},
])('finds a previously unknown $status request before its first model call without resubmitting',async requestStatus=>{
 const server:Server={previews:[],auths:[],requests:[],enabled:true,fail:url=>url.endsWith('/writing-requests')}
 const initial=serve(server)
 const first=render(<WritingLive {...props}/>)
 await ready()
 fireEvent.click(confirmBox())
 fireEvent.click(generate())
 await screen.findByText('暂时无法确定这次提交是否成功。请先查看提交结果。')
 const submission=JSON.parse(String(posts(initial,'/writing-requests')[0][1].body))
 first.unmount()
 const reads=serve(server)
 render(<WritingLive {...props}/>)
 const check=await screen.findByRole('button',{name:'查看提交结果'})
 await waitFor(()=>expect(check.matches(':disabled')).toBe(false))
 server.requests.push(makeRequest(submission,server.previews[0].request_json,0,requestStatus,null,true))
 fireEvent.click(check)
 await screen.findByRole('heading',{name:/写作记录 1/})
 await waitFor(()=>expect(screen.queryByRole('button',{name:'查看提交结果'})).toBeNull())
 expect(server.requests[0].model_calls).toEqual([])
 expect(reads.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
})

it('resolves an unknown authorization by its exact manifest and still waits for a new click to generate',async()=>{
 const server:Server={previews:[],auths:[],requests:[],enabled:true,fail:url=>url===authUrl}
 let fetcher=serve(server)
 render(<WritingLive {...props}/>)
 await ready()
 fireEvent.click(confirmBox());fireEvent.click(generate())
 await screen.findByText('暂时无法确定这次提交是否成功。请先查看提交结果。')
 const sent=body(posts(fetcher,'/writing-authorizations')[0])
 server.auths=[makeAuth(sent.tasks as Authorization['manifest']['tasks'],0)]
 fetcher=serve({...server,fail:undefined})
 fireEvent.click(screen.getByRole('button',{name:'查看提交结果'}))
 await waitFor(()=>expect(screen.queryByText('暂时无法确定这次提交是否成功。请先查看提交结果。')).toBeNull())
 expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
 fireEvent.click(confirmBox());fireEvent.click(generate())
 await waitFor(()=>expect(posts(fetcher,'/writing-requests')).toHaveLength(1))
 expect(posts(fetcher,'/writing-authorizations')).toHaveLength(0)
 expect(body(posts(fetcher,'/writing-requests')[0])).toMatchObject({authorization_id:authIds[0]})
})

it('creates one authorization and one writing request when the button is clicked repeatedly',async()=>{
 const fetcher=serve({previews:[],auths:[],requests:[],enabled:true})
 render(<WritingLive {...props}/>)
 await ready()
 fireEvent.click(confirmBox())
 const button=generate()
 fireEvent.click(button);fireEvent.click(button);fireEvent.click(button)
 await waitFor(()=>expect(posts(fetcher,'/writing-requests')).toHaveLength(1))
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20))})
 expect(posts(fetcher,'/writing-authorizations')).toHaveLength(1)
 expect(posts(fetcher,'/writing-requests')).toHaveLength(1)
})

it('warns before generating again and creates a new authorization for the same preview',async()=>{
 const server:Server={previews:[],auths:[],requests:[],enabled:true}
 let fetcher=serve(server)
 const first=render(<WritingLive {...props}/>);await ready();first.unmount()
 const bundle=server.previews[0],grant={logical_task_id:'task-1',bundles:[{bundle_id:bundle.id,bundle_sha256:bundle.bundle_sha256}]}
 server.auths=[makeAuth([grant],0)]
 server.requests=[makeRequest({bundle_id:bundle.id,authorization_id:authIds[0],logical_task_id:'task-1'},bundle.request_json,0,{status:'succeeded',reason_code:null,error_code:null},rawSnapshot)]
 fetcher=serve(server)
 render(<WritingLive {...props}/>);await ready()
 expect(screen.getByText('这一版已经生成过正文。再次生成会产生新的写作费用，之前的生成结果仍可查看。')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'生成正文初稿'})).toBeNull()
 fireEvent.click(confirmBox());fireEvent.click(screen.getByRole('button',{name:'再次生成正文'}))
 await waitFor(()=>expect(posts(fetcher,'/writing-requests')).toHaveLength(1))
 expect(posts(fetcher,'/writing-authorizations')).toHaveLength(1)
 expect(body(posts(fetcher,'/writing-requests')[0])).toMatchObject({authorization_id:authIds[1]})
})

it.each([
 ['a budget wait',{status:'waiting_confirmation',reason_code:'model_budget_missing',error_code:null}],
 ['a queued request',{status:'queued',reason_code:null,error_code:null}],
])('never reuses the authorization group of %s that has no model call yet after a reload',async(_name,requestStatus)=>{
 const server:Server={previews:[],auths:[],requests:[],enabled:true,noCalls:true,requestStatus}
 let fetcher=serve(server)
 const first=render(<WritingLive {...props}/>);await ready()
 fireEvent.click(confirmBox());fireEvent.click(generate())
 await waitFor(()=>expect(posts(fetcher,'/writing-requests')).toHaveLength(1))
 expect(server.requests[0].model_calls).toEqual([])
 first.unmount()
 fetcher=serve(server)
 render(<WritingLive {...props}/>);await ready()
 if(requestStatus.status==='queued'){
  // Still being generated: the page follows it and offers no second generation.
  await screen.findByText('正在生成正文，完成后会自动打开核对。')
  fireEvent.click(confirmBox())
  expect(generate().matches(':disabled')).toBe(true)
  fireEvent.click(generate())
  await act(async()=>{await Promise.resolve()})
  expect(posts(fetcher,'/writing-requests')).toHaveLength(0)
  expect(posts(fetcher,'/writing-authorizations')).toHaveLength(0)
  return
 }
 fireEvent.click(confirmBox());fireEvent.click(generate())
 await waitFor(()=>expect(posts(fetcher,'/writing-requests')).toHaveLength(1))
 expect(posts(fetcher,'/writing-authorizations')).toHaveLength(1)
 expect(body(posts(fetcher,'/writing-requests')[0])).toMatchObject({authorization_id:authIds[1]})
})

it('names the service in plain words for the real server values and never shows the endpoint or the English notice',async()=>{
 const notice='OpenAI stores background responses; selected material is transmitted externally.'
 serve({previews:[],auths:[],requests:[],enabled:true,capabilities:{provider:'https://api.openai.com/v1/responses',storage_scope:notice}})
 const view=render(<WritingLive {...props}/>);await ready()
 expect(screen.getByText('本次材料将发送给 OpenAI，生成结果由服务商保存（所选材料会发送到外部服务，后台生成记录由服务商保留）。')).toBeTruthy()
 expect(document.body.textContent).not.toContain('https://')
 expect(document.body.textContent).not.toContain(notice)
 view.unmount();sessionStorage.clear()
 serve({previews:[],auths:[],requests:[],enabled:true,capabilities:{provider:'https://other.example/v1',storage_scope:'Kept for 30 days.'}})
 render(<WritingLive {...props}/>);await ready()
 expect(screen.getByText('本次材料将发送给外部写作服务，生成结果由服务商保存。')).toBeTruthy()
 expect(document.body.textContent).not.toMatch(/https:\/\/|Kept for 30 days/)
})

it('opens a finished, unadopted draft for checking by itself after coming back',async()=>{
 const server:Server={previews:[],auths:[],requests:[],enabled:true}
 let fetcher=serve(server)
 const first=render(<WritingLive {...props}/>);await ready();first.unmount()
 const bundle=server.previews[0]
 server.auths=[makeAuth([{logical_task_id:'task-1',bundles:[{bundle_id:bundle.id,bundle_sha256:bundle.bundle_sha256}]}],0)]
 server.requests=[makeRequest({bundle_id:bundle.id,authorization_id:authIds[0],logical_task_id:'task-1'},bundle.request_json,0,{status:'succeeded',reason_code:null,error_code:null},rawSnapshot)]
 fetcher=serve(server)
 render(<WritingLive {...props}/>)
 await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/review-context'))).toBe(true))
 expect(screen.queryByRole('button',{name:'审核此原始候选'})).toBeNull()
 expect(screen.getByRole('button',{name:'继续核对这份正文'})).toBeTruthy()
})

it('names the receiving service and storage scope only from the server',async()=>{
 serve({previews:[],auths:[],requests:[],enabled:true,capabilities:{provider:'OpenAI',storage_scope:'OpenAI stores background responses; selected material is transmitted externally.'}})
 const view=render(<WritingLive {...props}/>);await ready()
 expect(screen.getByText('本次材料将发送给 OpenAI，生成结果由服务商保存（所选材料会发送到外部服务，后台生成记录由服务商保留）。')).toBeTruthy()
 expect(screen.getByText(/本次预留 US\$0\.19。/)).toBeTruthy()
 view.unmount();sessionStorage.clear()
 serve({previews:[],auths:[],requests:[],enabled:true,reserved:0})
 render(<WritingLive {...props}/>);await ready()
 expect(screen.getByText('本次材料将发送给外部写作服务，生成结果由服务商保存。')).toBeTruthy()
 expect(screen.queryByText(/OpenAI/)).toBeNull()
 expect(screen.queryByText(/本次预留|US\$|免费/)).toBeNull()
 expect(screen.getByText(/生成正文会产生写作费用。/)).toBeTruthy()
})

it('opens the science check by itself once the writing task succeeds',async()=>{
 vi.useFakeTimers({shouldAdvanceTime:true})
 const server:Server={previews:[],auths:[],requests:[],enabled:true}
 const fetcher=serve(server)
 render(<WritingLive {...props}/>);await ready()
 fireEvent.click(confirmBox());fireEvent.click(generate())
 await screen.findByText('正在生成正文，完成后会自动打开核对。')
 server.requests=[{...server.requests[0],candidate:rawSnapshot,task:{...server.requests[0].task,status:'succeeded',display_status:'succeeded'}}]
 await act(async()=>{await vi.advanceTimersByTimeAsync(3000)})
 await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/review-context'))).toBe(true))
 expect((await screen.findAllByLabelText(/段落主张分类/)).length).toBeGreaterThan(0)
 const polls=fetcher.mock.calls.filter(([url,init])=>url===`${base}/writing-requests`&&!init?.method).length
 await act(async()=>{await vi.advanceTimersByTimeAsync(6000)})
 expect(fetcher.mock.calls.filter(([url,init])=>url===`${base}/writing-requests`&&!init?.method)).toHaveLength(polls)
})

it.each([['budget_exceeded','model_budget_missing'],['model_budget_missing',null]])('shows the customer budget notice for %s without recovery or admin wording',async(reason,error)=>{
 const fetcher=serve({previews:[],auths:[],requests:[],enabled:true,requestStatus:{status:'waiting_confirmation',reason_code:reason,error_code:error}})
 render(<WritingLive {...props}/>);await ready()
 fireEvent.click(confirmBox());fireEvent.click(generate())
 await screen.findByText('写作费用额度暂未开通或已用完，本次材料尚未发送。请联系客服开通后回到这里继续生成。')
 expect(posts(fetcher,'/writing-requests')).toHaveLength(1)
 expect(document.body.textContent).not.toMatch(/model_budget_missing|budget_exceeded|管理员/)
 expect(screen.queryByRole('button',{name:'核对原写作任务'})).toBeNull()
 expect(screen.queryByRole('button',{name:/恢复/})).toBeNull()
 expect(screen.getByRole('heading',{name:'写作记录 1 · 等待写作额度'})).toBeTruthy()
 try{
  act(()=>setLocale('en'))
  expect(screen.getByRole('heading',{name:'Writing record 1 · Waiting for writing budget'})).toBeTruthy()
 }finally{act(()=>setLocale('zh-CN'))}
})

it.each([
 {role:'customer',reason:null,title:'写作记录 1'},
 {role:'staff',reason:'model_budget_missing',title:liveRequest.id},
])('keeps the normal confirmation heading for $role when the customer budget label does not apply',async({role,reason,title})=>{
 const request:LiveRequest={...liveRequest,candidate:null,task:{...liveRequest.task,status:'waiting_confirmation',display_status:'waiting_confirmation',reason_code:reason}}
 serve({previews:[],auths:[],requests:[request],enabled:true})
 render(<WritingLive {...props} customerSci={role==='customer'?sci:undefined}/>)
 await screen.findByRole('heading',{name:`${title} · 待用户确认`})
})

it('includes every cited excerpt in the automatic review preview',async()=>{
 const evidence=(id:string,quote:string)=>({id,quote})
 const snapshot={...version.snapshot,citation_snapshot:{paragraphs:[{fragments:[{bindings:[{evidence:[evidence('e1','First excerpt'),evidence('e2','Second excerpt')]}]}]},{fragments:[{bindings:[{evidence:[evidence('e3','Third excerpt'),evidence('e1','First excerpt')]}]}]}]}} as unknown as Snapshot
 const fetcher=serve({previews:[],auths:[],requests:[],enabled:true})
 render(<WritingLive {...props} customerSci={{...sci,article_type:'narrative_review'} as SciSettings} version={{...version,snapshot}}/>);await ready()
 expect(body(posts(fetcher,'/writing-previews')[0])).toMatchObject({article_type:'narrative_review',selected_evidence_ids:['e1','e2','e3']})
 const excerpt=screen.getByLabelText('Second excerpt') as HTMLInputElement
 expect(excerpt.checked).toBe(true)
 fireEvent.click(excerpt)
 expect(screen.queryByText('本次将使用以下材料生成正文')).toBeNull()
 expect(screen.getByText('写作材料已修改，请更新写作材料预览后再生成。')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'更新写作材料预览'}))
 await waitFor(()=>expect(posts(fetcher,'/writing-previews')).toHaveLength(2))
 expect(body(posts(fetcher,'/writing-previews')[1])).toMatchObject({selected_evidence_ids:['e1','e3']})
})

it('shows no hashes, internal identifiers or controlled-writing wording before and after submitting',async()=>{
 const server:Server={previews:[],auths:[],requests:[],enabled:true}
 serve(server)
 render(<WritingLive {...props}/>);await ready()
 const systemIds=()=>[...server.previews.flatMap(b=>[b.id,b.bundle_sha256]),...authIds,...requestIds,...callIds,'task-1']
 const scan=()=>findTechnicalText(document.body,{systemIds:systemIds()})
 const forbidden=/逻辑任务|wire|受控|SHA|[0-9a-f]{64}/
 expect(scan()).toEqual([])
 expect(document.body.textContent).not.toMatch(forbidden)
 expect(screen.queryByRole('region',{name:'写作批次授权'})).toBeNull()
 expect(screen.queryByLabelText('授权逻辑任务')).toBeNull()
 fireEvent.click(confirmBox());fireEvent.click(generate())
 await screen.findByText('正在生成正文，完成后会自动打开核对。')
 expect(scan()).toEqual([])
 expect(document.body.textContent).not.toMatch(forbidden)
 const region=screen.getByRole('region',{name:'写作工作区'})
 expect(within(region).getByRole('heading',{name:'生成正文'})).toBeTruthy()
})


it('adds an optional method source to the budget preview only after selection and authorizes the updated bundle', async () => {
 const source=(id:string,label:string,role:string)=>({id,file_id:id,kind:'original',label,role,sha256:'a'.repeat(64),content:{},download_url:null})
 const sources=[source('result','Study table.xlsx','user_results'),source('method','Supplementary notes.docx','methods')]
 const snapshot={...version.snapshot,sources,paper_plan:{kind:'research',title:'Study',keywords:[],sections:[],materials:[{selection:sources[0]}]}} as unknown as Snapshot
 const server:Server={previews:[],auths:[],requests:[],enabled:true}
 const fetcher=serve(server)
 render(<WritingLive {...props} version={{...version,snapshot}}/>)
 await ready()
 expect(screen.getByRole('checkbox',{name:/Study table.xlsx/})).toHaveProperty('checked',true)
 const optional=screen.getByRole('checkbox',{name:/Supplementary notes.docx/})
 expect(optional).toHaveProperty('checked',false)
 expect(body(posts(fetcher,'/writing-previews')[0]).selected_source_ids).toEqual(['result'])
 fireEvent.click(optional)
 fireEvent.click(screen.getByRole('button',{name:'更新写作材料预览'}))
 await ready()
 expect(body(posts(fetcher,'/writing-previews')[1]).selected_source_ids).toEqual(['result','method'])
 expect(posts(fetcher,'/writing-authorizations')).toHaveLength(0)
 expect(posts(fetcher,'/writing-requests')).toHaveLength(0)
 fireEvent.click(confirmBox());fireEvent.click(generate())
 await waitFor(()=>expect(posts(fetcher,'/writing-requests')).toHaveLength(1))
 const [updated,original]=server.previews
 expect(updated.bundle_sha256).not.toBe(original.bundle_sha256)
 expect(body(posts(fetcher,'/writing-authorizations')[0]).tasks).toEqual([{logical_task_id:'task-1',bundles:[{bundle_id:updated.id,bundle_sha256:updated.bundle_sha256}]}])
 expect(body(posts(fetcher,'/writing-requests')[0])).toMatchObject({bundle_id:updated.id,bundle_sha256:updated.bundle_sha256,authorization_id:authIds[0]})
})


it.each(['source identity','source order','validation source','base revision','base version id'] as const)(
 'prepares a different preview after a change to the %s', async difference => {
  const source=(id:string)=>({id,file_id:id,kind:'analysis_run',label:id+' result',role:'computed_results',sha256:hash(id),content:{},download_url:null})
  const sources=['source-a','source-b','source-c'].map(source)
  const snapshot={...version.snapshot,article_type:'methods',sources,paper_plan:{kind:'research',
   title:'Study',keywords:[],sections:[],materials:sources.slice(0,2).map(selection=>({selection}))}} as unknown as Snapshot
  const server:Server={previews:[],auths:[],requests:[],enabled:true}
  const fetcher=serve(server)
  const page=<WritingLive {...props} version={{...version,snapshot}}/>
  const first=render(page);await ready();first.unmount()
  const record=server.previews[0]
  expect(record.request_json.selected_source_ids).toEqual(['source-a','source-b'])
  switch(difference){
   case 'source identity': record.request_json.selected_source_ids=['source-a','source-c'];break
   case 'source order': record.request_json.selected_source_ids=['source-b','source-a'];break
   case 'validation source': record.request_json.validation_source_ids=['source-a'];break
   case 'base revision': record.request_json.base_revision=2;break
   case 'base version id': record.base_version_id='different-version';break
  }
  fetcher.mockClear()
  render(page);await ready()
  expect(posts(fetcher,'/writing-previews')).toHaveLength(1)
  expect(posts(fetcher,'/writing-authorizations')).toHaveLength(0)
  expect(posts(fetcher,'/writing-requests')).toHaveLength(0)
 })
