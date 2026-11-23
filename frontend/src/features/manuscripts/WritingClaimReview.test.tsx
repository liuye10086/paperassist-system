// B03 task 7: a literature claim without any selectable source sends the customer to add literature and back.
import {webcrypto} from 'node:crypto'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import WritingClaimReview from './WritingClaimReview'
import type {LocalManifest} from './writingLiveTypes'
import type {ProjectEvidenceOption} from './writingEvidenceOptions'
beforeEach(()=>vi.stubGlobal('crypto',webcrypto))
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const stamp='2026-11-19T08:00:00Z',base='/api/v1/projects/p1/literature/evidence'
const claim={id:'claim7',project_id:'p1',revision:1,content:'Clones stay stable.',context:'writing-v2:discussion',output_language:'en',created_at:stamp,updated_at:stamp}
const empty={sources:{},evidence:{}} as LocalManifest
const added:ProjectEvidenceOption={project_reference_id:'ref1',title:'Synthetic lineage study',search_id:'search1',metadata_version_id:'meta1',texts:['Lineage tracing shows stable clones over time.']}
const evidence={id:'ev1',claim_id:'claim7',claim_revision:1,project_reference_id:'ref1',quote:'stable clones',reading_scope:'abstract',source:{kind:'abstract',search_id:'search1',receipt_id:'receipt1',sha256:'1'.repeat(64)},location:{abstract_index:0,start:22,end:35},created_at:stamp}
const page=(items:unknown[])=>({project_id:'p1',items,total:items.length,page:1,page_size:10})
const props={projectId:'p1',text:claim.content,context:claim.context,language:'en' as const,onBinding:vi.fn(),paragraphName:'讨论 · 段落 2'}

it('shows the excerpt identified for this paragraph and lets the reviewer reuse its exact text', () => {
 const fetcher=vi.fn()
 vi.stubGlobal('fetch',fetcher)
 const onBinding=vi.fn()
 const record={evidence_id:'ev1',binding:{project_reference_id:'ref1',metadata_version_id:'meta1',metadata:{title:'Selected study'},evidence:[evidence]}}
 const manifest={sources:{},evidence:{e1:record,e2:{...record,binding:{...record.binding,metadata:{title:'Other study'}}}}} as unknown as LocalManifest
 render(<WritingClaimReview {...props} manifest={manifest} customerView suggestedEvidenceAliases={['e1']} onBinding={onBinding}/>)
 const sources=screen.getByRole('region',{name:'初稿为本段标出的文献'})
 expect(sources.textContent).toContain('Selected study')
 expect(sources.textContent).toContain('摘要')
 expect(sources.textContent).toContain(evidence.quote)
 expect(sources.textContent).not.toContain('Other study')
 fireEvent.click(screen.getByRole('button',{name:'用这段原文核对'}))
 expect(screen.getByLabelText('选择实际公开证据与书目')).toHaveProperty('value','e1')
 expect(screen.getByLabelText('新主张精确摘录')).toHaveProperty('value',evidence.quote)
 expect(screen.getByLabelText('本次支持决定')).toHaveProperty('value','needs_review')
 expect(onBinding).toHaveBeenCalledWith(null,[])
 expect(fetcher).not.toHaveBeenCalled()
})

it('asks a customer to add literature when no excerpt can be chosen',()=>{
 vi.stubGlobal('fetch',vi.fn())
 const onNeedEvidence=vi.fn()
 render(<WritingClaimReview {...props} manifest={empty} projectOptions={[]} onNeedEvidence={onNeedEvidence}/>)
 expect(screen.getByText('讨论 · 段落 2还缺一条文献依据。请选择支持这句话的原文。已加入的文献里没有可选原文。')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'去添加文献（完成后回到本段）'}))
 expect(onNeedEvidence).toHaveBeenCalledTimes(1)
})

it('does not ask to add literature while project literature is still being read',()=>{
 vi.stubGlobal('fetch',vi.fn())
 render(<WritingClaimReview {...props} manifest={empty} projectOptions={null} onNeedEvidence={vi.fn()}/>)
 expect(screen.queryByRole('button',{name:'去添加文献（完成后回到本段）'})).toBeNull()
})

it('restores the pending claim after returning and attaches an abstract excerpt of the added literature',async()=>{
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST'&&url===`${base}/claims/claim7/evidence`)return Response.json(evidence,{status:201})
  if(url===`${base}/claims/claim7`)return Response.json(claim)
  if(url.startsWith(`${base}/claims/claim7/evidence?`)||url.startsWith(`${base}/claims/claim7/reviews?`))return Response.json(page([]))
  return new Response(null,{status:404})
 })
 vi.stubGlobal('fetch',fetcher)
 const onClaimCreated=vi.fn()
 render(<WritingClaimReview {...props} manifest={empty} projectOptions={[added]} pendingClaim="claim7" returned onNeedEvidence={vi.fn()} onClaimCreated={onClaimCreated}/>)
 expect(screen.getByText('已加入 1 篇文献。请选择支持这句话的原文。')).toBeTruthy()
 await waitFor(()=>expect((screen.getByRole('button',{name:'为此精确文本创建新主张'}) as HTMLButtonElement).disabled).toBe(true))
 expect(fetcher.mock.calls.some(([url])=>url===`${base}/claims/claim7`)).toBe(true)
 expect(screen.queryByRole('button',{name:'去添加文献（完成后回到本段）'})).toBeNull()
 const select=screen.getByLabelText('选择实际公开证据与书目') as HTMLSelectElement
 const option=[...select.options].find(o=>o.textContent==='Synthetic lineage study · 摘要')!
 expect(option).toBeTruthy()
 fireEvent.change(select,{target:{value:option.value}})
 await waitFor(()=>expect((screen.getByLabelText('新主张精确摘录') as HTMLTextAreaElement).disabled).toBe(false))
 fireEvent.change(screen.getByLabelText('新主张精确摘录'),{target:{value:'stable clones'}})
 fireEvent.click(screen.getByRole('button',{name:'保存新主张证据'}))
 await screen.findByRole('checkbox',{name:'stable clones'})
 const post=fetcher.mock.calls.find(([url,init])=>init?.method==='POST'&&url===`${base}/claims/claim7/evidence`)!
 expect(JSON.parse(String(post[1]!.body))).toEqual({claim_revision:1,project_reference_id:'ref1',source_kind:'abstract',search_id:'search1',quote:'stable clones'})
 expect(onClaimCreated).not.toHaveBeenCalled()
})

it('reports a newly created claim so it can be restored later',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(claim,{status:201})))
 const onClaimCreated=vi.fn()
 render(<WritingClaimReview {...props} manifest={empty} projectOptions={[added]} onClaimCreated={onClaimCreated}/>)
 fireEvent.click(screen.getByRole('button',{name:'为此精确文本创建新主张'}))
 await waitFor(()=>expect(onClaimCreated).toHaveBeenCalledWith(expect.objectContaining({id:'claim7'})))
})

it('lists a frozen excerpt before project literature of the same reference',()=>{
 vi.stubGlobal('fetch',vi.fn())
 const frozen={sources:{},evidence:{e1:{evidence_id:'old',binding:{project_reference_id:'ref1',metadata_version_id:'meta1',metadata:{title:'Synthetic lineage study'},evidence:[{...evidence,id:'old',claim_id:'old-claim',reading_scope:'abstract'}]}}}} as unknown as LocalManifest
 render(<WritingClaimReview {...props} manifest={frozen} projectOptions={[added,{...added,project_reference_id:'ref2',title:'Second study'}]}/>)
 const labels=[...(screen.getByLabelText('选择实际公开证据与书目') as HTMLSelectElement).options].map(o=>o.textContent)
 expect(labels.filter(label=>label?.includes('Synthetic lineage study'))).toHaveLength(1)
 expect(labels).toContain('Second study · 摘要')
})
