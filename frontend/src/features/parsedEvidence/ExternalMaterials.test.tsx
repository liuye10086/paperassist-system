import {cleanup,render,screen,fireEvent,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ExternalMaterials from './ExternalMaterials'
import {setLocale} from '../../shared/i18n'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it('registers an external original with explicit provenance and never sends a report or model request',async()=>{
 const source={kind:'original',file_id:'f1',filename:'figure.png',file_type:'png',source_sha256:'a'.repeat(64),size_bytes:100,original_download_url:'/api/v1/projects/p1/files/f1/download',version_id:null,version:null,sha256:'a'.repeat(64),object_download_url:null,review_status:'not_reviewed'}
 const calls=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.includes('external-evidence-source'))return Response.json({source,items:[],total:0,page:1,page_size:20})
  if(init?.method==='POST')return Response.json({...JSON.parse(String(init.body)),id:'e1',evidence_id:'series',version:1,project_id:'p1',created_at:new Date().toISOString(),sha256:'b'.repeat(64),source,items:[],verification_status:'external_not_recomputed',computed_by_system:false,included_in_reports:false})
  return Response.json({items:[],total:0,page:1,page_size:10})
 });vi.stubGlobal('fetch',calls)
 render(<ExternalMaterials projectId="p1" files={[{id:'f1',filename:'figure.png',file_type:'png',size_bytes:100,uploaded_at:'2026-10-16',parse_status:'parsed',error:null}]}/> )
 fireEvent.change(screen.getByLabelText('材料源文件'),{target:{value:'f1'}})
 fireEvent.change(screen.getByLabelText('材料标题'),{target:{value:'External figure'}})
 fireEvent.change(screen.getByLabelText('来源说明（未知可留空）'),{target:{value:'Provided by collaborator'}})
 await screen.findByText('figure.png')
 await waitFor(()=>expect((screen.getByRole('button',{name:'保存材料新版本'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'保存材料新版本'}))
 await waitFor(()=>expect(calls.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(1))
 expect(JSON.parse(String(calls.mock.calls.find(([,i])=>i?.method==='POST')![1]?.body))).toMatchObject({file_id:'f1',source_kind:'original',original_data:'unknown',source_description:'Provided by collaborator',item_ids:[]})
 expect(calls.mock.calls.every(([url])=>!url.includes('report')&&!url.includes('recommendation'))).toBe(true)
})
