import {cleanup,fireEvent,render,screen,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptExports from './ManuscriptExports'
import {manuscriptFixture,exportFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
import {act} from '@testing-library/react'
import {setLocale} from '../../shared/i18n'
import {SchoolExportDetails} from './SchoolExportPanel'
import {findTechnicalText} from '../../test/technicalText'
afterEach(()=>{cleanup();sessionStorage.clear();vi.unstubAllGlobals();setLocale('zh-CN')})

const migrationSections = [
 { id:'plan-results', chapter_id:'chapter-8', label:'3 观测记录与条件比较', purpose:'results', text:'' },
 { id:'plan-methods', chapter_id:'chapter-7', label:'2 原方法标题', purpose:'materials_and_methods', text:'' },
 { id:'plan-removed', chapter_id:'chapter-10', label:'已删除的原章', purpose:'results', text:'' },
]
function migratedWordVersion(withGroups:boolean) {
 const chapters=[
  {id:'chapter-2',title:'2 本版方法',purpose:'materials_and_methods',result_group_ids:[]},
  {id:'chapter-9',title:'3 研究设计与条件比较',purpose:'results',result_group_ids:withGroups?['plan-results']:[]},
  {id:'chapter-8',title:'新模板复用了原编号',purpose:'discussion',result_group_ids:[]},
  {id:'chapter-new',title:'新模板另设的方法章节',purpose:'materials_and_methods',result_group_ids:[]},
 ]
 const material=(section_id:string,filename:string)=>({section_id,filename,kind:'table',result:'',
  selection:{id:filename,file_id:filename,kind:'original',role:'user_results'},worksheet_names:['Sheet 1']})
 return {...manuscriptFixture.versions[0],revision:4,exports:[],snapshot:{...manuscriptFixture.versions[0].snapshot,
  thesis_context:{chapters,confirmation:{}},school_change_provenance:{kind:'template_migration',mappings:withGroups?[
   {input_section_id:'chapter-7',chapter_id:'chapter-2'},{input_section_id:'chapter-8',chapter_id:'chapter-9'}]:[]},
  paper_plan:{kind:'thesis',title:'材料计划',keywords:[],sections:migrationSections,
   materials:[material('plan-results','原始第三章.xlsx'),material('plan-removed','已删除章节.xlsx')]},
 }} as unknown as ManuscriptVersion
}

it('shows the migrated customer Word chapters in export order with their saved table assignments', async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})))
 const version=migratedWordVersion(true),before=JSON.stringify(version.snapshot)
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version} customerThesis/>)
 const summary=within(await screen.findByRole('region',{name:'本版 Word 使用的章节与图表'}))
 expect(summary.getAllByRole('heading',{level:4}).map(h=>h.textContent)).toEqual(['2 本版方法','3 研究设计与条件比较'])
 expect(within(summary.getByRole('heading',{name:'3 研究设计与条件比较'}).closest('article')!).getByText('表 · 原始第三章.xlsx')).toBeTruthy()
 expect(summary.getByText(/入稿工作表.*Sheet 1/)).toBeTruthy()
 expect(summary.queryByText(/已删除章节.xlsx/)).toBeNull()
 expect(JSON.stringify(version.snapshot)).toBe(before)
})

it('does not attach an unassigned table to a reused chapter ID on the customer Word page',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})))
 const version=migratedWordVersion(false)
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version} customerThesis/>)
 const summary=within(await screen.findByRole('region',{name:'本版 Word 使用的章节与图表'}))
 expect(summary.queryAllByText(/原始第三章.xlsx|已删除章节.xlsx/)).toHaveLength(0)
 expect(summary.queryByRole('heading',{name:'3 观测记录与条件比较'})).toBeNull()
 expect(summary.queryAllByRole('heading',{level:4})).toHaveLength(0)
 expect(summary.getByText('本版没有已确认归属的计划章节或图表。')).toBeTruthy()
})

it('keeps the archived plan names in the staff Word summary',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})))
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={migratedWordVersion(true)}/>)
 const summary=within(await screen.findByRole('region',{name:'本版 Word 使用的章节与图表'}))
 expect(summary.getByRole('heading',{name:'3 观测记录与条件比较'})).toBeTruthy()
})
it('translates new front matter missing and signature review issues when the UI language changes',()=>{
 const front={schema_version:1 as const,cover_section_id:'s1',fields:[{id:'signature',label:'用户签名',kind:'signature' as const,required:true,source_id:'p1',style_source_id:null,section_id:'s1',chapter_id:null}],content_requirements:[]}
 const details={...plan,schema_version:2 as const,front_matter:front,report:{...report,issues:[{id:'school:field:signature',kind:'manual' as const,severity:'human_review' as const,location:'signature',message:'用户签名未提供，保留待填写。',source_evidence:[]}]}}
 render(<SchoolExportDetails plan={details}/>);act(()=>setLocale('en'))
 expect(screen.getByText(/用户签名 is missing/)).toBeTruthy()
})
it('collects only frozen dynamic fields for v2 and keeps user values across hidden views',async()=>{
 const front={schema_version:1,cover_section_id:'s1',fields:[{id:'degree',label:'培养类型',kind:'text',required:true,source_id:'p1',style_source_id:null,section_id:'s1',chapter_id:null},{id:'signature',label:'作者签名',kind:'signature',required:true,source_id:'p2',style_source_id:null,section_id:'s1',chapter_id:'manual1'}],content_requirements:[]}
 const v={...manuscriptFixture.versions[0],exports:[],snapshot:{...manuscriptFixture.versions[0].snapshot,thesis_context:{confirmation:{front_matter:front},confirmation_id:'cf',chapters:[{id:'manual1',title:'声明',purpose:'manual'}]}}} as unknown as ManuscriptVersion
 const fetcher=vi.fn(async()=>Response.json({items:[],pdf_status:'not_requested'}));vi.stubGlobal('fetch',fetcher)
 const view=render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={v}/>);
 expect(screen.queryByLabelText('学号')).toBeNull()
 fireEvent.change(screen.getByLabelText('培养类型 · 必填'),{target:{value:'用户填写'}})
 view.rerender(<ManuscriptExports projectId="p1" manuscriptId="m1" version={v} active={false}/>);view.rerender(<ManuscriptExports projectId="p1" manuscriptId="m1" version={v}/>);
 expect((screen.getByLabelText('培养类型 · 必填') as HTMLInputElement).value).toBe('用户填写')
 fireEvent.click(screen.getByRole('button',{name:'预览学校排版'}));await screen.findByRole('alert')
 const call=(fetcher.mock.calls as unknown as [string,RequestInit][]).find(([,init])=>init?.method==='POST')!
 expect(JSON.parse(String(call[1].body)).school.field_values).toEqual({degree:'用户填写'})
})
it('edits confirmed GS501 fields and directs signatures to the official Word form',()=>{
 const fields=[
  {id:'author',label:'论文作者',kind:'identity',section_id:'section-1',chapter_id:null},
  {id:'committee',label:'答辩委员会',kind:'text',section_id:'section-2',chapter_id:null},
  {id:'chair',label:'主席姓名',kind:'text',section_id:'section-2',chapter_id:null},
  {id:'signature',label:'原创性声明签署',kind:'signature',section_id:'section-3',chapter_id:'declaration'},
 ].map(field=>({...field,required:false,source_id:field.id,style_source_id:null}))
 const front={schema_version:1,cover_section_id:'section-1',fields,content_requirements:[]}
 const chapters=[
  {id:'declaration',title:'北京体育大学学位论文原创性声明',purpose:'manual'},
  {id:'thanks',title:'致谢',purpose:'acknowledgements'},
 ]
 const v={...version,snapshot:{...version.snapshot,thesis_context:{confirmation_id:'cf',chapters,
  confirmation:{front_matter:front,format_profile:'bsu-gs501-academic-masters-2026'}}}} as unknown as ManuscriptVersion
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})))
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={v}/> )
 expect(screen.getByLabelText('论文作者 · 可选')).toBeTruthy()
 expect(screen.getByLabelText('主席姓名 · 可选')).toBeTruthy()
 expect(screen.getByLabelText('致谢 · 人工文本')).toBeTruthy()
 expect(screen.queryByLabelText('答辩委员会 · 可选')).toBeNull()
 expect(screen.queryByLabelText('原创性声明签署 · 可选')).toBeNull()
 expect(screen.queryByLabelText('北京体育大学学位论文原创性声明 · 人工文本')).toBeNull()
 expect(screen.getByText(/本人在 Word 中插入电子签名/)).toBeTruthy()
})
it('collects explicit school fields and previews the request without submitting a task',async()=>{
 const version={...manuscriptFixture.versions[0],exports:[],snapshot:{...manuscriptFixture.versions[0].snapshot,thesis_context:{confirmation_id:'confirm1',chapters:[{id:'manual1',title:'声明',purpose:'manual'},{id:'abstract1',title:'英文摘要',purpose:'abstract'},{id:'ack1',title:'致谢',purpose:'acknowledgements'}]}}} as unknown as ManuscriptVersion
 const fetcher=vi.fn(async(_url:string,_init?:RequestInit)=>Response.json({items:[],pdf_status:'not_requested'}));vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version}/>);
 fireEvent.change(screen.getByLabelText('作者'),{target:{value:'测试作者'}})
 fireEvent.change(screen.getByLabelText('声明 · 人工文本'),{target:{value:'明确提供文本'}})
 fireEvent.change(screen.getByLabelText('英文摘要 · 关键词'),{target:{value:'one; two'}})
 fireEvent.change(screen.getByLabelText('致谢 · 人工文本'),{target:{value:'致谢由作者提供。'}})
 fireEvent.click(screen.getByRole('button',{name:'预览学校排版'}));await screen.findByRole('alert')
 const post=fetcher.mock.calls.find((call)=> (call as unknown as [string,RequestInit])[1]?.method==='POST') as unknown as [string,RequestInit]
 expect(post[0]).toContain('/versions/1/exports/preview')
 expect(JSON.parse(String(post[1].body))).toMatchObject({school:{manual_fields:{author:'测试作者'},manual_chapters:[{chapter_id:'manual1',text:'明确提供文本'},{chapter_id:'ack1',text:'致谢由作者提供。'}],keywords:[{chapter_id:'abstract1',values:['one','two']}],include_toc:true,toc_depth:3}})
})

const report={rules_version:'school-export-v1',issues:[{id:'m1',kind:'manual' as const,severity:'human_review' as const,location:'cover',message:'封面作者待补充',source_evidence:[]}],can_export:true,scientifically_verified:false as const}
const plan={schema_version:1 as const,rules_version:'school-export-v1',confirmation_id:'confirm1',confirmation_sha256:'a'.repeat(64),analysis_sha256:'b'.repeat(64),snapshot_sha256:'c'.repeat(64),options:{},styles:{},sections:[],chapters:[],requirements:[],rule_decisions:[{id:'font',message:'正文英文采用TNR',source_evidence:[]}],toc:{enabled:true,depth:3},label_map:{figures:{},tables:{}},report}
const version={...manuscriptFixture.versions[0],exports:[],snapshot:{...manuscriptFixture.versions[0].snapshot,thesis_context:{confirmation_id:'confirm1',chapters:[]}}} as unknown as ManuscriptVersion
it('describes revised thesis Word setup without the manuscript version number',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})))
 const {container}=render(<ManuscriptExports customerThesis revisedResult projectId="p1" manuscriptId="m1" version={version}/>);
 expect(await screen.findByText('修订稿尚未生成 Word。')).toBeTruthy()
 expect(screen.getByRole('heading',{name:'学校排版'})).toBeTruthy()
 expect(screen.getByLabelText('作者')).toBeTruthy()
 expect(container.textContent).not.toMatch(/版本/)
})
it('previews and creates using identical school options, restores static receipt and keeps Word without PDF generation',async()=>{
 const result={...exportFixture,school:{plan,report,field_update:{status:'updated',renderer:'local'}}};let created=false
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.includes('/pdf-exports'))return init?.method==='POST'?Response.json({detail:{code:'pdf_conversion_failed'}},{status:503}):Response.json({items:[]})
  if(url.endsWith('/preview'))return Response.json({schema_version:1,school:plan})
  if(init?.method==='POST'){created=true;return Response.json(result)}
  return Response.json({items:created?[result]:[],pdf_status:'not_requested'})
 });vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version}/>);
 fireEvent.change(screen.getByLabelText('作者'),{target:{value:'测试作者'}})
 fireEvent.click(screen.getByRole('button',{name:'预览学校排版'}));await screen.findByText(/封面作者待补充/)
 fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}));await screen.findByRole('link',{name:'下载 DOCX'})
 const calls=fetcher.mock.calls.filter(([,init])=>init?.method==='POST');expect(calls).toHaveLength(2);expect(calls[0][1]?.body).toBe(calls[1][1]?.body)
 expect(screen.getByText('目录更新回执')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'生成 PDF'})).toBeNull()
 expect(screen.getByRole('link',{name:'下载 DOCX'}).getAttribute('href')).toBe(exportFixture.download_url)
 expect(fetcher.mock.calls.some(([url,init])=>url.includes('/pdf-exports')&&init?.method==='POST')).toBe(false)
})
it('sends the unchanged empty SCI request without a school key',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>init?.method==='POST'?Response.json(exportFixture):Response.json({items:[],pdf_status:'not_requested'}));vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={{...manuscriptFixture.versions[0],exports:[]} as unknown as ManuscriptVersion}/>);
 fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}));await screen.findByRole('link',{name:'下载 DOCX'})
 expect(fetcher.mock.calls.find(([,init])=>init?.method==='POST')?.[1]?.body).toBe('{}')
})

it('does not offer a second layout pass when a school DOCX already contains its TOC layout manifest',async()=>{
 const result={...exportFixture,school:{plan,report,field_update:{status:'updated'}}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/pdf-exports')?{items:[]}:{items:[result],pdf_status:'not_requested'})))
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version}/>);
 await screen.findByRole('link',{name:'下载 DOCX'})
 expect(screen.queryByRole('button',{name:'排版与公式'})).toBeNull()
 expect(screen.getByText('学校目录已完成排版，请直接下载 Word。')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'刷新 PDF 状态'})).toBeNull()
})

it('keeps the existing layout entry for school exports without a TOC manifest',async()=>{
 const result={...exportFixture,school:{plan:{...plan,toc:{enabled:false,depth:3}},report,field_update:{status:'not_requested'}}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/pdf-exports')?{items:[]}:{items:[result],pdf_status:'not_requested'})))
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version}/>);
 expect(await screen.findByRole('button',{name:'排版与公式'})).toBeTruthy()
 expect(screen.getByRole('link',{name:'下载 DOCX'})).toBeTruthy()
})

// B04 task 11: customer wording of the school export options.
const customerChapters=[{id:'chapter-result',title:'第三章 实验结果',level:1,purpose:'results',output_language:'zh-CN',result_group_ids:[]}]
const customerVersion=(confirmation:Record<string,unknown>={},extra:Record<string,unknown>={})=>({...manuscriptFixture.versions[0],id:'v3',revision:3,exports:[],snapshot:{...manuscriptFixture.versions[0].snapshot,output_language:'zh-CN',...extra,thesis_context:{confirmation_id:'confirm1',chapters:customerChapters,confirmation}}}) as unknown as ManuscriptVersion
const customerBase='/api/v1/projects/p1/manuscripts/m1/versions/3/exports'
const customerPlan=(canExport:boolean)=>({...plan,sections:[{chapter_id:'__cover__',page_number:null},{chapter_id:'chapter-result',page_number:{format:'decimal',mode:'restart',start:1}},{chapter_id:'unknown',page_number:null}],chapters:[{id:'chapter-result',title:'第三章 实验结果'}],
 report:{...report,can_export:canExport,issues:canExport?[]:[{id:'e1',kind:'format' as const,severity:'error' as const,location:'cover',message:'封面缺少题名',source_evidence:[]}]}})
function customerServer(canExport:boolean){
 return vi.fn(async(url:string,_init?:RequestInit)=>url===`${customerBase}/preview`?Response.json({schema_version:1,school:customerPlan(canExport)}):Response.json({items:[]}))
}
it('words the customer school export options as the cover and contents of this Word',async()=>{
 const fetcher=customerServer(true);vi.stubGlobal('fetch',fetcher)
 const {container}=render(<ManuscriptExports customerThesis projectId="p1" manuscriptId="m1" version={customerVersion()}/>)
 await screen.findByText('当前版本尚未生成 Word。')
 expect(screen.getByRole('heading',{name:'封面与目录'})).toBeTruthy()
 expect(screen.getByText('按第 3 版导出；封面等填写内容只用于这次 Word。')).toBeTruthy()
 fireEvent.click(screen.getByLabelText('包含目录'))
 fireEvent.change(screen.getByLabelText('目录深度'),{target:{value:'2'}})
 fireEvent.click(screen.getByRole('button',{name:'检查能否生成 Word'}))
 expect(await screen.findByText('可以生成 Word。')).toBeTruthy()
 const post=(fetcher.mock.calls as unknown as [string,RequestInit][]).find(([,init])=>init?.method==='POST')!
 expect(JSON.parse(String(post[1].body)).school).toMatchObject({include_toc:false,toc_depth:2})
 const pages=[...container.querySelectorAll('.school-export-details > ul')].at(-1)!
 expect([...pages.querySelectorAll('li')].map(li=>li.textContent?.split(' · ')[0])).toEqual(['封面','第三章 实验结果','第 3 节'])
 for(const text of ['工程','版本 3','盲审稿会隐去','盲审','导出固定稿件'])expect(container.textContent).not.toContain(text)
 expect(container.querySelectorAll('details')).toHaveLength(0)
 expect(findTechnicalText(container,{systemIds:['confirm1','chapter-result','__cover__','a'.repeat(64),'b'.repeat(64),'c'.repeat(64)]})).toEqual([])
})
it('tells the customer when the school check blocks the Word',async()=>{
 vi.stubGlobal('fetch',customerServer(false))
 render(<ManuscriptExports customerThesis projectId="p1" manuscriptId="m1" version={customerVersion()}/>)
 await screen.findByText('当前版本尚未生成 Word。')
 fireEvent.click(screen.getByRole('button',{name:'检查能否生成 Word'}))
 expect((await screen.findByText('有必须修改的项，暂时不能生成 Word。')).getAttribute('role')).toBe('alert')
 expect((screen.getByRole('button',{name:'生成 Word'}) as HTMLButtonElement).disabled).toBe(true)
})
it('keeps GS501 identity fields for the identified Word and the third-party notice without hiding wording',async()=>{
 const front={schema_version:1,cover_section_id:'section-1',fields:[{id:'author',label:'论文作者',kind:'identity',required:true,source_id:'author',style_source_id:null,section_id:'section-1',chapter_id:null}],content_requirements:[]}
 vi.stubGlobal('fetch',customerServer(true))
 const {container}=render(<ManuscriptExports customerThesis projectId="p1" manuscriptId="m1" version={customerVersion({front_matter:front,format_profile:'bsu-gs501-academic-masters-2026'})}/>)
 await screen.findByText('当前版本尚未生成 Word。')
 const panel=screen.getByRole('heading',{name:'封面与目录'}).parentElement!
 expect(within(panel).getByText('盲评版请按学校要求交第三方处理。')).toBeTruthy()
 expect(screen.getByLabelText('论文作者 · 必填')).toBeTruthy()
 for(const text of ['盲审稿会隐去','隐去','工程'])expect(container.textContent).not.toContain(text)
})
it('disables the sealed customer options after language review',async()=>{
 const sealed={manual_fields:{author:'合成作者',student_id:'',department:'',major:'',class_name:'',supervisor:'',submission_date:''},manual_chapters:[],english_title:'Reviewed title',keywords:[],include_toc:true,toc_depth:3}
 vi.stubGlobal('fetch',customerServer(true))
 render(<ManuscriptExports customerThesis projectId="p1" manuscriptId="m1" version={customerVersion({},{writing_provenance:{provider_provenance:'synthetic_fixture',verification_status:'not_verified',language_review_id:'lr1',school_export_options:sealed}})}/>)
 await screen.findByText('当前版本尚未生成 Word。')
 expect(screen.getByLabelText('作者').matches(':disabled')).toBe(true)
 expect((screen.getByLabelText('作者') as HTMLInputElement).value).toBe('合成作者')
 expect(screen.getByLabelText('目录深度').matches(':disabled')).toBe(true)
})
it('keeps the staff school export wording',async()=>{
 vi.stubGlobal('fetch',customerServer(true))
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={customerVersion()}/>)
 expect(screen.getByRole('heading',{name:'学校固定版本导出'})).toBeTruthy()
 expect(screen.getByText('导出固定稿件版本 3；人工字段仅保存到本次导出。')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'预览学校排版'}))
 expect(await screen.findByText('学校检查允许工程导出。')).toBeTruthy()
})
// B05 task 11: the customer Word page names what the customer fills in and what the button checks.
const thanks={id:'chapter-thanks',title:'致谢',level:1,purpose:'acknowledgements',output_language:'zh-CN',result_group_ids:[]}
const thanksVersion=()=>{const value=customerVersion();value.snapshot.thesis_context!.chapters=[...customerChapters,thanks] as never;return value}
it('words the customer Word options without manual-text or layout-preview wording',async()=>{
 vi.stubGlobal('fetch',customerServer(true))
 const {container}=render(<ManuscriptExports customerThesis projectId="p1" manuscriptId="m1" version={thanksVersion()}/>)
 await screen.findByText('当前版本尚未生成 Word。')
 expect(screen.getByRole('group',{name:'封面和补充内容'})).toBeTruthy()
 expect(screen.getByLabelText('致谢 · 需要你填写的内容')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'检查能否生成 Word'}))
 expect(await screen.findByText('可以生成 Word。')).toBeTruthy()
 expect(container.textContent).not.toMatch(/人工文本|预览学校排版|本次导出内容/)
})
it('words the customer Word options in English',async()=>{
 setLocale('en')
 vi.stubGlobal('fetch',customerServer(true))
 render(<ManuscriptExports customerThesis projectId="p1" manuscriptId="m1" version={thanksVersion()}/>)
 expect(await screen.findByRole('group',{name:'Cover and other content'})).toBeTruthy()
 expect(screen.getByLabelText('致谢 · What you need to fill in')).toBeTruthy()
 expect(screen.getByRole('button',{name:'Check whether Word can be generated'})).toBeTruthy()
})
it('keeps the staff manual-text wording on the staff Word page',async()=>{
 vi.stubGlobal('fetch',customerServer(true))
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={thanksVersion()}/>)
 expect(screen.getByRole('group',{name:'本次导出内容'})).toBeTruthy()
 expect(screen.getByLabelText('致谢 · 人工文本')).toBeTruthy()
})
