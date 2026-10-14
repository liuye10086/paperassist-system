import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { setLocale } from '../../shared/i18n'
import { clearApiSession } from '../../shared/api/client'
import ParsedEvidencePanel from './ParsedEvidencePanel'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); setLocale('zh-CN') })
const props = { projectId:'p', fileId:'f', versionId:'v1', kind:'document_version' as const }
function evidence(version='v1', text='图1：原文') {
 const base='/api/v1/projects/p/files/f'
 return { schema_version:1, source:{project_id:'p',file_id:'f',version_id:version,version:1,kind:'document_version',filename:'原文.docx',sha256:'a'.repeat(64),source_sha256:'b'.repeat(64),parent_version_id:null,parent_object_download_url:null,original_download_url:base+'/download',object_download_url:base+'/document-versions/'+version+'/download'},format:'docx',parser_version:'openxml-docx-v1',scope:{kind:'document',pages:[] as number[]},counts:{images:1} as Record<string,number>,count_semantics:'stored_evidence_not_research_n',pagination:{page:1,page_size:20,total:1,returned:1,has_more:false},items:[{id:'text1',kind:'text',location:{part:'word/document.xml',path:'/document/body/p[1]'},text,value:null,cells:[],rows:null,columns:null,image_id:null,preview_url:null,associations:[],uncertainties:[]}],uncertainties:['stored_counts_not_research_n'],warnings:[] }
}
it.each(['docx','pdf','xlsx'])('shows readable labels and format-specific cell coordinates for %s',async(format)=>{
 const data=evidence();data.format=format;data.counts={paragraphs:1}
 if(format==='pdf')data.scope.pages=[1]
 Object.assign(data.items[0].location,{row:format==='xlsx'?5:format==='pdf'?1:0,column:format==='xlsx'?3:format==='pdf'?1:0,coordinate:format==='xlsx'?'C5':null})
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(data)))
 render(<ParsedEvidencePanel {...props}/>);fireEvent.click(screen.getByRole('button',{name:'解析内容与来源'}))
 await screen.findByText('存储段落数')
 expect(screen.getByText('文本')).toBeTruthy()
 expect(screen.getByText(new RegExp(format==='xlsx'?'行 5，列 3':'行 1，列 1'))).toBeTruthy()
 if(format==='docx')expect(screen.getByText(/已保存的文档结构/)).toBeTruthy()
 if(format==='pdf')expect(screen.getByText('解析范围 · 物理页 1')).toBeTruthy()
})
it.each(['zh-CN','en'] as const)('maps all stored enum labels and preserves user value in %s',async(locale)=>{
 setLocale(locale)
 const data=evidence();data.counts={paragraphs:1,tables:2,cells:3,images:4,pages:5,text_blocks:6,pages_without_text:7,embedded_images:8,rows:9,fields:10}
 Object.assign(data.items[0],{value:{kind:'number',typed:'123.00',raw_available:false,original_typed:null,raw_source_version_id:null,raw_type:null,raw:null,number_format:null,formula:null,unit:{status:'unconfirmed',value:null}}})
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(data)))
 render(<ParsedEvidencePanel {...props}/>);fireEvent.click(screen.getByRole('button',{name:locale==='en'?'Parsed content and sources':'解析内容与来源'}))
 await screen.findByText('123.00',{exact:false})
 expect(screen.getByText(locale==='en'?'Read type and original value · Number':'读取类型与原值 · 数值')).toBeTruthy()
 expect(screen.getByText('图1：原文')).toBeTruthy()
 expect(screen.getByText(locale==='en'?'Stored paragraphs':'存储段落数')).toBeTruthy()
 const {evidenceLabels,evidenceMessages}=await import('./evidenceMessages')
 for(const code of ['paragraphs','tables','cells','images','pages','text_blocks','pages_without_text','embedded_images','rows','fields','text','table','cell','field','row','image','number','boolean','blank','date','datetime','time','duration','formula','error']){
  expect(evidenceLabels[code]).toBeTruthy();expect(evidenceLabels[code]).not.toBe(code);expect(evidenceMessages[evidenceLabels[code]]).toBeTruthy()
 }
})
it('loads only when opened and translates labels without translating original text', async () => {
 const fetch=vi.fn(async()=>Response.json(evidence()))
 vi.stubGlobal('fetch',fetch)
 setLocale('en')
 render(<ParsedEvidencePanel {...props}/>)
 expect(fetch).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'Parsed content and sources'}))
 expect(await screen.findByText('图1：原文')).toBeTruthy()
 expect(screen.getAllByText('Stored counts are not the research sample size.')).toHaveLength(2)
 expect(fetch).toHaveBeenCalledTimes(1)
})
it('discards an older version response after selection changes', async () => {
 let resolve:(response:Response)=>void=()=>{}
 vi.stubGlobal('fetch',vi.fn((url:string)=>url.includes('/document-versions/v1/')?new Promise<Response>(r=>{resolve=r}):Promise.resolve(Response.json(evidence('v2','new text')))))
 const view=render(<ParsedEvidencePanel {...props}/>)
 fireEvent.click(screen.getByRole('button',{name:'解析内容与来源'}))
 view.rerender(<ParsedEvidencePanel {...props} versionId="v2"/>)
 fireEvent.click(screen.getByRole('button',{name:'解析内容与来源'}))
 await screen.findByText('new text')
 resolve(Response.json(evidence()))
 await waitFor(()=>expect(screen.queryByText('图1：原文')).toBeNull())
})
it('clears evidence on session changes and denies mismatched source payloads', async () => {
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(evidence())))
 render(<ParsedEvidencePanel {...props}/>)
 fireEvent.click(screen.getByRole('button',{name:'解析内容与来源'}))
 await screen.findByText('图1：原文')
 clearApiSession()
 await waitFor(()=>expect(screen.queryByText('图1：原文')).toBeNull())
})
it('reports request timeout and allows an explicit reload',async()=>{
 vi.useFakeTimers()
 vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(()=>{})))
 render(<ParsedEvidencePanel {...props}/>)
 fireEvent.click(screen.getByRole('button',{name:'解析内容与来源'}))
 await act(async()=>{await vi.advanceTimersByTimeAsync(15001)})
 expect(screen.getByRole('alert').textContent).toBe('解析证据读取失败，请重试。')
 expect(screen.queryByText('正在读取解析证据……')).toBeNull()
})
it('clears displayed evidence after a forbidden object download',async()=>{
 const lost=vi.fn()
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.endsWith('/download')?Response.json({detail:{code:'forbidden'}},{status:403}):Response.json(evidence())))
 render(<ParsedEvidencePanel {...props} onUnavailable={lost}/>)
 fireEvent.click(screen.getByRole('button',{name:'解析内容与来源'}))
 await screen.findByText('图1：原文')
 fireEvent.click(screen.getByRole('link',{name:'下载证据对象'}))
 await waitFor(()=>expect(screen.queryByText('图1：原文')).toBeNull())
 expect(lost).toHaveBeenCalledTimes(1)
})
it('rejects wrong identities, external URLs and inconsistent pagination',async()=>{
 const {isEvidence}=await import('./evidenceApi')
 const good=evidence()
 expect(isEvidence(good,props,1)).toBe(true)
 expect(isEvidence({...good,source:{...good.source,file_id:'other'}},props,1)).toBe(false)
 expect(isEvidence({...good,source:{...good.source,object_download_url:'https://external.test/track'}},props,1)).toBe(false)
 expect(isEvidence({...good,pagination:{...good.pagination,returned:2}},props,1)).toBe(false)
 expect(isEvidence({...good,scope:{...good.scope,sheet_name:{malformed:true}}},props,1)).toBe(false)
})
it('the document entry keeps the prior successful evidence source after a failed selection',async()=>{
 const {default:DocumentVersions}=await import('../documents/DocumentVersions')
 const base='/api/v1/projects/p/files/f/document-versions'
 const good={id:'v1',file_id:'f',version:1,task_id:'t1',status:'succeeded',created_at:'2026-10-12',completed_at:'2026-10-12',parser_version:'openxml-docx-v1',summary:{counts:{paragraphs:1,tables:0,cells:0,images:0},warnings:[]},error:null,download_url:base+'/v1/download',blocks_url:base+'/v1/blocks',styles:[],sections:[],images:[]}
 const bad={...good,id:'failed',version:2,status:'failed',summary:null,error:{code:'invalid_document',message:'ignored'},download_url:null,blocks_url:null}
 const fetch=vi.fn(async(url:string)=>{
  if(url.includes('/evidence?'))return Response.json(evidence())
  if(url.includes('/blocks?'))return Response.json({items:[],total:0,page:1,page_size:20})
  if(url.endsWith('/failed'))return Response.json(bad)
  if(url.endsWith('/v1'))return Response.json(good)
  return Response.json({items:[good,bad],total:2,page:1,page_size:5,latest_version:2})
 })
 vi.stubGlobal('fetch',fetch)
 render(<DocumentVersions projectId="p" fileId="f" filename="paper.docx" active onUnavailable={()=>{}}/>)
 fireEvent.click(await screen.findByRole('button',{name:'Word 版本 v1 · 已完成'}))
 await screen.findByRole('button',{name:'解析内容与来源'})
 fireEvent.click(screen.getByRole('button',{name:'Word 版本 v2 · 执行失败'}))
 await screen.findByText('继续显示此前成功版本 v1 的内容。')
 fireEvent.click(screen.getByRole('button',{name:'解析内容与来源'}))
 await screen.findByText('图1：原文')
 expect(fetch.mock.calls.filter(([url])=>url.includes('/evidence?')).map(([url])=>url)).toEqual([base+'/v1/evidence?page=1'])
})
it.each(['zh-CN','en'] as const)('shows stored Word/PDF/OCR warnings, their real scope and unmodified original messages in %s',async(locale)=>{
 setLocale(locale)
 const warnings=[
  {code:'revisions',message:'修订内容未自动接受或提取。',count:2,scope:'document',pages:[],location:null},
  {code:'undecoded_characters',message:'存在未解码字符，文字内容请核对原件。',count:3,scope:'page',pages:[2],location:{page_number:2,bbox:[0,0,300,400]}},
  {code:'low_confidence',message:'部分文字置信度较低，请对照原图核对。',count:1,scope:'page',pages:[5],location:{page_number:5,bbox:[0,0,100,100],coordinate_system:'image_pixels_top_left'}},
 ]
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...evidence(),warnings})))
 render(<ParsedEvidencePanel {...props}/>)
 fireEvent.click(screen.getByRole('button',{name:locale==='en'?'Parsed content and sources':'解析内容与来源'}))
 await screen.findByText('图1：原文')
 for(const warning of warnings)expect(screen.getByText(warning.message)).toBeTruthy()
 expect(screen.getByText(locale==='en'?'Undecoded characters':'未解码字符')).toBeTruthy()
 expect(screen.getByText(locale==='en'?'Document-level warning':'文档范围警告')).toBeTruthy()
 expect(screen.getAllByText(locale==='en'?'Physical page 2':'物理页 2').length).toBeGreaterThan(0)
 expect(screen.getByText(locale==='en'?'Recorded count: 3':'记录数量：3')).toBeTruthy()
})
