import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptPresentation from './ManuscriptPresentation'
import ManuscriptExports from './ManuscriptExports'
import {manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
import {emptyPresentation} from './presentationTypes'
const version={...manuscriptFixture.versions[0],exports:[]} as unknown as ManuscriptVersion
const quality={scientific_semantic:'pending',word_wps:'pending',real_compliance:'pending'}
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('trims terminology variants and excludes blank variants from outgoing configuration',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{
  if(!init?.method)return Response.json({items:[]})
  const input=JSON.parse(String(init.body));return Response.json({...input,schema_version:1,checks:[],paragraph_groups:[],quality,can_export:true})
 });vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptPresentation projectId="p1" manuscriptId="m1" version={version} versions={[version]} active onSelect={vi.fn()}/>);await screen.findByText('尚无已保存输出配置。');fireEvent.click(screen.getByRole('button',{name:'添加术语'}));fireEvent.change(screen.getByLabelText('中文术语'),{target:{value:'肿瘤坏死因子'}});fireEvent.change(screen.getByLabelText('英文术语'),{target:{value:'TNF'}});fireEvent.change(screen.getByLabelText(/允许变体/),{target:{value:'   \n TNF alpha \n\n TNF-α \n  '}});fireEvent.click(screen.getByRole('button',{name:'预览配置核对'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true));const post=fetcher.mock.calls.find(([,init])=>init?.method==='POST')!;expect(JSON.parse(String(post[1]?.body)).config.terminology[0].variants).toEqual(['TNF alpha','TNF-α'])
})
it('keeps the same export request key after a lost POST response and refreshing the same saved configuration',async()=>{
 const saved={id:'presentation-fixed',manuscript_id:'m1',revision:1,schema_version:1,base_version_id:version.id,peer_version_id:null,config:emptyPresentation(),checks:[],paragraph_groups:[],quality,can_export:true,stale:false,stale_version_ids:[]}
 let reads=0
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/presentations')){reads++;return Response.json({items:[saved]})}
  if(init?.method==='POST')throw new TypeError('response lost')
  return Response.json({items:[],pdf_status:'not_requested'})
 });vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptExports projectId="p1" manuscriptId="m1" version={version} versions={[version]}/>);await screen.findByRole('option',{name:/配置版本 1/});fireEvent.change(screen.getByLabelText('已保存输出配置'),{target:{value:saved.id}});fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}));await screen.findByRole('alert')
 fireEvent.click(screen.getByRole('button',{name:'刷新配置版本'}));await waitFor(()=>expect(reads).toBe(2));await act(async()=>{});fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}));await waitFor(()=>expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(2))
 const posts=fetcher.mock.calls.filter(([,init])=>init?.method==='POST');expect(posts[0][0]).toBe(posts[1][0]);expect(posts[0][1]?.body).toBe(posts[1][1]?.body);expect(new Headers(posts[1][1]?.headers).get('Idempotency-Key')).toBe(new Headers(posts[0][1]?.headers).get('Idempotency-Key'))
 await waitFor(()=>expect((screen.getByRole('button',{name:'生成 DOCX'}) as HTMLButtonElement).disabled).toBe(false));fireEvent.change(screen.getByLabelText('审阅输出模式'),{target:{value:'blind'}});fireEvent.click(screen.getByRole('button',{name:'生成 DOCX'}));await waitFor(()=>expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(3));const changed=fetcher.mock.calls.filter(([,init])=>init?.method==='POST')[2];expect(JSON.parse(String(changed[1]?.body)).review_mode).toBe('blind');expect(new Headers(changed[1]?.headers).get('Idempotency-Key')).not.toBe(new Headers(posts[0][1]?.headers).get('Idempotency-Key'))
})
