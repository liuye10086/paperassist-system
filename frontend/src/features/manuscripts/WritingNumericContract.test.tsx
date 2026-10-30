import {webcrypto} from 'node:crypto'
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import WritingAuthorization from './WritingAuthorization'
import WritingScienceReview from './WritingScienceReview'
import {authFixture,bundleFixture,liveRequest,rawSnapshot,reviewContext,scienceReview} from './writingLiveFixtures'
import {manuscriptFixture} from './manuscriptFixtures'
import {validAuthorization,validManifest} from './writingLiveTypes'
import {validSnapshot} from './manuscriptTypes'

const numericContext={
 c1:{kind:'provided_context',location:'materials_and_methods[0]',origin:'user_provided',text:'Use n−1 as the divisor.',values:[{fact_path:'/numbers/0',value:'-1'}]},
 c2:{kind:'provided_context',location:'illustrations[0].caption',origin:'frozen_illustration',text:'The whisker limit is 1.5 IQR.',values:[{fact_path:'/numbers/0',value:'1.5'}]},
} as const
beforeEach(()=>vi.stubGlobal('crypto',webcrypto))
afterEach(()=>{cleanup();vi.unstubAllGlobals()})

it('validates optional frozen numeric context without accepting malformed catalogs',()=>{
 const manifest={sources:{s1:'source1'},evidence:{},numeric_context:numericContext}
 expect(validManifest(manifest)).toBe(true)
 expect(validManifest({sources:{},evidence:{}})).toBe(true)
 for(const context of [null,[],{c1:{...numericContext.c1,origin:'model_generated'}},{s1:numericContext.c1},{c1:{...numericContext.c1,values:[{fact_path:'/numbers/0',value:1}]}}]){
  expect(validManifest({...manifest,numeric_context:context})).toBe(false)
 }
})

it('reads reviewed context occurrences while retaining legacy numeric binding boundaries',()=>{
 const snapshot={...rawSnapshot,methods:[{id:'method:1',text:'Use n−1.',origin:'model_generated',source_ids:[],citations:[],numeric_bindings:[{occurrence:0,value:'-1',kind:'context',source_alias:'c1',fact_path:'/numbers/0',evidence_id:null}]}]}
 expect(validSnapshot(snapshot,'p1')).toBe(true)
 expect(validSnapshot({...snapshot,writing_provenance:undefined},'p1')).toBe(false)
 expect(validSnapshot({...snapshot,methods:[{...snapshot.methods[0],numeric_bindings:[{...snapshot.methods[0].numeric_bindings[0],evidence_id:'e1'}]}]},'p1')).toBe(false)
})

it('accepts one to four actual authorization tasks and rejects empty duplicate or excessive groups',()=>{
 const bundles=Array.from({length:5},(_,i)=>bundleFixture(`b${i+1}`))
 for(const count of [1,2,4])expect(validAuthorization(authFixture(bundles.slice(0,count)),'p1')).toBe(true)
 expect(validAuthorization(authFixture([]),'p1')).toBe(false)
 expect(validAuthorization(authFixture(bundles),'p1')).toBe(false)
 const duplicate=authFixture(bundles.slice(0,2));duplicate.manifest.tasks[1].logical_task_id=duplicate.manifest.tasks[0].logical_task_id
 expect(validAuthorization(duplicate,'p1')).toBe(false)
})

it.each([false,true])('creates a minimal authorization only when every selected package uses the new contract (mixed legacy: %s)',async(mixedLegacy)=>{
 const bundles=[bundleFixture('en-full'),bundleFixture('zh-full')],authorization=authFixture(bundles)
 Object.assign(bundles[0].local_manifest,{numeric_context:{}})
 if(!mixedLegacy)Object.assign(bundles[1].local_manifest,{numeric_context:{}})
 bundles[1].request_json.output_language='zh-CN'
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>Response.json(url.endsWith('/manuscripts')?{items:[manuscriptFixture]}:url.endsWith('/writing-previews')?{items:bundles}:init?.method==='POST'?authorization:{items:[]}))
 vi.stubGlobal('fetch',fetcher);render(<WritingAuthorization projectId="p1" onSelect={vi.fn()}/>)
 fireEvent.click(screen.getByRole('button',{name:'读取同项目稿件与授权'}))
 await screen.findByRole('option',{name:/Saved draft/});await waitFor(()=>expect(screen.getByLabelText('读取其他稿件的冻结预览').matches(':disabled')).toBe(false))
 fireEvent.change(screen.getByLabelText('读取其他稿件的冻结预览'),{target:{value:'m1'}})
 await screen.findAllByRole('button',{name:'核对完整材料 en-full'});await waitFor(()=>expect(screen.getByLabelText('读取其他稿件的冻结预览').matches(':disabled')).toBe(false))
 const groups=screen.getAllByRole('group',{name:/^逻辑任务 \d$/})
 fireEvent.click(within(groups[0]).getByRole('checkbox',{name:/en-full$/}));fireEvent.click(within(groups[1]).getByRole('checkbox',{name:/zh-full$/}))
 expect(screen.getByRole('button',{name:'明确创建批次授权'}).matches(':disabled')).toBe(true)
 const confirmation=screen.getByLabelText(/我已核对.*逻辑任务的全部 wire/)
 if(mixedLegacy){expect(confirmation.matches(':disabled')).toBe(true);expect(fetcher.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);return}
 expect(confirmation.matches(':disabled')).toBe(false)
 fireEvent.click(confirmation);fireEvent.click(screen.getByRole('button',{name:'明确创建批次授权'}))
 await screen.findByRole('button',{name:'关闭此授权'})
 const body=JSON.parse(String(fetcher.mock.calls.find(([,init])=>init?.method==='POST')![1]?.body))
 expect(body.tasks).toEqual(bundles.map((b,i)=>({logical_task_id:`task-${i+1}`,bundles:[{bundle_id:b.id,bundle_sha256:b.bundle_sha256}]})))
})

it('shows exact context provenance and requires manual independent study and context decisions',async()=>{
 const candidate={...rawSnapshot,sections:rawSnapshot.sections!.map(s=>s.id==='materials_and_methods'?{...s,paragraphs:s.paragraphs.map(p=>({...p,text:'The study has n=12. Use n−1 as the divisor.'}))}:s),writing_provenance:{...rawSnapshot.writing_provenance!,numeric_contract_version:2}}
 const context={...reviewContext,candidate,required_paragraph_ids:['materials_and_methods:1'],local_manifest:{sources:{s1:'source1'},evidence:{},numeric_context:numericContext},reviews:[]}
 const bundle={...bundleFixture(),local_manifest:context.local_manifest}
 bundle.wire_json=JSON.stringify({input:JSON.stringify({sources:[{alias:'s1',facts:[{fact_path:'/statistics/n',value:'12'}]}]})})
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>Response.json(url.endsWith('/review-context')?context:init?.method==='POST'?scienceReview:bundle))
 vi.stubGlobal('fetch',fetcher);render(<WritingScienceReview projectId="p1" manuscriptId="m1" request={{...liveRequest,candidate}} onPublished={vi.fn()}/>)
 fireEvent.click(screen.getByRole('button',{name:'读取精确科学审核上下文'}))
 await screen.findByText('materials_and_methods[0]')
 expect(screen.getByText('Use n−1 as the divisor.')).toBeTruthy();expect(screen.getByText('illustrations[0].caption')).toBeTruthy();expect(screen.getByText('The whisker limit is 1.5 IQR.')).toBeTruthy()
 expect(screen.getByText('c1 /numbers/0 = -1')).toBeTruthy();expect(screen.getByText('c2 /numbers/0 = 1.5')).toBeTruthy()
 await waitFor(()=>expect(screen.getByLabelText('段落主张分类 materials_and_methods:1').matches(':disabled')).toBe(false))
 expect((screen.getByLabelText('段落主张分类 materials_and_methods:1') as HTMLSelectElement).value).toBe('')
 expect(screen.queryAllByLabelText('数值归属')).toHaveLength(0)
 expect((screen.getByLabelText('标题研究对象一致') as HTMLInputElement).checked).toBe(false)
 fireEvent.change(screen.getByLabelText('段落主张分类 materials_and_methods:1'),{target:{value:'context_claim'}})
 expect(screen.getByRole('option',{name:'研究数值与已提供方法/上下文'})).toBeTruthy()
 fireEvent.change(screen.getByLabelText('科学核对理由 materials_and_methods:1'),{target:{value:'Compared n=12 with the frozen study fact and n−1 with the supplied method.'}})
 fireEvent.click(screen.getByRole('button',{name:'添加数值出现绑定'}));fireEvent.click(screen.getByRole('button',{name:'添加数值出现绑定'}))
 let occurrences=screen.getAllByRole('group',{name:/^数值出现 \d$/})
 fireEvent.change(within(occurrences[0]).getByLabelText('精确事实路径和值'),{target:{value:'s1|/statistics/n'}})
 fireEvent.change(within(occurrences[1]).getByLabelText('数值归属'),{target:{value:'context'}})
 occurrences=screen.getAllByRole('group',{name:/^数值出现 \d$/})
 fireEvent.change(within(occurrences[1]).getByLabelText('精确上下文路径和值'),{target:{value:'c1|/numbers/0'}})
 for(const name of ['标题研究对象一致','标题方向一致','标题强度一致','摘要目的一致','摘要方法一致','摘要关键结果一致','摘要结论一致'])fireEvent.click(screen.getByLabelText(name))
 fireEvent.change(screen.getByLabelText('标题一致性依据'),{target:{value:'Title checked'}});fireEvent.change(screen.getByLabelText('摘要一致性依据'),{target:{value:'Abstract checked'}})
 fireEvent.click(screen.getByRole('button',{name:'封存本次科学审核'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([url,init])=>url.endsWith('/reviews')&&init?.method==='POST')).toBe(true))
 const body=JSON.parse(String(fetcher.mock.calls.find(([url,init])=>url.endsWith('/reviews')&&init?.method==='POST')![1]?.body))
 expect(body.paragraphs[0].classification).toBe('context_claim')
 expect(body.paragraphs[0].numeric_bindings).toEqual([{occurrence:0,value:'12',kind:'study',source_alias:'s1',fact_path:'/statistics/n'},{occurrence:1,value:'-1',kind:'context',source_alias:'c1',fact_path:'/numbers/0'}])
 expect(body.paragraphs[0].claim).toBeNull();expect(fetcher.mock.calls.some(([url])=>url.endsWith('/publish'))).toBe(false)
})
