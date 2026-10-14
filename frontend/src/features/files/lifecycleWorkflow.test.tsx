import {afterEach,expect,test,vi} from 'vitest'
import {act,cleanup,render,screen,fireEvent,waitFor} from '@testing-library/react'
import DocumentVersions from '../documents/DocumentVersions'
import {lifecycleResponse} from './lifecycleFixtures'
import FileDetails from './FileDetails'
import {setApiSession} from '../../shared/api/client'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
test('Word reparse opens an impact review and performs no POST before explicit confirmation',async()=>{
 const posted:RequestInit[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){posted.push(init);return Response.json({})}
  return lifecycleResponse(url)??Response.json({items:[],total:0,page:1,page_size:5,latest_version:0})
 }))
 render(<DocumentVersions projectId="p" fileId="f" filename="paper.docx" active onUnavailable={()=>{}}/>)
 await screen.findByRole('button',{name:'重新解析 Word'})
 fireEvent.click(screen.getByRole('button',{name:'重新解析 Word'}))
 expect(posted).toHaveLength(0)
 expect(await screen.findByRole('dialog',{name:'重解析影响确认'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'取消'}))
 expect(posted).toHaveLength(0)
})
test('file details removes the prior scope metadata immediately on file switch and account change',async()=>{
 let resolve!:(v:Response)=>void
 const detail={id:'f',filename:'old confidential file',file_type:'docx',size_bytes:1,parse_status:'parsed',purposes:[],metadata_revision:1,uploader_recorded:true,references:{},source:{kind:'docx_parse',preview_available:true}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.includes('/other/')?new Promise<Response>(r=>{resolve=r}):lifecycleResponse(url)??Response.json(url.endsWith('/details')?detail:{items:[],total:0,page:1,page_size:5,latest_version:0})))
 const props={projectId:'p',active:true,onUnavailable:()=>{},onUpdated:()=>{}}
 const view=render(<FileDetails {...props} fileId="f"/>);await screen.findByRole('heading',{name:'文件详情 · old confidential file'})
 view.rerender(<FileDetails {...props} fileId="other"/>);expect(screen.queryByRole('heading',{name:'文件详情 · old confidential file'})).toBeNull()
 await act(async()=>resolve(Response.json({...detail,id:'other',filename:'another file'})));await screen.findByRole('heading',{name:'文件详情 · another file'})
 act(()=>setApiSession('new account'));expect(screen.queryByRole('heading',{name:'文件详情 · another file'})).toBeNull()
})
test('a valid-looking older version cannot acknowledge a new parse request',async()=>{
 const older={id:'old',file_id:'f',version:1,task_id:'old-task',status:'queued',created_at:'2026-10-13',completed_at:null,parser_version:'docx',summary:null,error:null,download_url:null,blocks_url:null}
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>init?.method==='POST'?Response.json(older):lifecycleResponse(url)??Response.json({items:[],total:0,page:1,page_size:5,latest_version:2})))
 render(<DocumentVersions projectId="p" fileId="f" filename="paper.docx" active onUnavailable={()=>{}}/>);await waitFor(()=>expect(screen.getByRole('button',{name:'重新解析 Word'}).hasAttribute('disabled')).toBe(false));fireEvent.click(screen.getByRole('button',{name:'重新解析 Word'}));await waitFor(()=>expect(screen.getByRole('button',{name:'确认并开始重解析'}).hasAttribute('disabled')).toBe(false));fireEvent.click(screen.getByRole('button',{name:'确认并开始重解析'}));await screen.findByText('提交结果尚未确认，请使用同一请求确认结果。');expect(screen.getByRole('button',{name:'使用同一请求确认解析结果'})).toBeTruthy()
})
