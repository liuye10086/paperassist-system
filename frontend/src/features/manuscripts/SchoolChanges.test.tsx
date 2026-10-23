import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import SchoolChanges from './SchoolChanges'
import {manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
import type {SchoolChange} from './schoolChangeTypes'
import {clearApiSession} from '../../shared/api/client'

afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const version={...manuscriptFixture.versions[0],id:'base2',revision:2,snapshot:{...manuscriptFixture.versions[0].snapshot,thesis_context:{confirmation_id:'old',chapters:[{id:'c1',title:'方法',level:1,purpose:'materials_and_methods',output_language:'zh-CN',result_group_ids:[]}]}}} as unknown as ManuscriptVersion
const change:SchoolChange={id:'change1',kind:'template_migration',manuscript_id:'m1',base_version_id:'base2',base_revision:2,created_at:'2026-10-22T00:00:00Z',input_sha256:'a'.repeat(64),source:{target_confirmation_id:'new'},original_download_url:null,input_sections:[{id:'s1',title:'原方法',paragraphs:['原工程说明'],suggested_chapter_id:'c1',match_method:'title',candidate_chapter_ids:['c1','c2']}],target_chapters:[{id:'c1',title:'新方法',level:1,purpose:'materials_and_methods',output_language:'zh-CN',result_group_ids:[]},{id:'c2',title:'新结论',level:1,purpose:'conclusion',output_language:'zh-CN',result_group_ids:[]}],mappings:[{input_section_id:'s1',chapter_id:'c1'}],differences:[{kind:'template_changed',location:'c1',message:'标题已更新',before:'方法',after:'新方法'}],issues:[],can_adopt:true,preview_sha256:'b'.repeat(64),adopted_revision:null}
function server(view:SchoolChange=change){
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/school-templates'))return Response.json({items:[{id:'t2',name:'工程更新模板',version_label:'工程版',confirmation:{id:'new'}}]})
  if(url.includes('/files?'))return Response.json({items:[{id:'f1',filename:'回传修改稿.docx',file_type:'docx',parse_status:'parsed'}],total:1,page:1,page_size:50})
  if(url.includes('/document-versions'))return Response.json({items:[{id:'parse1',version:1}],total:1,page:1,page_size:5})
  if(url.endsWith('/adopt'))return Response.json({...manuscriptFixture,id:'m1',current_revision:4})
  if(init?.method==='POST')return Response.json(view,{status:201})
  return Response.json({items:[]})
 });vi.stubGlobal('fetch',fetcher);return fetcher
}
it('uses the selected fixed base and current root revision, then invalidates a preview when mapping changes',async()=>{
 const fetcher=server();const adopted=vi.fn()
 render(<SchoolChanges projectId="p1" manuscriptId="m1" version={version} currentRevision={3} active onAdopted={adopted}/>);
 fireEvent.change(await screen.findByLabelText('迁移目标模板'),{target:{value:'new'}})
 fireEvent.click(screen.getByRole('button',{name:'登记模板迁移'}));await screen.findByText('标题已更新')
 expect(fetcher.mock.calls.some(([url,init])=>url.endsWith('/versions/2/school-changes')&&init?.method==='POST')).toBe(true)
 fireEvent.change(screen.getByLabelText('原方法 · 对应章节'),{target:{value:'c2'}})
 expect((screen.getByRole('button',{name:'确认匹配并另存版本'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'预览匹配与差异'}));await waitFor(()=>expect((screen.getByRole('button',{name:'确认匹配并另存版本'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'确认匹配并另存版本'}));await waitFor(()=>expect(adopted).toHaveBeenCalled())
 const call=fetcher.mock.calls.find(([url])=>url.endsWith('/adopt'))!
 expect(JSON.parse(String(call[1]?.body))).toMatchObject({expected_revision:3,preview_sha256:'b'.repeat(64)})
 expect(new Headers(call[1]?.headers).get('Idempotency-Key')).toBeTruthy()
})
it('registers a retained DOCX parse version and preserves a blocked input without adopting numeric changes',async()=>{
 const view:SchoolChange={...change,kind:'docx_return',source:{file_id:'f1',document_version_id:'parse1',filename:'回传修改稿.docx'},original_download_url:'/api/v1/projects/p1/files/f1/download',issues:[{code:'numeric_changed',severity:'error',message:'数值变化须核实',location:'c1'}],can_adopt:false}
 const fetcher=server(view)
 render(<SchoolChanges projectId="p1" manuscriptId="m1" version={version} currentRevision={3} active onAdopted={vi.fn()}/>);
 fireEvent.change(await screen.findByLabelText('回传 DOCX 原件'),{target:{value:'f1'}})
 await screen.findByRole('option',{name:'解析版本 1'})
 fireEvent.click(screen.getByRole('button',{name:'登记回传稿'}));await screen.findByText('数值变化须核实')
 expect(screen.getByRole('link',{name:'下载回传原件'}).getAttribute('href')).toBe('/api/v1/projects/p1/files/f1/download')
 expect((screen.getByRole('button',{name:'确认匹配并另存版本'}) as HTMLButtonElement).disabled).toBe(true)
 const call=fetcher.mock.calls.find(([url,init])=>url.endsWith('/versions/2/school-changes')&&init?.method==='POST')!
 expect(JSON.parse(String(call[1]?.body))).toMatchObject({kind:'docx_return',file_id:'f1',document_version_id:'parse1'})
 expect(fetcher.mock.calls.some(([url])=>url.endsWith('/adopt'))).toBe(false)
})
it('reuses an uncertain registration request and clears returned content when the session changes',async()=>{
 const original=server();const keys:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/versions/2/school-changes')&&init?.method==='POST'){
   keys.push(new Headers(init.headers).get('Idempotency-Key')!);if(keys.length===1)throw new Error('network lost')
  }
  return original(url,init)
 }))
 render(<SchoolChanges projectId="p1" manuscriptId="m1" version={version} currentRevision={3} active onAdopted={vi.fn()}/>);
 fireEvent.change(await screen.findByLabelText('迁移目标模板'),{target:{value:'new'}})
 fireEvent.click(screen.getByRole('button',{name:'登记模板迁移'}));await screen.findByRole('alert')
 fireEvent.click(screen.getByRole('button',{name:'登记模板迁移'}));await screen.findByText('标题已更新')
 expect(keys).toHaveLength(2);expect(keys[0]).toBe(keys[1])
 act(()=>clearApiSession());expect(screen.queryByText('标题已更新')).toBeNull()
 expect(screen.queryByRole('button',{name:'确认匹配并另存版本'})).toBeNull()
})
