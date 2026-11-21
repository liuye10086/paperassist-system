import {StrictMode} from 'react'
import {STANDARD_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import {webcrypto} from 'node:crypto'
import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import WritingScienceReview from './WritingScienceReview'
import WritingLanguageReview from './WritingLanguageReview'
import {liveRequest,reviewContext,scienceReview,languageContext,languageArtifact,bundleFixture,hash} from './writingLiveFixtures'
import {bodyProjection,canonicalJson} from './writingLiveTypes'
import {manuscriptFixture} from './manuscriptFixtures'
import {useWritingOperation} from './useWritingOperation'
beforeEach(()=>vi.stubGlobal('crypto',webcrypto))
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals()})
const props={projectId:'p1',manuscriptId:'m1',request:liveRequest,onPublished:vi.fn()}
it('requires every scientific classification and explicit title abstract checks, binds corrected canonical text, then asks for artifact selection',async()=>{
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>Response.json(url.endsWith('/review-context')?reviewContext:url.endsWith('/b1')?bundleFixture():init?.method==='POST'?scienceReview:{items:[]}));vi.stubGlobal('fetch',fetcher)
 render(<WritingScienceReview {...props}/>);fireEvent.click(screen.getByRole('button',{name:'读取精确科学审核上下文'}));await screen.findByText('原始 SHA: '+reviewContext.candidate_sha256)
 expect(screen.getByRole('button',{name:'封存本次科学审核'}).matches(':disabled')).toBe(true)
 await waitFor(()=>expect(screen.getByLabelText('精确审后文本 title:1').matches(':disabled')).toBe(false))
 for(const id of reviewContext.required_paragraph_ids){fireEvent.change(screen.getByLabelText(`段落主张分类 ${id}`),{target:{value:'non_claim'}});fireEvent.change(screen.getByLabelText(`科学核对理由 ${id}`),{target:{value:'Checked against frozen source'}})}
 fireEvent.change(screen.getByLabelText('精确审后文本 title:1'),{target:{value:'Corrected title'}})
 expect(within(screen.getByRole('region',{name:'题摘一致性核对用审后正文'})).getByRole('heading',{level:3}).textContent).toBe('Corrected title')
 expect(within(screen.getByRole('region',{name:'原始模型候选（只读）'})).getByRole('heading',{level:3}).textContent).toBe(reviewContext.candidate.title)
 expect(reviewContext.candidate.sections![0].paragraphs[0].text).toBe('Original title')
 for(const name of ['标题研究对象一致','标题方向一致','标题强度一致','摘要目的一致','摘要方法一致','摘要关键结果一致','摘要结论一致'])fireEvent.click(screen.getByLabelText(name))
 fireEvent.change(screen.getByLabelText('标题一致性依据'),{target:{value:'Title checked'}});fireEvent.change(screen.getByLabelText('摘要一致性依据'),{target:{value:'Abstract checked'}})
 fireEvent.click(screen.getByRole('button',{name:'封存本次科学审核'}));await waitFor(()=>expect(fetcher.mock.calls.some(([url,init])=>url.endsWith('/reviews')&&init?.method==='POST')).toBe(true))
 const post=fetcher.mock.calls.find(([url,init])=>url.endsWith('/reviews')&&init?.method==='POST')!;const body=JSON.parse(String(post[1]?.body));expect(body.paragraphs[0].text_sha256).toBe(hash('"Corrected title"'));expect(body.consistency.body_sha256).toBe(hash(canonicalJson(bodyProjection(reviewContext.candidate,{'title:1':'Corrected title'}))))
 expect((screen.getByLabelText('明确选择科学审核产物') as HTMLSelectElement).value).toBe('');expect(fetcher.mock.calls.some(([url])=>url.endsWith('/publish'))).toBe(false)
})
it('clears title abstract approvals when paragraph text or classification changes',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/review-context')?reviewContext:bundleFixture())));render(<WritingScienceReview {...props}/>);fireEvent.click(screen.getByRole('button',{name:'读取精确科学审核上下文'}));await screen.findByLabelText('标题研究对象一致');await waitFor(()=>expect(screen.getByLabelText('标题研究对象一致').matches(':disabled')).toBe(false));fireEvent.click(screen.getByLabelText('标题研究对象一致'));fireEvent.change(screen.getByLabelText('精确审后文本 title:1'),{target:{value:'New exact claim'}});expect((screen.getByLabelText('标题研究对象一致') as HTMLInputElement).checked).toBe(false)
})
it('requires each language item and sends Unicode codepoint exceptions; publishes only the explicitly selected two artifacts',async()=>{
 const published={...manuscriptFixture,current_revision:2};const onPublished=vi.fn();const fetcher=vi.fn(async(url:string,init?:RequestInit)=>Response.json(url.endsWith('/publish')?published:url.endsWith('/language-reviews')&&init?.method==='POST'?languageArtifact:url.endsWith('/language-context')?languageContext:{items:[]}));vi.stubGlobal('fetch',fetcher)
 render(<WritingLanguageReview projectId="p1" manuscriptId="m1" baseRevision={1} review={scienceReview} onPublished={onPublished}/>);expect(document.body.textContent).not.toContain(scienceReview.review_sha256);expect(screen.getByRole('button',{name:'显式发布审核后版本'}).matches(':disabled')).toBe(true);fireEvent.click(screen.getByRole('button',{name:'读取真实 DOCX 全语言清单'}));await screen.findByText('已读取当前固定版本的语言核对清单');await waitFor(()=>expect(screen.getByRole('button',{name:'封存独立语言审核'}).closest('fieldset')?.disabled).toBe(false))
 expect(screen.getByRole('button',{name:'封存独立语言审核'}).matches(':disabled')).toBe(true)
 const area=screen.getAllByLabelText('清单精确文字（可选择局部范围）')[0] as HTMLTextAreaElement;area.focus();area.setSelectionRange(2,5);fireEvent.select(area)
 const item=within(area.closest('fieldset')!);fireEvent.change(item.getByLabelText('局部例外理由'),{target:{value:'Established name'}});fireEvent.click(item.getByRole('button',{name:'添加此局部例外'}))
 for(const select of screen.getAllByLabelText('此项语言决定'))fireEvent.change(select,{target:{value:'target_language'}})
 for(const reason of screen.getAllByLabelText('此项语言审核理由'))fireEvent.change(reason,{target:{value:'Each visible text reviewed'}})
 fireEvent.click(screen.getByRole('button',{name:'封存独立语言审核'}));await waitFor(()=>expect(screen.getByRole('option',{name:/语言审核产物 1/})).toBeTruthy());expect(document.body.textContent).not.toContain(languageArtifact.artifact_sha256);const body=JSON.parse(String(fetcher.mock.calls.find(([url,init])=>url.endsWith('/language-reviews')&&init?.method==='POST')![1]?.body));expect(body.decisions[0].exceptions).toEqual([{start:1,end:4,kind:'proper_name',reason:'Established name'}]);expect(fetcher.mock.calls.some(([u])=>u.endsWith('/publish'))).toBe(false)
 fireEvent.change(screen.getByLabelText('明确选择语言审核产物'),{target:{value:'language1'}});fireEvent.click(screen.getByLabelText('我已核对所选科学与语言产物及最终版本，明确发布为不可变新版本。'));fireEvent.click(screen.getByRole('button',{name:'显式发布审核后版本'}));await waitFor(()=>expect(onPublished).toHaveBeenCalled())
 const publish=JSON.parse(String(fetcher.mock.calls.find(([url])=>url.endsWith('/publish'))![1]?.body));expect(publish).toEqual({schema_version:2,expected_revision:1,review_id:'science1',review_sha256:scienceReview.review_sha256,language_review_id:'language1',language_review_sha256:languageArtifact.artifact_sha256})
})
it('invalidates old language decisions when whitelisted text changes and preserves server rejection',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>url.endsWith('/language-context')&&init?.method==='POST'?Response.json({error:{code:'manuscript_writing_language_invalid'}},{status:422}):Response.json(url.endsWith('/language-context')?languageContext:{items:[]})));render(<WritingLanguageReview projectId="p1" manuscriptId="m1" baseRevision={1} review={scienceReview} onPublished={vi.fn()}/>);fireEvent.click(screen.getByRole('button',{name:'读取真实 DOCX 全语言清单'}));await screen.findByText('已读取当前固定版本的语言核对清单');await waitFor(()=>expect(screen.getByLabelText('局部语言修正').matches(':disabled')).toBe(false));fireEvent.change(screen.getByLabelText('局部语言修正'),{target:{value:'Changed'}});expect(screen.queryByLabelText('此项语言决定')).toBeNull();expect(screen.getByText('材料已更改，旧清单决定和发布选择已失效。请重新预览。')).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'预览修正后的完整语言清单'}));await waitFor(()=>expect(screen.getAllByRole('alert').length).toBeGreaterThan(1));expect(screen.getByRole('button',{name:'显式发布审核后版本'}).matches(':disabled')).toBe(true)
})
it('labels the SCI customer language inventory as Word export text', async () => {
 const inventory = [{ ...languageContext.inventory[0], kind: 'export_text' }]
 vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(
  url.endsWith('/language-context') ? { ...languageContext, inventory } : { items: [] },
 )))
 render(<StrictMode><WritingLanguageReview projectId="p1" manuscriptId="m1" baseRevision={1}
  review={scienceReview} onPublished={vi.fn()} customerSci /></StrictMode>)
 fireEvent.click(screen.getByRole('button', { name: '开始语言核对' }))
 expect(await screen.findByRole('group', { name: '核对项目 1 · Word 导出文字' })).toBeTruthy()
})
it('selects an already sealed language review on a fresh mount and publishes those exact artifacts',async()=>{
 const onPublished=vi.fn()
 const candidate={...scienceReview.candidate,paper_plan:{kind:'research' as const,title:scienceReview.candidate.title,keywords:[],sections:[],materials:[]}}
 const plannedReview={...scienceReview,candidate}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/reviews/science1/language-reviews'))return Response.json({items:[{id:languageArtifact.id,created_at:'2026-11-18T02:30:00Z'}]})
  if(url.endsWith('/language-reviews/language1'))return Response.json({...languageArtifact,candidate})
  if(url.endsWith('/publish')&&init?.method==='POST')return Response.json({...manuscriptFixture,current_revision:2})
  throw Error(url)
 })
 vi.stubGlobal('fetch',fetcher)
 render(<StrictMode><WritingLanguageReview projectId="p1" manuscriptId="m1" baseRevision={1} review={plannedReview} onPublished={onPublished} customerSci/></StrictMode>)
 // A returning customer continues from the latest sealed language review without choosing it again.
 await screen.findByRole('region',{name:'待显式发布的最终版本'})
 expect(screen.queryByText('高级设置：按编号回读历史语言产物')).toBeNull()
 expect(screen.queryByLabelText('明确选择语言审核产物')).toBeNull()
 const adopt=screen.getByRole('button',{name:'采用这份稿件'})
 await waitFor(()=>expect(adopt.matches(':disabled')).toBe(false))
 fireEvent.click(adopt)
 await waitFor(()=>expect(onPublished).toHaveBeenCalledOnce())
 expect(JSON.parse(String(fetcher.mock.calls.find(([,init])=>init?.method==='POST')![1]?.body))).toMatchObject({
  review_id:scienceReview.id,review_sha256:scienceReview.review_sha256,language_review_id:languageArtifact.id,
  language_review_sha256:languageArtifact.artifact_sha256,expected_revision:1,
 })
})
function OperationHarness(){const op=useWritingOperation();return <><button disabled={op.busy} onClick={()=>void op.run('/local-test',(v):v is {ok:boolean}=>!!v&&typeof v==='object'&&'ok'in v,{exact:'body'})}>submit</button>{op.error&&<p role="alert">{op.error}</p>}</>}
function ScopedOperationHarness(){
 const op=useWritingOperation({projectId:'p1',manuscriptId:'m1',versionId:'v1',operation:'rejection-test'})
 return <><button disabled={op.busy} onClick={()=>void op.run('/local-test',(v):v is {ok:boolean}=>!!v&&typeof v==='object'&&'ok'in v,{exact:'body'})}>submit</button>
  {op.pending?.phase==='unknown'&&<p>pending replay</p>}{op.error&&<p role="alert">{op.error}</p>}</>
}
it('clears a pending writing request after a definitive closed-authorization response',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({detail:{code:'manuscript_writing_authorization_closed'}},{status:409})))
 render(<ScopedOperationHarness/>);fireEvent.click(screen.getByRole('button',{name:'submit'}))
 await screen.findByRole('alert')
 expect(screen.queryByText('pending replay')).toBeNull()
 cleanup()
 render(<ScopedOperationHarness/>)
 expect(screen.queryByText('pending replay')).toBeNull()
})
it('surfaces timeouts rather than silently clearing a failed submission',async()=>{
 vi.useFakeTimers();vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(()=>{})));render(<OperationHarness/>);fireEvent.click(screen.getByRole('button'));await act(async()=>{vi.advanceTimersByTime(STANDARD_REQUEST_TIMEOUT_MS+1)});expect(screen.getByRole('alert').textContent).toContain('请求未确认')
})
it('blocks overlapping submits and keeps the same idempotency key after an uncertain failure',async()=>{
 let fail:(error:Error)=>void=()=>{};const fetcher=vi.fn((_url:string,_init?:RequestInit)=>new Promise<Response>((_resolve,reject)=>{fail=reject}));vi.stubGlobal('fetch',fetcher);render(<OperationHarness/>);fireEvent.click(screen.getByRole('button'));fireEvent.click(screen.getByRole('button'));expect(fetcher).toHaveBeenCalledTimes(1);await act(async()=>fail(Error('lost')));fireEvent.click(screen.getByRole('button'));expect(fetcher).toHaveBeenCalledTimes(2);expect(new Headers(fetcher.mock.calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(fetcher.mock.calls[1][1]?.headers).get('Idempotency-Key'))
})
it('blocks new language confirmation for an empty image absent from the fixed candidate figures',async()=>{
 const context={...languageContext,inventory:[{location:'en:image:missing-fixed-image',kind:'image',text:'',content_sha256:'c'.repeat(64),language_known:true,no_text:true}]};const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/language-context')?context:{items:[]}));vi.stubGlobal('fetch',fetcher)
 render(<WritingLanguageReview projectId="p1" manuscriptId="m1" baseRevision={1} review={scienceReview} onPublished={vi.fn()}/>);fireEvent.click(screen.getByRole('button',{name:'读取真实 DOCX 全语言清单'}));await screen.findByText('已读取当前固定版本的语言核对清单')
 const decision=screen.getByLabelText('此项语言决定');expect((decision.closest('fieldset') as HTMLFieldSetElement).disabled).toBe(true);fireEvent.change(decision,{target:{value:'no_text'}});fireEvent.change(screen.getByLabelText('此项语言审核理由'),{target:{value:'Cannot identify this exact image'}});expect((screen.getByRole('button',{name:'封存独立语言审核'}) as HTMLButtonElement).disabled).toBe(true);expect(screen.getByText('本次清单中的第 1 个图像项目（不是图号）')).toBeTruthy();expect(fetcher.mock.calls.some(([url,init])=>url.endsWith('/language-reviews')&&init?.method==='POST')).toBe(false)
})

// B03 task 6: customers go from the sealed science review straight into the language review and adopt with one click.
async function fillCustomerScience(){
 await waitFor(()=>expect(screen.getAllByLabelText(/^段落主张分类/)[0].matches(':disabled')).toBe(false))
 for(const select of screen.getAllByLabelText(/^段落主张分类/))fireEvent.change(select,{target:{value:'non_claim'}})
 for(const basis of screen.getAllByLabelText(/^科学核对理由/))fireEvent.change(basis,{target:{value:'Checked against frozen source'}})
 for(const name of ['标题研究对象一致','标题方向一致','标题强度一致','摘要目的一致','摘要方法一致','摘要关键结果一致','摘要结论一致'])fireEvent.click(screen.getByLabelText(name))
 fireEvent.change(screen.getByLabelText('标题一致性依据'),{target:{value:'Title checked'}});fireEvent.change(screen.getByLabelText('摘要一致性依据'),{target:{value:'Abstract checked'}})
}
function customerScienceFetch(sealed:{done:boolean}){
 return vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/review-context'))return Response.json({...reviewContext,reviews:sealed.done?[{...scienceReview,created_at:'2026-11-19T08:30:00Z'}]:[]})
  if(url.endsWith('/writing-previews/b1'))return Response.json(bundleFixture())
  if(url.endsWith('/reviews')&&init?.method==='POST'){sealed.done=true;return Response.json({...scienceReview,created_at:'2026-11-19T08:30:00Z'})}
  return Response.json({items:[]})
 })
}
it('opens the language review by itself after a customer seals the science review, and drops it after any edit',async()=>{
 sessionStorage.clear()
 const sealed={done:false};vi.stubGlobal('fetch',customerScienceFetch(sealed))
 render(<WritingScienceReview {...props} customerSci autoLoad/>)
 await fillCustomerScience()
 expect(screen.queryByLabelText('明确选择科学审核产物')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'完成科学核对'}))
 expect((await screen.findByText('科学核对已完成，已进入语言核对。')).closest('[role="status"]')).toBeTruthy()
 const language=await screen.findByRole('region',{name:'语言核对'})
 await waitFor(()=>expect(document.activeElement).toBe(within(language).getByRole('heading',{name:'语言核对'})))
 expect(screen.queryByLabelText('明确选择科学审核产物')).toBeNull()
 expect(screen.getByText(/^科学核对 · /)).toBeTruthy()
 expect(document.body.textContent).not.toContain('science1')
 fireEvent.change(screen.getAllByLabelText(/^科学核对理由/)[0],{target:{value:'Changed after sealing'}})
 expect(screen.queryByRole('region',{name:'语言核对'})).toBeNull()
 expect(screen.queryByText('科学核对已完成，已进入语言核对。')).toBeNull()
})
it('returns a customer to the language review of the record sealed from the same draft',async()=>{
 sessionStorage.clear()
 const sealed={done:false};vi.stubGlobal('fetch',customerScienceFetch(sealed))
 const first=render(<WritingScienceReview {...props} customerSci autoLoad/>)
 await fillCustomerScience();fireEvent.click(screen.getByRole('button',{name:'完成科学核对'}))
 await screen.findByRole('region',{name:'语言核对'});first.unmount()
 render(<WritingScienceReview {...props} customerSci autoLoad/>)
 expect(await screen.findByRole('region',{name:'语言核对'})).toBeTruthy()
})
it('keeps the explicit science review choice for internal roles',async()=>{
 sessionStorage.clear()
 const sealed={done:false};vi.stubGlobal('fetch',customerScienceFetch(sealed))
 render(<WritingScienceReview {...props}/>);fireEvent.click(screen.getByRole('button',{name:'读取精确科学审核上下文'}))
 await screen.findByText('原始 SHA: '+reviewContext.candidate_sha256)
 await waitFor(()=>expect(screen.getByLabelText('标题研究对象一致').matches(':disabled')).toBe(false))
 for(const id of reviewContext.required_paragraph_ids){fireEvent.change(screen.getByLabelText(`段落主张分类 ${id}`),{target:{value:'non_claim'}});fireEvent.change(screen.getByLabelText(`科学核对理由 ${id}`),{target:{value:'Checked'}})}
 for(const name of ['标题研究对象一致','标题方向一致','标题强度一致','摘要目的一致','摘要方法一致','摘要关键结果一致','摘要结论一致'])fireEvent.click(screen.getByLabelText(name))
 fireEvent.change(screen.getByLabelText('标题一致性依据'),{target:{value:'T'}});fireEvent.change(screen.getByLabelText('摘要一致性依据'),{target:{value:'A'}})
 fireEvent.click(screen.getByRole('button',{name:'封存本次科学审核'}))
 await waitFor(()=>expect(screen.getByRole('option',{name:/science1/})).toBeTruthy())
 expect((screen.getByLabelText('明确选择科学审核产物') as HTMLSelectElement).value).toBe('')
 expect(screen.queryByText('科学核对已完成，已进入语言核对。')).toBeNull()
 expect(screen.queryByRole('region',{name:'独立语言审核与发布'})).toBeNull()
})
it('lets a customer adopt the sealed language review with one click and no selection or checkbox',async()=>{
 const published={...manuscriptFixture,current_revision:2};const onPublished=vi.fn()
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/publish'))return Response.json(published)
  if(url.endsWith('/language-reviews')&&init?.method==='POST')return Response.json(languageArtifact)
  if(url.endsWith('/language-context'))return Response.json(languageContext)
  return Response.json({items:[]})
 });vi.stubGlobal('fetch',fetcher)
 render(<WritingLanguageReview projectId="p1" manuscriptId="m1" baseRevision={1} baseSavedAt="2026-11-19T07:40:00Z" scienceParagraphs={7} review={scienceReview} onPublished={onPublished} customerSci/>)
 fireEvent.click(screen.getByRole('button',{name:'开始语言核对'}));await screen.findByText('本版稿件的语言核对清单')
 expect(screen.getByText('核对图表文字')).toBeTruthy()
 expect(screen.getByRole('button',{name:'预览修改后的清单'})).toBeTruthy()
 await waitFor(()=>expect(screen.getByRole('button',{name:'完成语言核对'}).closest('fieldset')?.disabled).toBe(false))
 for(const select of screen.getAllByLabelText('此项语言决定'))fireEvent.change(select,{target:{value:'target_language'}})
 for(const reason of screen.getAllByLabelText('此项语言审核理由'))fireEvent.change(reason,{target:{value:'Reviewed'}})
 fireEvent.click(screen.getByRole('button',{name:'完成语言核对'}))
 const adopt=await screen.findByRole('button',{name:'采用这份稿件'})
 await waitFor(()=>expect(adopt.matches(':disabled')).toBe(false))
 const summary=screen.getByRole('region',{name:'完成稿件复核'})
 expect(summary.textContent).toContain('科学核对 7/7 段');expect(summary.textContent).toContain('语言核对 2/2 项')
 expect(summary.textContent).toContain('采用后保存为第 2 版，用于生成 Word。');expect(summary.textContent).toMatch(/第 1 版 · /)
 expect(screen.queryByLabelText('明确选择语言审核产物')).toBeNull()
 expect(screen.queryByLabelText('我已核对所选科学与语言产物及最终版本，明确发布为不可变新版本。')).toBeNull()
 expect(screen.queryByText('高级设置：按编号回读历史语言产物')).toBeNull()
 fireEvent.click(adopt);fireEvent.click(adopt)
 await waitFor(()=>expect(onPublished).toHaveBeenCalledOnce())
 const publishes=fetcher.mock.calls.filter(([url])=>url.endsWith('/publish'));expect(publishes).toHaveLength(1)
 expect(JSON.parse(String(publishes[0][1]?.body))).toMatchObject({language_review_id:'language1',language_review_sha256:languageArtifact.artifact_sha256,review_id:'science1',expected_revision:1})
 expect(onPublished.mock.calls[0][0].current_revision).toBe(2)
})


it('recovers the customer science review read after StrictMode cleanup without replaying writes', async () => {
 const reads: {signal:AbortSignal;resolve:(value:Response)=>void}[]=[]
 const fetcher=vi.fn((url:string,init?:RequestInit)=>{
  if(url.endsWith('/review-context'))return new Promise<Response>(resolve=>reads.push({resolve,signal:init!.signal as AbortSignal}))
  return Promise.resolve(Response.json(url.endsWith('/b1')?bundleFixture():{items:[]}))
 })
 vi.stubGlobal('fetch',fetcher)
 const view=render(<StrictMode><WritingScienceReview {...props} customerSci autoLoad/></StrictMode>)
 await waitFor(()=>expect(reads).toHaveLength(2))
 expect(reads[0].signal.aborted).toBe(true)
 expect(reads[1].signal.aborted).toBe(false)
 const start=screen.getByRole('button',{name:'开始逐段核对'})
 expect(start.matches(':disabled')).toBe(true)
 expect(screen.getByText('正在读取逐段核对资料……')).toBeTruthy()
 view.rerender(<StrictMode><WritingScienceReview {...props} request={{...liveRequest,candidate:{...liveRequest.candidate!}}} customerSci autoLoad/></StrictMode>)
 expect(reads).toHaveLength(2)
 await act(async()=>reads[1].resolve(Response.json(reviewContext)))
 await waitFor(()=>expect(start.matches(':disabled')).toBe(false))
 expect(screen.queryByText('正在读取逐段核对资料……')).toBeNull()
 const check=screen.getByLabelText<HTMLInputElement>('标题研究对象一致')
 const changedValue=!check.checked
 fireEvent.click(check)
 expect(check.checked).toBe(changedValue)
 await act(async()=>reads[0].resolve(Response.json({detail:{code:'internal_error'}},{status:500})))
 expect(check.checked).toBe(changedValue)
 expect(start.matches(':disabled')).toBe(false)
 expect(screen.queryByRole('alert')).toBeNull()
 expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
})


it('unlocks a failed science review read and retries that read when the customer asks', async () => {
 let reads=0
 const fetcher=vi.fn(async (url:string,_init?:RequestInit)=>{
  if(url.endsWith('/review-context')){
   reads+=1
   return reads<=2?Response.json({detail:{code:'internal_error'}},{status:500}):Response.json(reviewContext)
  }
  return Response.json(url.endsWith('/b1')?bundleFixture():{items:[]})
 })
 vi.stubGlobal('fetch',fetcher)
 render(<StrictMode><WritingScienceReview {...props} customerSci autoLoad/></StrictMode>)
 await screen.findByRole('alert')
 const start=screen.getByRole('button',{name:'开始逐段核对'})
 expect(start.matches(':disabled')).toBe(false)
 expect(reads).toBe(2)
 fireEvent.click(start)
 await screen.findByLabelText('标题研究对象一致')
 expect(reads).toBe(3)
 expect(fetcher.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false)
})
