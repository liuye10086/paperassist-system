import {afterEach,expect,test,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import FileLifecyclePanel from './FileLifecyclePanel'
import FileImpactReview from './FileImpactReview'
import {assessmentFixture,lifecycleResponse} from './lifecycleFixtures'
import {setApiSession} from '../../shared/api/client'
import {setLocale} from '../../shared/i18n'
import {StrictMode} from 'react'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN');vi.useRealTimers()})
const receipt=(file='f',status='retained',reason='reason')=>{const a=assessmentFixture(file);return {id:'request',file_id:file,reason,status,requested_at:'2026-10-13T00:00:00Z',resolved_at:'2026-10-13T00:00:00Z',policy_version:a.policy_version,assessment_revision:a.assessment_revision,assessment:{...a,deletion_status:status,reasons:status==='blocked'?[{code:'internal_testing_retention'},{code:'active_tasks'}]:a.reasons}}}
async function confirm(){fireEvent.change(screen.getByRole('textbox',{name:'删除申请理由'}),{target:{value:' reason '}});fireEvent.click(screen.getByRole('button',{name:'提交删除申请'}));await waitFor(()=>expect(screen.getByRole('button',{name:'确认提交删除申请'}).hasAttribute('disabled')).toBe(false));fireEvent.click(screen.getByRole('button',{name:'确认提交删除申请'}))}
test.each(['retained','blocked'])('records %s outcome, reason and timestamp without removing existing preview',async status=>{
 const posts:RequestInit[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){posts.push(init);return Response.json(receipt('f',status))}return lifecycleResponse(url)!}))
 render(<><p>Old preview</p><FileLifecyclePanel projectId="p" fileId="f" active onUnavailable={()=>{}}/></>)
 await confirm();await screen.findByText(status==='retained'?'已记录申请，文件按规则保留':'申请存在阻塞原因，文件继续保留')
 expect(posts).toHaveLength(1);expect(JSON.parse(posts[0].body as string)).toEqual({expected_assessment_revision:'a'.repeat(64),reason:'reason'})
 expect((screen.getByRole('textbox',{name:'删除申请理由'}) as HTMLTextAreaElement).value).toBe('');expect(screen.getByText('Old preview')).toBeTruthy();expect(document.querySelector('time')).toBeTruthy()
})
test('unknown submission is frozen and double-click replay preserves body/key after impact changes',async()=>{
 const posts:RequestInit[]=[];let resolve!:(v:Response)=>void
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){posts.push(init);if(posts.length===1)throw new TypeError('network');return new Promise<Response>(r=>{resolve=r})}return lifecycleResponse(url)!}))
 render(<FileLifecyclePanel projectId="p" fileId="f" active onUnavailable={()=>{}}/>);await confirm();await screen.findByText('提交结果尚未确认，请使用同一请求确认结果。')
 expect((screen.getByRole('textbox',{name:'删除申请理由'}) as HTMLTextAreaElement).value).toBe(' reason ')
 fireEvent.click(screen.getByRole('button',{name:'重新读取影响'}));await waitFor(()=>expect(screen.getByRole('button',{name:'重新读取影响'}).hasAttribute('disabled')).toBe(false))
 const retry=screen.getByRole('button',{name:'使用同一请求确认申请结果'});fireEvent.click(retry);fireEvent.click(retry);expect(posts).toHaveLength(2)
 expect(posts[1].body).toBe(posts[0].body);expect(new Headers(posts[1].headers).get('Idempotency-Key')).toBe(new Headers(posts[0].headers).get('Idempotency-Key'))
 await act(async()=>resolve(Response.json(receipt())));await screen.findByText('已记录申请，文件按规则保留')
})
test('409 rejects old key and requires fresh visible impact review',async()=>{
 const posts:RequestInit[]=[];vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){posts.push(init);return posts.length===1?Response.json({detail:{code:'file_assessment_conflict'}},{status:409}):Response.json(receipt())}return lifecycleResponse(url)!}))
 render(<FileLifecyclePanel projectId="p" fileId="f" active onUnavailable={()=>{}}/>);await confirm();await screen.findByRole('alert');expect(screen.queryByRole('dialog')).toBeNull();await confirm();await screen.findByText('已记录申请，文件按规则保留');expect(new Headers(posts[1].headers).get('Idempotency-Key')).not.toBe(new Headers(posts[0].headers).get('Idempotency-Key'))
})
test('history pager uses full total independently of assessment and failed reads remain errors',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{if(url.includes('page=2'))return new Response('',{status:500});return Response.json({items:[receipt()],total:21,page:1,page_size:10})}))
 render(<FileLifecyclePanel projectId="p" fileId="f" active onUnavailable={()=>{}}/>);await screen.findByText('删除申请共 21 条');fireEvent.click(screen.getByRole('button',{name:'下一页删除申请'}));await screen.findByRole('alert');expect(screen.queryByText('尚无删除申请。')).toBeNull()
})
test('file switch and session change suppress late old receipt and wipe reason/history',async()=>{
 let resolve!:(v:Response)=>void;vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST')return new Promise<Response>(r=>{resolve=r});return lifecycleResponse(url,url.includes('/other/')?'other':'f')!}))
 const view=render(<FileLifecyclePanel projectId="p" fileId="f" active onUnavailable={()=>{}}/>);await confirm();view.rerender(<FileLifecyclePanel projectId="p" fileId="other" active onUnavailable={()=>{}}/>);await act(async()=>resolve(Response.json(receipt())));expect(screen.queryByText('已记录申请，文件按规则保留')).toBeNull();expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('')
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'account A private reason'}});act(()=>setApiSession('account-b'));expect(screen.queryByRole('textbox')).toBeNull();expect(screen.queryByText('account A private reason')).toBeNull()
})
test('impact tasks paginate stable pages, show safe sources and distinguish attempt from success',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.includes('/tasks')?Response.json({items:[{id:'private-id',origin:'task',task_type:'parse_file',status:'failed',created_at:'2026-10-13',sources:[{kind:'parse_versions',id:'private-source',version:1}],has_newer_version:true,source_status:url.includes('page=2')?'newer_published_version':'newer_attempt_available',stale_reasons:[url.includes('page=2')?'newer_published_version':'newer_attempt_available']}],total:11,page:url.includes('page=2')?2:1,page_size:10,counts:assessmentFixture().counts}):lifecycleResponse(url)!))
 render(<FileImpactReview projectId="p" fileId="f" action="reparse" operation="Word" onUnavailable={()=>{}} onCancel={()=>{}} onConfirm={()=>{}}/>);await screen.findByText('有更新的尝试，尚不代表已发布成功版本');expect(screen.getByText('解析版本 · 版本 v1')).toBeTruthy();expect(screen.queryByText('private-id')).toBeNull();fireEvent.click(screen.getByRole('button',{name:'下一页受影响任务'}));await screen.findByText('有更新的已发布版本');expect(within(screen.getByRole('navigation',{name:'受影响任务分页'})).getByText('第 2 页')).toBeTruthy()
})
test('unavailable original disables reparse and never claims all historical downloads are healthy',async()=>{
 const a={...assessmentFixture('f','reparse'),original_available:false,original_integrity:'missing',can_reparse:false,reparse_reason:'original_missing',deletion_status:'blocked',reasons:[{code:'internal_testing_retention'},{code:'original_missing'}]}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.includes('/assessment')?Response.json(a):lifecycleResponse(url)!))
 render(<FileImpactReview projectId="p" fileId="f" action="reparse" operation="Word" onUnavailable={()=>{}} onCancel={()=>{}} onConfirm={()=>{}}/>);await screen.findByText('本次原件不可用，保留策略不代表原件已恢复。');expect(screen.getByRole('button',{name:'确认并开始重解析'}).hasAttribute('disabled')).toBe(true)
})
test('receipt for another reason is an unknown result and preserves the original request for replay',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>init?.method==='POST'?Response.json(receipt('f','retained','different reason')):lifecycleResponse(url)!))
 render(<FileLifecyclePanel projectId="p" fileId="f" active onUnavailable={()=>{}}/>);await confirm()
 await screen.findByText('提交结果尚未确认，请使用同一请求确认结果。')
 expect(screen.queryByText('已记录申请，文件按规则保留')).toBeNull();expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe(' reason ')
})
test('observed version change invalidates loaded confirmation while its new assessment is pending',async()=>{
 let resolve!:(v:Response)=>void,reads=0;const confirm=vi.fn(),props={projectId:'p',fileId:'f',action:'reparse' as const,operation:'Word',onUnavailable:()=>{},onCancel:()=>{},onConfirm:confirm}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.includes('/assessment')&&++reads>1?new Promise<Response>(r=>{resolve=r}):lifecycleResponse(url)!))
 const view=render(<FileImpactReview {...props} observedVersion={1}/>);await waitFor(()=>expect(screen.getByRole('button',{name:'确认并开始重解析'}).hasAttribute('disabled')).toBe(false))
 view.rerender(<FileImpactReview {...props} observedVersion={2}/>);fireEvent.click(screen.getByRole('button',{name:'确认并开始重解析'}));expect(confirm).not.toHaveBeenCalled()
 await act(async()=>resolve(Response.json(assessmentFixture('f','reparse'))));await waitFor(()=>expect(screen.getByRole('button',{name:'确认并开始重解析'}).hasAttribute('disabled')).toBe(false))
})
test('assessment timeout is bounded and suppresses the late response after a retry',async()=>{
 vi.useFakeTimers();let resolve!:(v:Response)=>void,reads=0
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.includes('/assessment')&&++reads===1?new Promise<Response>(r=>{resolve=r}):lifecycleResponse(url)!))
 render(<FileImpactReview projectId="p" fileId="f" action="reparse" operation="Word" onUnavailable={()=>{}} onCancel={()=>{}} onConfirm={()=>{}}/>);await act(async()=>vi.advanceTimersByTimeAsync(15000))
 expect(screen.getByRole('alert').textContent).toBe('影响读取失败或超时，请重新读取。');fireEvent.click(screen.getByRole('button',{name:'重新读取影响'}));await act(async()=>vi.advanceTimersByTimeAsync(0))
 await act(async()=>resolve(Response.json({...assessmentFixture('f','reparse'),original_available:false,original_integrity:'missing',can_reparse:false,reparse_reason:'original_missing'})))
 expect(screen.getByRole('button',{name:'确认并开始重解析'}).hasAttribute('disabled')).toBe(false);expect(screen.queryByText('本次原件不可用，保留策略不代表原件已恢复。')).toBeNull()
})
test('losing permission while paging tasks clears the prior assessment instead of retaining its details',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.includes('/tasks')?url.includes('page=2')?new Response('',{status:403}):Response.json({items:[],total:11,page:1,page_size:10,counts:assessmentFixture().counts}):lifecycleResponse(url)!))
 const unavailable=vi.fn();render(<FileImpactReview projectId="p" fileId="f" action="reparse" operation="Word" onUnavailable={unavailable} onCancel={()=>{}} onConfirm={()=>{}}/>);await screen.findByText('本次已核验原件可读取。');fireEvent.click(screen.getByRole('button',{name:'下一页受影响任务'}));await waitFor(()=>expect(unavailable).toHaveBeenCalled());expect(screen.queryByText('本次已核验原件可读取。')).toBeNull()
})
test('timed-out deletion submission offers same-key replay and ignores late acknowledgement',async()=>{
 vi.useFakeTimers();const posts:RequestInit[]=[];let resolve!:(v:Response)=>void
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){posts.push(init);return posts.length===1?new Promise<Response>(r=>{resolve=r}):Response.json(receipt())}return lifecycleResponse(url)!}))
 render(<FileLifecyclePanel projectId="p" fileId="f" active onUnavailable={()=>{}}/>);fireEvent.change(screen.getByRole('textbox'),{target:{value:'reason'}});fireEvent.click(screen.getByRole('button',{name:'提交删除申请'}));await act(async()=>vi.advanceTimersByTimeAsync(0));fireEvent.click(screen.getByRole('button',{name:'确认提交删除申请'}));await act(async()=>vi.advanceTimersByTimeAsync(15000));expect(screen.getByText('提交结果尚未确认，请使用同一请求确认结果。')).toBeTruthy()
 await act(async()=>resolve(Response.json(receipt())));expect(screen.queryByText('已记录申请，文件按规则保留')).toBeNull();fireEvent.click(screen.getByRole('button',{name:'使用同一请求确认申请结果'}));await act(async()=>vi.advanceTimersByTimeAsync(0));expect(screen.getByText('已记录申请，文件按规则保留')).toBeTruthy();expect(posts[1].body).toBe(posts[0].body);expect(new Headers(posts[1].headers).get('Idempotency-Key')).toBe(new Headers(posts[0].headers).get('Idempotency-Key'))
})
test('application StrictMode permits one explicitly confirmed deletion submission',async()=>{
 const posts:RequestInit[]=[];vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){posts.push(init);return Response.json(receipt())}return lifecycleResponse(url)!}))
 render(<StrictMode><FileLifecyclePanel projectId="p" fileId="f" active onUnavailable={()=>{}}/></StrictMode>);await confirm();expect(posts).toHaveLength(1)
})
