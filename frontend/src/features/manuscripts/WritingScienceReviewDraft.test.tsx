import {webcrypto} from 'node:crypto'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import WritingScienceReview from './WritingScienceReview'
import {ManuscriptDraftProvider} from './ManuscriptDraftProvider'
import {liveRequest,reviewContext,bundleFixture} from './writingLiveFixtures'
beforeEach(()=>{sessionStorage.clear();vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/review-context')?reviewContext:url.endsWith('/b1')?bundleFixture():{items:[]})))})
afterEach(()=>{cleanup();vi.unstubAllGlobals();sessionStorage.clear()})
const props={projectId:'p1',manuscriptId:'m1',request:liveRequest,onPublished:vi.fn()}
const first=reviewContext.required_paragraph_ids[0]
async function load(){fireEvent.click(screen.getByRole('button',{name:'读取精确科学审核上下文'}));await screen.findByText('原始 SHA: '+reviewContext.candidate_sha256)}
function decide(){
 fireEvent.change(screen.getByLabelText(`段落主张分类 ${first}`),{target:{value:'non_claim'}})
 fireEvent.change(screen.getByLabelText(`科学核对理由 ${first}`),{target:{value:'Checked in this tab'}})
 fireEvent.click(screen.getByLabelText('标题研究对象一致'))
 fireEvent.change(screen.getByLabelText('标题一致性依据'),{target:{value:'Title basis kept'}})
}
it('restores paragraph decisions, checks and consistency bases after remounting',async()=>{
 const view=render(<WritingScienceReview {...props}/>);await load();decide();view.unmount()
 render(<WritingScienceReview {...props}/>);await load()
 expect(screen.getByLabelText(`段落主张分类 ${first}`)).toHaveProperty('value','non_claim')
 expect(screen.getByLabelText(`科学核对理由 ${first}`)).toHaveProperty('value','Checked in this tab')
 expect(screen.getByLabelText('标题研究对象一致')).toHaveProperty('checked',true)
 expect(screen.getByLabelText('标题一致性依据')).toHaveProperty('value','Title basis kept')
})
it('keeps decisions for one writing request only',async()=>{
 const view=render(<WritingScienceReview {...props}/>);await load();decide();view.unmount()
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/review-context')?{...reviewContext,request_id:'w2',reviews:[]}:url.endsWith('/b1')?bundleFixture():{items:[]})))
 render(<WritingScienceReview {...props} request={{...liveRequest,id:'w2'}}/>);await load()
 expect(screen.getByLabelText(`段落主张分类 ${first}`)).toHaveProperty('value','')
 expect(screen.getByLabelText('标题一致性依据')).toHaveProperty('value','')
})
it('does not count persisted review decisions as unsaved changes',async()=>{
 const guards=new Map<unknown,()=>boolean>()
 const register=(guard:(preserve?:boolean)=>boolean,isDirty?:()=>boolean)=>{guards.set(guard,isDirty??(()=>true));return ()=>{guards.delete(guard)}}
 vi.stubGlobal('confirm',vi.fn(()=>false))
 render(<ManuscriptDraftProvider register={register}><WritingScienceReview {...props}/></ManuscriptDraftProvider>)
 await load();decide()
 expect([...guards.values()].some(isDirty=>isDirty())).toBe(false)
 expect([...guards.keys()].every(guard=>(guard as (preserve?:boolean)=>boolean)(false))).toBe(true)
 expect(window.confirm).not.toHaveBeenCalled()
})

// B03 task 7: going to add a source and coming back to the same paragraph.
const twoDiscussion={...reviewContext.candidate,sections:reviewContext.candidate.sections!.map(s=>s.id==='discussion'?{...s,paragraphs:[s.paragraphs[0],{...s.paragraphs[0],id:'discussion:2',text:'Second discussion'}]}:s)}
const returnContext={...reviewContext,candidate:twoDiscussion,reviews:[],required_paragraph_ids:[...reviewContext.required_paragraph_ids,'discussion:2'],claim_contexts:{...reviewContext.claim_contexts,'discussion:2':'writing-v2:discussion:2'}}
const returnClaim={id:'claim7',project_id:'p1',revision:1,content:'Second discussion',context:'writing-v2:discussion:2',output_language:'en',created_at:'2026-11-19T08:00:00Z',updated_at:'2026-11-19T08:00:00Z'}
const literaturePage=(items:unknown[]=[])=>({project_id:'p1',items,total:items.length,page:1,page_size:10})
function serveReturn(){
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/review-context'))return Response.json(returnContext)
  if(url.endsWith('/b1'))return Response.json(bundleFixture())
  if(url.includes('/literature/references?')||url.includes('/literature/citations/candidates?'))return Response.json(literaturePage())
  if(init?.method==='POST'&&url.endsWith('/evidence/claims'))return Response.json(returnClaim,{status:201})
  if(url.endsWith('/evidence/claims/claim7'))return Response.json(returnClaim)
  if(url.includes('/evidence/claims/claim7/'))return Response.json(literaturePage())
  return Response.json({items:[]})
 })
 vi.stubGlobal('fetch',fetcher);return fetcher
}
const customer={...props,customerSci:true}
const second='讨论 · 段落 2'
it('reads the review again on return, keeps the decisions and focuses the original paragraph',async()=>{
 serveReturn()
 const view=render(<WritingScienceReview {...customer} autoLoad/>)
 fireEvent.change(await screen.findByLabelText(`段落主张分类 ${second}`),{target:{value:'non_claim'}})
 fireEvent.change(screen.getByLabelText(`科学核对理由 ${second}`),{target:{value:'Kept across the trip'}})
 expect(screen.getByText('已核对 1 / 7 段')).toBeTruthy()
 view.unmount()
 const fetcher=serveReturn()
 render(<WritingScienceReview {...customer} initialParagraph="discussion:2"/>)
 await waitFor(()=>expect(document.activeElement?.id).toBe('writing-paragraph-discussion:2'))
 expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/review-context'))).toBe(true)
 expect(screen.getByLabelText(`段落主张分类 ${second}`)).toHaveProperty('value','non_claim')
 expect(screen.getByLabelText(`科学核对理由 ${second}`)).toHaveProperty('value','Kept across the trip')
 expect(screen.queryByText('原位置已不可用，已回到逐段核对。')).toBeNull()
})
it('says the original place is gone when the paragraph is no longer reviewed',async()=>{
 serveReturn()
 render(<WritingScienceReview {...customer} initialParagraph="discussion:9"/>)
 expect(await screen.findByText('原位置已不可用，已回到逐段核对。')).toBeTruthy()
})
it('sends a literature claim without excerpts to add literature and restores its claim on return',async()=>{
 serveReturn()
 const onNeedSource=vi.fn()
 const view=render(<WritingScienceReview {...customer} autoLoad onNeedSource={onNeedSource}/>)
 fireEvent.change(await screen.findByLabelText(`段落主张分类 ${second}`),{target:{value:'literature_claim'}})
 fireEvent.change(screen.getByLabelText(`科学核对理由 ${second}`),{target:{value:'Needs a source'}})
 fireEvent.click(screen.getByRole('button',{name:'为此精确文本创建新主张'}))
 await waitFor(()=>expect((screen.getByRole('button',{name:'为此精确文本创建新主张'}) as HTMLButtonElement).disabled).toBe(true))
 fireEvent.click(await screen.findByRole('button',{name:'去添加文献（完成后回到本段）'}))
 expect(onNeedSource).toHaveBeenCalledWith('literature','discussion:2',{section:'讨论',paragraph:2})
 view.unmount()
 const fetcher=serveReturn()
 render(<WritingScienceReview {...customer} initialParagraph="discussion:2" onNeedSource={onNeedSource}/>)
 await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/evidence/claims/claim7'))).toBe(true))
 expect(screen.getByLabelText(`段落主张分类 ${second}`)).toHaveProperty('value','literature_claim')
 expect(screen.getByLabelText(`科学核对理由 ${second}`)).toHaveProperty('value','Needs a source')
 await waitFor(()=>expect((screen.getByRole('button',{name:'为此精确文本创建新主张'}) as HTMLButtonElement).disabled).toBe(true))
})
