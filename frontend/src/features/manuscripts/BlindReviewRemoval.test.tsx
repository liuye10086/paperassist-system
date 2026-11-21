import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptExports from './ManuscriptExports'
import ManuscriptPresentation from './ManuscriptPresentation'
import PresentationLanguagePanel from './PresentationLanguagePanel'
import PresentationExportDetails from './PresentationExportDetails'
import {exportFixture,manuscriptFixture,snapshotFixture} from './manuscriptFixtures'
import {validExport,type ManuscriptExport,type ManuscriptVersion} from './manuscriptTypes'
import {emptyPresentation,normalizePresentationConfig,validPresentation,validSavedPresentation,type PresentationExport,type SavedPresentation} from './presentationTypes'
import {apiError,setLocale,translate} from '../../shared/i18n'
import {errorMessages} from '../../shared/i18n/errorMessages'

// B04 task 0.5f: blind review is removed (2026-11-19). New output is identified only; historical blind exports stay
// readable and downloadable, labelled 历史盲审稿, with no retry, derivation or language-confirmation reuse.
afterEach(()=>{cleanup();vi.unstubAllGlobals();sessionStorage.clear();setLocale('zh-CN')})
const quality={scientific_semantic:'pending',word_wps:'pending',real_compliance:'pending'} as const
const legacyBlind={identity_terms:['历史身份词'],hidden_chapter_ids:[],exceptions:[],manual_image_review:false}
const chapters=[{id:'chapter-result',title:'第三章 实验结果',level:1,purpose:'results',output_language:'zh-CN',result_group_ids:[]}]
const profile={revision:2,school:'测试学校',department:'',major:'',degree_type:'硕士',education_level:'研究生',applicable_version:'2026',bound_confirmation_id:'confirm1'}
const thesisContext=(format_profile?:string)=>({schema_version:1,profile,template_version_id:'template1',confirmation_id:'confirm1',confirmation_sha256:'a'.repeat(64),confirmation:{id:'confirm1',chapters:chapters.map(({id,title,level})=>({id,title,level})),...(format_profile?{format_profile}:{})},source_files:[],chapters})
const thesisVersion=(format_profile?:string)=>({...manuscriptFixture.versions[0],exports:[],snapshot:{...snapshotFixture,output_language:'zh-CN',thesis_context:thesisContext(format_profile)}}) as unknown as ManuscriptVersion
const blindPresentation={binding:{presentation_version_id:'p-old',language_view:'zh-CN',review_mode:'blind'},checks:[{code:'blind:images',status:'pending',message:'Images require blind review'}],quality,blind:{known_identity_check:'passed',remaining:[],images:'pending_manual_review',exceptions:[],anonymity_verified:false}}
const blindExport={...exportFixture,id:'blind-old',filename:'毕业论文盲审稿.docx',download_url:'/api/v1/projects/p1/manuscripts/m1/exports/blind-old/download',presentation:blindPresentation}
const failedBlind={...exportFixture,id:'blind-failed',task_id:'blind-task',status:'failed',error_code:'export_failed',filename:null,download_url:null,sha256:null,size_bytes:null,presentation:blindPresentation}

it('keeps only the identified Word flow for thesis customers and never sends review_mode',async()=>{
 const version=thesisVersion(),exportPath='/api/v1/projects/p1/manuscripts/m1/versions/1/exports'
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>url===exportPath&&init?.method==='POST'?Response.json({...exportFixture,status:'queued',download_url:null,sha256:null,size_bytes:null,filename:null}):Response.json({items:[]}))
 vi.stubGlobal('fetch',fetcher)
 const {container}=render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version} customerThesis/>)
 await screen.findByText('当前版本尚未生成 Word。')
 expect(screen.queryByRole('group',{name:'毕业论文 Word 类型'})).toBeNull()
 expect(screen.queryByRole('button',{name:'普通署名稿'})).toBeNull()
 expect(screen.queryByRole('button',{name:'独立盲审派生稿'})).toBeNull()
 for(const text of ['盲审','独立盲审派生稿','审阅输出模式'])expect(container.textContent).not.toContain(text)
 fireEvent.click(screen.getByRole('button',{name:'生成 Word'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([url,init])=>url===exportPath&&init?.method==='POST')).toBe(true))
 const body=JSON.parse(String(fetcher.mock.calls.find(([url,init])=>url===exportPath&&init?.method==='POST')![1]?.body))
 expect(body).toHaveProperty('school');expect(body).not.toHaveProperty('review_mode')
 expect(fetcher.mock.calls.some(([url])=>url.includes('/presentations'))).toBe(false)
})

it('accepts historical blind exports and lists them read-only with download and no retry or derivation',async()=>{
 expect(validExport(blindExport,'p1','m1')).toBe(true)
 expect(validExport(failedBlind,'p1','m1')).toBe(true)
 const version={...thesisVersion(),exports:[]} as ManuscriptVersion
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/exports')?{items:[failedBlind,blindExport]}:{items:[]})))
 const view=render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version} customerThesis/>)
 await waitFor(()=>expect(screen.getAllByText(/历史盲审稿/).length).toBeGreaterThanOrEqual(2))
 expect(screen.getByRole('link',{name:'下载这份 Word'}).getAttribute('href')).toBe(blindExport.download_url)
 expect(screen.queryByRole('button',{name:'重试'})).toBeNull()
 for(const text of ['独立盲审派生稿','盲审自动检查回执','图片身份仍待人工核对。','Images require blind review'])expect(view.container.textContent).not.toContain(text)
 view.unmount()
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/exports')?{items:[failedBlind,blindExport]}:{items:[]})))
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={{...manuscriptFixture.versions[0],exports:[]} as unknown as ManuscriptVersion}/>)
 await screen.findByRole('link',{name:'下载 DOCX'})
 expect(screen.getAllByText(/历史盲审稿/).length).toBeGreaterThanOrEqual(2)
 expect(screen.queryByRole('button',{name:'重试 DOCX'})).toBeNull()
 expect(screen.queryByRole('region',{name:/排版/})).toBeNull()
})

it('exports a saved configuration for staff without a review mode selector or payload field',async()=>{
 const version={...manuscriptFixture.versions[0],exports:[]} as unknown as ManuscriptVersion
 const saved={id:'p1',manuscript_id:'m1',revision:1,schema_version:1,base_version_id:version.id,peer_version_id:null,config:emptyPresentation(),checks:[],paragraph_groups:[],quality,can_export:true,stale:false,stale_version_ids:[]}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/presentations'))return Response.json({items:[saved]})
  if(init?.method==='POST')return Response.json({...exportFixture,status:'queued',filename:null,download_url:null,sha256:null,size_bytes:null})
  return Response.json({items:[]})
 });vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version} versions={[version]}/>)
 await screen.findByRole('option',{name:/配置版本 1/});fireEvent.change(screen.getByLabelText('已保存输出配置'),{target:{value:'p1'}})
 expect(screen.getByLabelText('输出语言视图')).toBeTruthy();expect(screen.queryByLabelText('审阅输出模式')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([,i])=>i?.method==='POST')).toBe(true))
 expect(JSON.parse(String(fetcher.mock.calls.find(([,i])=>i?.method==='POST')![1]?.body))).toEqual({presentation_version_id:'p1',language_view:version.snapshot.output_language})
})

it('validates new configurations without blind and never writes the legacy key',()=>{
 const preview={schema_version:1,base_version_id:'v1',peer_version_id:null,config:emptyPresentation(),checks:[],paragraph_groups:[],quality,can_export:true}
 expect('blind' in emptyPresentation()).toBe(false)
 expect(validPresentation(preview,'v1')).toBe(true)
 expect(validSavedPresentation({...preview,id:'p1',manuscript_id:'m1',revision:1,created_at:'2026-11-19T00:00:00Z',stale:false,stale_version_ids:[]},'m1')).toBe(true)
 const legacy={...emptyPresentation(),blind:legacyBlind}
 expect(validPresentation({...preview,config:legacy},'v1')).toBe(true)
 expect('blind' in normalizePresentationConfig(legacy)).toBe(false)
})

it('removes blind rules from the staff configuration and re-saves a historical configuration without blind',async()=>{
 const version=manuscriptFixture.versions[0] as unknown as ManuscriptVersion
 const legacy={id:'p-old',revision:1,manuscript_id:'m1',base_version_id:version.id,peer_version_id:null,schema_version:1,created_at:'2026-11-01T00:00:00Z',config:{...emptyPresentation(),blind:legacyBlind},checks:[{code:'blind:rules',status:'pending',message:'Blind rules pending'},{code:'blind:images',status:'pending',message:'Blind images pending'},{code:'ethics',status:'pending',message:'Ethics pending'}],paragraph_groups:[],quality,can_export:true,stale:false,stale_version_ids:[]}
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{if(!init?.method)return Response.json({items:[legacy]});const input=JSON.parse(String(init.body));return Response.json({...legacy,...input,id:'p-new',revision:2,checks:[]})})
 vi.stubGlobal('fetch',fetcher)
 const {container}=render(<ManuscriptPresentation projectId="p1" manuscriptId="m1" version={version} versions={[version]} onSelect={vi.fn()} active/>)
 await screen.findByText('Ethics pending')
 for(const text of ['盲审规则与人工核对','明确隐藏的身份词','添加盲审例外','Blind rules pending','Blind images pending'])expect(container.textContent).not.toContain(text)
 fireEvent.change(screen.getByLabelText('已保存输出配置'),{target:{value:'p-old'}})
 fireEvent.click(screen.getByRole('button',{name:'添加作者'}))
 fireEvent.click(screen.getByRole('button',{name:'保存输出配置'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([,i])=>i?.method==='POST')).toBe(true))
 expect(JSON.parse(String(fetcher.mock.calls.find(([,i])=>i?.method==='POST')![1]?.body)).config).not.toHaveProperty('blind')
})

it('never offers a historical blind export as a language confirmation source',()=>{
 const inventory=[{location:'body',kind:'export_text',text:'English text.',content_sha256:'b'.repeat(64),target_language:'en',protected_identity:false,scope:'narrative',verification:'pending_manual_review'}]
 const presentation={id:'p1',manuscript_id:'m1',revision:1,base_version_id:'v1',peer_version_id:null,config:emptyPresentation()} as SavedPresentation
 const make=(id:string,review_mode:'identified'|'blind')=>({...exportFixture,id,version_id:'v1',sha256:'a'.repeat(64),presentation:{binding:{presentation_version_id:'p1',language_view:'en',review_mode},checks:[],quality,language_inventory:inventory}}) as ManuscriptExport
 const props={config:emptyPresentation(),baseVersionId:'v1',peerVersionId:null,presentations:[presentation],onChange:vi.fn(),onBlocked:vi.fn()}
 const view=render(<PresentationLanguagePanel {...props} exports={[make('blind-source','blind'),make('signed-source','identified')]}/>)
 const select=screen.getByLabelText('语言确认来源 DOCX') as HTMLSelectElement
 expect(Array.from(select.options).map(o=>o.value)).toEqual(['','signed-source'])
 expect(view.container.textContent).not.toContain('盲审稿')
 view.rerender(<PresentationLanguagePanel {...props} key="blind-only" exports={[make('blind-source','blind')]}/>)
 expect(screen.getByText('尚无包含精确语言清单的已完成导出；先生成对应配置的 DOCX。')).toBeTruthy()
})

it('shows historical blind export details only as a read-only label without the blind receipt',()=>{
 const {container}=render(<PresentationExportDetails value={blindPresentation as unknown as PresentationExport} customerView/>)
 expect(screen.getByText(/历史盲审稿/)).toBeTruthy()
 for(const text of ['独立盲审派生稿','盲审自动检查回执','明确身份词自动检查已完成','盲审检查等待实际 DOCX 完成。','Images require blind review'])expect(container.textContent).not.toContain(text)
})

it('tells GS501 users that the blind-review version goes to a third party',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})))
 const view=render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={thesisVersion('bsu-gs501-academic-masters-2026')} customerThesis/>)
 expect(screen.getByText('盲评版请按学校要求交第三方处理。')).toBeTruthy()
 view.unmount()
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={thesisVersion('bsu-gs501-academic-masters-2026')}/>)
 expect(screen.getByText('盲评版请按学校要求交第三方处理。')).toBeTruthy()
 cleanup()
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={thesisVersion()} customerThesis/>)
 expect(screen.queryByText('盲评版请按学校要求交第三方处理。')).toBeNull()
 setLocale('en')
 cleanup()
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={thesisVersion('bsu-gs501-academic-masters-2026')}/>)
 expect(document.body.textContent).not.toContain('盲评版请按学校要求交第三方处理。')
 expect(document.body.textContent).toMatch(/third party/i)
})

it('maps blind_review_removed to the customer notice and drops the retired blind error codes',()=>{
 const id=apiError({detail:{code:'blind_review_removed',message:'raw'}},'请求失败，请重试。')
 expect(translate(id)).toBe('盲审已移出产品范围，请交第三方处理。')
 expect(Object.keys(errorMessages)).not.toContain('school_blind_identity_remaining')
 expect(Object.keys(errorMessages)).not.toContain('gs501_reviewed_output_stale')
 setLocale('en');expect(translate(id)).not.toMatch(/[㐀-鿿]/)
})
