import { lifecycleResponse } from '../files/lifecycleFixtures'
import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DocumentVersions from './DocumentVersions'
import { validateFile } from '../files/batchUploadApi'
import { setLocale } from '../../shared/i18n'
import { isOcrPageResponse, parseOcrPageSelection } from './ocrApi'
import OcrPage from './OcrPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); setLocale('zh-CN') })
const base = '/api/v1/projects/p/files/f/document-versions'
const pdf = { id:'text', file_id:'f', version:1, task_id:'task', kind:'pdf_document', status:'succeeded', created_at:'2026-10-12', completed_at:null, parser_version:'pdf', summary:{counts:{pages:12,text_blocks:1,tables:0,cells:0,pages_without_text:11},warnings:[]}, error:null, download_url:'download', pages_url:'pages' }
const ocr = { ...pdf, id:'ocr', version:2, kind:'ocr_document', summary:{counts:{pages:2,text_blocks:21,images:2,pages_without_text:0},warnings:[]}, selected_pages:[3,12], source_pages:12, images:[{id:'preview-secret',mime:'image/jpeg',size_bytes:3,inline_preview:true,download_url:'https://external.invalid/private'}] }
const textPage = (page:number) => ({page_number:page,width:600,height:800,rotation:0,bbox:[0,0,600,800],text_status:page===1?'text':'no_extractable_text',text_blocks:page===1?[{kind:'text',id:'t',text:'Keep PDF text',source:{page_number:1,bbox:[0,0,10,10],label:'private'}}]:[],tables:[],warnings:[]})
const ocrPage = (page:number) => ({page_number:page===1?3:12,width:1200,height:1600,rotation:0,preview_image_id:'preview-secret',source_width:600,source_height:800,source_coordinate_system:'pdf_points_bottom_left',pixel_to_source:[0.5,0,0,0,-0.5,800],transforms:[],text_status:'text',text_blocks:Array.from({length:21},(_,i)=>({kind:'ocr_text',id:`private-${i}`,text:`OCR line ${i+1}`,score:i===0?0.7:0.99,review_status:'unreviewed',polygon:[[10,20],[100,20],[100,50],[10,50]],source:{page_number:page===1?3:12,label:'private-source',polygon:[[5,10],[50,10],[50,25],[5,25]],coordinate_system:'pdf_points_bottom_left'}})),warnings:[]})
function mockDocuments(versions = [pdf, ocr], post?: (url:string, init:RequestInit)=>Response) {
 const create=vi.fn(()=>`blob:ocr-${create.mock.calls.length}`),revoke=vi.fn();const NativeURL=URL
 vi.stubGlobal('URL',class extends NativeURL {static createObjectURL=create;static revokeObjectURL=revoke})
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>{
  const impact=lifecycleResponse(url);if(impact)return impact
  if(init?.method==='POST')return post?.(url,init)??Response.json({...ocr,status:'queued'})
  if(url.includes('/images/'))return new Response('jpg',{headers:{'Content-Type':'image/jpeg'}})
  if(url.includes('/pages')){const page=Number(new URL(url,'http://localhost').searchParams.get('page'));return Response.json({items:[url.includes('/ocr/')?ocrPage(page):textPage(page)],total:url.includes('/ocr/')?2:12,page,page_size:1})}
  if(url.includes('?'))return Response.json({items:versions,total:versions.length,page:1,page_size:5,latest_version:versions.length})
  return Response.json(versions.find(v=>url.endsWith(`/${v.id}`)))
 });vi.stubGlobal('fetch',fetch);return {fetch,create,revoke}
}
test('PNG and both JPEG filename extensions are accepted with the existing size limit',()=>{
 for(const name of ['scan.png','scan.JPG','scan.jpeg'])expect(validateFile(new File(['image'],name))).toBeNull()
 expect(validateFile(new File([new Uint8Array(10485761)],'large.jpg'))).toBe('单文件不能超过 10 MiB。')
})
test('PDF switches between text and OCR by version kind and uses physical source pages',async()=>{
 const user=userEvent.setup();const {fetch,create,revoke}=mockDocuments()
 const view=render(<DocumentVersions projectId="p" fileId="f" filename="paper.pdf" fileType="pdf" active onUnavailable={()=>{}} />)
 await user.click(await screen.findByRole('button',{name:'PDF 版本 v1 · 已完成'}));await screen.findByText('Keep PDF text')
 await user.click(screen.getByRole('button',{name:'PDF 版本 v2 · 已完成'}));await screen.findByText('OCR line 1')
 expect(screen.queryByText('Keep PDF text')).toBeNull();expect(screen.getByText('物理页 3 · OCR 文字候选')).toBeTruthy()
 expect(await screen.findByRole('img',{name:'物理页 3 原图预览'})).toBeTruthy();expect(create).toHaveBeenCalledTimes(1)
 expect(screen.queryByText('OCR line 21')).toBeNull();expect(screen.getByText('较低置信度')).toBeTruthy();expect(screen.queryByRole('button',{name:'确认正确'})).toBeNull()
 await user.click(screen.getByRole('button',{name:'OCR line 1'}));expect(document.querySelector('polygon[data-selected="true"]')?.getAttribute('points')).toBe('10,20 100,20 100,50 10,50')
 expect(document.querySelector('svg')?.getAttribute('viewBox')).toBe('0 0 1200 1600')
 await user.click(screen.getByRole('button',{name:'下一页 OCR 文字'}));expect(screen.getByRole('button',{name:'OCR line 21'})).toBeTruthy()
 await user.click(screen.getByRole('button',{name:'下一张识别页'}));await screen.findByText('物理页 12 · OCR 文字候选')
 expect(fetch.mock.calls.some(([url])=>url===base+'/ocr/pages?page=2')).toBe(true)
 expect(fetch.mock.calls.some(([url])=>url.startsWith('https:'))).toBe(false)
 expect(screen.queryByText('preview-secret')).toBeNull();expect(screen.queryByText('private-source')).toBeNull()
 view.unmount();await waitFor(()=>expect(revoke).toHaveBeenCalled())
})
test('PDF page entry accepts arbitrary unique physical pages and rejects more than ten without truncation',async()=>{
 const user=userEvent.setup();const posted:{url:string;body:unknown;key:string|null}[]=[]
 mockDocuments([pdf],(url,init)=>{posted.push({url,body:JSON.parse(init.body as string),key:new Headers(init.headers).get('Idempotency-Key')});return Response.json({...ocr,status:'queued'})})
 render(<DocumentVersions projectId="p" fileId="f" filename="paper.pdf" active onUnavailable={()=>{}} />)
 await screen.findByRole('button',{name:'PDF 版本 v1 · 已完成'})
 const input=screen.getByRole('textbox',{name:'识别物理页（1—100）'})
 await user.type(input,'1-11');await user.click(screen.getByRole('button',{name:'识别所选页'}));expect(posted).toHaveLength(0);expect(screen.getByRole('alert').textContent).toContain('每次选择 1—10 个不重复的物理页')
 await user.clear(input);await user.type(input,'1, 12');await user.click(screen.getByRole('button',{name:'识别所选页'}));expect(posted).toHaveLength(0);await user.click(await screen.findByRole('button',{name:'确认并开始重解析'}))
 await waitFor(()=>expect(posted).toHaveLength(1));expect(posted[0].url).toBe(base+'/ocr');expect(posted[0].body).toEqual({expected_latest_version:1,expected_assessment_revision:'a'.repeat(64),page_numbers:[1,12]});expect(posted[0].key).toBeTruthy()
})
test('failed OCR version can be inspected while the prior successful content remains available',async()=>{
 const user=userEvent.setup();const failed={...ocr,id:'failed',version:3,status:'failed',summary:null,error:{code:'unknown',message:'internal-secret'}}
 mockDocuments([pdf,failed as never])
 render(<DocumentVersions projectId="p" fileId="f" filename="paper.pdf" active onUnavailable={()=>{}} />)
 await user.click(await screen.findByRole('button',{name:'PDF 版本 v1 · 已完成'}));await screen.findByText('Keep PDF text')
 await user.click(screen.getByRole('button',{name:'PDF 版本 v3 · 执行失败'}));await screen.findByRole('heading',{name:'PDF 版本 v3'})
 expect(screen.getByText('Keep PDF text')).toBeTruthy();expect(screen.queryByText('internal-secret')).toBeNull()
})
test('English OCR image document actions and notices retain the original recognized strings',async()=>{
 const user=userEvent.setup();setLocale('en');mockDocuments([ocr])
 render(<DocumentVersions projectId="p" fileId="f" filename="scan.jpeg" fileType={'jpeg' as never} active onUnavailable={()=>{}} />)
 await user.click(await screen.findByRole('button',{name:'Image version v2 · Completed'}));await screen.findByText('OCR line 1')
 expect(screen.getByRole('button',{name:'Recognize image again'})).toBeTruthy();expect(screen.getByText('All recognized text awaits human verification.')).toBeTruthy()
})
test('manual page boundaries reject duplicate, zero, above one hundred, reverse and oversized ranges',()=>{
 expect(parseOcrPageSelection('100, 1, 3-5')).toEqual([1,3,4,5,100])
 expect(parseOcrPageSelection('1-10')).toHaveLength(10)
 for(const input of ['', '0','101','1,1','10-1','1-11','1 2 3 4 5 6 7 8 9 10 100','1.5','abc'])expect(parseOcrPageSelection(input)).toBeNull()
})
test('OCR page validation keeps physical page independent from response ordinal and rejects invalid confidence, review state and coordinates',()=>{
 const page=ocrPage(2)
 expect(isOcrPageResponse({items:[page],total:2,page:2,page_size:1},2)).toBe(true)
 for(const block of [{...page.text_blocks[0],score:1.1},{...page.text_blocks[0],review_status:'confirmed'},{...page.text_blocks[0],polygon:[[1,2]]}])expect(isOcrPageResponse({items:[{...page,text_blocks:[block]}],total:2,page:2,page_size:1},2)).toBe(false)
})
test('more than ten suggested pages stay unselected until the user chooses, and do not erase a manual choice',async()=>{
 const user=userEvent.setup();mockDocuments([pdf])
 render(<DocumentVersions projectId="p" fileId="f" filename="paper.pdf" active onUnavailable={()=>{}} />)
 await screen.findByText('建议页超过 10 页，请勾选或输入本次最多 10 页。')
 const input=screen.getByRole('textbox',{name:'识别物理页（1—100）'}) as HTMLInputElement
 expect(input.value).toBe('');expect(screen.getAllByRole('checkbox').every(box=>!(box as HTMLInputElement).checked)).toBe(true)
 await user.type(input,'1, 100');await user.click(screen.getByRole('button',{name:'刷新 PDF 版本'}));await waitFor(()=>expect(input.value).toBe('1, 100'))
})
test('page suggestion checkboxes refuse an eleventh selection while retaining ten selected pages',async()=>{
 const user=userEvent.setup();mockDocuments([pdf])
 render(<DocumentVersions projectId="p" fileId="f" filename="paper.pdf" active onUnavailable={()=>{}} />)
 await screen.findByText('建议页超过 10 页，请勾选或输入本次最多 10 页。')
 for(const checkbox of screen.getAllByRole('checkbox'))await user.click(checkbox)
 expect(screen.getAllByRole('checkbox').filter(box=>(box as HTMLInputElement).checked)).toHaveLength(10)
 expect(screen.getByRole('alert').textContent).toContain('每次选择 1—10 个不重复的物理页')
})
test('OCR image can be retried after a transport failure and revokes the authenticated blob on unmount',async()=>{
 const user=userEvent.setup(),unavailable=vi.fn();const {create,revoke}=mockDocuments()
 let fail=true;const fetch=vi.fn(async()=>fail?new Response(null,{status:500}):new Response('jpg',{headers:{'Content-Type':'image/jpeg'}}));vi.stubGlobal('fetch',fetch)
 const view=render(<OcrPage page={ocrPage(1) as never} image={ocr.images[0]} url={base+'/ocr/images/preview-secret'} onUnavailable={unavailable} />)
 await screen.findByRole('alert');fail=false;await user.click(screen.getByRole('button',{name:'重新读取图片'}));await screen.findByRole('img')
 expect((fetch.mock.calls[1] as unknown as [string,RequestInit])[1].credentials).toBe('same-origin');expect(create).toHaveBeenCalledTimes(1)
 view.unmount();expect(revoke).toHaveBeenCalledWith('blob:ocr-1');expect(unavailable).not.toHaveBeenCalled()
})
test('image version resubmission uses ordinary reparse endpoint and expected latest version',async()=>{
 const user=userEvent.setup(),posted:{url:string;body:unknown}[]=[]
 mockDocuments([ocr],(url,init)=>{posted.push({url,body:JSON.parse(init.body as string)});return Response.json({...ocr,status:'queued'})})
 render(<DocumentVersions projectId="p" fileId="f" filename="scan.png" fileType="png" active onUnavailable={()=>{}} />)
 await screen.findByRole('button',{name:'图片版本 v2 · 已完成'});await user.click(screen.getByRole('button',{name:'重新识别图片'}));await user.click(await screen.findByRole('button',{name:'确认并开始重解析'}))
 expect(posted).toEqual([{url:base,body:{expected_latest_version:1,expected_assessment_revision:'a'.repeat(64)}}])
 expect(screen.queryByRole('textbox',{name:'识别物理页（1—100）'})).toBeNull()
})
test('an unconfirmed OCR submission reuses its frozen page body and idempotency key, a conflict rereads version',async()=>{
 const user=userEvent.setup();let latest=1
 const posted:{body:{expected_latest_version:number;page_numbers:number[]};key:string|null}[]=[]
 const {fetch}=mockDocuments([pdf],(_url,init)=>{
  posted.push({body:JSON.parse(init.body as string),key:new Headers(init.headers).get('Idempotency-Key')})
  if(posted.length===1)return new Response(null,{status:500})
  if(posted.length===2){latest=4;return Response.json({detail:{code:'document_version_conflict'}},{status:409})}
  return Response.json({...ocr,status:'queued',version:5,selected_pages:[9]})
 })
 const original=fetch.getMockImplementation()!
 fetch.mockImplementation(async(url,init)=>lifecycleResponse(url)??(url.includes('?')&&!url.includes('/pages')?Response.json({items:[pdf],total:1,page:1,page_size:5,latest_version:latest}):original(url,init)))
 render(<DocumentVersions projectId="p" fileId="f" filename="paper.pdf" active onUnavailable={()=>{}} />)
 await screen.findByRole('button',{name:'PDF 版本 v1 · 已完成'})
 await user.type(screen.getByRole('textbox',{name:'识别物理页（1—100）'}),'3, 12')
 await user.click(screen.getByRole('button',{name:'识别所选页'}));await user.click(await screen.findByRole('button',{name:'确认并开始重解析'}));await screen.findByRole('alert')
 await user.clear(screen.getByRole('textbox',{name:'识别物理页（1—100）'}));await user.type(screen.getByRole('textbox',{name:'识别物理页（1—100）'}),'9');latest=3;await user.click(screen.getByRole('button',{name:'刷新 PDF 版本'}));
 await user.click(screen.getByRole('button',{name:'使用同一请求确认解析结果'}));await screen.findByText('文档版本已变化，请刷新版本后重试。')
 await user.click(screen.getByRole('button',{name:'识别所选页'}));await user.click(await screen.findByRole('button',{name:'确认并开始重解析'}))
 expect(posted[1]).toEqual(posted[0]);expect(posted[2].body).toEqual({expected_latest_version:4,expected_assessment_revision:'a'.repeat(64),page_numbers:[9]});expect(posted[2].key).not.toBe(posted[1].key)
})
test('no more than ten blank pages are suggested by default while arbitrary text pages remain selectable',async()=>{
 const user=userEvent.setup();const short={...pdf,summary:{...pdf.summary,counts:{...pdf.summary.counts,pages:3,pages_without_text:2}}}
 mockDocuments([short])
 render(<DocumentVersions projectId="p" fileId="f" filename="paper.pdf" active onUnavailable={()=>{}} />)
 const input=await screen.findByRole('textbox',{name:'识别物理页（1—100）'}) as HTMLInputElement
 await waitFor(()=>expect(input.value).toBe('2, 3'))
 expect(screen.getAllByRole('checkbox').every(box=>(box as HTMLInputElement).checked)).toBe(true)
 await user.clear(input);await user.type(input,'1');expect(input.value).toBe('1')
})
test('OCR preview permission failures invoke project access handling and never create a public image URL',async()=>{
 const unavailable=vi.fn();const {create}=mockDocuments();vi.stubGlobal('fetch',vi.fn(async()=>new Response(null,{status:403})))
 render(<OcrPage page={ocrPage(1) as never} image={ocr.images[0]} url={base+'/ocr/images/preview-secret'} onUnavailable={unavailable} />)
 await screen.findByRole('alert');expect(unavailable).toHaveBeenCalledOnce();expect(create).not.toHaveBeenCalled();expect(screen.queryByRole('img')).toBeNull()
})
