import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ProjectLiterature from './ProjectLiterature'
import CitationSnapshot from './CitationSnapshot'
import LiteratureChecks from './LiteratureChecks'
import type {DraftView} from './citationApi'
import {setLocale} from '../../shared/i18n'
const stamp='2026-10-19T01:00:00Z'
const page=(items:unknown[],total=items.length,p=1)=>({project_id:'p1',items,total,page:p,page_size:10})
const source={search_id:'search1',receipt_id:'receipt1',source_kind:'synthetic_fixture',query:'Synthetic query',effective_query:'Synthetic query',retrieved_at:stamp,cached:false,ordinal:1,source_download_url:'/api/v1/projects/p1/literature/receipts/receipt1/source'}
const record={pmid:'123',title:'Synthetic original title',authors:['Original Author'],year:2025,journal:'Synthetic Journal',doi:'10.synthetic/example',abstract:[],abstract_status:'not_returned',full_text_status:'not_acquired',verification_status:'not_verified',doi_resolution_status:'not_checked',keywords:[],mesh_terms:[],full_text_links:[]}
const reference={id:'ref1',reference_id:'record1',project_id:'p1',pmid:'123',record,selection:{status:'candidate',note:'',revision:1},source,created_at:stamp,updated_at:stamp}
const review={id:'review1',claim_id:'claim1',claim_revision:1,project_reference_id:'ref1',evidence_ids:['evidence1'],status:'partial',relevance:'related',reason:'User original reason 原文',narrowed_statement:'User original narrowed claim',limitations:'User original limitation',decided_by:'tester',created_at:stamp}
const checkCandidate={...reference,sources:[{...source,output_language:'en'}],saved_record:null,doi_resolution:null,content_support:[{claim_id:'claim1',claim_revision:1,content:'Original claim 原文',output_language:'en',latest_review:review,source_current:true}]}
function receipt(kind='saved_record',id='check1',language='en',status=kind==='saved_record'?'synthetic_match':'resolved') {return {id,project_reference_id:'ref1',kind,search_id:'search1',source_kind:'synthetic_fixture',output_language:language,created_at:stamp,source_current:true,result:{status,network_attempted:false,execution_kind:kind==='saved_record'?'local':'synthetic_fixture',error_code:null,doi:kind==='saved_record'?null:'10.synthetic/example',http_status:kind==='saved_record'?null:302,resolution_target:kind==='saved_record'?null:'https://synthetic.invalid/article',source:{search_id:'search1',receipt_id:'receipt1',source_kind:'synthetic_fixture',sha256:'a'.repeat(64),record_sha256:'b'.repeat(64),pmid:'123'}}}}
function setup(options:{synthetic?:boolean;candidate?:unknown;citationClaims?:unknown[];history?:ReturnType<typeof receipt>[];postFail?:boolean;historyFail?:boolean;override?:(url:string,init?:RequestInit)=>Promise<Response>|Response|undefined}={}){
 let history=options.history??[];let candidate={...checkCandidate,...options.candidate as object}
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  const custom=options.override?.(url,init);if(custom)return custom
  if(url.includes('/checks/')){
   if(url.endsWith('/config'))return Response.json({project_id:'p1',page_size:10,check_kinds:['saved_record','doi_resolution'],doi_check_available:!!options.synthetic,doi_network_enabled:false,doi_execution_kind:options.synthetic?'synthetic_fixture':'disabled',real_model_calls:false})
   if(url.endsWith('/receipts')&&init?.method==='POST'){
    if(options.postFail)return Response.json({detail:{code:'literature_source_conflict'}},{status:409})
    const body=JSON.parse(init.body as string);const item=receipt(body.kind,`check${history.length+1}`);history=[item,...history];candidate={...candidate,[body.kind]:item};return Response.json(item,{status:201})
   }
   if(url.includes('/history?'))return options.historyFail?Response.json({}, {status:500}):Response.json(page(history))
   if(url.endsWith('/references/ref1'))return Response.json(candidate)
   throw Error(`Unexpected check request: ${url}`)
  }
  if(url.endsWith('/citations/config'))return Response.json({project_id:'p1',format:'nlm_numeric_journal_v1',real_model_calls:false})
  if(url.includes('/citations/candidates?'))return Response.json(page([{...reference,metadata:null,materials:[],has_abstract:false,holds_full_paper:false,claims:options.citationClaims??[],todos:[]}]))
  if(url.includes('/citations/drafts?'))return Response.json(page([]))
  if(url.endsWith('/config'))return Response.json({available:false,reason:null,candidate_limits:[20,50,100],default_limit:20,page_size:10,publication_types:[],full_text_acquisition:false,claim_verification:false})
  if(url.includes('/references/ref1?'))return Response.json({...reference,sources:{items:[source],total:1,page:1,page_size:10},decisions:[]})
  if(url.includes('/references?'))return Response.json(page([reference]))
  if(url.includes('/searches?'))return Response.json(page([]))
  throw Error(url)
 });vi.stubGlobal('fetch',fetch);return fetch
}
async function open(entry:'literature'|'citations'='literature'){
 render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active/>);
 if(entry==='citations')fireEvent.click(screen.getByRole('button',{name:'引用工作台'}))
 else fireEvent.click(await screen.findByRole('button',{name:'查看候选详情'}))
 fireEvent.click(await screen.findByRole('button',{name:'查看三项核验与历史'}));return await screen.findByRole('region',{name:'文献三项核验'})
}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it.each(['literature','citations'] as const)('opens independent checks and history from %s without fetching a paged check list',async entry=>{
 const fetch=setup({history:[receipt()]});const region=await open(entry)
 expect(await within(region).findAllByText('来源匹配')).not.toHaveLength(0);expect(within(region).getByText('DOI 解析')).toBeTruthy();expect(within(region).getByText('按论述人工支持')).toBeTruthy()
 expect(within(region).getByText('Original claim 原文')).toBeTruthy();expect(within(region).getByText('User original reason 原文')).toBeTruthy();expect(within(region).getByText('Partially supported')).toBeTruthy()
 expect(within(region).getByText('核验历史')).toBeTruthy();expect(fetch.mock.calls.some(([u])=>u.includes('/checks/candidates'))).toBe(false)
 expect(screen.queryByText('书目存在性：未核验')).toBeNull();expect(screen.queryByText('DOI 解析：未核验')).toBeNull();expect(screen.queryByText('DOI 未检查解析')).toBeNull()
 expect(within(region).queryByText(/receipt1|check1|aaaaaa/)).toBeNull()
})
it('disables DOI requests in normal configuration and keeps source checking local',async()=>{
 const fetch=setup();const region=await open();const doi=await within(region).findByRole('button',{name:'检查 DOI 解析'})
 expect((doi as HTMLButtonElement).disabled).toBe(true);fireEvent.click(doi)
 expect(await within(region).findByText('Real DOI requests are disabled in this environment.')).toBeTruthy();expect(fetch.mock.calls.some(([,i])=>i?.method==='POST')).toBe(false)
 fireEvent.click(within(region).getByRole('button',{name:'核查保存来源'}));expect(await within(region).findAllByText('Offline synthetic source match')).not.toHaveLength(0)
 const post=fetch.mock.calls.find(([,i])=>i?.method==='POST')!;expect(JSON.parse(post[1]!.body as string)).toEqual({kind:'saved_record',search_id:'search1'});expect(new Headers(post[1]!.headers).get('Idempotency-Key')).toBeTruthy()
})
it('appends intentional checks with new keys and marks simulated DOI success prominently',async()=>{
 const fetch=setup({synthetic:true});const region=await open();const button=await within(region).findByRole('button',{name:'模拟 DOI 解析（离线）'})
 await waitFor(()=>expect((button as HTMLButtonElement).disabled).toBe(false));fireEvent.click(button);await within(region).findAllByText('Offline simulation — no real DOI verification')
 await waitFor(()=>expect(within(region).getAllByText('DOI resolves to a landing target')).not.toHaveLength(0));fireEvent.click(button)
 await waitFor(()=>expect(fetch.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(2))
 const posts=fetch.mock.calls.filter(([,i])=>i?.method==='POST');expect(new Headers(posts[0][1]!.headers).get('Idempotency-Key')).not.toBe(new Headers(posts[1][1]!.headers).get('Idempotency-Key'))
 await waitFor(()=>expect(within(region).getByText('共 2 项 · 第 1 / 1 页')).toBeTruthy());expect(fetch.mock.calls.every(([u])=>u.startsWith('/api/v1/'))).toBe(true)
 expect(within(region).getAllByRole('link',{name:'打开落地目标（不会自动访问）'})[0].getAttribute('rel')).toContain('noopener')
})
it('keeps immutable history visible after save and history refresh failures',async()=>{
 let failHistory=false;const fetch=setup({history:[receipt()],postFail:true,override:u=>failHistory&&u.includes('/checks/')&&u.includes('/history?')?Response.json({}, {status:500}):undefined});const region=await open()
 await within(region).findByText('Offline synthetic source match');fireEvent.click(within(region).getByRole('button',{name:'核查保存来源'}));await within(region).findByRole('alert')
 failHistory=true;fireEvent.click(within(region).getByRole('button',{name:'刷新核验记录'}));await waitFor(()=>expect(fetch.mock.calls.filter(([u])=>u.includes('/history?')).length).toBeGreaterThan(1))
 expect(within(region).getByText('Offline synthetic source match')).toBeTruthy();expect(within(region).getByText('核验历史')).toBeTruthy()
})
it('retains the last successful history page when the next page fails and supports return and retry',async()=>{
 const firstPage=Array.from({length:10},(_,i)=>receipt('saved_record',`check${i+1}`));let failNext=true
 const fetch=setup({override:url=>url.includes('/checks/')&&url.includes('/history?')?url.endsWith('page=2')?(failNext?Response.json({}, {status:500}):Response.json(page([receipt('doi_resolution','check11','en','timeout')],11,2))):Response.json(page(firstPage,11)):undefined})
 const region=await open();const nav=()=>within(region).getByRole('navigation',{name:'核验历史分页'})
 await within(region).findByText('共 11 项 · 第 1 / 2 页');fireEvent.click(within(nav()).getByRole('button',{name:'下一页'}));await within(region).findByRole('alert')
 expect(within(region).getAllByText('Offline synthetic source match')).toHaveLength(10);expect(within(nav()).getByText('共 11 项 · 第 1 / 2 页')).toBeTruthy()
 expect(within(region).getByText('第 2 页读取失败；当前显示已读第 1 页。')).toBeTruthy()
 fireEvent.click(within(region).getByRole('button',{name:'返回已读第 1 页'}));await waitFor(()=>expect(fetch.mock.calls.filter(([url])=>url.endsWith('/history?page=1'))).toHaveLength(2))
 expect(within(region).queryByRole('button',{name:'重试第 2 页'})).toBeNull()
 fireEvent.click(within(nav()).getByRole('button',{name:'下一页'}));await within(region).findByRole('button',{name:'重试第 2 页'})
 failNext=false;fireEvent.click(within(region).getByRole('button',{name:'重试第 2 页'}));await within(region).findByText('DOI resolution timed out')
 expect(within(nav()).getByText('共 11 项 · 第 2 / 2 页')).toBeTruthy();expect(within(region).queryByText('Offline synthetic source match')).toBeNull()
 fireEvent.click(within(nav()).getByRole('button',{name:'上一页'}));await within(region).findByText('共 11 项 · 第 1 / 2 页');expect(within(region).getAllByText('Offline synthetic source match')).toHaveLength(10)
})
it.each(['project','reference'] as const)('does not reuse a retained history page after changing %s',async scope=>{
 let release!:(value:Response)=>void
 setup({override:url=>{
  if(url.includes('/p1/')&&url.includes('/references/ref1/history?'))return url.endsWith('page=2')?new Promise<Response>(resolve=>release=resolve):Response.json(page([receipt()],11))
  if(url.includes('/p2/')||url.includes('/checks/references/ref2')){
   if(url.endsWith('/config'))return Response.json({project_id:'p2',page_size:10,check_kinds:['saved_record','doi_resolution'],doi_check_available:false,doi_network_enabled:false,doi_execution_kind:'disabled',real_model_calls:false})
   if(url.includes('/history?'))return Response.json(page([]))
   return Response.json({...checkCandidate,id:scope==='reference'?'ref2':'ref1',content_support:[]})
  }
  return undefined
 }})
 const view=render(<LiteratureChecks projectId="p1" referenceId="ref1" onDenied={vi.fn()}/>);await screen.findByText('Offline synthetic source match');fireEvent.click(within(screen.getByRole('navigation',{name:'核验历史分页'})).getByRole('button',{name:'下一页'}));await waitFor(()=>expect(release).toBeTypeOf('function'))
 view.rerender(<LiteratureChecks projectId={scope==='project'?'p2':'p1'} referenceId={scope==='reference'?'ref2':'ref1'} onDenied={vi.fn()}/>);expect(screen.queryByText('Offline synthetic source match')).toBeNull()
 await act(async()=>release(Response.json({}, {status:500})));await screen.findByText('尚无核验历史。');expect(screen.queryByText('Offline synthetic source match')).toBeNull();expect(screen.queryByText('Original claim 原文')).toBeNull()
})
it('retains historical status while warning about a changed source and blocks unsafe landing URLs',async()=>{
 const old=receipt('doi_resolution');old.source_current=false;old.result.resolution_target='javascript:alert(1)'
 setup({history:[old],candidate:{doi_resolution:old,saved_record:receipt('saved_record','new','en','source_conflict')}});const region=await open()
 expect(await within(region).findAllByText('Saved source conflict — review required')).not.toHaveLength(0);expect(within(region).getAllByText('Current source differs or is unavailable; the historical result is unchanged.')).not.toHaveLength(0)
 expect(within(region).queryByRole('link',{name:'打开落地目标（不会自动访问）'})).toBeNull();expect(within(region).getAllByText('Landing target cannot be safely opened.')).not.toHaveLength(0)
 expect(within(region).getAllByRole('link',{name:'下载原始 JSON/XML'}).length).toBeGreaterThan(0)
})
it('clears checks and ignores late data after switching projects',async()=>{
 let release!:(r:Response)=>void
 setup({override:u=>u.endsWith('/checks/references/ref1')?new Promise<Response>(r=>release=r):u.includes('/p2/')?Response.json(u.endsWith('/config')?{available:false,reason:null,candidate_limits:[20,50,100],default_limit:20,page_size:10,publication_types:[],full_text_acquisition:false,claim_verification:false}:{...page([]),project_id:'p2'}):undefined})
 const view=render(<ProjectLiterature projectId="p1" researchTopic="Old" active/>);fireEvent.click(await screen.findByRole('button',{name:'查看候选详情'}));fireEvent.click(await screen.findByRole('button',{name:'查看三项核验与历史'}));await waitFor(()=>expect(release).toBeTypeOf('function'))
 view.rerender(<ProjectLiterature projectId="p2" researchTopic="New" active/>);await act(async()=>release(Response.json(checkCandidate)))
 expect(screen.queryByRole('region',{name:'文献三项核验'})).toBeNull();expect(screen.queryByText('Original claim 原文')).toBeNull()
})
it('uses English controls with Chinese saved explanations and never translates bibliography or user reasons',async()=>{
 setLocale('en');setup({candidate:{sources:[{...source,output_language:'zh-CN'}],saved_record:receipt('saved_record','check1','zh-CN'),content_support:[{...checkCandidate.content_support[0],output_language:'zh-CN'}]}})
 render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active/>);fireEvent.click(await screen.findByRole('button',{name:'View candidate details'}));fireEvent.click(await screen.findByRole('button',{name:'View checks and history'}))
 const region=await screen.findByRole('region',{name:'Three independent literature checks'});expect(await within(region).findByText('离线合成来源匹配')).toBeTruthy();expect(within(region).getByText('部分支持')).toBeTruthy();expect(within(region).getByRole('button',{name:'Check saved source'})).toBeTruthy();expect(within(region).getByText('User original reason 原文')).toBeTruthy();expect(screen.getAllByText('Synthetic original title').length).toBeGreaterThan(0)
})
it('identifies every result source separately from the next selected check source',async()=>{
 setup({history:[receipt()],candidate:{sources:[{...source,output_language:'en'},{...source,search_id:'search2',receipt_id:'receipt2',output_language:'zh-CN'}],saved_record:receipt()}})
 const region=await open();fireEvent.change(await within(region).findByLabelText('下一次核查来源'),{target:{value:'search2'}})
 expect(within(region).getAllByText('Result from saved search 1')).toHaveLength(2)
 expect(within(region).queryByText('Result from saved search 2')).toBeNull()
 expect(within(region).getByText('当前环境关闭真实 DOI 请求。')).toBeTruthy()
})
it.each([['zh-CN','en'],['en','zh-CN']] as const)('uses the merged citation support basis in saved claim language (%s UI / %s claim)',async(ui,language)=>{
 setLocale(ui);setup({citationClaims:[{id:'claim1',revision:1,content:'Original claim 原文',latest_review:review,review_source_current:false,citation_eligible:false,supplement_rounds_used:1}],candidate:{content_support:[{...checkCandidate.content_support[0],output_language:language,source_current:false}]}})
 render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active/>);fireEvent.click(screen.getByRole('button',{name:ui==='en'?'Citation workbench':'引用工作台'}));await screen.findByText('Synthetic original title')
 expect(screen.queryByText(ui==='en'?'View support basis per claim':'按论述查看支持依据')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:ui==='en'?'View checks and history':'查看三项核验与历史'}))
 const region=await screen.findByRole('region',{name:ui==='en'?'Three independent literature checks':'文献三项核验'}),status=language==='en'?'Partially supported':'部分支持',limitation=language==='en'?'Current source differs or is unavailable; the historical result is unchanged.':'当前来源已变化或不可用；历史结果保留原样。'
 expect(await within(region).findByText(status)).toBeTruthy();expect(within(region).getByText(limitation)).toBeTruthy();expect(screen.getAllByText('User original reason 原文')).toHaveLength(1)
 expect(within(region).getByText('User original limitation')).toBeTruthy();expect(within(region).getByText('User original narrowed claim')).toBeTruthy();expect(within(region).getByText('Original claim 原文')).toBeTruthy()
 act(()=>setLocale(ui==='en'?'zh-CN':'en'));expect(within(region).getByText(status)).toBeTruthy();expect(within(region).getByText(limitation)).toBeTruthy();expect(within(region).getByRole('button',{name:ui==='en'?'去核验论述与证据':'Review claims and evidence'})).toBeTruthy()
})
it.each([['zh-CN','en'],['en','zh-CN']] as const)('uses saved citation version language (%s UI / %s output)',(ui,outputLanguage)=>{
 setLocale(ui);const view={id:'draft1',revision:1,current_changes:[{reasons:['reference_source_changed']}],snapshot:{output_language:outputLanguage,paragraphs:[],output:{text:'Frozen original text 原文',references:[]}}} as unknown as DraftView
 render(<CitationSnapshot projectId="p1" view={view}/>);expect(screen.getByText(outputLanguage==='en'?'The text and references below come from this frozen version; save a new version to update them.':'以下正文与参考文献均来自本版冻结快照；编辑后须保存新版本更新输出。')).toBeTruthy();expect(screen.getByText(outputLanguage==='en'?'Reference source has changed':'文献来源已变化')).toBeTruthy();expect(screen.getByText('Frozen original text 原文')).toBeTruthy()
})
