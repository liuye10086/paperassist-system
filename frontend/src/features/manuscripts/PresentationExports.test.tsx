import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptExports from './ManuscriptExports'
import {exportFixture,manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
import {emptyPresentation} from './presentationTypes'
const version={...manuscriptFixture.versions[0],exports:[]} as unknown as ManuscriptVersion
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('binds language and blind export to selected saved configuration and keeps legacy payload empty',async()=>{
 const saved={id:'p1',manuscript_id:'m1',revision:1,schema_version:1,base_version_id:version.id,peer_version_id:null,config:emptyPresentation(),checks:[],paragraph_groups:[],quality:{scientific_semantic:'pending',word_wps:'pending',real_compliance:'pending'},can_export:true,stale:false,stale_version_ids:[]}
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/presentations'))return Response.json({items:[saved]})
  if(init?.method==='POST')return Response.json({...exportFixture,status:'queued',filename:null,download_url:null,sha256:null,size_bytes:null})
  return Response.json({items:[],pdf_status:'not_requested'})
 });vi.stubGlobal('fetch',fetcher);const view=render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version} versions={[version]}/>)
 await screen.findByRole('option',{name:/配置版本 1/});fireEvent.change(screen.getByLabelText('已保存输出配置'),{target:{value:'p1'}});fireEvent.change(screen.getByLabelText('输出语言视图'),{target:{value:'zh-CN-en'}});fireEvent.change(screen.getByLabelText('审阅输出模式'),{target:{value:'blind'}});fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([,i])=>i?.method==='POST')).toBe(true));const post=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(JSON.parse(String(post[1]?.body))).toEqual({presentation_version_id:'p1',language_view:'zh-CN-en',review_mode:'blind'})
 view.unmount();fetcher.mockClear();render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version}/>);fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}));await waitFor(()=>expect(fetcher.mock.calls.some(([,i])=>i?.method==='POST')).toBe(true));expect(JSON.parse(String(fetcher.mock.calls.find(([,i])=>i?.method==='POST')![1]?.body))).toEqual({})
})
it('previews the selected blind output from the server and displays actual export binding and remaining manual checks',async()=>{
 const binding={presentation_version_id:'p1',language_view:'en',review_mode:'blind'}
 const saved={id:'p1',manuscript_id:'m1',revision:1,schema_version:1,base_version_id:version.id,peer_version_id:null,config:emptyPresentation(),checks:[],paragraph_groups:[],quality:{scientific_semantic:'pending',word_wps:'pending',real_compliance:'pending'},can_export:true,stale:false,stale_version_ids:[]}
 const receipt={binding,checks:[{code:'image',status:'pending',message:'Images require review'}],quality:{real_compliance:'pending'},blind:{known_identity_check:'passed',remaining:[],images:'pending_manual_review',exceptions:[],anonymity_verified:false},language_inventory:[]}
 const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>{
  if(url.endsWith('/presentations'))return Response.json({items:[saved]})
  if(url.endsWith('/preview'))return Response.json({schema_version:1,presentation:{binding,checks:receipt.checks,quality:receipt.quality,preview_paragraphs:[{id:'redacted',text:'[BLINDED] supplied manuscript',target_language:'en'}],notice:'固定文本预览，实际DOCX/PDF身份检查以导出完成回执为准'}})
  if(url.includes('/pdf-exports'))return Response.json({items:[]})
  return Response.json({items:[{...exportFixture,presentation:receipt}],pdf_status:'not_requested'})
 });vi.stubGlobal('fetch',fetcher);render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version} versions={[version]}/>);await screen.findByRole('option',{name:/配置版本 1/});fireEvent.change(screen.getByLabelText('已保存输出配置'),{target:{value:'p1'}});fireEvent.change(screen.getByLabelText('审阅输出模式'),{target:{value:'blind'}});fireEvent.click(screen.getByRole('button',{name:'预览固定输出'}));await screen.findByText('[BLINDED] supplied manuscript');expect(screen.getByRole('link',{name:'下载 DOCX'})).toBeTruthy();expect(screen.getByText('图片身份仍待人工核对。')).toBeTruthy()
 const post=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(JSON.parse(String(post[1]?.body))).toMatchObject({presentation_version_id:'p1',review_mode:'blind'})
})
