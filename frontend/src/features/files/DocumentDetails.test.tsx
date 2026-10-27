import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, fireEvent } from '@testing-library/react'
import FileDetails from '../files/FileDetails'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
test.each(['png','jpeg'])('image %s file details retain OCR history after failure',async fileType=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/details')?{id:'f',filename:`scan.${fileType}`,file_type:fileType,size_bytes:100,uploaded_at:'2026-10-12',parse_status:'failed',error:null,purposes:[],metadata_revision:1,uploader_recorded:true,references:{},source:{kind:'ocr_parse',preview_available:true,preview_row_limit:null,parser_version:'ocr'}}:{items:[],total:0,page:1,page_size:5,latest_version:2})))
 render(<FileDetails projectId="p" fileId="f" active onUnavailable={()=>{}} onUpdated={()=>{}} />)
 fireEvent.click(await screen.findByRole('button',{name:'解析与文字核对'}))
 expect(await screen.findByRole('heading',{name:'图片识别版本'})).toBeTruthy()
 expect(screen.queryByText(/前.*行/)).toBeNull()
})
test('Word file details show document history even after latest failure and no Excel preview description', async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/details') ? {
 id:'f',filename:'paper.docx',file_type:'docx',size_bytes:100,uploaded_at:'2026-10-12',parse_status:'failed',error:null,purposes:[],metadata_revision:1,uploader_recorded:true,references:{},source:{kind:'docx_parse',preview_available:true,preview_row_limit:null,parser_version:'openxml-docx-v1'}
 } : {items:[],total:0,page:1,page_size:5,latest_version:2})))
 render(<FileDetails projectId="p" fileId="f" active onUnavailable={()=>{}} onUpdated={()=>{}} />)
 fireEvent.click(await screen.findByRole('button',{name:'解析与文字核对'}))
 expect(await screen.findByRole('heading',{name:'Word 解析版本'})).toBeTruthy()
 expect(screen.queryByText(/前.*行/)).toBeNull()
})

test('Word preview opens file details and never sends a WorkbookPreview request',async()=>{
 const {default:ProjectFileLibrary}=await import('./ProjectFileLibrary');const {default:userEvent}=await import('@testing-library/user-event');const user=userEvent.setup();const preview=vi.fn()
 const file={id:'f',filename:'paper.docx',file_type:'docx',size_bytes:100,uploaded_at:'2026-10-12',parse_status:'parsed',error:null,purposes:[],metadata_revision:1,uploader_recorded:true}
 const fetch=vi.fn(async(url:string)=>Response.json(url.includes('document-versions')?{items:[],total:0,page:1,page_size:5,latest_version:1}:url.endsWith('/details')?{...file,references:{},source:{kind:'docx_parse',preview_available:true,preview_row_limit:null,parser_version:'openxml-docx-v1'}}:{items:[file],total:1,page:1,page_size:5}));vi.stubGlobal('fetch',fetch)
 render(<ProjectFileLibrary projectId="p" active uploadVersion={0} busy={false} previewState={null} onPreview={preview} onUnavailable={()=>{}}/> )
 await user.click(await screen.findByRole('button',{name:'预览 paper.docx'}));await screen.findByRole('heading',{name:'Word 解析版本'})
 expect(preview).not.toHaveBeenCalled();expect(fetch.mock.calls.some(([url])=>url.endsWith('/preview'))).toBe(false)
})
