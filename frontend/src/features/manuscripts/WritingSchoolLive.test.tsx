import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import WritingScienceReview from './WritingScienceReview'
import ManuscriptWriting from './ManuscriptWriting'
import WritingLanguageReview from './WritingLanguageReview'
import {manuscriptFixture,snapshotFixture} from './manuscriptFixtures'
import {scienceReview,languageContext,reviewContext,liveRequest} from './writingLiveFixtures'
import {validPreviewInput,bodyProjection} from './writingLiveTypes'
import type {Snapshot,ManuscriptVersion} from './manuscriptTypes'
const chapters=[{id:'declaration-x',title:'人工声明',purpose:'manual',output_language:'zh-CN'}, {id:'refs-middle',title:'文献',purpose:'references',output_language:'en'}, {id:'abstract-zh',title:'中文摘要',purpose:'abstract',output_language:'zh-CN'}, {id:'abstract-en',title:'English Abstract',purpose:'abstract',output_language:'en'}, {id:'methods-dynamic',title:'独立方法',purpose:'materials_and_methods',output_language:'en'}].map(c=>({...c,level:2,result_group_ids:[]}))
const snapshot={...snapshotFixture,thesis_context:{schema_version:1,profile:{revision:2,school:'测试学校',department:'',major:'',degree_type:'硕士',education_level:'研究生',applicable_version:'2026',bound_confirmation_id:'confirm1'},template_version_id:'template1',confirmation_id:'confirm1',confirmation_sha256:'a'.repeat(64),confirmation:{id:'confirm1',chapters:chapters.map(({id,title,level})=>({id,title,level}))},source_files:[],chapters},sections:chapters.map(c=>({...c,paragraphs:[{id:c.id+':1',text:c.title,origin:'user_provided',source_ids:[],citations:[]}]})),school_content_report:{rules_version:'school_v1',issues:[],can_publish:true,scientifically_verified:false}} as unknown as Snapshot
const props={projectId:'p1',manuscriptId:'m1',version:{...manuscriptFixture.versions[0],snapshot} as ManuscriptVersion,onPublished:vi.fn()}
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals()})
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
it('requires explicit literal decisions only for protected identity and invalidates decisions after school options change',async()=>{
 const review={...scienceReview,candidate:snapshot};const inventory=[{location:'identity:p1',kind:'paragraph',text:'本人',content_sha256:'e'.repeat(64),scope:'label',target_language:'zh-CN',chapter_id:'declaration-x',protected_identity:true},{location:'body:p2',kind:'paragraph',text:'Methods',content_sha256:'f'.repeat(64),scope:'narrative',target_language:'en',chapter_id:'methods-dynamic',protected_identity:false}]
 const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('language-context')?{...languageContext,schema_version:3,candidate:snapshot,inventory,editable_fields:[]}:{items:[]}));vi.stubGlobal('fetch',fetcher)
 render(<WritingLanguageReview projectId="p1" manuscriptId="m1" baseRevision={1} review={review} onPublished={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'读取真实 DOCX 全语言清单'}));await screen.findByRole('group',{name:/identity:p1/})
 const identity=screen.getByRole('group',{name:/identity:p1/}),body=screen.getByRole('group',{name:/body:p2/})
 expect(within(identity).queryByRole('option',{name:'目标语言文字已逐项核对'})).toBeNull();expect(within(body).queryByRole('option',{name:'已逐项核对用户提供的身份原文'})).toBeNull()
 expect(within(identity).getByLabelText('此项语言决定')).toHaveProperty('value','')
 fireEvent.change(within(identity).getByLabelText('此项语言决定'),{target:{value:'provided_literal'}});fireEvent.change(within(identity).getByLabelText('此项语言审核理由'),{target:{value:'核对本人原文'}})
 fireEvent.change(within(body).getByLabelText('此项语言决定'),{target:{value:'target_language'}});fireEvent.change(within(body).getByLabelText('此项语言审核理由'),{target:{value:'English checked'}})
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
