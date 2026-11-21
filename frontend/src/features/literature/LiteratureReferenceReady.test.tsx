// B03 task 7: a reference added for a paragraph counts as done only once it is shortlisted and its bibliography is usable.
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ProjectLiterature from './ProjectLiterature'

const stamp='2026-11-19T02:30:00Z'
const base='/api/v1/projects/p1/literature'
const page=(items:unknown[])=>({project_id:'p1',items,total:items.length,page:1,page_size:10})
const source={search_id:'search1',receipt_id:'receipt1',query:'lineage',effective_query:'lineage',retrieved_at:stamp,source_kind:'ncbi_eutilities',cached:false,ordinal:1,source_download_url:`${base}/receipts/receipt1/source`}
const reference={id:'ref1',reference_id:'book1',project_id:'p1',pmid:'38123456',record:{pmid:'38123456',title:'Synthetic lineage study',authors:[],year:2024,journal:'Clinical Journal',doi:null,abstract:[{label:null,text:'Stable clones.'}],abstract_status:'available',full_text_status:'not_acquired',verification_status:'not_verified',doi_resolution_status:'not_checked',keywords:[],mesh_terms:[],full_text_links:[]},selection:{status:'candidate',note:'',revision:1},source,created_at:stamp,updated_at:stamp}
const metadata={article_type:'journal',authors:[{family:'Chen',given:'',initials:'L',collective:''}],title:'Synthetic lineage study',journal_title:'Clinical Journal',journal_abbreviation:'Clin J',year:'2024',date:'2024',volume:'2',issue:'',pages:'1-3',article_number:'',doi:'',pmid:'38123456'}
const meta={id:'meta1',project_reference_id:'ref1',revision:1,mode:'extract',metadata,source:{search_id:'search1',receipt_id:'receipt1',source_kind:'ncbi_eutilities',source_download_url:`${base}/receipts/receipt1/source`,pmid:'38123456',sha256:'1'.repeat(64),record_sha256:'2'.repeat(64)},source_description:'PubMed',basis:'checked',source_verified:true,source_current:true,usable:true,gaps:[],created_at:stamp}
const candidate=(usable:boolean)=>({id:'ref1',pmid:'38123456',record:{title:'Synthetic lineage study'},selection:{status:'shortlisted',note:'',revision:2},source,metadata:usable?meta:null,materials:[],has_abstract:true,holds_full_paper:false,claims:[],todos:usable?[]:['extract_metadata']})

function serve(state:{usable:boolean}){
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='PATCH')return Response.json({...reference,selection:{status:'shortlisted',note:'',revision:2}})
  if(url.endsWith('/citations/config'))return Response.json({project_id:'p1',format:'nlm_numeric_journal_v1',real_model_calls:false})
  if(url.includes('/citations/candidates?')||url.includes('/citations/todos?'))return Response.json(page([candidate(state.usable)]))
  if(url.includes('/citations/drafts?'))return Response.json(page([]))
  if(url.includes('/references/ref1?'))return Response.json({...reference,sources:{items:[source],total:1,page:1,page_size:10},decisions:[]})
  if(url.endsWith('/config'))return Response.json({available:false,reason:null,candidate_limits:[20,50,100],default_limit:20,page_size:10,publication_types:[],full_text_acquisition:false,claim_verification:false})
  if(url.includes('/references?'))return Response.json(page([reference]))
  if(url.includes('/searches?'))return Response.json(page([]))
  return Response.json(page([]))
 })
 vi.stubGlobal('fetch',fetcher);return fetcher
}
afterEach(()=>{cleanup();vi.unstubAllGlobals()})

async function shortlist(){
 fireEvent.click(await screen.findByRole('button',{name:'查看候选详情'}))
 const region=await screen.findByRole('region',{name:'候选文献详情'})
 fireEvent.click(within(region).getByRole('button',{name:'人工筛选'}))
 fireEvent.change(within(region).getByLabelText('人工筛选状态'),{target:{value:'shortlisted'}})
 fireEvent.click(within(region).getByRole('button',{name:'保存人工筛选'}))
}

it('reports a reference that is shortlisted with a usable bibliography',async()=>{
 serve({usable:true})
 const onReferenceReady=vi.fn()
 render(<ProjectLiterature projectId="p1" researchTopic="Lineage" active customerSci onReferenceReady={onReferenceReady}/>)
 await shortlist()
 await waitFor(()=>expect(onReferenceReady).toHaveBeenCalledWith('ref1'))
 expect(onReferenceReady).toHaveBeenCalledTimes(1)
})

it('stays on the literature page until the bibliography of a shortlisted reference is checked',async()=>{
 const state={usable:false}
 serve(state)
 const onReferenceReady=vi.fn()
 render(<ProjectLiterature projectId="p1" researchTopic="Lineage" active customerSci onReferenceReady={onReferenceReady}/>)
 await shortlist()
 expect(await screen.findByText('还需核对这篇文献的书目信息，完成后会自动回到本段。')).toBeTruthy()
 expect(onReferenceReady).not.toHaveBeenCalled()
 state.usable=true
 fireEvent.click(screen.getByRole('button',{name:'引用工作台'}))
 await waitFor(()=>expect(onReferenceReady).toHaveBeenCalledWith('ref1'))
})

it('does not report anything without a paragraph waiting for it',async()=>{
 const fetcher=serve({usable:true})
 render(<ProjectLiterature projectId="p1" researchTopic="Lineage" active customerSci/>)
 await shortlist()
 await waitFor(()=>expect(fetcher.mock.calls.some(([,init])=>init?.method==='PATCH')).toBe(true))
 expect(screen.queryByText('还需核对这篇文献的书目信息，完成后会自动回到本段。')).toBeNull()
})
