import {afterEach,expect,test,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import ReportCollections from './ReportCollections'
import {correlationResult} from '../analysis/correlationFixtures'
import {setLocale} from '../../shared/i18n'
import {defaultConfig} from '../figure-workbench/config'
const source=correlationResult.source
const config={id:'config-version',source,config:{...defaultConfig('scatter','zh-CN'),style:{...defaultConfig('scatter','zh-CN').style,title:'Study association'}}}
const pending={result:correlationResult,figure:null,explanation:null,configuration:config,projection:{id:'projection1'}}
const request={id:'request1',version_id:'cv1',export_revision:1,status:'waiting',missing:[{figure_config_version_id:'config-version',kind:'figure'}],report:null}
const version={id:'cv1',revision:1,title:'Study report',language:'zh-CN',automatic:true,items:[{...pending,figure_number:1}],requests:[request]}
const collection={id:'collection1',title:'Study report',current_version_id:'cv1',versions:[version]}
const props={projectId:'p1',fileId:'f1',source,language:'zh-CN' as const}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
test('offers PDF for the exact saved collection DOCX and shows both frozen revisions',async()=>{
 const report={schema_version:1,id:'collection-report1',filename:'saved.docx',collection_id:'collection1',collection_version_id:'cv1',build_request_id:'request1',export_revision:2,language:'zh-CN',sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),size_bytes:100,engine:{id:'collection_word_v1'}}
 const saved={...collection,versions:[{...version,requests:[{...request,export_revision:2,status:'succeeded',missing:[],report}]}]}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>url.includes('/pdf-exports')?init?.method==='POST'?Response.json({detail:{code:'pdf_renderer_unavailable'}},{status:503}):Response.json({items:[]}):Response.json(url.includes('/candidates')?{items:[pending]}:{items:[saved]}));vi.stubGlobal('fetch',fetcher)
 render(<ReportCollections {...props}/>);await screen.findByRole('link',{name:'下载此版本 Word'});const button=await screen.findByRole('button',{name:'生成 PDF'});await waitFor(()=>expect(button.hasAttribute('disabled')).toBe(false));fireEvent.click(button);await screen.findByRole('alert')
 expect(screen.getByRole('button',{name:'排版与公式'})).toBeTruthy();expect(fetcher.mock.calls.some(([url])=>url.includes('/layout-exports'))).toBe(false);
 expect(screen.getByRole('link',{name:'下载此版本 Word'})).toBeTruthy();expect(screen.getByText(/集合 v1 · 导出 v2/)).toBeTruthy();const post=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(JSON.parse(String(post[1]?.body))).toMatchObject({source_kind:'collection_report',source_id:'collection-report1'})
})
test('pending figure selection saves an exact configuration dependency without paid work',async()=>{
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?collection:url.includes('/candidates')?{items:[pending]}:{items:[]}));vi.stubGlobal('fetch',fetch)
 render(<ReportCollections {...props}/>)
 await screen.findByText('Study association · 图表待生成')
 fireEvent.change(screen.getByLabelText('集合标题'),{target:{value:'Study report'}})
 fireEvent.click(screen.getByLabelText('Study association · 图表待生成'))
 fireEvent.click(screen.getByRole('button',{name:'保存并启用集合'}))
 await waitFor(()=>expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true))
 const mutation=fetch.mock.calls.find(([,init])=>init?.method==='POST')!
 expect(mutation[0]).toBe('/api/v1/projects/p1/report-collections')
 expect(JSON.parse(String(mutation[1]?.body))).toMatchObject({automatic:true,items:[{figure_config_version_id:'config-version'}]})
 expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1)
})
test('explicit export reuses its key after an uncertain response and GET never creates a report',async()=>{
 const keys:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){keys.push(new Headers(init.headers).get('Idempotency-Key')!);if(keys.length===1)throw new TypeError('network');return Response.json({...request,export_revision:2})}
  return Response.json(url.includes('/candidates')?{items:[pending]}:{items:[collection]})
 }))
 render(<ReportCollections {...props}/>)
 await screen.findByText('集合版本 1 · 当前版本')
 expect(keys).toEqual([])
 fireEvent.click(screen.getByRole('button',{name:'生成新版报告'}))
 await screen.findByRole('alert')
 fireEvent.click(screen.getByRole('button',{name:'生成新版报告'}))
 await waitFor(()=>expect(keys.length).toBe(2))
 expect(keys[0]).toBe(keys[1])
})
test('English collection interface keeps internal IDs out of visible text',async()=>{
 setLocale('en');const enPending={...pending,configuration:{...config,config:{...config.config,language:'en'}}}
 const enCollection={...collection,versions:[{...version,language:'en',items:[enPending]}]}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/candidates')?{items:[enPending]}:{items:[enCollection]})))
 render(<ReportCollections {...props} language='en'/>)
 await screen.findByText('Study association · Figure generation pending')
 expect(screen.getByText('Collection version 1 · Current version')).toBeTruthy()
 expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/)
 expect(document.body.textContent).not.toContain('config-version')
 expect(document.body.textContent).not.toContain(source.dataset_sha256)
})

test('nine-section preview uses readable facts and scoped enum labels while preserving author text',async()=>{
 const keys=['overview','quality','processing','methods','statistics','figures','explanations','findings','summary']
 const content={source:{kind:'prepared_dataset_version',rules_version:'excel_profile_v1',dataset_version:1},record_count:5,valid_count:4,research_request:{question:'confirmed',observation_structure:'independent'},selected_fields:[{name:'confirmed',prepared_unit:{status:'confirmed',value:'confirmed'},type_counts:{number:4}}],method:'pearson_beta_two_sided',statistics:{n:4,p_value:{value:0.2,method:'pearson_beta_two_sided'},warnings:['correlation_not_causation']},rules_version:'analysis_plan_rules_v3',engine:{id:'internal-engine'},missing:true}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/preview')?{schema_version:1,language:'zh-CN',items:[pending],ready:false,missing:[{figure_id:'pending',kind:'figure'}],sections:keys.map(key=>({key,title:key,content:[content]}))}:url.includes('/candidates')?{items:[pending]}:{items:[collection]})))
 const {container}=render(<ReportCollections {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'预览九类报告内容'}))
 await screen.findByText('九类报告内容预览')
 const preview=container.querySelector('.report-preview')!
 expect(preview.querySelectorAll(':scope > details')).toHaveLength(9)
 expect(preview.querySelectorAll(':scope > details[open]')).toHaveLength(0)
 expect(preview.textContent).toContain('所选字段');expect(preview.textContent).toContain('研究声明')
 expect(preview.textContent).toContain('Pearson双侧Beta检验');expect(preview.textContent).toContain('已确认')
 expect(preview.textContent).toContain('confirmed');expect(preview.textContent).toContain('0.2')
 expect(preview.textContent).not.toMatch(/资料|prepared_dataset_version|excel_profile_v1|analysis_plan_rules_v3|pearson_beta_two_sided|internal-engine/)
})
