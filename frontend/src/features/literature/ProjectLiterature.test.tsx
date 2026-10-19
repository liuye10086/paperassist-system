import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import ProjectLiterature from './ProjectLiterature'
import { literatureTask } from './fixtures'
import { clearApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
const stamp = '2026-10-08T01:00:00Z'
const config = { available: false, reason: 'ncbi_not_configured', candidate_limits: [20,50,100], default_limit:20, page_size:10, publication_types:[], full_text_acquisition:false, claim_verification:false }
const page = (items: unknown[] = [], project='p1', current=1, total=items.length) => ({ project_id:project, items, total, page:current, page_size:10 })
// Synthetic bibliography: deliberately not a real publication.
const reference = {id:'candidate1',reference_id:'book1',project_id:'p1',pmid:'123',record:{pmid:'123',title:'Synthetic original title',authors:[],year:null,journal:null,doi:'10.synthetic/a?b',abstract:[],abstract_status:'not_returned',full_text_status:'not_acquired',verification_status:'not_verified',doi_resolution_status:'not_checked',keywords:[],mesh_terms:[],full_text_links:[{source:'PMC',url:'https://evil.test/PMC1'}]},selection:{status:'candidate',note:'',revision:1},source:{search_id:'search1',receipt_id:'receipt1',query:'synthetic',effective_query:'(synthetic)',retrieved_at:stamp,source_kind:'synthetic_fixture',cached:false,ordinal:1,source_download_url:'/api/v1/projects/p1/literature/receipts/receipt1/source'},created_at:stamp,updated_at:stamp}
const detail = {...reference,sources:{items:[reference.source],total:1,page:1,page_size:10},decisions:[]}
function setup(override?: (url:string,init?:RequestInit)=>Promise<Response>|Response|undefined) {
 const mock=vi.fn(async (input:string,init?:RequestInit) => {
  const custom=override?.(input,init);if(custom)return custom
  if(input.endsWith('/config'))return Response.json(config)
  if(input.includes('/references/candidate1'))return Response.json(detail)
  if(input.includes('/references?'))return Response.json(page([reference]))
  if(input.endsWith('/searches')&&init?.method==='POST')return Response.json(literatureTask,{status:202})
  if(input.includes('/searches?'))return Response.json(page())
  throw Error(input)
 });vi.stubGlobal('fetch',mock);return mock
}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it.each(['zh-CN','en'] as const)('shows saved replay context unchanged with neutral receipt wording in %s',async locale=>{
 setLocale(locale)
 const context={kind:'section',label:'论文章节',text:'真实回执离线重放（未再次外发）'}
 const source={...reference.source,source_kind:'ncbi_eutilities',source_context:context}
 setup(url=>url.includes('/references/candidate1')?Response.json({...detail,source,sources:{...detail.sources,items:[source]}}):undefined)
 render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active/>);
 await userEvent.click(await screen.findByRole('button',{name:locale==='en'?'View candidate details':'查看候选详情'}))
 const region=await screen.findByRole('region',{name:locale==='en'?'Candidate reference details':'候选文献详情'})
 expect(within(region).getAllByText(locale==='en'?'Saved search context':'保存的检索背景')).toHaveLength(2)
 expect(within(region).getAllByText(context.label)).toHaveLength(2)
 expect(within(region).getAllByText(context.text)).toHaveLength(2)
 expect(within(region).getAllByText(locale==='en'?/Saved source record/:/已保存的来源记录/)).toHaveLength(2)
 expect(within(region).queryByText(/本次获取来源|Source from this retrieval/)).toBeNull()
 expect(within(region).getAllByText('synthetic')).toHaveLength(2)
 expect(within(region).getAllByRole('link',{name:locale==='en'?'Download original JSON/XML':'下载原始 JSON/XML'})).toHaveLength(2)
})
it.each([undefined,null,{kind:'section',label:'',text:''},{kind:'feedback',label:'  ',text:'\n'}])('hides absent or empty saved source context (%j)',async source_context=>{
 const source={...reference.source,source_context}
 setup(url=>url.includes('/references/candidate1')?Response.json({...detail,source,sources:{...detail.sources,items:[source]}}):undefined)
 render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active/>);
 await userEvent.click(await screen.findByRole('button',{name:'查看候选详情'}))
 const region=await screen.findByRole('region',{name:'候选文献详情'})
 expect(within(region).queryByText('保存的检索背景')).toBeNull()
 expect(within(region).getAllByRole('link',{name:'下载原始 JSON/XML'})).toHaveLength(2)
})
it('saves while NCBI is disabled and reuses idempotency for an unchanged retry',async()=>{
 const mock=setup();const open=vi.fn();render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active onOpenTask={open}/>);
 expect(await screen.findByText(/已保存结果仍可查看/)).toBeTruthy()
 const query=screen.getByLabelText('PubMed 检索式');fireEvent.change(query,{target:{value:'synthetic[Title]'}})
 await userEvent.click(screen.getByRole('button',{name:'保存检索并创建任务'}));await screen.findByText('检索任务已保存。')
 await userEvent.click(screen.getByRole('button',{name:'保存检索并创建任务'}));await waitFor(()=>expect(mock.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(2))
 const posts=mock.mock.calls.filter(([,i])=>i?.method==='POST');expect(new Headers(posts[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(posts[1][1]?.headers).get('Idempotency-Key'))
 expect(JSON.parse(posts[0][1]!.body as string)).toMatchObject({research_topic:'Synthetic topic',query:'synthetic[Title]',limit:20,sort:'relevance',year_from:null,publication_types:[],source_context:{kind:'project_topic'}})
 await userEvent.click(screen.getByRole('button',{name:'查看检索任务'}));expect(open).toHaveBeenCalledWith('search1')
})
it('rejects reversed years without posting and uses a new key after editing',async()=>{
 const mock=setup();render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active/>);await screen.findByText(/已保存结果仍可查看/)
 fireEvent.change(screen.getByLabelText('PubMed 检索式'),{target:{value:'synthetic'}})
 fireEvent.change(screen.getByLabelText('起始年份'),{target:{value:'2026'}});fireEvent.change(screen.getByLabelText('结束年份'),{target:{value:'2020'}})
 fireEvent.submit(screen.getByRole('form',{name:'文献检索条件'}));expect(await screen.findByText('请检查研究主题、检索式和年份范围。')).toBeTruthy();expect(mock.mock.calls.some(([,i])=>i?.method==='POST')).toBe(false)
 fireEvent.change(screen.getByLabelText('结束年份'),{target:{value:'2026'}});await userEvent.click(screen.getByRole('button',{name:'保存检索并创建任务'}));await screen.findByText('检索任务已保存。')
 fireEvent.change(screen.getByLabelText('PubMed 检索式'),{target:{value:'changed'}});await userEvent.click(screen.getByRole('button',{name:'保存检索并创建任务'}));await waitFor(()=>expect(mock.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(2))
 const posts=mock.mock.calls.filter(([,i])=>i?.method==='POST');expect(new Headers(posts[0][1]?.headers).get('Idempotency-Key')).not.toBe(new Headers(posts[1][1]?.headers).get('Idempotency-Key'))
})
it('keeps original bibliography, missing fields, safe links and explicit acquisition states',async()=>{
 setup();render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active/>);await userEvent.click(await screen.findByRole('button',{name:'查看候选详情'}))
 expect(await screen.findByText('摘要未返回')).toBeTruthy();expect(screen.getAllByText(/作者未提供/).length).toBeGreaterThan(0);expect(screen.getAllByText(/年份未提供/).length).toBeGreaterThan(0)
 expect(screen.getByText('全文未取得')).toBeTruthy();expect(screen.getByRole('button',{name:'查看三项核验与历史'})).toBeTruthy();expect(screen.getAllByText(/合成测试资料/).length).toBeGreaterThan(0)
 expect(screen.getByRole('link',{name:'DOI 未核验入口'}).getAttribute('href')).toBe('https://doi.org/10.synthetic%2Fa%3Fb')
 expect(screen.queryByRole('link',{name:'PMC 全文入口'})).toBeNull();expect(screen.getByRole('link',{name:'PubMed 原始条目'}).getAttribute('rel')).toContain('noopener')
 expect(screen.getAllByRole('link',{name:'下载原始 JSON/XML'}).length).toBeGreaterThan(0);expect(screen.queryByText('receipt1')).toBeNull()
})
it('sends the expected selection revision and reloads after a conflict',async()=>{
 const mock=setup((u,i)=>u.endsWith('/references/candidate1')&&i?.method==='PATCH'?Response.json({detail:{code:'literature_revision_conflict'}},{status:409}):undefined)
 render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active/>);await userEvent.click(await screen.findByRole('button',{name:'查看候选详情'}));await screen.findByText('摘要未返回')
 await userEvent.selectOptions(screen.getByLabelText('人工筛选状态'),'shortlisted');await userEvent.type(screen.getByLabelText('筛选备注'),'Needs reading')
 await userEvent.click(screen.getByRole('button',{name:'保存人工筛选'}));expect(await screen.findByText('候选状态已变化，已重新读取；请核对后再保存。')).toBeTruthy()
 expect(JSON.parse(mock.mock.calls.find(([,i])=>i?.method==='PATCH')![1]!.body as string)).toEqual({expected_revision:1,status:'shortlisted',note:'Needs reading'})
})
it('ignores an old project response after switching projects and clears on logout',async()=>{
 let release!:(r:Response)=>void;setup(u=>u.includes('/p1/literature/references?')?new Promise<Response>(r=>release=r):u.includes('/p2/literature/references?')?Response.json(page([],'p2')):u.includes('/p2/literature/searches?')?Response.json(page([],'p2')):undefined)
 const view=render(<ProjectLiterature projectId="p1" researchTopic="Old topic" active/>);await screen.findByText(/已保存结果仍可查看/)
 view.rerender(<ProjectLiterature projectId="p2" researchTopic="New topic" active/>);await waitFor(()=>expect((screen.getByLabelText('研究主题') as HTMLTextAreaElement).value).toBe('New topic'));await act(async()=>release(Response.json(page([reference]))));expect(screen.queryByText('Synthetic original title')).toBeNull()
 act(()=>clearApiSession());expect(await screen.findByText('会话已失效，请重新登录。')).toBeTruthy();expect(screen.queryByRole('form')).toBeNull()
})
it('uses English controls while preserving source titles',async()=>{
 setLocale('en');setup();render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active/>);expect(await screen.findByText('Synthetic original title')).toBeTruthy();expect(screen.getByRole('button',{name:'Save search and create task'})).toBeTruthy()
})
it('clears inaccessible project data on permission loss',async()=>{
 let deny=false;setup((u)=>deny&&u.endsWith('/config')?Response.json({detail:{code:'forbidden'}},{status:403}):undefined)
 render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active/>);await screen.findByText('Synthetic original title');deny=true
 await userEvent.click(screen.getByRole('button',{name:'刷新文献记录'}));expect(await screen.findByText('项目不存在或无权访问。')).toBeTruthy();expect(screen.queryByText('Synthetic original title')).toBeNull();expect(screen.queryByRole('form')).toBeNull()
})
it('clamps an emptied final candidate page and disables navigation on an empty result',async()=>{
 let emptied=false
 setup(u=>u.includes('/references?')?Response.json(page(u.includes('page=2')?[]:emptied?[]:[reference],'p1',u.includes('page=2')?2:1,emptied?0:11)):undefined)
 render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active/>);await screen.findByText('Synthetic original title')
 const navigation=screen.getByRole('navigation',{name:'候选文献分页'});emptied=true
 await userEvent.click(within(navigation).getByRole('button',{name:'下一页'}));await screen.findByText('当前条件下暂无候选文献。')
 await waitFor(()=>expect(within(screen.getByRole('navigation',{name:'候选文献分页'})).getByText('共 0 项 · 第 1 / 1 页')).toBeTruthy());expect((within(screen.getByRole('navigation',{name:'候选文献分页'})).getByRole('button',{name:'下一页'}) as HTMLButtonElement).disabled).toBe(true)
})
it('shows frozen search conditions and edits a copy without mutating history',async()=>{
 const input={research_topic:'Synthetic old topic',source_context:{kind:'feedback',label:'Synthetic supervisor',text:'Synthetic feedback'},query:'synthetic old query',year_from:2020,year_to:2025,publication_types:['Review'],sort:'pub_date',limit:50,output_language:'en'}
 const search={id:'search1',project_id:'p1',task:literatureTask,input,effective_query:'(synthetic old query)',query_translation:null,matched_count:null,retrieved_count:0,missing_pmids:[],warnings:[],created_at:stamp,updated_at:stamp,source_url:'https://pubmed.ncbi.nlm.nih.gov/?term=synthetic'}
 setup(u=>u.includes('/searches?page=')?Response.json(page([search])):u.endsWith('/searches/search1')?Response.json(search):undefined)
 render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active/>);await userEvent.click(await screen.findByRole('button',{name:'查看本次检索'}))
 const saved=await screen.findByRole('region',{name:'已保存的检索条件'});expect(await within(saved).findByText(/Years: 2020–2025/)).toBeTruthy()
 await userEvent.click(screen.getByRole('button',{name:'编辑后重新检索'}));expect((screen.getByLabelText('研究主题') as HTMLTextAreaElement).value).toBe('Synthetic old topic');fireEvent.change(screen.getByLabelText('PubMed 检索式'),{target:{value:'New query'}});expect(within(saved).getByText('synthetic old query')).toBeTruthy()
})
it.each([false,true])('keeps historical candidate details through reload, source paging and selection save (conflict=%s)',async conflict=>{
 const input={research_topic:'Synthetic old topic',source_context:{kind:'project_topic',label:'',text:'Synthetic old topic'},query:'synthetic',year_from:null,year_to:null,publication_types:[],sort:'relevance',limit:20,output_language:'zh-CN'}
 const search={id:'search1',project_id:'p1',task:literatureTask,input,effective_query:'(synthetic)',query_translation:null,matched_count:1,retrieved_count:1,missing_pmids:[],warnings:[],created_at:stamp,updated_at:stamp,source_url:'https://pubmed.ncbi.nlm.nih.gov/?term=synthetic'}
 const newerSource={...reference.source,search_id:'search2',receipt_id:'receipt2',query:'new synthetic query',source_download_url:'/api/v1/projects/p1/literature/receipts/receipt2/source'}
 const newer={...reference,source:newerSource,record:{...reference.record,title:'Synthetic newer title',abstract_status:'available',abstract:[{label:null,text:'Synthetic newer abstract'}]}}
 let saved=false
 const mock=setup((url,init)=>{
  if(url.endsWith('/searches/search1'))return Response.json(search)
  if(url.includes('/references/candidate1')){
   if(init?.method==='PATCH'){saved=true;return conflict?Response.json({detail:{code:'literature_revision_conflict'}},{status:409}):Response.json(newer)}
   const params=new URL(url,'http://test.local').searchParams
   const selected=params.get('search_id')==='search1'?reference:newer
   return Response.json({...selected,selection:{...selected.selection,revision:saved?2:1},sources:{items:params.get('page')==='2'?[newerSource]:[newerSource,reference.source],total:11,page:Number(params.get('page')),page_size:10},decisions:[]})
  }
  return undefined
 })
 render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active initialSearchId="search1"/>);
 await userEvent.click(await screen.findByRole('button',{name:'查看候选详情'}))
 const region=screen.getByRole('region',{name:'候选文献详情'})
 expect(await within(region).findByText('Synthetic original title')).toBeTruthy()
 expect(within(region).queryByText('Synthetic newer abstract')).toBeNull()
 expect(within(region).getByText('当前条目快照来源')).toBeTruthy()
 expect(within(region).getByText('全部检索来源')).toBeTruthy()
 await userEvent.click(within(region).getByRole('button',{name:'重新读取候选详情'}))
 expect(await within(region).findByText('Synthetic original title')).toBeTruthy()
 await userEvent.click(within(screen.getByRole('navigation',{name:'候选来源分页'})).getByRole('button',{name:'下一页'}))
 await waitFor(()=>expect(within(region).getByText('共 11 项 · 第 2 / 2 页')).toBeTruthy())
 expect(within(region).getByText('Synthetic original title')).toBeTruthy()
 await userEvent.click(within(region).getByRole('button',{name:'保存人工筛选'}))
 await waitFor(()=>expect(mock.mock.calls.filter(([url,init])=>url.includes('/references/candidate1?')&&init?.method!=='PATCH').length).toBeGreaterThanOrEqual(4))
 expect(await within(region).findByText('Synthetic original title')).toBeTruthy()
 expect(within(region).queryByText('Synthetic newer abstract')).toBeNull()
 expect(mock.mock.calls.filter(([url,init])=>url.includes('/references/candidate1?')&&init?.method!=='PATCH').every(([url])=>new URL(url,'http://test.local').searchParams.get('search_id')==='search1')).toBe(true)
})
it.each(['zh-CN','en'] as const)('explains saved inputs and PubMed coverage in %s',async locale=>{
 setLocale(locale);setup();render(<ProjectLiterature projectId="p1" researchTopic="Synthetic topic" active/>);
 expect(await screen.findByText(locale==='en'?'Search inputs are saved as entered; later edits do not change history.':'检索依据按本次填写保存，后续修改不会改写历史。')).toBeTruthy()
 expect(screen.getByText(locale==='en'?'PubMed mainly covers biomedicine; full-text availability depends on what is actually obtained.':'PubMed 主要覆盖生物医学，全文可得性以实际取得为准。')).toBeTruthy()
 expect(screen.getByRole('link',{name:locale==='en'?'NCBI usage and copyright notice':'NCBI 使用与版权说明'}).getAttribute('href')).toBe('https://www.ncbi.nlm.nih.gov/About/disclaimer.html')
 await userEvent.click(await screen.findByRole('button',{name:locale==='en'?'View candidate details':'查看候选详情'}))
 expect((await screen.findAllByText(locale==='en'?/Synthetic fixture/:/合成测试资料/)).length).toBeGreaterThan(0)
})
