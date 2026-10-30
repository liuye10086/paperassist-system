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
 render(<WritingLanguageReview projectId="p1" manuscriptId="m1" baseRevision={1} review={scienceReview} onPublished={onPublished}/>);expect(screen.getByRole('button',{name:'显式发布审核后版本'}).matches(':disabled')).toBe(true);fireEvent.click(screen.getByRole('button',{name:'读取真实 DOCX 全语言清单'}));await screen.findByText('清单 SHA '+languageContext.inventory_sha256);await waitFor(()=>expect(screen.getByRole('button',{name:'封存独立语言审核'}).closest('fieldset')?.disabled).toBe(false))
 expect(screen.getByRole('button',{name:'封存独立语言审核'}).matches(':disabled')).toBe(true)
 const area=screen.getAllByLabelText('清单精确文字（可选择局部范围）')[0] as HTMLTextAreaElement;area.focus();area.setSelectionRange(2,5);fireEvent.select(area)
 const item=within(area.closest('fieldset')!);fireEvent.change(item.getByLabelText('局部例外理由'),{target:{value:'Established name'}});fireEvent.click(item.getByRole('button',{name:'添加此局部例外'}))
 for(const select of screen.getAllByLabelText('此项语言决定'))fireEvent.change(select,{target:{value:'target_language'}})
 for(const reason of screen.getAllByLabelText('此项语言审核理由'))fireEvent.change(reason,{target:{value:'Each visible text reviewed'}})
 fireEvent.click(screen.getByRole('button',{name:'封存独立语言审核'}));await waitFor(()=>expect(screen.getByRole('option',{name:/language1/})).toBeTruthy());const body=JSON.parse(String(fetcher.mock.calls.find(([url,init])=>url.endsWith('/language-reviews')&&init?.method==='POST')![1]?.body));expect(body.decisions[0].exceptions).toEqual([{start:1,end:4,kind:'proper_name',reason:'Established name'}]);expect(fetcher.mock.calls.some(([u])=>u.endsWith('/publish'))).toBe(false)
 fireEvent.change(screen.getByLabelText('明确选择语言审核产物'),{target:{value:'language1'}});fireEvent.click(screen.getByLabelText('我已核对所选科学与语言产物及最终版本，明确发布为不可变新版本。'));fireEvent.click(screen.getByRole('button',{name:'显式发布审核后版本'}));await waitFor(()=>expect(onPublished).toHaveBeenCalled())
 const publish=JSON.parse(String(fetcher.mock.calls.find(([url])=>url.endsWith('/publish'))![1]?.body));expect(publish).toEqual({schema_version:2,expected_revision:1,review_id:'science1',review_sha256:scienceReview.review_sha256,language_review_id:'language1',language_review_sha256:languageArtifact.artifact_sha256})
})
it('invalidates old language decisions when whitelisted text changes and preserves server rejection',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>url.endsWith('/language-context')&&init?.method==='POST'?Response.json({error:{code:'manuscript_writing_language_invalid'}},{status:422}):Response.json(url.endsWith('/language-context')?languageContext:{items:[]})));render(<WritingLanguageReview projectId="p1" manuscriptId="m1" baseRevision={1} review={scienceReview} onPublished={vi.fn()}/>);fireEvent.click(screen.getByRole('button',{name:'读取真实 DOCX 全语言清单'}));await screen.findByText('清单 SHA '+languageContext.inventory_sha256);await waitFor(()=>expect(screen.getByLabelText('局部语言修正').matches(':disabled')).toBe(false));fireEvent.change(screen.getByLabelText('局部语言修正'),{target:{value:'Changed'}});expect(screen.queryByLabelText('此项语言决定')).toBeNull();expect(screen.getByText('材料已更改，旧清单决定和发布选择已失效。请重新预览。')).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'预览修正后的完整语言清单'}));await waitFor(()=>expect(screen.getAllByRole('alert').length).toBeGreaterThan(1));expect(screen.getByRole('button',{name:'显式发布审核后版本'}).matches(':disabled')).toBe(true)
})
function OperationHarness(){const op=useWritingOperation();return <><button disabled={op.busy} onClick={()=>void op.run('/local-test',(v):v is {ok:boolean}=>!!v&&typeof v==='object'&&'ok'in v,{exact:'body'})}>submit</button>{op.error&&<p role="alert">{op.error}</p>}</>}
it('surfaces timeouts rather than silently clearing a failed submission',async()=>{
 vi.useFakeTimers();vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(()=>{})));render(<OperationHarness/>);fireEvent.click(screen.getByRole('button'));await act(async()=>{vi.advanceTimersByTime(15001)});expect(screen.getByRole('alert').textContent).toContain('请求未确认')
})
it('blocks overlapping submits and keeps the same idempotency key after an uncertain failure',async()=>{
 let fail:(error:Error)=>void=()=>{};const fetcher=vi.fn((_url:string,_init?:RequestInit)=>new Promise<Response>((_resolve,reject)=>{fail=reject}));vi.stubGlobal('fetch',fetcher);render(<OperationHarness/>);fireEvent.click(screen.getByRole('button'));fireEvent.click(screen.getByRole('button'));expect(fetcher).toHaveBeenCalledTimes(1);await act(async()=>fail(Error('lost')));fireEvent.click(screen.getByRole('button'));expect(fetcher).toHaveBeenCalledTimes(2);expect(new Headers(fetcher.mock.calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(fetcher.mock.calls[1][1]?.headers).get('Idempotency-Key'))
})
