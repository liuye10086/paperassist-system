import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import WritingScienceReview from './WritingScienceReview'
import ManuscriptWriting from './ManuscriptWriting'
import WritingLanguageReview from './WritingLanguageReview'
import WritingLive from './WritingLive'
import {manuscriptFixture,snapshotFixture} from './manuscriptFixtures'
import {scienceReview,languageArtifact,languageContext,reviewContext,liveRequest,bundleFixture,hash,rawSnapshot} from './writingLiveFixtures'
import {validPreviewInput,bodyProjection,type Authorization,type Bundle,type LiveRequest,type PreviewInput} from './writingLiveTypes'
import {setLocale} from '../../shared/i18n'
import {webcrypto} from 'node:crypto'
import {findTechnicalText} from '../../test/technicalText'
import type {Snapshot,ManuscriptVersion} from './manuscriptTypes'
const chapters=[{id:'declaration-x',title:'人工声明',purpose:'manual',output_language:'zh-CN'}, {id:'refs-middle',title:'文献',purpose:'references',output_language:'en'}, {id:'abstract-zh',title:'中文摘要',purpose:'abstract',output_language:'zh-CN'}, {id:'abstract-en',title:'English Abstract',purpose:'abstract',output_language:'en'}, {id:'methods-dynamic',title:'独立方法',purpose:'materials_and_methods',output_language:'en'}].map(c=>({...c,level:2,result_group_ids:[]}))
const snapshot={...snapshotFixture,thesis_context:{schema_version:1,profile:{revision:2,school:'测试学校',department:'',major:'',degree_type:'硕士',education_level:'研究生',applicable_version:'2026',bound_confirmation_id:'confirm1'},template_version_id:'template1',confirmation_id:'confirm1',confirmation_sha256:'a'.repeat(64),confirmation:{id:'confirm1',chapters:chapters.map(({id,title,level})=>({id,title,level}))},source_files:[],chapters},sections:chapters.map(c=>({...c,paragraphs:[{id:c.id+':1',text:c.title,origin:'user_provided',source_ids:[],citations:[]}]})),school_content_report:{rules_version:'school_v1',issues:[],can_publish:true,scientifically_verified:false}} as unknown as Snapshot
const props={projectId:'p1',manuscriptId:'m1',version:{...manuscriptFixture.versions[0],snapshot} as ManuscriptVersion,onPublished:vi.fn()}
afterEach(()=>{cleanup();setLocale('zh-CN');sessionStorage.clear();vi.useRealTimers();vi.unstubAllGlobals()})
it('uses only the school preview contract in a thesis customer session',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{}:{items:[],capabilities:{real_calls_enabled:false}}))
 vi.stubGlobal('fetch',fetcher)
 render(<WritingLive {...props} customerThesis/>)
 await waitFor(()=>expect(screen.getByLabelText('写作方式').matches(':disabled')).toBe(false))
 expect(screen.queryByLabelText('文章类型与范围编辑')).toBeNull()
 expect(screen.queryByRole('button',{name:'提交已授权写作'})).toBeNull()
 expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
 fireEvent.click(screen.getByRole('button',{name:'更新写作材料预览'}))
 await waitFor(()=>expect(fetcher.mock.calls.find(([url,init])=>url.endsWith('/writing-previews')&&init?.method==='POST')).toBeTruthy())
 const call=fetcher.mock.calls.find(([,init])=>init?.method==='POST')!
 expect(JSON.parse(String(call[1]?.body))).toMatchObject({schema_version:3,base_revision:1,mode:'full_draft'})
 expect(fetcher.mock.calls.every(([url])=>!url.includes('/tasks/'))).toBe(true)
})
it('opens school controlled writing and sends schema3 dynamic writable targets while displaying protected chapters',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{}:{items:[],capabilities:{real_calls_enabled:false}}));vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptWriting {...props}/>);fireEvent.click(screen.getByRole('button',{name:'受控写作与人工审核'}));await screen.findByRole('region',{name:'受控写作工作区'})
 await waitFor(()=>expect(screen.getByLabelText('受控写作方式').matches(':disabled')).toBe(false))
 fireEvent.change(screen.getByLabelText('受控写作方式'),{target:{value:'rewrite_section'}})
 const select=screen.getByLabelText('重写目标章节');expect(within(select).getAllByRole('option').map(x=>(x as HTMLOptionElement).value)).toEqual(['abstract-zh','abstract-en','methods-dynamic'])
 expect(screen.getByText(/declaration-x.*zh-CN/)).toBeTruthy()
 fireEvent.change(select,{target:{value:'methods-dynamic'}});fireEvent.click(screen.getByRole('button',{name:'冻结完整外发预览'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([,i])=>i?.method==='POST')).toBe(true))
 const input=JSON.parse(String(fetcher.mock.calls.find(([,i])=>i?.method==='POST')![1]?.body));expect(input.schema_version).toBe(3);expect(input.target_section).toBe('methods-dynamic')
})
it('validates dynamic schema3 input and digests only school generated purposes in frozen order',()=>{
 const input={schema_version:3,base_revision:1,mode:'rewrite_section',target_section:'methods-dynamic',output_language:'en',instructions:'',keywords:[],acknowledgements:'',selected_source_ids:[],selected_evidence_ids:[]};expect(validPreviewInput(input)).toBe(true)
 expect(validPreviewInput({...input,schema_version:2})).toBe(false)
 expect(bodyProjection(snapshot,{}).map(c=>c.id)).toEqual(['abstract-zh','abstract-en','methods-dynamic'])
})
it('selects only writable school paragraphs for a scoped article request',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{}:{items:[],capabilities:{real_calls_enabled:false}}));vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptWriting {...props}/>);fireEvent.click(screen.getByRole('button',{name:'受控写作与人工审核'}))
 await waitFor(()=>expect(screen.getByLabelText('受控写作方式').matches(':disabled')).toBe(false))
 fireEvent.click(screen.getByLabelText('文章类型与范围编辑'))
 fireEvent.change(screen.getByLabelText('受控写作方式'),{target:{value:'polish'}})
 const select=screen.getByLabelText('目标章节') as HTMLSelectElement
 expect(Array.from(select.options,o=>o.value)).toEqual(['abstract-zh','abstract-en','methods-dynamic'])
 for(const option of Array.from(select.options))option.selected=option.value==='methods-dynamic'
 fireEvent.change(select);fireEvent.click(screen.getByRole('button',{name:'冻结完整外发预览'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([,i])=>i?.method==='POST')).toBe(true))
 const body=JSON.parse(String(fetcher.mock.calls.find(([,i])=>i?.method==='POST')![1]?.body))
 expect(body).toMatchObject({schema_version:4,document_kind:'thesis',article_type:'research',mode:'polish',target_sections:['methods-dynamic'],keywords:[],acknowledgements:''})
})
it('reviews identities and actual school references as supplied and invalidates decisions after school options change',async()=>{
 const review={...scienceReview,candidate:snapshot};const inventory=[{location:'identity:p1',kind:'paragraph',text:'本人',content_sha256:'e'.repeat(64),scope:'label',target_language:'zh-CN',chapter_id:'declaration-x',protected_identity:true},{location:'body:p2',kind:'paragraph',text:'Methods',content_sha256:'f'.repeat(64),scope:'narrative',target_language:'en',chapter_id:'methods-dynamic',protected_identity:false},{location:'refs:p3',kind:'export_text',text:'[1] An English reference in a Chinese thesis.',content_sha256:'a'.repeat(64),scope:'reference_metadata',target_language:'zh-CN',chapter_id:'refs-middle'}]
 const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('language-context')?{...languageContext,schema_version:3,candidate:snapshot,inventory,editable_fields:[]}:{items:[]}));vi.stubGlobal('fetch',fetcher)
 render(<WritingLanguageReview projectId="p1" manuscriptId="m1" baseRevision={1} review={review} onPublished={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'读取真实 DOCX 全语言清单'}));await screen.findByRole('group',{name:/核对项目 1/})
 const identity=screen.getByRole('group',{name:/核对项目 1/}),body=screen.getByRole('group',{name:/核对项目 2/})
 const reference=within(screen.getByRole('group',{name:/核对项目 3/}))
 expect(within(identity).queryByRole('option',{name:'目标语言文字已逐项核对'})).toBeNull();expect(within(body).queryByRole('option',{name:'已逐项核对用户提供的身份原文'})).toBeNull()
 expect(reference.getByRole('option',{name:'已核对参考文献原文'})).toBeTruthy()
 expect(within(body).queryByRole('option',{name:'已核对参考文献原文'})).toBeNull()
 expect(within(identity).getByLabelText('此项语言决定')).toHaveProperty('value','')
 fireEvent.change(within(identity).getByLabelText('此项语言决定'),{target:{value:'provided_literal'}});fireEvent.change(within(identity).getByLabelText('此项语言审核理由'),{target:{value:'核对本人原文'}})
 fireEvent.change(within(body).getByLabelText('此项语言决定'),{target:{value:'target_language'}});fireEvent.change(within(body).getByLabelText('此项语言审核理由'),{target:{value:'English checked'}})
 fireEvent.change(reference.getByLabelText('此项语言决定'),{target:{value:'provided_literal'}})
 fireEvent.change(reference.getByLabelText('此项语言审核理由'),{target:{value:'已核对书目原始著录'}})
 expect(screen.getByRole('button',{name:'封存独立语言审核'}).matches(':disabled')).toBe(false)
 fireEvent.change(screen.getByLabelText('英文题名'),{target:{value:'Changed title'}})
 expect(screen.getByRole('alert').textContent).toContain('旧清单决定和发布选择已失效')
 fireEvent.click(screen.getByRole('button',{name:'预览修正后的完整语言清单'}));await waitFor(()=>expect(screen.getByRole('button',{name:'封存独立语言审核'}).matches(':disabled')).toBe(true))
 const posts=fetcher.mock.calls.filter(([u,i])=>u.endsWith('language-context')&&i?.method==='POST');expect(JSON.parse(String(posts.at(-1)![1]?.body))).toMatchObject({schema_version:3,school:{english_title:'Changed title'}})
})


it('requires independent checks for both school abstracts and preserves frozen title after editing a later chapter',async()=>{
 const required=snapshot.sections!.filter(c=>['abstract','materials_and_methods'].includes(c.purpose!)).flatMap(c=>c.paragraphs.map(p=>p.id));const context={...reviewContext,candidate:snapshot,reviews:[],required_paragraph_ids:required,paragraph_languages:Object.fromEntries(snapshot.sections!.flatMap(c=>c.paragraphs.map(p=>[p.id,c.output_language]))),abstract_chapter_ids:['abstract-zh','abstract-en']}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>Response.json(url.endsWith('/review-context')?context:url.endsWith('/reviews')&&init?.method==='POST'?{}:{items:[]}));vi.stubGlobal('fetch',fetcher)
 render(<WritingScienceReview projectId="p1" manuscriptId="m1" request={{...liveRequest,input:{...liveRequest.input,schema_version:3},candidate:snapshot}} onPublished={vi.fn()}/>);fireEvent.click(screen.getByRole('button',{name:'读取精确科学审核上下文'}));await screen.findByLabelText('精确审后文本 methods-dynamic:1')
 for(const id of required){fireEvent.change(screen.getByLabelText('段落主张分类 '+id),{target:{value:'non_claim'}});fireEvent.change(screen.getByLabelText('科学核对理由 '+id),{target:{value:'逐段核对'}})}
 for(const label of ['标题研究对象一致','标题方向一致','标题强度一致'])fireEvent.click(screen.getByLabelText(label));fireEvent.change(screen.getByLabelText('标题一致性依据'),{target:{value:'冻结题名符合正文'}})
 const groups=['abstract-zh','abstract-en'].map(id=>screen.getByRole('group',{name:new RegExp(' · '+id+'$')}));
 for(const group of groups)for(const label of ['摘要目的一致','摘要方法一致','摘要关键结果一致','摘要结论一致'])fireEvent.click(within(group).getByLabelText(label))
 fireEvent.change(screen.getByLabelText('摘要一致性依据 abstract-zh'),{target:{value:'中文摘要逐项核对'}});expect(screen.getByRole('button',{name:'封存本次科学审核'}).matches(':disabled')).toBe(true)
 fireEvent.change(screen.getByLabelText('摘要一致性依据 abstract-en'),{target:{value:'English abstract checked'}});fireEvent.click(screen.getByRole('button',{name:'封存本次科学审核'}));await waitFor(()=>expect(fetcher.mock.calls.some(([,i])=>i?.method==='POST')).toBe(true))
 const body=JSON.parse(String(fetcher.mock.calls.find(([,i])=>i?.method==='POST')![1]?.body));expect(body.schema_version).toBe(3);expect(Object.keys(body.consistency.abstracts)).toEqual(['abstract-zh','abstract-en']);expect(body.consistency.abstract).toBeUndefined();expect(body.paragraphs).toHaveLength(3)
})

it('keeps A single-language reference ordering independent of the final generated chapter',()=>{
 const a={...snapshot,sections:snapshot.sections!.filter(c=>c.id!=='abstract-en').map(c=>({...c,output_language:'en' as const}))};expect(bodyProjection(a,{}).map(c=>c.id)).toEqual(['abstract-zh','methods-dynamic']);expect(a.sections[1].purpose).toBe('references')
 expect(validPreviewInput({schema_version:3,base_revision:1,mode:'rewrite_section',target_section:'学校:动态/章节-方法',output_language:'en',instructions:'',keywords:[],acknowledgements:'',selected_source_ids:[],selected_evidence_ids:[]})).toBe(true)
})
it('creates each literature claim in its school paragraph language instead of the project language',async()=>{
 const id='abstract-zh:1';const context={...reviewContext,candidate:snapshot,reviews:[],required_paragraph_ids:[id],claim_contexts:{[id]:'school-claim-exact'},paragraph_languages:{[id]:'zh-CN'},abstract_chapter_ids:['abstract-zh','abstract-en']}
 const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/review-context')?context:{items:[]}));vi.stubGlobal('fetch',fetcher)
 render(<WritingScienceReview projectId="p1" manuscriptId="m1" request={{...liveRequest,input:{...liveRequest.input,schema_version:3},candidate:snapshot}} onPublished={vi.fn()}/>);fireEvent.click(screen.getByRole('button',{name:'读取精确科学审核上下文'}));await screen.findByLabelText('段落主张分类 '+id)
 fireEvent.change(screen.getByLabelText('段落主张分类 '+id),{target:{value:'literature_claim'}});fireEvent.click(screen.getByRole('button',{name:'为此精确文本创建新主张'}));await waitFor(()=>expect(fetcher.mock.calls.some(([,i])=>i?.method==='POST')).toBe(true));const post=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(JSON.parse(String(post[1]?.body))).toMatchObject({output_language:'zh-CN',context:'school-claim-exact',content:'中文摘要'})
})

it('offers a figure version in its frozen school chapter language when the project language differs',async()=>{
 const figure={id:'figure-local',number:1,title:'中文结果图',caption:'中文图示',sha256:'a'.repeat(64),source_ids:['figure-source'],panels:[]}
 const group={id:'results-group',title:'Results',paragraphs:[],tables:[],figures:[figure]}
 const resultChapter={id:'results-zh',title:'中文结果',level:1,purpose:'results' as const,output_language:'zh-CN' as const,result_group_ids:[group.id],paragraphs:[]}
 const candidate={...snapshot,output_language:'en' as const,results_groups:[group],sections:[...snapshot.sections!,resultChapter],thesis_context:{...snapshot.thesis_context!,chapters:[...snapshot.thesis_context!.chapters,resultChapter]},sources:[{kind:'figure' as const,id:'figure-source',file_id:'file-local',role:'image_observation' as const,label:'Synthetic figure',sha256:'a'.repeat(64),download_url:null,content:{}}]}
 const review={...scienceReview,candidate}
 const version={schema_version:1,id:'zh-version',output_language:'zh-CN',mode:'no_text_confirmation',original:{kind:'figure',id:'figure-source',file_id:'file-local',sha256:figure.sha256},sha256:'b'.repeat(64),snapshot_sha256:'c'.repeat(64),data_fingerprint:null,geometry_fingerprint:null,text_manifest:[],title:'中文图版本',caption:'中文图',download_url:'/api/v1/projects/p1/manuscript-figure-language-versions/zh-version/download'}
 const english={...version,id:'en-version',output_language:'en',title:'English figure version',download_url:'/api/v1/projects/p1/manuscript-figure-language-versions/en-version/download'}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('language-context')?{...languageContext,schema_version:3,output_language:'en',candidate,inventory:[],editable_fields:[]}:{items:[version,english]})))
 render(<WritingLanguageReview projectId="p1" manuscriptId="m1" baseRevision={1} review={review} onPublished={vi.fn()}/>);fireEvent.click(screen.getByRole('button',{name:'读取真实 DOCX 全语言清单'}))
 const selector=await screen.findByLabelText('明确选择独立图版本 中文结果图')
 await waitFor(()=>expect(within(selector).getByRole('option',{name:/中文图版本/})).toBeTruthy())
 expect(within(selector).queryByRole('option',{name:/English figure version/})).toBeNull()
})

it('keeps only the local school language-context POST alive past 15 seconds and stops once at 110 seconds',async()=>{
 vi.useFakeTimers()
 let signal:AbortSignal|undefined
 const fetcher=vi.fn((url:string,init?:RequestInit)=>{
  if(url.endsWith('language-context')){signal=init?.signal as AbortSignal;return new Promise<Response>(()=>{})}
  return Promise.resolve(Response.json({items:[]}))
 });vi.stubGlobal('fetch',fetcher)
 render(<WritingLanguageReview projectId="p1" manuscriptId="m1" baseRevision={1} review={{...scienceReview,candidate:snapshot}} onPublished={vi.fn()}/> )
 fireEvent.click(screen.getByRole('button',{name:'读取真实 DOCX 全语言清单'}))
 await act(async()=>{await vi.advanceTimersByTimeAsync(15_001)})
 expect(signal?.aborted).toBe(false)
 await act(async()=>{await vi.advanceTimersByTimeAsync(94_998)})
 expect(signal?.aborted).toBe(false)
 await act(async()=>{await vi.advanceTimersByTimeAsync(1)})
 expect(signal?.aborted).toBe(true)
 expect(screen.getByRole('alert').textContent).toContain('不会自动重试或重新调用')
 expect(fetcher.mock.calls.filter(([url])=>url.endsWith('language-context'))).toHaveLength(1)
})

// B04 task 7: the B03 customer writing chain (one confirmation, generating again, budget wait, coming back to a
// paragraph) on a thesis, plus the thesis customer wording.
const thesisBundleIds=['7c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f','8d2e3f4a-5b6c-4d7e-9f8a-0b1c2d3e4f5a']
const thesisAuthIds=['1e2f3a4b-5c6d-4e7f-8a9b-0c1d2e3f4a5b','2f3a4b5c-6d7e-4f8a-9b0c-1d2e3f4a5b6c']
const thesisRequestIds=['3a4b5c6d-7e8f-4a9b-8c0d-2e3f4a5b6c7d']
type ThesisServer={previews:Bundle[];auths:Authorization[];requests:LiveRequest[];requestStatus?:{status:string;reason_code:string|null;error_code:string|null}}
const thesisBase='/api/v1/projects/p1/manuscripts/m1'
const thesisPosts=(fetcher:ReturnType<typeof vi.fn>,suffix:string)=>fetcher.mock.calls.filter(([url,init])=>(init as RequestInit|undefined)?.method==='POST'&&String(url).endsWith(suffix))
function thesisBundle(input:PreviewInput,index:number):Bundle{
 const fixture=bundleFixture(thesisBundleIds[index]),wire=JSON.stringify({model:'gpt-5.4-2026-03-05',input:JSON.stringify({instructions:'Write the school chapters.',sources:[],evidence:[]})})
 const school={schema_version:1,chapters:{chapter1:{chapter_id:'methods-dynamic',title:'独立方法',level:2,purpose:'materials_and_methods',output_language:'en',result_group_ids:[]}},writable_aliases:['chapter1']}
 return {...fixture,request_json:input,wire_json:wire,bundle_sha256:hash(wire),wire_sha256:hash(wire),wire_bytes:new TextEncoder().encode(wire).length,local_manifest:{...fixture.local_manifest,school,protected_identity:{sha256:hash('identity')}} as Bundle['local_manifest']}
}
function thesisAuth(tasks:Authorization['manifest']['tasks'],index:number):Authorization{
 return {id:thesisAuthIds[index],project_id:'p1',status:'active',revision:1,manifest_sha256:hash('thesis-manifest'+index),manifest:{tasks,max_posts:6,max_corrections:2,materials:[]},occupied_posts:0,logical_task_usage:[]}
}
function thesisRequest(call:{bundle_id:string;authorization_id:string;logical_task_id:string},input:PreviewInput,index:number,status={status:'queued',reason_code:null as string|null,error_code:null as string|null},candidate:Snapshot|null=null):LiveRequest{
 const id=thesisRequestIds[index]
 return {...liveRequest,id,input,base_revision:1,candidate,execution:call,task:{...liveRequest.task,id,status:status.status,display_status:status.status,reason_code:status.reason_code,error_code:status.error_code} as LiveRequest['task'],model_calls:[]}
}
function serveThesis(server:ThesisServer){
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){
   const sent=JSON.parse(String(init.body))
   if(url===`${thesisBase}/writing-previews`){const created=thesisBundle(sent,server.previews.length);server.previews.unshift(created);return Response.json(created)}
   if(url==='/api/v1/projects/p1/writing-authorizations'){const created=thesisAuth(sent.tasks,server.auths.length);server.auths.unshift(created);return Response.json(created)}
   if(url===`${thesisBase}/writing-requests`){const input=server.previews.find(b=>b.id===sent.bundle_id)!.request_json;const created=thesisRequest(sent,input,server.requests.length,server.requestStatus);server.requests.unshift(created);return Response.json(created)}
   return Response.json({})
  }
  if(url===`${thesisBase}/writing-previews`)return Response.json({items:server.previews,capabilities:{real_calls_enabled:true}})
  if(url===`${thesisBase}/writing-requests`)return Response.json({items:server.requests})
  if(url==='/api/v1/projects/p1/writing-authorizations')return Response.json({items:server.auths})
  return Response.json({items:[]})
 })
 vi.stubGlobal('fetch',fetcher);return fetcher
}
const thesisGenerate=()=>screen.getByRole('button',{name:/^(生成正文初稿|再次生成正文)$/})
const thesisConfirm=()=>screen.getByLabelText('我确认用以上材料生成正文，接受本次写作费用和外部保存范围。')
async function thesisReady(){await waitFor(()=>expect(screen.getByText('本次将使用以下材料生成正文')).toBeTruthy());await waitFor(()=>expect(thesisConfirm().matches(':disabled')).toBe(false))}

it('prepares the thesis preview on entry and generates with one confirmation in two more clicks',async()=>{
 vi.stubGlobal('crypto',webcrypto)
 const server:ThesisServer={previews:[],auths:[],requests:[]}
 const fetcher=serveThesis(server)
 render(<WritingLive {...props} customerThesis/>);await thesisReady()
 expect(thesisPosts(fetcher,'/writing-previews')).toHaveLength(1)
 expect(JSON.parse(String(thesisPosts(fetcher,'/writing-previews')[0][1]?.body))).toMatchObject({schema_version:3,base_revision:1,mode:'full_draft'})
 expect(thesisGenerate().matches(':disabled')).toBe(true)
 fireEvent.click(thesisConfirm());fireEvent.click(thesisGenerate())
 await waitFor(()=>expect(thesisPosts(fetcher,'/writing-requests')).toHaveLength(1))
 const bundle=server.previews[0]
 expect(JSON.parse(String(thesisPosts(fetcher,'/writing-authorizations')[0][1]?.body))).toEqual({schema_version:2,confirmed:true,tasks:[{logical_task_id:'task-1',bundles:[{bundle_id:bundle.id,bundle_sha256:bundle.bundle_sha256}]}]})
 expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST').map(([url])=>String(url).split('/').at(-1))).toEqual(['writing-previews','writing-authorizations','writing-requests'])
 await screen.findByText('正在生成正文，完成后会自动打开核对。')
 const systemIds=[...server.previews.flatMap(b=>[b.id,b.bundle_sha256]),...thesisAuthIds,...thesisRequestIds,'task-1']
 expect(findTechnicalText(document.body,{systemIds})).toEqual([])
 expect(document.body.textContent).not.toMatch(/declaration-x|refs-middle|abstract-zh|abstract-en|methods-dynamic/)
 expect(document.body.textContent).not.toMatch(/冻结|科学正文用途|受控|SHA|[0-9a-f]{64}/)
})

it('says generating again costs another fee on a thesis version that already has a body',async()=>{
 vi.stubGlobal('crypto',webcrypto)
 const server:ThesisServer={previews:[],auths:[],requests:[]}
 serveThesis(server)
 const first=render(<WritingLive {...props} customerThesis/>);await thesisReady();first.unmount()
 const bundle=server.previews[0]
 server.auths=[thesisAuth([{logical_task_id:'task-1',bundles:[{bundle_id:bundle.id,bundle_sha256:bundle.bundle_sha256}]}],0)]
 server.requests=[thesisRequest({bundle_id:bundle.id,authorization_id:thesisAuthIds[0],logical_task_id:'task-1'},bundle.request_json,0,{status:'succeeded',reason_code:null,error_code:null},rawSnapshot)]
 const fetcher=serveThesis(server)
 render(<WritingLive {...props} customerThesis/>);await thesisReady()
 expect(screen.getByText('这一版已经生成过正文。再次生成会产生新的写作费用，之前的生成结果仍可查看。')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'生成正文初稿'})).toBeNull()
 fireEvent.click(thesisConfirm());fireEvent.click(screen.getByRole('button',{name:'再次生成正文'}))
 await waitFor(()=>expect(thesisPosts(fetcher,'/writing-requests')).toHaveLength(1))
 expect(JSON.parse(String(thesisPosts(fetcher,'/writing-requests')[0][1]?.body))).toMatchObject({authorization_id:thesisAuthIds[1]})
})

it('offers original task review for a historical thesis writing wait',async()=>{
 vi.stubGlobal('crypto',webcrypto)
 const server:ThesisServer={previews:[],auths:[],requests:[],requestStatus:{status:'waiting_confirmation',reason_code:'model_budget_missing',error_code:null}}
 serveThesis(server)
 render(<WritingLive {...props} customerThesis/>);await thesisReady()
 fireEvent.click(thesisConfirm());fireEvent.click(thesisGenerate())
 expect(await screen.findByRole('button',{name:'核对原写作任务'})).toBeTruthy()
 expect(document.body.textContent).not.toContain('联系客服开通')
})

it('uses customer wording for the thesis chapters that can be generated',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[],capabilities:{real_calls_enabled:false}})))
 render(<WritingLive {...props} customerThesis/>)
 const region=await screen.findByRole('region',{name:'本次可生成的章节'})
 expect(region.textContent).toContain('题名沿用你保存的论文题目；致谢等章节不会改写。')
 expect(within(region).getByText(/^独立方法 · /).textContent).toContain('可生成')
 expect(within(region).getByText(/^人工声明 · /).textContent).not.toContain('declaration-x')
 expect(document.body.textContent).not.toMatch(/冻结|科学正文用途|SHA/)
})

it('keeps the internal wording for the thesis chapters in the staff writing page',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[],capabilities:{real_calls_enabled:false}})))
 render(<WritingLive {...props}/>)
 const region=await screen.findByRole('region',{name:'冻结学校章节'})
 expect(region.textContent).toContain('题名由用户冻结；仅科学正文用途可生成，其他章节保持保护。')
})

// Coming back from adding a source to a thesis paragraph: the chapter title names the place, “正文” when it has none.
const reviewChapters=[{id:'methods-dynamic',title:'独立方法',level:1,purpose:'materials_and_methods',output_language:'en',result_group_ids:[]},{id:'untitled-chapter',title:'',level:1,purpose:'results',output_language:'zh-CN',result_group_ids:[]}]
const reviewParagraph=(id:string,text:string)=>({id,text,origin:'model_generated',source_ids:[],citations:[],numeric_bindings:[]})
const thesisReviewSnapshot={...snapshot,thesis_context:{...snapshot.thesis_context!,confirmation:{id:'confirm1',chapters:reviewChapters.map(({id,title,level})=>({id,title,level}))},chapters:reviewChapters},
 sections:[{...reviewChapters[0],paragraphs:[reviewParagraph('methods-dynamic:1','Methods one'),reviewParagraph('methods-dynamic:2','Methods two')]},{...reviewChapters[1],paragraphs:[reviewParagraph('untitled-chapter:1','无题章节')]}]} as unknown as Snapshot
const thesisReviewContext={...reviewContext,candidate:thesisReviewSnapshot,reviews:[],required_paragraph_ids:['methods-dynamic:1','methods-dynamic:2','untitled-chapter:1'],claim_contexts:{'methods-dynamic:1':'c1','methods-dynamic:2':'c2','untitled-chapter:1':'c3'},paragraph_languages:{'methods-dynamic:1':'en','methods-dynamic:2':'en','untitled-chapter:1':'zh-CN'},abstract_chapter_ids:[]}
it('names thesis paragraphs by chapter title, falls back to “正文” and focuses the paragraph on return',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/review-context')?thesisReviewContext:{items:[]})))
 const request={...liveRequest,input:{...liveRequest.input,schema_version:3},candidate:thesisReviewSnapshot} as LiveRequest
 render(<WritingScienceReview projectId="p1" manuscriptId="m1" request={request} customerSci customerThesis initialParagraph="methods-dynamic:2" onPublished={vi.fn()}/>)
 await waitFor(()=>expect(document.activeElement?.id).toBe('writing-paragraph-methods-dynamic:2'))
 expect(screen.getByLabelText('段落主张分类 独立方法 · 段落 2')).toBeTruthy()
 expect(screen.getByLabelText('段落主张分类 正文 · 段落 1')).toBeTruthy()
})

it.each([['zh-CN', '封面与目录', '学号', '作者'], ['en', 'Cover and table of contents', 'Student ID', 'Author']] as const)(
 'shows the saved cover and contents on the customer adoption page in %s', async (locale, heading, student, author) => {
  setLocale(locale)
  const options = {manual_fields:{author:'Sample Author',student_id:'S-2026-47'}, field_values:{}, manual_chapters:[{chapter_id:'declaration-x',text:'My original declaration.'}], english_title:'An original title', keywords:[{chapter_id:'abstract-en',values:['maps','samples']}], include_toc:true, toc_depth:2}
  const candidate={...snapshot,writing_provenance:{...scienceReview.candidate.writing_provenance!,school_export_options:options}}
  const saved:typeof languageArtifact={...languageArtifact,candidate}
  const fetcher=vi.fn(async(url:string)=>Response.json(url.endsWith('/language-reviews')?{items:[{id:saved.id,created_at:'2026-11-20T05:00:00Z'}]}:url.endsWith('/'+saved.id)?saved:{items:[]}))
  vi.stubGlobal('fetch',fetcher)
  const {unmount}=render(<WritingLanguageReview customerThesis projectId="p1" manuscriptId="m1" baseRevision={5} review={{...scienceReview,candidate}} onPublished={vi.fn()}/>)
  const finished=within(await screen.findByRole('region',{name:locale==='en'?'Finish the manuscript check':'完成稿件复核'}))
  const summary=within(finished.getByRole('region',{name:heading}))
  expect(summary.getByText(student)).toBeTruthy();expect(summary.getByText('S-2026-47')).toBeTruthy()
  expect(summary.getByText(author)).toBeTruthy();expect(summary.getByText('Sample Author')).toBeTruthy()
  for(const value of ['An original title','My original declaration.','maps · samples']) expect(summary.getByText(value)).toBeTruthy()
  expect(summary.getByText(/English Abstract.*(关键词|Keywords)/i)).toBeTruthy()
  expect(summary.getByText(/(目录深度|TOC depth|Table of contents depth).*2/i)).toBeTruthy()
  expect(finished.queryByText(/field values|manual fields|toc depth$|include toc|^values$/i)).toBeNull()
  unmount()
  const field={id:'input-8',label:'校方登记名称',kind:'text',required:true,source_id:'src',style_source_id:null,section_id:'s1',chapter_id:null}
  const front={schema_version:1,cover_section_id:'s1',fields:[field],content_requirements:[]}
  const customCandidate={...candidate,thesis_context:{...snapshot.thesis_context!,confirmation:{front_matter:front}},writing_provenance:{...candidate.writing_provenance,school_export_options:{...options,manual_fields:{},field_values:{'input-8':'保留原文'},include_toc:false}}}
  saved.candidate=customCandidate
  render(<WritingLanguageReview customerThesis projectId="p1" manuscriptId="m1" baseRevision={5} review={{...scienceReview,candidate:customCandidate}} onPublished={vi.fn()}/>)
  const custom=within(within(await screen.findByRole('region',{name:locale==='en'?'Finish the manuscript check':'完成稿件复核'})).getByRole('region',{name:heading}))
  expect(custom.getByText('校方登记名称')).toBeTruthy();expect(custom.getByText('保留原文')).toBeTruthy()
  expect(custom.getByText(locale==='en'?'No table of contents':'不含目录')).toBeTruthy()
  expect(custom.queryByText('input-8')).toBeNull()
})

it('preserves the staff school export details when a reviewer explicitly selects the saved language record', async()=>{
 const candidate={...snapshot,writing_provenance:{...scienceReview.candidate.writing_provenance!,school_export_options:{manual_fields:{author:'Staff sample',student_id:'S-99'},include_toc:true,toc_depth:2}}}
 const saved={...languageArtifact,candidate}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/language-reviews')?{items:[{id:saved.id,created_at:'2026-11-20T05:00:00Z'}]}:url.endsWith('/'+saved.id)?saved:{items:[]})))
 render(<WritingLanguageReview projectId="p1" manuscriptId="m1" baseRevision={5} review={{...scienceReview,candidate}} onPublished={vi.fn()}/>)
 await screen.findByRole('option',{name:/语言审核产物 1/})
 fireEvent.change(screen.getByLabelText('明确选择语言审核产物'),{target:{value:saved.id}})
 const disclosure=(await screen.findByText('已固定的学校导出选项')).closest('details')!
 expect(disclosure).toBeTruthy()
 expect(within(disclosure).getByText('Staff sample')).toBeTruthy()
 expect(within(disclosure).queryByText('S-99')).toBeNull()
})
