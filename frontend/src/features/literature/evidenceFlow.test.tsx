import {afterEach,it,expect,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import EvidenceWorkspace from './EvidenceWorkspace'
import {setLocale} from '../../shared/i18n'
import {literatureTask} from './fixtures'
import {sourceText,validEvidence,validReviewInput} from './evidenceApi'
const stamp='2026-10-19T00:00:00Z'
// Synthetic fixture: original text deliberately represents no real publication.
const source={search_id:'search1',receipt_id:'receipt1',query:'Synthetic query',effective_query:'Synthetic query',retrieved_at:stamp,source_kind:'synthetic_fixture',cached:false,ordinal:1,source_download_url:'/api/v1/projects/p1/literature/receipts/receipt1/source'}
const reference={id:'ref1',reference_id:'book1',project_id:'p1',pmid:'123',record:{pmid:'123',title:'Synthetic untranslated title',authors:[],year:null,journal:null,doi:null,abstract:[{label:'RESULTS',text:'Synthetic actual saved abstract text.'}],abstract_status:'available',full_text_status:'not_acquired',verification_status:'not_verified',doi_resolution_status:'not_checked',keywords:[],mesh_terms:[],full_text_links:[]},selection:{status:'candidate',note:'',revision:1},source,created_at:stamp,updated_at:stamp,sources:{items:[source],total:1,page:1,page_size:10},decisions:[]}
const claim={id:'claim1',project_id:'p1',revision:1,content:'Synthetic claim',context:'',output_language:'en',created_at:stamp,updated_at:stamp,versions:[{revision:1,content:'Synthetic claim',output_language:'en',created_at:stamp}],is_current:true,supplement:null}
const evidence={id:'e1',claim_id:'claim1',claim_revision:1,project_reference_id:'ref1',quote:'actual saved abstract',reading_scope:'abstract',source:{kind:'abstract',search_id:'search1',receipt_id:'receipt1',sha256:'a'.repeat(64)},location:{abstract_index:0,label:'RESULTS',start:10,end:31},created_at:stamp}
const page=(items:unknown[],size=10)=>({items,total:items.length,page:1,page_size:size})
function fixture(savedReference:unknown=reference){let assistanceSaved:Record<string,unknown>|null=null;let materialSaved:unknown=null;let savedEvidence=false;const reviews:unknown[]=[];const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
 if(init?.method==='POST'){
  const body=JSON.parse(init.body as string)
  if(url.endsWith('/evidence')){savedEvidence=true;return Response.json(evidence,{status:201})}
  if(url.endsWith('/reviews')){const r={id:'review1',claim_id:'claim1',decided_by:'00000000-0000-0000-0000-000000000001',created_at:stamp,...body};reviews.push(r);return Response.json(r,{status:201})}
  if(url.endsWith('/materials')){materialSaved={id:'material1',project_reference_id:'ref1',source:{kind:'document_version',file_id:'file1',filename:'Synthetic paper.pdf',version_id:'v1',version:1,sha256:'a'.repeat(64)},source_description:body.source_description,match_note:body.match_note,created_at:stamp};return Response.json(materialSaved)}
  if(url.endsWith('/assistance/tasks')){const task={...literatureTask,id:'assist1',task_type:'literature_assistance',phase:body.kind==='search_plan'?'plan':'verify',input_version:{kind:'literature_assistance',workflow_version:'literature_assistance_v1',assistance_kind:body.kind,input_digest:'b'.repeat(64),output_language:body.output_language}};assistanceSaved={task,kind:body.kind,input_version:task.input_version,result:null,real_calls_enabled:false};return Response.json(task,{status:202})}
 }
 if(url.endsWith('/evidence/config'))return Response.json({project_id:'p1',full_text_mode:'user_upload',real_model_calls:false,supplement_round_limit:1,supplement_candidate_limit:20})
 if(url.includes('/references/ref1?'))return Response.json(savedReference)
 if(url.includes('/references?'))return Response.json({...page([reference]),project_id:'p1'})
 if(url.includes('/claims/claim1/evidence?'))return Response.json(page(savedEvidence?[evidence]:[]))
 if(url.includes('/claims/claim1/reviews?'))return Response.json(page(reviews))
 if(url.includes('/claims/claim1?'))return Response.json(claim)
 if(url.includes('/claims?'))return Response.json(page([claim]))
 if(url.includes('/material-options?'))return Response.json(page([{file_id:'file1',filename:'Synthetic paper.pdf',file_type:'pdf',versions:[{kind:'document_version',version_id:'v1',version:1,label:'Synthetic parsed version'}]}]))
 if(url.includes('/materials/material1/source?'))return Response.json({source:(materialSaved as {source:unknown}).source,...page([{id:'item1',kind:'text',text:'Synthetic actual saved material.',location:{page_number:3,path:'Synthetic paragraph'}}],20)})
 if(url.includes('/materials?'))return Response.json(page(materialSaved?[materialSaved]:[]))
 if(url.includes('/assistance/tasks?'))return Response.json(page(assistanceSaved?[assistanceSaved]:[]))
 if(url.endsWith('/assistance/tasks/assist1'))return Response.json(assistanceSaved)
 throw Error(url)
 });vi.stubGlobal('fetch',fetch);return fetch}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it.each(['zh-CN','en'] as const)('shows selected evidence source context without translating its text in %s',async locale=>{
 setLocale(locale)
 const source_context={kind:'section',label:'论文章节',text:'真实回执离线重放（未再次外发）'}
 fixture({...reference,source:{...source,source_context}})
 render(<EvidenceWorkspace projectId="p1" researchTopic="Synthetic topic"/>);
 fireEvent.change(await screen.findByLabelText(locale==='en'?'Project reference':'选择项目文献'),{target:{value:'ref1'}})
 expect(await screen.findByText(locale==='en'?'Saved search context':'保存的检索背景')).toBeTruthy()
 expect(screen.getByText(source_context.label)).toBeTruthy()
 expect(screen.getByText(source_context.text)).toBeTruthy()
})
it('does not treat uncertain relevance as support and rejects evidence without position or with mismatched scope',()=>{
 const review={claim_revision:1,project_reference_id:'ref1',evidence_ids:['e1'],status:'supported',relevance:'uncertain',reason:'Synthetic reason',narrowed_statement:'',limitations:''}
 expect(validReviewInput(review)).toBe(false)
 expect(validEvidence({...evidence,location:{}},'claim1',1)).toBe(false)
 expect(validEvidence({...evidence,reading_scope:'user_material'},'claim1',1)).toBe(false)
})
it('uses actual abstract and search snapshot, then requires partial boundary before saving manual history',async()=>{
 const fetch=fixture();render(<EvidenceWorkspace projectId="p1" researchTopic="Synthetic topic"/>);
 fireEvent.change(await screen.findByLabelText('选择项目文献'),{target:{value:'ref1'}})
 fireEvent.click(screen.getByRole('button',{name:'论述核验'}));await screen.findByRole('option',{name:'Synthetic claim'});fireEvent.change(screen.getByLabelText('选择论述'),{target:{value:'claim1'}})
 await screen.findByRole('option',{name:/版本 1/})
 fireEvent.click(screen.getByRole('button',{name:'摘要与 PMC'}));fireEvent.click(await screen.findByRole('button',{name:'从此摘要段摘录'}))
 fireEvent.change(screen.getByLabelText('精确摘录'),{target:{value:'fabricated text'}})
 expect((screen.getByRole('button',{name:'保存来源证据'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('精确摘录'),{target:{value:'actual saved abstract'}})
 fireEvent.click(screen.getByRole('button',{name:'保存来源证据'}))
 const checkbox=await screen.findByLabelText('读取范围：摘要');fireEvent.click(checkbox)
 fireEvent.change(screen.getByLabelText('论述支持状态'),{target:{value:'partial'}})
 fireEvent.change(screen.getByLabelText('文献相关性'),{target:{value:'related'}})
 fireEvent.change(screen.getByLabelText('人工核验理由'),{target:{value:'Synthetic bounded reason'}})
 expect((screen.getByRole('button',{name:'保存人工核验'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('收窄后的论述（部分支持必填）'),{target:{value:'Synthetic narrower statement'}})
 fireEvent.click(screen.getByRole('button',{name:'保存人工核验'}))
 expect(await screen.findByText('已记录当前项目用户的人工判定。')).toBeTruthy()
 expect(screen.queryByText(/00000000-0000-0000-0000-000000000001/)).toBeNull()
 act(()=>setLocale('en'))
 expect(screen.getByText('Manual decision by the current project user recorded.')).toBeTruthy()
 const post=fetch.mock.calls.find(([url,init])=>url.endsWith('/evidence')&&init?.method==='POST')!
 expect(JSON.parse(post[1]!.body as string)).toEqual({claim_revision:1,project_reference_id:'ref1',source_kind:'abstract',search_id:'search1',quote:'actual saved abstract'})
 expect(new Headers(post[1]!.headers).get('Idempotency-Key')).toBeTruthy()
 expect(fetch.mock.calls.filter(([url,init])=>url.endsWith('/reviews')&&init?.method==='POST')).toHaveLength(1)
})
it('links named material versions and exposes actual text with its saved location',async()=>{
 const fetch=fixture();render(<EvidenceWorkspace projectId="p1" researchTopic="Synthetic topic"/>);
 fireEvent.change(await screen.findByLabelText('选择项目文献'),{target:{value:'ref1'}})
 fireEvent.click(screen.getByRole('button',{name:'全文与解析材料'}));await screen.findByRole('option',{name:'Synthetic paper.pdf'});fireEvent.change(await screen.findByLabelText('项目文件'),{target:{value:'file1'}})
 fireEvent.change(screen.getByLabelText('解析或 OCR 核对版本'),{target:{value:'v1'}})
 fireEvent.change(screen.getByLabelText('书目对应确认'),{target:{value:'Synthetic checked match'}})
 expect((screen.getByRole('button',{name:'关联所选材料'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('来源说明'),{target:{value:'Synthetic uploaded full text'}})
 fireEvent.click(screen.getByRole('button',{name:'关联所选材料'}))
 expect(await screen.findByText('Synthetic actual saved material.')).toBeTruthy()
 expect(screen.getByText('page_number: 3 · path: Synthetic paragraph')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'从此条目摘录'}))
 fireEvent.click(screen.getByRole('button',{name:'论述核验'}));expect(screen.getByText('当前读取范围：用户材料条目')).toBeTruthy()
 const post=fetch.mock.calls.find(([url,init])=>url.endsWith('/materials')&&init?.method==='POST')!
 expect(JSON.parse(post[1]!.body as string)).toMatchObject({project_reference_id:'ref1',file_id:'file1',source_kind:'document_version',version_id:'v1'})
})
it('prevents unreadable OCR blocks from becoming quotable text',()=>{
 expect(sourceText({id:'ocr1',kind:'text',text:'Synthetic uncertain OCR',location:{page_number:1},uncertainties:['unreadable']})).toBe('')
})
it('records model planning as an authorization wait and never posts a manual review',async()=>{
 const fetch=fixture();render(<EvidenceWorkspace projectId="p1" researchTopic="Synthetic topic"/>);
 fireEvent.click(screen.getByRole('button',{name:'辅助任务'}));fireEvent.click(await screen.findByRole('button',{name:'保存检索方案建议任务'}))
 expect(await screen.findByText('模型任务已保存，人工决定未改变。')).toBeTruthy()
 expect(await screen.findByText('当前任务尚无模型建议，请查看等待或失败状态。')).toBeTruthy()
 await waitFor(()=>expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1))
 const post=fetch.mock.calls.find(([,init])=>init?.method==='POST')!
 expect(post[0]).toContain('/literature/assistance/tasks')
 expect(JSON.parse(post[1]!.body as string)).toMatchObject({kind:'search_plan',output_language:'zh-CN',research_topic:'Synthetic topic'})
})

it('accepts an actual verify-phase evidence review task in POST, list and saved details',async()=>{
 const fetch=fixture();render(<EvidenceWorkspace projectId="p1" researchTopic="Synthetic topic"/>);
 fireEvent.change(await screen.findByLabelText('选择项目文献'),{target:{value:'ref1'}})
 fireEvent.click(screen.getByRole('button',{name:'论述核验'}));await screen.findByRole('option',{name:'Synthetic claim'});fireEvent.change(screen.getByLabelText('选择论述'),{target:{value:'claim1'}})
 await screen.findByRole('option',{name:/版本 1/})
 fireEvent.click(screen.getByRole('button',{name:'摘要与 PMC'}));fireEvent.click(await screen.findByRole('button',{name:'从此摘要段摘录'}))
 fireEvent.change(screen.getByLabelText('精确摘录'),{target:{value:'actual saved abstract'}})
 fireEvent.click(screen.getByRole('button',{name:'保存来源证据'}))
 fireEvent.click(await screen.findByLabelText('读取范围：摘要'))
 fireEvent.click(screen.getByRole('button',{name:'辅助任务'}));fireEvent.click(screen.getByRole('button',{name:'保存所选证据的核验建议任务'}))
 expect(await screen.findByText('模型任务已保存，人工决定未改变。')).toBeTruthy()
 expect(await screen.findByRole('region',{name:'模型建议详情'})).toBeTruthy()
 expect(screen.getByRole('button',{name:'查看建议与等待状态'})).toBeTruthy()
 const post=fetch.mock.calls.find(([url,init])=>url.endsWith('/assistance/tasks')&&init?.method==='POST')!
 expect(JSON.parse(post[1]!.body as string)).toMatchObject({kind:'evidence_review',claim_id:'claim1',claim_revision:1,project_reference_id:'ref1',evidence_ids:['e1']})
 expect(fetch.mock.calls.some(([url,init])=>url.endsWith('/reviews')&&init?.method==='POST')).toBe(false)
})

it('allows an explicitly confirmed evidence refresh after an unknown settled submission',async()=>{
 const fetch=fixture(),original=fetch.getMockImplementation()!;fetch.mockImplementation((u,i)=>u.endsWith('/assistance/tasks')&&i?.method==='POST'?Promise.reject(new Error('Synthetic response lost')):original(u,i));
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(true),alert=vi.spyOn(window,'alert').mockImplementation(()=>{});
 render(<EvidenceWorkspace projectId="p1" researchTopic="Synthetic topic"/>);fireEvent.click(screen.getByRole('button',{name:'辅助任务'}));fireEvent.click(screen.getByRole('button',{name:'保存检索方案建议任务'}));await screen.findByText('保存结果未确认，请刷新记录；相同输入重试沿用请求标识。');
 await waitFor(()=>expect((screen.getByRole('button',{name:'保存检索方案建议任务'}) as HTMLButtonElement).disabled).toBe(false));fireEvent.click(screen.getByRole('button',{name:'刷新证据记录'}));expect(confirm).toHaveBeenCalled();expect(alert).not.toHaveBeenCalled();await waitFor(()=>expect(screen.queryByText('保存结果未确认，请刷新记录；相同输入重试沿用请求标识。')).toBeNull());confirm.mockRestore();alert.mockRestore();
});
