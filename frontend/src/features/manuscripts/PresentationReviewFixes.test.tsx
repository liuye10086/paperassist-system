import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptPresentation from './ManuscriptPresentation'
import ManuscriptExports from './ManuscriptExports'
import {exportFixture,manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
import {emptyPresentation} from './presentationTypes'
const version={...manuscriptFixture.versions[0],exports:[]} as unknown as ManuscriptVersion
const quality={scientific_semantic:'pending',word_wps:'pending',real_compliance:'pending'}
afterEach(()=>{cleanup();sessionStorage.clear();vi.unstubAllGlobals()})
it('trims terminology variants and excludes blank variants from outgoing configuration',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{
  if(!init?.method)return Response.json({items:[]})
  const input=JSON.parse(String(init.body));return Response.json({...input,schema_version:1,checks:[],paragraph_groups:[],quality,can_export:true})
 });vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptPresentation projectId="p1" manuscriptId="m1" version={version} versions={[version]} active onSelect={vi.fn()}/>);await screen.findByText('尚无已保存输出配置。');fireEvent.click(screen.getByRole('button',{name:'添加术语'}));fireEvent.change(screen.getByLabelText('中文术语'),{target:{value:'肿瘤坏死因子'}});fireEvent.change(screen.getByLabelText('英文术语'),{target:{value:'TNF'}});fireEvent.change(screen.getByLabelText(/允许变体/),{target:{value:'   \n TNF alpha \n\n TNF-α \n  '}});fireEvent.click(screen.getByRole('button',{name:'预览配置核对'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true));const post=fetcher.mock.calls.find(([,init])=>init?.method==='POST')!;expect(JSON.parse(String(post[1]?.body)).config.terminology[0].variants).toEqual(['TNF alpha','TNF-α'])
})
it('refreshes status and explicitly retries a lost export using the same fixed output configuration',async()=>{
 const saved={id:'presentation-fixed',manuscript_id:'m1',revision:1,schema_version:1,base_version_id:version.id,peer_version_id:null,config:emptyPresentation(),checks:[],paragraph_groups:[],quality,can_export:true,stale:false,stale_version_ids:[]}
 const manuscript='/api/v1/projects/p1/manuscripts/m1'
 const endpoint=`${manuscript}/versions/1/exports`
 const items:unknown[]=[]
 let lostResponse=false
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/presentations'))return Response.json({items:[saved]})
  if(url===endpoint&&init?.method==='POST'){
   if(!lostResponse){lostResponse=true;throw new TypeError('response lost')}
   const id=`export${items.length+1}`
   const item={...exportFixture,id,download_url:`${manuscript}/exports/${id}/download`,presentation:{binding:JSON.parse(String(init.body)),checks:[],quality}}
   items.unshift(item)
   return Response.json(item)
  }
  return Response.json({items:url===endpoint?items:[]})
 })
 vi.stubGlobal('fetch',fetcher)
 const reads=()=>fetcher.mock.calls.filter(([url,init])=>url===endpoint&&!init?.method)
 const posts=()=>fetcher.mock.calls.filter(([,init])=>init?.method==='POST')
 const key=(init?:RequestInit)=>new Headers(init?.headers).get('Idempotency-Key')
 const binding={presentation_version_id:saved.id,language_view:'en',review_mode:'identified'}
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version} versions={[version]}/>)
 await screen.findByRole('option',{name:/配置版本 1/})
 await screen.findByText('当前版本尚未生成 Word。')
 fireEvent.change(screen.getByLabelText('已保存输出配置'),{target:{value:saved.id}})
 const generate=screen.getByRole('button',{name:'生成 DOCX'})
 fireEvent.click(generate)
 await screen.findByRole('alert')
 expect(screen.getByText('Word 提交结果待核对，原请求和固定输入已保留。')).toBeTruthy()
 expect(generate).toHaveProperty('disabled',true)
 expect(screen.getByRole('button',{name:'刷新配置版本'}).matches(':disabled')).toBe(true)
 expect(screen.getByLabelText('审阅输出模式').matches(':disabled')).toBe(true)
 const beforeRefresh=reads().length
 fireEvent.click(screen.getByRole('button',{name:'刷新 DOCX 状态'}))
 await waitFor(()=>expect(reads()).toHaveLength(beforeRefresh+1))
 expect(posts()).toHaveLength(1)
 fireEvent.click(screen.getByRole('button',{name:'用原请求重试 Word'}))
 await screen.findByRole('link',{name:'下载 DOCX'})
 expect(posts()).toHaveLength(2)
 const [first,retry]=posts()
 expect(first[0]).toBe(endpoint)
 expect(retry[0]).toBe(first[0])
 expect(JSON.parse(String(first[1]?.body))).toEqual(binding)
 expect(retry[1]?.body).toBe(first[1]?.body)
 expect(key(first[1])).toBeTruthy()
 expect(key(retry[1])).toBe(key(first[1]))
 expect(generate).toHaveProperty('disabled',false)
 fireEvent.change(screen.getByLabelText('审阅输出模式'),{target:{value:'blind'}})
 fireEvent.click(generate)
 await waitFor(()=>expect(screen.getAllByRole('link',{name:'下载 DOCX'})).toHaveLength(2))
 expect(posts()).toHaveLength(3)
 const changed=posts()[2]
 expect(changed[0]).toBe(endpoint)
 expect(JSON.parse(String(changed[1]?.body))).toEqual({...binding,review_mode:'blind'})
 expect(key(changed[1])).toBeTruthy()
 expect(key(changed[1])).not.toBe(key(first[1]))
})
