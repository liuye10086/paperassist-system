// B03 任务 10：SCI 客户的文献与引用页不折叠、不露系统 ID、不给原始 JSON/XML 下载。
// 夹具 ID 用 UUID 与真实哈希（'a'.repeat(64) 扫描不到），全部登记进 systemIds。
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {setLocale} from '../../shared/i18n'
import {findTechnicalText} from '../../test/technicalText'
import ProjectLiterature from './ProjectLiterature'
import CitationSnapshot from './CitationSnapshot'
import type {DraftView} from './citationApi'

const projectId='3f6b2a1c-8d4e-4f70-9a5b-1c2d3e4f5a6b'
const referenceId='8a7b6c5d-4e3f-4a1b-9c8d-7e6f5a4b3c2d'
const searchId='1b2c3d4e-5f60-4718-89ab-cdef01234567'
const receiptId='c0ffee12-3456-4789-abcd-ef0123456789'
const metaId='d1e2f3a4-b5c6-4d7e-8f90-a1b2c3d4e5f6'
const claimId='e5f6a7b8-c9d0-4e1f-a2b3-c4d5e6f7a8b9'
const reviewId='f6a7b8c9-d0e1-4f2a-b3c4-d5e6f7a8b9c0'
const materialId='a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d'
const fileId='b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e'
const versionId='c3d4e5f6-a7b8-4c9d-8e1f-2a3b4c5d6e7f'
const checkId='d4e5f6a7-b8c9-4d0e-9f2a-3b4c5d6e7f80'
const evidenceId='e6f7a8b9-c0d1-4e2f-a3b4-c5d6e7f8a9b0'
const draftId='f7a8b9c0-d1e2-4f3a-b4c5-d6e7f8a9b0c1'
const draftVersionId='0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d'
const sha='18533238bb1daaa4a8600f1c533cd8ce7c66996ba7ee120b8ee6cc766e3670e2'
const recordSha='7d9e3f1a2b4c6d8e0f1a3b5c7d9e1f3a5b7c9d1e3f5a7b9c1d3e5f7a9b1c3d5e'
const systemIds=[projectId,referenceId,searchId,receiptId,metaId,claimId,reviewId,materialId,fileId,versionId,checkId,evidenceId,draftId,draftVersionId,sha,recordSha]
const rawValues=['supported','partial','unsupported','needs_review','related','unrelated','uncertain','user_material','pmc_fulltext','shortlisted','synthetic_match','saved_record','doi_resolution','full_paper','unconfirmed','ncbi_eutilities','doi_org']
const scan=()=>findTechnicalText(document.body,{systemIds,rawValues})
const stamp='2026-11-19T02:30:00Z'
const base=`/api/v1/projects/${projectId}/literature`
const page=(items:unknown[])=>({project_id:projectId,items,total:items.length,page:1,page_size:10})
const metadata={article_type:'journal',authors:[{family:'Chen',given:'',initials:'L',collective:''}],title:'Serum markers in cases',journal_title:'Clinical Journal',journal_abbreviation:'Clin J',year:'2024',date:'2024 May 12',volume:'2',issue:'',pages:'1-3',article_number:'',doi:'10.1000/clin.2024.12',pmid:'38123456'}
const source={search_id:searchId,receipt_id:receiptId,source_kind:'ncbi_eutilities',source_download_url:`${base}/receipts/${receiptId}/source`,sha256:sha,record_sha256:recordSha,pmid:'38123456'}
const meta={id:metaId,project_reference_id:referenceId,revision:1,mode:'extract',metadata,source,source_description:'PubMed 保存记录',basis:'按保存记录核对',source_verified:true,source_current:true,usable:true,gaps:[],created_at:stamp}
const review={id:reviewId,claim_id:claimId,claim_revision:1,project_reference_id:referenceId,evidence_ids:[evidenceId],status:'supported',relevance:'related',reason:'摘要直接支持',narrowed_statement:'',limitations:'仅摘要',decided_by:'客户',created_at:stamp}
const material={id:materialId,file_id:fileId,source_kind:'document_version',version_id:versionId,completeness:'unconfirmed',confirmation:null,source_current:true,actual_item_count:2,read_items:[{id:evidenceId,claim_id:claimId,claim_revision:1,quote:'病例组血清指标更高。',reading_scope:'user_material',location:{page_number:2}}]}
const candidate={id:referenceId,pmid:'38123456',record:{title:'Serum markers in cases',verification_status:'not_verified',doi_resolution_status:'not_checked'},selection:{status:'shortlisted',note:'',revision:1},source,metadata:meta,materials:[material],has_abstract:true,holds_full_paper:false,claims:[{id:claimId,revision:1,content:'病例组血清指标更高。',latest_review:review,review_source_current:true,citation_eligible:true,supplement_rounds_used:0}],todos:[]}
const checkSource={search_id:searchId,receipt_id:receiptId,source_kind:'ncbi_eutilities',query:'serum markers',effective_query:'serum markers',retrieved_at:stamp,cached:false,ordinal:1,source_download_url:`${base}/receipts/${receiptId}/source`,output_language:'zh-CN'}
const receipt={id:checkId,project_reference_id:referenceId,kind:'doi_resolution',search_id:searchId,source_kind:'ncbi_eutilities',output_language:'zh-CN',created_at:stamp,source_current:true,result:{status:'resolved',network_attempted:true,execution_kind:'doi_org',error_code:null,doi:'10.1000/clin.2024.12',http_status:302,resolution_target:'https://journal.example.org/article',source:{search_id:searchId,receipt_id:receiptId,source_kind:'ncbi_eutilities',sha256:sha,record_sha256:recordSha,pmid:'38123456'}}}
const checkCandidate={id:referenceId,reference_id:referenceId,project_id:projectId,pmid:'38123456',record:{pmid:'38123456',title:'Serum markers in cases',authors:['Chen L'],year:2024,journal:'Clinical Journal',doi:'10.1000/clin.2024.12'},selection:{status:'shortlisted',note:'',revision:1},source:checkSource,sources:[checkSource],saved_record:null,doi_resolution:receipt,content_support:[],created_at:stamp,updated_at:stamp}

function serve(){
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
  if(url.startsWith(`${base}/checks/`)){
   if(url.endsWith('/config'))return Response.json({project_id:projectId,page_size:10,check_kinds:['saved_record','doi_resolution'],doi_check_available:false,doi_network_enabled:false,doi_execution_kind:'disabled',real_model_calls:false})
   if(url.includes('/history?'))return Response.json(page([receipt]))
   if(url.endsWith(`/references/${referenceId}`))return Response.json(checkCandidate)
  }
  if(url.endsWith('/citations/config'))return Response.json({project_id:projectId,format:'nlm_numeric_journal_v1',page_size:10,supported_article_types:['journal'],material_completeness:['full_paper','fragment','unconfirmed'],manual_metadata_requires_confirmation:true,real_model_calls:false})
  if(url.includes('/citations/candidates?')||url.includes('/citations/todos?'))return Response.json(page([candidate]))
  if(url.includes(`/citations/references/${referenceId}/metadata?`))return Response.json(page([meta]))
  if(url.includes('/confirmations?'))return Response.json(page([]))
  if(url.includes('/citations/drafts?'))return Response.json(page([]))
  if(url.includes(`/references/${referenceId}?`))return Response.json({...checkCandidate,sources:{items:[checkSource],total:1,page:1,page_size:10},decisions:[]})
  if(url.endsWith('/config'))return Response.json({available:false,reason:null,candidate_limits:[20,50,100],default_limit:20,page_size:10,publication_types:[],full_text_acquisition:false,claim_verification:false})
  if(url.includes('/searches?')||url.includes('/references?'))return Response.json(page([]))
  throw Error(url)
 }))
}
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();setLocale('zh-CN')})
const folds=()=>document.querySelectorAll('.literature-workspace details, .literature-workspace [aria-expanded]').length

it('shows customer citation checks as a sub-view with no folds, raw downloads or system IDs',async()=>{
 serve()
 render(<ProjectLiterature projectId={projectId} researchTopic="血清指标" customerSci active literatureNavigation={{view:'citations',referenceId:''}}/>)
 await screen.findByText('Serum markers in cases')
 expect(folds()).toBe(0)
 fireEvent.click(screen.getByRole('button',{name:'查看三项核验与历史'}))
 const checks=await screen.findByRole('region',{name:'文献三项核验'})
 expect(screen.queryByRole('region',{name:'引用候选与待办'})).toBeNull()
 await within(checks).findAllByText(/PMID 38123456/)
 expect(within(checks).getAllByText(/DOI 10\.1000\/clin\.2024\.12/).length).toBeGreaterThan(0)
 expect(within(checks).getByRole('heading',{name:'核验历史'})).toBeTruthy()
 expect(within(checks).queryByText(/HTTP/)).toBeNull()
 expect(within(checks).queryByRole('link',{name:'下载原始 JSON/XML'})).toBeNull()
 expect(folds()).toBe(0)
 expect(scan()).toEqual([])
 fireEvent.click(screen.getByRole('button',{name:'返回引用候选'}))
 await screen.findByRole('region',{name:'引用候选与待办'})
 expect(screen.queryByRole('region',{name:'文献三项核验'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'核对材料与书目'}))
 const panel=await screen.findByRole('region',{name:'材料与书目核对'})
 expect(within(panel).getByRole('heading',{name:'只读书目历史与来源'})).toBeTruthy()
 await within(panel).findByRole('button',{name:/书目版本 1 ·/})
 expect(within(panel).queryByRole('link',{name:'下载原始 JSON/XML'})).toBeNull()
 expect(within(panel).getByRole('heading',{name:'完整性历史'})).toBeTruthy()
 expect(folds()).toBe(0)
 expect(scan()).toEqual([])
})

it('keeps the analyst citation checks as an inline toggle with raw downloads',async()=>{
 serve()
 render(<ProjectLiterature projectId={projectId} researchTopic="血清指标" active literatureNavigation={{view:'citations',referenceId:''}}/>)
 await screen.findByText('Serum markers in cases')
 const toggle=screen.getByRole('button',{name:'查看三项核验与历史'})
 expect(toggle.getAttribute('aria-expanded')).toBe('false')
 fireEvent.click(toggle)
 const checks=await screen.findByRole('region',{name:'文献三项核验'})
 expect(screen.getByRole('region',{name:'引用候选与待办'})).toBeTruthy()
 await within(checks).findAllByText(/HTTP 302/)
 expect(within(checks).getAllByRole('link',{name:'下载原始 JSON/XML'}).length).toBeGreaterThan(0)
})

const snapshotView={id:draftId,version_id:draftVersionId,project_id:projectId,revision:1,current_revision:1,is_current:true,created_at:stamp,current_changes:[],snapshot:{output_language:'zh-CN',title:'讨论段落',output:{text:'病例组血清指标更高 (1)。',references:[{number:1,project_reference_id:referenceId,text:'Chen L. Serum markers in cases. Clin J. 2024;2:1-3.'}],paragraphs:[]},paragraphs:[{id:'p-discussion',fragments:[{kind:'claim',claim_id:claimId,claim_revision:1,text:'病例组血清指标更高。',bindings:[{project_reference_id:referenceId,review_id:reviewId,metadata_version_id:metaId,metadata,review,metadata_source:meta,evidence:[{id:evidenceId,reading_scope:'user_material',quote:'病例组血清指标更高。',source:{kind:'document_version',file_id:fileId,filename:'cases.pdf',version:1},location:{page_number:2}}]}]}]}]}} as unknown as DraftView

it('shows the customer citation snapshot sources openly without JSON downloads',()=>{
 render(<div className="literature-workspace"><CitationSnapshot projectId={projectId} view={snapshotView} customerSci/></div>)
 expect(screen.getByRole('heading',{name:'本版引用来源与证据'})).toBeTruthy()
 expect(screen.getByText('摘要直接支持',{exact:false})).toBeTruthy()
 expect(screen.queryByRole('link',{name:'下载本版冻结输出'})).toBeNull()
 expect(screen.queryByRole('link',{name:'下载本版来源快照'})).toBeNull()
 expect(screen.queryByRole('link',{name:'下载原始 JSON/XML'})).toBeNull()
 expect(screen.getByRole('link',{name:'下载原始文件'})).toBeTruthy()
 expect(folds()).toBe(0)
 expect(scan()).toEqual([])
})

it('keeps the analyst citation snapshot sources folded with JSON downloads',()=>{
 render(<CitationSnapshot projectId={projectId} view={snapshotView}/>)
 expect(document.querySelector('details')).toBeTruthy()
 expect(screen.getByRole('link',{name:'下载本版冻结输出',hidden:true})).toBeTruthy()
})
