import { lifecycleResponse } from '../files/lifecycleFixtures'
import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DocumentVersions from './DocumentVersions'
import { validateFile } from '../files/batchUploadApi'
import PdfPage from './PdfPage'
import { setLocale } from '../../shared/i18n'
import { readFileSync } from 'node:fs'
const documentStyles=readFileSync('src/features/documents/documents.css','utf8')
const appStyles=readFileSync('src/app/App.css','utf8')
afterEach(() => { cleanup(); vi.unstubAllGlobals(); setLocale('zh-CN') })
const whitespacePage = {page_number:1,width:600,height:800,rotation:0,bbox:[0,0,600,800],text_status:'text' as const,warnings:[],text_blocks:[],tables:[{kind:'table' as const,id:'whitespace',candidate:true as const,source:{page_number:1,bbox:[0,0,100,100],label:'internal'},rows:1,columns:1,cells:[{row:1,column:1,text:'第一行\n第二行\nA  B',bbox:null}]}]}
test('PDF table values visibly preserve extracted newlines and consecutive spaces', () => {
 render(<><style>{documentStyles}</style><PdfPage page={whitespacePage}/></>)
 const value=screen.getByRole('table').querySelector('td p')!
 expect(value.textContent).toBe('第一行\n第二行\nA  B')
 expect(getComputedStyle(value).whiteSpace).toBe('pre-wrap')
})
test('PDF wide tables use the existing scrollable table region', () => {
 render(<><style>{appStyles}</style><PdfPage page={whitespacePage}/></>)
 expect(getComputedStyle(screen.getByRole('table').parentElement!).overflow).toBe('auto')
})
test('mixed upload accepts PDF and keeps the file size limit', () => {
 expect(validateFile(new File(['pdf'], 'paper.pdf'))).toBeNull()
 expect(validateFile(new File([new Uint8Array(10485761)], 'large.pdf'))).toBe('单文件不能超过 10 MiB。')
})
test('document format follows file metadata rather than the filename', () => {
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[],total:0,page:1,page_size:5,latest_version:0})))
 render(<DocumentVersions projectId="p" fileId="f" filename="renamed.bin" fileType="pdf" active onUnavailable={()=>{}} />)
 expect(screen.getByRole('heading',{name:'PDF 解析版本'})).toBeTruthy()
})
test('large PDF page shows only twenty blocks and table rows and preserves strings and empty cells', async () => {
 const user=userEvent.setup();const source={page_number:1,bbox:[0,0,100,100],label:'internal'}
 render(<PdfPage page={{page_number:1,width:600,height:800,rotation:0,bbox:source.bbox,text_status:'text',warnings:[],text_blocks:Array.from({length:21},(_,i)=>({kind:'text',id:`b${i}`,text:`Text ${i+1}`,source})),tables:[{kind:'table',id:'t',candidate:true,source,rows:21,columns:2,cells:Array.from({length:21},(_,i)=>({row:i+1,column:1,text:`00${i+1}`,bbox:null}))}]}} />)
 expect(screen.queryByText('Text 21')).toBeNull();expect(screen.getByRole('table').querySelectorAll('tr')).toHaveLength(20)
 expect(screen.getByText('001')).toBeTruthy();expect(screen.getByRole('table').querySelectorAll('tr')[0].querySelectorAll('td')[1].querySelector('p')?.textContent).toBe('')
 await user.click(screen.getByRole('button',{name:'下一页文本块'}));expect(screen.getByText('Text 21')).toBeTruthy()
 await user.click(screen.getByRole('button',{name:'下一页表格行'}));expect(screen.getByRole('table').querySelectorAll('tr')).toHaveLength(1);expect(screen.getByText('0021')).toBeTruthy()
})
test('English PDF source and no text notice avoid claiming a scanned page', () => {
 setLocale('en')
 render(<PdfPage page={{page_number:2,width:600,height:800,rotation:0,bbox:[0,0,600,800],text_status:'no_extractable_text',warnings:[],text_blocks:[],tables:[]}} />)
 expect(screen.getByText('PDF page 2')).toBeTruthy()
 expect(screen.getByText('This page has no extractable text. OCR has not been performed; download the original to verify.')).toBeTruthy()
})
test('PDF shared actions reread conflict revision and preserve old content when a newer page fails', async () => {
 const user=userEvent.setup();let latest=2;const posted:number[]=[]
 const v={id:'v1',file_id:'f',version:1,task_id:'t',kind:'pdf_document',status:'succeeded',created_at:'2026-10-12',completed_at:null,parser_version:'pdf',summary:{counts:{pages:1,text_blocks:1,tables:0,cells:0,pages_without_text:0},warnings:[]},error:null,download_url:'download',pages_url:'pages'}
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  const impact=lifecycleResponse(url);if(impact)return impact
  if(init?.method==='POST'){posted.push(JSON.parse(init.body as string).expected_latest_version);if(posted.length===1){latest=3;return Response.json({detail:{code:'document_version_conflict'}},{status:409})}return Response.json({...v,id:'queued',status:'queued',version:4})}
  if(url.includes('/v2/pages'))return Response.json({detail:{code:'unknown',message:'private-error'}},{status:500})
  if(url.includes('/pages'))return Response.json({items:[{page_number:1,width:600,height:800,rotation:0,bbox:[0,0,600,800],text_status:'text',text_blocks:[{kind:'text',id:'text',text:'Keep old PDF',source:{page_number:1,bbox:[0,0,100,100],label:'internal'}}],tables:[],warnings:[]}],total:1,page:1,page_size:1})
  if(url.includes('?'))return Response.json({items:[v,{...v,id:'v2',version:2},{...v,id:'failed',version:3,status:'failed',error:{code:'encrypted_document',message:'private-error'}}],total:3,page:1,page_size:5,latest_version:latest})
  return Response.json(url.endsWith('/v2')?{...v,id:'v2',version:2}:v)
 }))
 render(<DocumentVersions projectId="p" fileId="f" filename="paper.pdf" active onUnavailable={()=>{}} />)
 await user.click(await screen.findByRole('button',{name:'PDF 版本 v1 · 已完成'}));await screen.findByText('Keep old PDF')
 await user.click(screen.getByRole('button',{name:'PDF 版本 v2 · 已完成'}));await screen.findByRole('alert');expect(screen.getByText('Keep old PDF')).toBeTruthy();expect(screen.queryByText('private-error')).toBeNull()
 expect(screen.getByText('PDF 文件已加密，请上传未加密的 PDF。')).toBeTruthy()
 await user.click(screen.getByRole('button',{name:'重新提取文本'}));await user.click(await screen.findByRole('button',{name:'确认并开始重解析'}));await screen.findByText('文档版本已变化，请刷新版本后重试。')
 await user.click(screen.getByRole('button',{name:'刷新 PDF 版本'}));await user.click(screen.getByRole('button',{name:'重新提取文本'}));await user.click(await screen.findByRole('button',{name:'确认并开始重解析'}));expect(posted).toEqual([2,3]);expect(screen.getByText('Keep old PDF')).toBeTruthy()
})
test('PDF versions use physical pages with candidate sources and no text notice', async () => {
 const user = userEvent.setup()
 const version = { id:'v1',file_id:'f',version:1,task_id:'t',kind:'pdf_document',status:'succeeded',created_at:'2026-10-12',completed_at:null,parser_version:'pdf',summary:{counts:{pages:2,text_blocks:1,tables:1,cells:1,pages_without_text:1},warnings:[]},error:null,download_url:'download',pages_url:'pages' }
 vi.stubGlobal('fetch',vi.fn(async (url:string) => {
  if(url.includes('/pages')) {const page=url.endsWith('=2')?2:1;return Response.json({items:[{page_number:page,width:600,height:800,rotation:0,bbox:[0,0,600,800],text_status:page===1?'text':'no_extractable_text',text_blocks:page===1?[{kind:'text',id:'private',text:'Original text',source:{page_number:1,bbox:[0,0,100,100],label:'secret'}}]:[],tables:page===1?[{kind:'table',id:'table',candidate:true,source:{page_number:1,bbox:[0,0,100,100],label:'secret'},rows:1,columns:1,cells:[{row:1,column:1,text:'001.20',bbox:null}]}]:[],warnings:[]}],total:2,page,page_size:1})}
  return Response.json(url.includes('?')?{items:[version],total:1,page:1,page_size:5,latest_version:1}:version)
 }))
 render(<DocumentVersions projectId="p" fileId="f" filename="paper.pdf" active onUnavailable={()=>{}} />)
 await user.click(await screen.findByRole('button',{name:'PDF 版本 v1 · 已完成'}))
 expect(await screen.findByText('Original text')).toBeTruthy()
 expect(screen.getByText('001.20')).toBeTruthy()
 expect(screen.getByText('第 1 页 · 候选表格 1 · 第 1 行第 1 列')).toBeTruthy()
 expect(screen.queryByText('secret')).toBeNull()
 await user.click(screen.getByRole('button',{name:'下一页 PDF'}))
 expect(await screen.findByText('此页无可提取文字，当前未进行 OCR，请下载原件核对。')).toBeTruthy()
})
