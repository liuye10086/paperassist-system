import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import EvidenceWorkspace from './EvidenceWorkspace'
import LiteratureAssistance from './LiteratureAssistance'
import LiteraturePmc from './LiteraturePmc'
import LiteratureClaims from './LiteratureClaims'
import ModelCallHistory from './ModelCallHistory'
import CitationSnapshot from './CitationSnapshot'
import {validPmcReceipt,validPmcContent} from './pmcApi'
import {validEvidence} from './evidenceApi'
import {validAssistanceRequest,validAssistance} from './assistanceApi'
import {setLocale} from '../../shared/i18n'
import {literatureTask} from './fixtures'
import {readFileSync} from 'node:fs'
import {literatureBatch06Messages} from '../../shared/i18n/literatureBatch06Messages'
import {translate} from '../../shared/i18n'
const stamp='2026-10-19T00:00:00Z',hash='a'.repeat(64)
const page=(items:unknown[],number=1,total=items.length,size=10)=>({items,page:number,total,page_size:size})
const scope={extracted:'body paragraphs and table text only; excludes abstract, figures, supplements and back matter',whole_article_verified:false,paragraph_count:21,table_count:0}
const receipt={id:'pmc1',project_reference_id:'ref1',pmcid:'PMC123',pmid:'123',source_kind:'stage05_batch06_public',status:'succeeded',license:{code:'CC-BY-4.0',url:'https://creativecommons.org/licenses/by/4.0/'},scope,created_at:stamp,responses:[{metadata_prefix:'pmc',http_status:200,error:null,sha256:hash,source_download_url:'/api/v1/projects/p1/literature/pmc/receipts/pmc1/raw/1',attempted:true,capture_status:'complete',received_bytes:123,retained_bytes:123,byte_limit:8388608,admission_code:null}]}
const evidence={id:'ev1',claim_id:'claim1',claim_revision:1,project_reference_id:'ref1',quote:'Saved actual paragraph',reading_scope:'pmc_fulltext',source:{kind:'pmc',pmc_receipt_id:'pmc1',pmcid:'PMC123',pmid:'123',sha256:hash,license:receipt.license,scope,source_kind:receipt.source_kind,source_download_url:receipt.responses[0].source_download_url},location:{item_id:'pmc-item-1',kind:'paragraph',section:['Results'],xml_path:'./body/p[1]',start:0,end:22},created_at:stamp}
const claim={id:'claim1',project_id:'p1',revision:1,content:'Synthetic bounded claim',context:'',output_language:'en' as const,created_at:stamp,updated_at:stamp,versions:[{revision:1,content:'Synthetic bounded claim',output_language:'en' as const,created_at:stamp}],is_current:true,supplement:null}
const task={...literatureTask,id:'assist1',task_type:'literature_assistance',phase:'plan',status:'succeeded',display_status:'succeeded',reason_code:null,error_code:null,input_version:{kind:'literature_assistance',workflow_version:'literature_assistance_v1',assistance_kind:'search_plan',input_digest:hash,output_language:'en'}}
const result={direction:'Saved direction',terms:['term'],synonyms:[],mesh_candidates:[{term:'Candidate',verified:false}],query:'original[Title]',explanation:'Saved explanation'}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it('accepts only explicitly bounded PMC evidence while preserving old sources',()=>{
 expect(validEvidence(evidence,'claim1',1)).toBe(true)
 expect(validEvidence({...evidence,source:{...evidence.source,scope:{...scope,whole_article_verified:true}}},'claim1',1)).toBe(false)
 expect(validEvidence({...evidence,reading_scope:'user_material'},'claim1',1)).toBe(false)
})
it.each(['zh-CN','en'] as const)('reads saved PMC receipts, paginates actual source and never acquires HTTP in %s',async locale=>{
 setLocale(locale);const calls=vi.fn(async(url:string,init?:RequestInit)=>{
  expect(init?.method??'GET').toBe('GET')
  if(url.includes('/pmc/receipts/pmc1/source')){const n=Number(new URL(url,'http://local').searchParams.get('page'));return Response.json({source:receipt,status:'succeeded',scope,...page([{id:`pmc-item-${n}`,kind:'paragraph',text:n===1?'Saved actual paragraph':'Saved second page',location:{section:['Results'],kind:'paragraph',xml_path:'./body/p[1]'}}],n,21,20)})}
  if(url.includes('/pmc/receipts?'))return Response.json(page([receipt]))
  if(url.endsWith('/evidence/config'))return Response.json({project_id:'p1',full_text_mode:'user_upload',real_model_calls:false,supplement_round_limit:1,supplement_candidate_limit:20})
  return Response.json(page([]))
 });vi.stubGlobal('fetch',calls)
 const view=render(<EvidenceWorkspace projectId="p1" researchTopic="topic"/>);
 const panel=await screen.findByRole('region',{name:locale==='en'?'Saved PMC sources':'已保存 PMC 来源'})
 fireEvent.click(await within(panel).findByRole('button',{name:locale==='en'?'View saved source':'查看已保存来源'}))
 expect(await within(panel).findByText('Saved actual paragraph')).toBeTruthy()
 expect(within(panel).getByText(/CC-BY-4.0/)).toBeTruthy()
 expect(within(panel).getByText(locale==='en'?'Only acquired body paragraphs and table text are available; the whole article has not been verified.':'仅读取已取得的正文段落与表格文字；未核验整篇全文。')).toBeTruthy()
 const nav=within(panel).getByRole('navigation',{name:locale==='en'?'PMC source pages':'PMC 来源分页'})
 fireEvent.click(within(nav).getByRole('button',{name:locale==='en'?'Next page':'下一页'}))
 expect(await within(panel).findByText('Saved second page')).toBeTruthy()
 view.rerender(<EvidenceWorkspace projectId="p2" researchTopic="other"/>);await waitFor(()=>expect(screen.queryByText('Saved second page')).toBeNull())
 expect(calls.mock.calls.every(c=>!c[1]?.method||c[1].method==='GET')).toBe(true)
})
it('validates comparison request and result with current task version',()=>{
 const request={kind:'evidence_comparison',claim_id:'claim1',claim_revision:1,evidence_ids:['ev1','ev2'],output_language:'en'}
 expect(validAssistanceRequest(request)).toBe(true);expect(validAssistanceRequest({...request,evidence_ids:['ev1','ev1']})).toBe(false)
 const comparisonTask={...task,phase:'verify',input_version:{...task.input_version,assistance_kind:'evidence_comparison'}}
 const comparison={task:comparisonTask,kind:'evidence_comparison',input_version:comparisonTask.input_version,result:{comparison:'conflicting',status:'needs_review',relevance:'uncertain',reason:'Different populations',narrowed_statement:'',limitations:['Selected excerpts only'],evidence_ids:['ev1','ev2']},real_calls_enabled:false}
 expect(validAssistance(comparison,'p1')).toBe(true)
 expect(validAssistance({...comparison,result:{...comparison.result,status:'supported'}},'p1')).toBe(false)
})
it('submits multiple references as a comparison while leaving manual decisions untouched',async()=>{
 const selected={claim,evidence:[evidence,{...evidence,id:'ev2',project_reference_id:'ref2'}],evidenceIds:['ev1','ev2'],isCurrent:true}
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{...task,phase:'verify',input_version:{...task.input_version,assistance_kind:'evidence_comparison'}}:url.endsWith('assist1')?{task,kind:'search_plan',input_version:task.input_version,result:null,real_calls_enabled:false}:page([])));vi.stubGlobal('fetch',fetch)
 const view=render(<LiteratureAssistance projectId="p1" researchTopic="topic" referenceId="ref1" selection={selected as never} onDenied={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'保存多来源比较建议任务'}))
 await waitFor(()=>expect(fetch.mock.calls.some(c=>c[1]?.method==='POST')).toBe(true))
 const post=fetch.mock.calls.find(c=>c[1]?.method==='POST')!;expect(JSON.parse(post[1]!.body as string)).toEqual({kind:'evidence_comparison',claim_id:'claim1',claim_revision:1,evidence_ids:['ev1','ev2'],output_language:'zh-CN'})
 expect(fetch.mock.calls.some(c=>c[0].includes('/reviews'))).toBe(false)
 view.rerender(<LiteratureAssistance projectId="p1" researchTopic="topic" referenceId="ref1" selection={{...selected,evidence:[evidence,{...evidence,id:'ev2'}]} as never} onDenied={vi.fn()}/>);
 expect((screen.getByRole('button',{name:'保存多来源比较建议任务'}) as HTMLButtonElement).disabled).toBe(true)
})
it('shows saved call facts without inventing live provenance or unknown zero costs; query copy stays editable',async()=>{
 const detail={task,kind:'search_plan',input_version:task.input_version,result,real_calls_enabled:false,model_calls:[{model:'gpt-6.1-sol',status:'completed',provider_status:'completed',error_code:null,provenance:'not_recorded',usage_status:'pending',usage:{input_tokens:100,output_tokens:50,total_tokens:150,cached_input_tokens:0},estimated_cost_micro_usd:null,created_at:stamp}]}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('assist1')?detail:page([detail]))))
 render(<LiteratureAssistance projectId="p1" researchTopic="topic" referenceId="" selection={null} onDenied={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'查看建议与等待状态'}))
 expect(await screen.findByText('gpt-6.1-sol')).toBeTruthy();expect(screen.getByText('来源未单独记录；不能据模型名确认真实调用。')).toBeTruthy();expect(screen.getByText('费用未知，待核对')).toBeTruthy();expect(document.body.textContent).not.toContain('$0.00')
 const copy=screen.getByLabelText('可编辑检索式副本') as HTMLTextAreaElement;fireEvent.change(copy,{target:{value:'edited[Title]'}});expect(copy.value).toBe('edited[Title]');expect(screen.getByText('original[Title]',{selector:'pre'})).toBeTruthy()
})
it('hands an actual PMC receipt and item to the quote form and saves only an exact substring',async()=>{
 const onSource=vi.fn(),onDenied=vi.fn();vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/source?')?{source:receipt,status:'succeeded',scope,...page([{id:'pmc-item-1',kind:'paragraph',text:'Saved actual paragraph',location:evidence.location}],1,1,20)}:page([receipt]))))
 const pmc=render(<LiteraturePmc projectId="p1" referenceId="ref1" onSource={onSource} onDenied={onDenied}/>);
 fireEvent.click(await screen.findByRole('button',{name:'查看已保存来源'}));fireEvent.click(await screen.findByRole('button',{name:'从此 PMC 片段摘录'}));const selection=onSource.mock.calls.at(-1)![0];expect(selection).toEqual({source_kind:'pmc',pmc_receipt_id:'pmc1',project_reference_id:'ref1',item_id:'pmc-item-1',text:'Saved actual paragraph'});pmc.unmount()
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?evidence:url.includes('/claims/claim1?')?claim:url.includes('/claims?')?page([claim]):page([])));vi.stubGlobal('fetch',fetch)
 render(<LiteratureClaims projectId="p1" referenceId="ref1" source={selection} onSelection={vi.fn()} onDenied={onDenied}/>);fireEvent.change(await screen.findByLabelText('选择论述'),{target:{value:'claim1'}});await screen.findByRole('option',{name:/版本 1/})
 fireEvent.change(screen.getByLabelText('精确摘录'),{target:{value:'Fabricated quote'}});expect((screen.getByRole('button',{name:'保存来源证据'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('精确摘录'),{target:{value:evidence.quote}});fireEvent.click(screen.getByRole('button',{name:'保存来源证据'}));await waitFor(()=>expect(fetch.mock.calls.some(c=>c[1]?.method==='POST')).toBe(true))
 expect(JSON.parse(fetch.mock.calls.find(c=>c[1]?.method==='POST')![1]!.body as string)).toEqual({claim_revision:1,project_reference_id:'ref1',source_kind:'pmc',pmc_receipt_id:'pmc1',item_id:'pmc-item-1',quote:evidence.quote})
})
it.each(['zh-CN','en'] as const)('shows failed or unrequested PMC transport honestly and keeps old receipts readable in %s',async locale=>{
 setLocale(locale);const failed={...receipt,status:'pmc_request_failed',scope:null,license:{...receipt.license,data_licenses:[{code:'CC0-1.0',url:'https://creativecommons.org/publicdomain/zero/1.0/',scope:'data'}]},responses:[{...receipt.responses[0],metadata_prefix:'pmc_fm',source_download_url:'/api/v1/projects/p1/literature/pmc/receipts/pmc1/raw/0'},{...receipt.responses[0],http_status:null,error:'pmc_request_failed',sha256:null,attempted:false,capture_status:'not_requested',received_bytes:0,retained_bytes:0,admission_code:'live_budget_exhausted'}]}
 expect(validPmcReceipt(failed,'p1')).toBe(true);const old={...receipt,responses:receipt.responses.map(({attempted,capture_status,received_bytes,retained_bytes,byte_limit,admission_code,...rest})=>{void attempted;void capture_status;void received_bytes;void retained_bytes;void byte_limit;void admission_code;return rest})};expect(validPmcReceipt(old,'p1')).toBe(true)
 expect(validPmcContent({source:failed,status:failed.status,scope:null,...page([{id:'pmc-item-1',kind:'paragraph',text:'Forbidden',location:evidence.location}],1,1,20)},'p1',failed as never,1)).toBe(false)
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/source?')?{source:failed,status:failed.status,scope:null,...page([],1,0,20)}:page([failed]))));render(<LiteraturePmc projectId="p1" referenceId="ref1" onSource={vi.fn()} onDenied={vi.fn()}/>);fireEvent.click(await screen.findByRole('button',{name:locale==='en'?'View saved source':'查看已保存来源'}));expect(await screen.findByText(new RegExp(locale==='en'?'Request not admitted; no HTTP sent':'未获准请求，未发送 HTTP'))).toBeTruthy();expect(screen.getByText('CC0-1.0')).toBeTruthy();expect(screen.queryByRole('button',{name:locale==='en'?'Quote this PMC excerpt':'从此 PMC 片段摘录'})).toBeNull();expect(screen.getAllByRole('link',{name:locale==='en'?'Download saved original XML':'下载已保存原始 XML'})).toHaveLength(1)
})
it.each(['zh-CN','en'] as const)('shows reconstructed old PMC capture as unrecorded in %s',async locale=>{
 setLocale(locale);const old={...receipt,responses:receipt.responses.map(r=>({...r,capture_recorded:false}))}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/source?')?{source:old,status:old.status,scope,...page([],1,0,20)}:page([old]))))
 render(<LiteraturePmc projectId="p1" referenceId="ref1" onSource={vi.fn()} onDenied={vi.fn()}/>);fireEvent.click(await screen.findByRole('button',{name:locale==='en'?'View saved source':'查看已保存来源'}))
 expect(await screen.findByText(new RegExp(locale==='en'?'Capture status was not separately recorded':'捕获状态未单独记录'))).toBeTruthy()
 expect(screen.queryByText(locale==='en'?'Complete response received':'完整接收')).toBeNull()
})
it.each(['zh-CN','en'] as const)('keeps failed business tasks distinct from completed calls and preserves stored estimates in %s',async locale=>{
 setLocale(locale);const failedTask={...task,status:'failed',display_status:'failed',error_code:'literature_assistance_invalid'},call={model:'gpt-6.1-sol',status:'completed',provider_status:'completed',error_code:null,provenance:'not_recorded',usage_status:'estimated',usage:{input_tokens:100,output_tokens:50,total_tokens:150,cached_input_tokens:0},estimated_cost_micro_usd:75529,created_at:stamp};const detail={task:failedTask,kind:'search_plan',input_version:task.input_version,result:null,real_calls_enabled:false,model_calls:[call]}
 expect(validAssistance(detail,'p1')).toBe(true);vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('assist1')?detail:page([detail]))));render(<LiteratureAssistance projectId="p1" researchTopic="topic" referenceId="" selection={null} onDenied={vi.fn()}/>);fireEvent.click(await screen.findByRole('button',{name:locale==='en'?'View suggestion and wait status':'查看建议与等待状态'}));expect(await screen.findByText('gpt-6.1-sol')).toBeTruthy();expect(screen.getByText(/0.075529/)).toBeTruthy();expect(screen.getByText(locale==='en'?'This suggestion task failed; saved calls and usage are retained.':'此建议任务失败，已保存调用与用量仍保留。')).toBeTruthy();expect(screen.queryByLabelText(locale==='en'?'Editable query copy':'可编辑检索式副本')).toBeNull()
})
it('does not rewrite the absence of legacy call projection as no call or zero cost',()=>{render(<ModelCallHistory/>);expect(screen.getByText('此历史响应未提供调用记录。')).toBeTruthy();expect(screen.queryByText('尚无已保存模型调用。')).toBeNull()})
it('translates every batch06 label in both language modes',()=>{for(const key of Object.keys(literatureBatch06Messages)){setLocale('en');expect(translate(key,{count:1,references:2,paragraphs:1,tables:1,received:1,retained:1,amount:'0.1'})).not.toMatch(/[\u3400-\u9fff]/);setLocale('zh-CN');expect(translate(key)).toMatch(/[\u3400-\u9fff]/)}})
it('translates every new component status, control and reading-scope label',()=>{
 setLocale('en');const missing:string[]=[]
 for(const file of ['LiteraturePmc.tsx','pmcApi.ts','ModelCallHistory.tsx','AssistanceResult.tsx','LiteratureAssistance.tsx','evidenceApi.ts']){const source=readFileSync(new URL(file,import.meta.url),'utf8');for(const match of source.matchAll(/'([^'\n]*[\u3400-\u9fff][^'\n]*)'/g)){if(/[\u3400-\u9fff]/.test(translate(match[1])))missing.push(match[1])}}
 expect(missing).toEqual([])
})
it('retains selection across evidence pages but saves manual decisions for the selected reference only',async()=>{
 const second={...evidence,id:'ev2',project_reference_id:'ref2',quote:'Second reference excerpt'},onSelection=vi.fn();const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){const body=JSON.parse(init.body as string);return Response.json({id:'review1',claim_id:'claim1',decided_by:'owner',created_at:stamp,...body})}
  if(url.includes('/claims/claim1/evidence?')){const n=Number(new URL(url,'http://local').searchParams.get('page'));return Response.json(page(n===1?[evidence]:[second],n,11))}
  return Response.json(url.includes('/claims/claim1?')?claim:url.includes('/claims?')?page([claim]):page([]))
 });vi.stubGlobal('fetch',fetch);render(<LiteratureClaims projectId="p1" referenceId="ref1" source={null} onSelection={onSelection} onDenied={vi.fn()}/>);fireEvent.change(await screen.findByLabelText('选择论述'),{target:{value:'claim1'}});fireEvent.click(await screen.findByLabelText('读取范围：PMC 正文片段'));fireEvent.click(within(screen.getByRole('navigation',{name:'证据分页'})).getByRole('button',{name:'下一页'}));fireEvent.click(await screen.findByLabelText('读取范围：PMC 正文片段'))
 await waitFor(()=>expect(onSelection.mock.calls.at(-1)![0].evidenceIds).toEqual(['ev1','ev2']))
 expect(new Set(onSelection.mock.calls.at(-1)![0].evidence.map((e:{project_reference_id:string})=>e.project_reference_id)).size).toBe(2)
 fireEvent.change(screen.getByLabelText('人工核验理由'),{target:{value:'Manual bounded review'}});fireEvent.click(screen.getByRole('button',{name:'保存人工核验'}));await waitFor(()=>expect(fetch.mock.calls.some(c=>c[1]?.method==='POST')).toBe(true));expect(JSON.parse(fetch.mock.calls.find(c=>c[1]?.method==='POST')![1]!.body as string).evidence_ids).toEqual(['ev1'])
})
it.each(['zh-CN','en'] as const)('identifies off-page abstract evidence and retained selections in %s',async locale=>{
 setLocale(locale)
 const first={...evidence,id:'off-page',project_reference_id:'ref2',reading_scope:'abstract',source:{kind:'abstract',search_id:'search2',receipt_id:'receipt2',sha256:hash},location:{abstract_index:0,start:0,end:14},quote:'Off-page abstract',bibliography:{title:'Synthetic second-page title',pmid:'456'}}
 const second={...first,id:'next-page',project_reference_id:'ref3',quote:'Another abstract',bibliography:{title:'Synthetic third-page title',pmid:'789'}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.includes('/claims/claim1/evidence?')?Response.json(page(Number(new URL(url,'http://local').searchParams.get('page'))===1?[first]:[second],Number(new URL(url,'http://local').searchParams.get('page')),11)):Response.json(url.includes('/claims/claim1?')?claim:url.includes('/claims?')?page([claim]):page([]))))
 render(<LiteratureClaims projectId="p1" referenceId="ref1" referenceTitles={{ref1:'First-page title'}} source={null} onSelection={vi.fn()} onDenied={vi.fn()}/>)
 fireEvent.change(await screen.findByLabelText(locale==='en'?'Choose claim':'选择论述'),{target:{value:'claim1'}})
 expect(await screen.findByText('Synthetic second-page title · PMID 456')).toBeTruthy()
 fireEvent.click(await screen.findByLabelText(locale==='en'?'Reading scope: abstract':'读取范围：摘要'))
 fireEvent.click(within(screen.getByRole('navigation',{name:locale==='en'?'Evidence pages':'证据分页'})).getByRole('button',{name:locale==='en'?'Next page':'下一页'}))
 expect(await screen.findByText('Synthetic third-page title · PMID 789')).toBeTruthy()
 expect(screen.getByText(/Synthetic second-page title · PMID 456/)).toBeTruthy()
})
it('keeps the actual PMC excerpt scope and saved XML link in citation history',()=>{
 const view={id:'draft1',revision:1,current_changes:[],snapshot:{output_language:'en',output:{text:'Frozen cited text',references:[]},paragraphs:[{id:'paragraph1',fragments:[{kind:'claim',text:'Frozen supported claim',bindings:[{review_id:'review1',metadata:{title:'Saved reference title'},review:{reason:'Saved manual decision',limitations:'Selected excerpts only'},metadata_source:{revision:1,source:{source_kind:'synthetic_fixture',source_download_url:'/api/v1/projects/p1/literature/receipts/receipt1/source'},source_description:'Saved bibliography',basis:'Saved basis',source_verified:true,source_current:true},evidence:[evidence]}]}]}]}}
 render(<CitationSnapshot projectId="p1" view={view as never}/>);fireEvent.click(screen.getByText('本版引用来源与证据'));expect(screen.getByText(/Reading scope for this citation: PMC body excerpt/)).toBeTruthy();expect(screen.getByText(evidence.quote)).toBeTruthy();expect(screen.getByRole('link',{name:'下载已保存原始 XML'}).getAttribute('href')).toBe('/api/v1/projects/p1/literature/pmc/receipts/pmc1/raw/1');expect(screen.queryByText('本次阅读范围：用户材料摘录')).toBeNull()
})
