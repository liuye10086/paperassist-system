import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptExports from './ManuscriptExports'
import {manuscriptFixture,exportFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('collects explicit school fields and previews the request without submitting a task',async()=>{
 const version={...manuscriptFixture.versions[0],exports:[],snapshot:{...manuscriptFixture.versions[0].snapshot,thesis_context:{confirmation_id:'confirm1',chapters:[{id:'manual1',title:'声明',purpose:'manual'},{id:'abstract1',title:'英文摘要',purpose:'abstract'}]}}} as unknown as ManuscriptVersion
 const fetcher=vi.fn(async(_url:string,_init?:RequestInit)=>Response.json({items:[],pdf_status:'not_requested'}));vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version}/>);
 fireEvent.change(screen.getByLabelText('作者'),{target:{value:'测试作者'}})
 fireEvent.change(screen.getByLabelText('声明 · 人工文本'),{target:{value:'明确提供文本'}})
 fireEvent.change(screen.getByLabelText('英文摘要 · 关键词'),{target:{value:'one; two'}})
 fireEvent.click(screen.getByRole('button',{name:'预览学校排版'}));await screen.findByRole('alert')
 const post=fetcher.mock.calls.find((call)=> (call as unknown as [string,RequestInit])[1]?.method==='POST') as unknown as [string,RequestInit]
 expect(post[0]).toContain('/versions/1/exports/preview')
 expect(JSON.parse(String(post[1].body))).toMatchObject({school:{manual_fields:{author:'测试作者'},manual_chapters:[{chapter_id:'manual1',text:'明确提供文本'}],keywords:[{chapter_id:'abstract1',values:['one','two']}],include_toc:true,toc_depth:3}})
})

const report={rules_version:'school-export-v1',issues:[{id:'m1',kind:'manual' as const,severity:'human_review' as const,location:'cover',message:'封面作者待补充',source_evidence:[]}],can_export:true,scientifically_verified:false as const}
const plan={schema_version:1 as const,rules_version:'school-export-v1',confirmation_id:'confirm1',confirmation_sha256:'a'.repeat(64),analysis_sha256:'b'.repeat(64),snapshot_sha256:'c'.repeat(64),options:{},styles:{},sections:[],chapters:[],requirements:[],rule_decisions:[{id:'font',message:'正文英文采用TNR',source_evidence:[]}],toc:{enabled:true,depth:3},label_map:{figures:{},tables:{}},report}
const version={...manuscriptFixture.versions[0],exports:[],snapshot:{...manuscriptFixture.versions[0].snapshot,thesis_context:{confirmation_id:'confirm1',chapters:[]}}} as unknown as ManuscriptVersion
it('previews and creates using identical school options, restores static receipt and keeps Word after PDF failure',async()=>{
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
 fireEvent.click(await screen.findByRole('button',{name:'生成 PDF'}));await screen.findByRole('alert')
 expect(screen.getByRole('link',{name:'下载 DOCX'}).getAttribute('href')).toBe(exportFixture.download_url)
 const pdf=fetcher.mock.calls.find(([url,init])=>url.includes('/pdf-exports')&&init?.method==='POST')!;expect(JSON.parse(String(pdf[1]?.body))).toMatchObject({source_kind:'manuscript_export',source_id:'export1'})
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
 expect(screen.getByText('学校目录已完成排版，请直接下载 Word 或生成 PDF。')).toBeTruthy()
 expect(screen.getByRole('button',{name:'刷新 PDF 状态'})).toBeTruthy()
})

it('keeps the existing layout entry for school exports without a TOC manifest',async()=>{
 const result={...exportFixture,school:{plan:{...plan,toc:{enabled:false,depth:3}},report,field_update:{status:'not_requested'}}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/pdf-exports')?{items:[]}:{items:[result],pdf_status:'not_requested'})))
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version}/>);
 expect(await screen.findByRole('button',{name:'排版与公式'})).toBeTruthy()
 expect(screen.getByRole('link',{name:'下载 DOCX'})).toBeTruthy()
})
