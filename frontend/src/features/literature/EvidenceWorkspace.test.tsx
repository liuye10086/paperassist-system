import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,it,expect,vi} from 'vitest'
import EvidenceWorkspace from './EvidenceWorkspace'
import {validReviewInput,validEvidencePage,validMaterialOptions} from './evidenceApi'
import {setLocale} from '../../shared/i18n'
const stamp='2026-10-19T00:00:00Z'
// Synthetic fixtures only: no real publication, model result, or external service.
const claim={id:'claim1',project_id:'p1',revision:2,content:'Synthetic claim',context:'Synthetic context',output_language:'en',created_at:stamp,updated_at:stamp,versions:[{revision:1,content:'Synthetic old claim',output_language:'en',created_at:stamp},{revision:2,content:'Synthetic claim',output_language:'en',created_at:stamp}],is_current:true,supplement:{task_id:'search1',round:1,limit:20}}
const page=(items:unknown[],size=10)=>({project_id:'p1',items,total:items.length,page:1,page_size:size})
function setup(){const fetch=vi.fn(async(url:string)=>{
 if(url.endsWith('/evidence/config'))return Response.json({project_id:'p1',full_text_mode:'user_upload',real_model_calls:false,supplement_round_limit:1,supplement_candidate_limit:20})
 if(url.includes('/claims/claim1?'))return Response.json(claim)
 if(url.includes('/claims/claim1/evidence?')||url.includes('/claims/claim1/reviews?'))return Response.json(page([]))
 if(url.includes('/claims?'))return Response.json(page([claim]))
 if(url.includes('/material-options?'))return Response.json(page([{file_id:'file1',filename:'Synthetic paper.pdf',file_type:'pdf',versions:[{kind:'document_version',version_id:'v1',version:1,label:'Parsed version 1'}]}]))
 if(url.includes('/materials?')||url.includes('/assistance/tasks?')||url.includes('/references?'))return Response.json(page([]))
 throw Error(url)
 });vi.stubGlobal('fetch',fetch);return fetch}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it('requires evidence, partial boundary and independent relevance for manual decisions',()=>{
 const review={claim_revision:1,project_reference_id:'ref1',evidence_ids:[],status:'supported',relevance:'related',reason:'Synthetic reason',narrowed_statement:'',limitations:''}
 expect(validReviewInput(review)).toBe(false)
 expect(validReviewInput({...review,evidence_ids:['e1'],status:'partial'})).toBe(false)
 expect(validReviewInput({...review,evidence_ids:['e1'],relevance:'unrelated'})).toBe(false)
 expect(validReviewInput({...review,status:'needs_review'})).toBe(true)
})
it('rejects absent source scope and malformed choices instead of inventing missing states',()=>{
 expect(validEvidencePage(page([{id:'e1',claim_id:'c1',claim_revision:1,project_reference_id:'r1',quote:'Synthetic quote'}]),'p1','c1',1,1)).toBe(false)
 expect(validMaterialOptions(page([{file_id:'f1',filename:'Synthetic.pdf',versions:[]}]),'p1',1)).toBe(false)
})
it('shows named files, claim history, reading scope and exhausted supplement',async()=>{
 setup();render(<EvidenceWorkspace projectId="p1" researchTopic="Synthetic topic" outputLanguage="en"/>);
 fireEvent.click(screen.getByRole('button',{name:'全文与解析材料'}));expect(await screen.findByRole('option',{name:'Synthetic paper.pdf'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'论述核验'}));await screen.findByRole('option',{name:'Synthetic claim'});fireEvent.change(screen.getByLabelText('选择论述'),{target:{value:'claim1'}})
 expect(await screen.findByRole('option',{name:/Synthetic old claim/})).toBeTruthy()
 expect(screen.getByText('Abstract evidence cannot establish full text details. Successful parsing does not establish claim support.')).toBeTruthy()
 expect((screen.getByRole('button',{name:'创建补搜任务'}) as HTMLButtonElement).disabled).toBe(true)
 await waitFor(()=>expect((screen.getByLabelText('论述文本') as HTMLTextAreaElement).value).toBe('Synthetic claim'));fireEvent.change(screen.getByLabelText('查看论述版本'),{target:{value:'1'}})
 await waitFor(()=>expect((screen.getByRole('button',{name:'保存人工核验'}) as HTMLButtonElement).disabled).toBe(true))
})
it('uses English controls independently from task output language',async()=>{
 setLocale('en');setup();render(<EvidenceWorkspace projectId="p1" researchTopic="Synthetic topic" outputLanguage="zh-CN"/>);
 fireEvent.click(screen.getByRole('button',{name:'Full text and parsed materials'}));expect(await screen.findByRole('option',{name:'Synthetic paper.pdf'})).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'Claim verification'}))
 expect(screen.getByRole('button',{name:'Create claim'})).toBeTruthy()
 expect((screen.getByLabelText('Claim output language') as HTMLSelectElement).value).toBe('zh-CN')
})
