import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import InsightDelivery from './InsightDelivery'
import type {Result} from './contracts'
import {apiFetch} from '../../shared/api/client'
import {fixedContext,fixedExports,fixedSha} from '../bio-reader-reports/testFixtures'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',captureApiSession:()=>()=>{},onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear()})

const base='/api/v1/projects/p1'
const result={id:'topic',kind:'integration',summary:{topic_method:'cellchat'},methods:{},manifest:{},
 manifest_sha256:fixedSha,task:{id:'task',status:'succeeded'},members:[]} as unknown as Result
const plot=(id:string,title:string,sourceId=result.id)=>({id,title,figure_type:'topic_cellchat',manifest_sha256:fixedSha,
 source_id:sourceId,source_sha256:fixedSha})

it('prepares the chosen replot order and preserves separate original and per-figure reproduction',async()=>{
 vi.mocked(apiFetch).mockImplementation(async (url,init)=>Response.json(String(url).endsWith('/figures')?
  {items:[plot('first','通讯图甲'),plot('second','通讯图乙'),plot('other','异源图','other')]}:
  String(url).endsWith('/prepare')?fixedContext(JSON.parse(String(init?.body))):fixedExports()))
 render(<InsightDelivery projectId="p1" result={result}/>)
 fireEvent.click(await screen.findByLabelText('通讯图乙'))
 fireEvent.click(screen.getByLabelText('通讯图甲'))
 expect(screen.queryByLabelText('异源图')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'准备详细报告'}))
 const word=await screen.findByRole('link',{name:/下载.*docx/})
 expect(word.getAttribute('href')).toBe(base+'/bio-reader-reports/context1/reports/formal1/members/docx/download')
 const prepare=vi.mocked(apiFetch).mock.calls.find(([url])=>String(url).endsWith('/bio-reader-reports/prepare'))
 expect(JSON.parse(String(prepare?.[1]?.body)).selection).toEqual({kind:'insight',result_version_id:'topic',figure_version_ids:['second','first']})
 expect(screen.getByRole('link',{name:'下载原分析复现包'}).getAttribute('href')).toBe(base+'/bio-insight-results/topic/reproducibility-package')
 expect(screen.getByRole('link',{name:'通讯图乙：下载重绘复现包'}).getAttribute('href')).toBe(base+'/bio-insight-results/second/reproducibility-package')
 expect(result.members).toEqual([])
})

it('preserves the current enrichment in the server-normalized Bulk shortcut',async()=>{
 const ora={...result,id:'ora',kind:'ora',summary:{bulk_enrichment:true},methods:{bulk_enrichment:{},config:{kind:'ora',bulk_enrichment:{},result_source_ids:['comparison']}}} as Result
 vi.mocked(apiFetch).mockImplementation(async (url,init)=>{
  if(String(url).endsWith('/figures'))return Response.json({items:[]})
  if(String(url).endsWith('/prepare')){
   const body=JSON.parse(String(init?.body))
   return Response.json(fixedContext({...body,selection:{kind:'bulk',delivery:{comparison_version_id:'comparison',
    result_version_ids:['ora'],language:body.language==='en'?'en':'zh',selections:[],sensitivity:null,evidence:[],facts_digest:fixedSha}}}))
  }
  return Response.json(fixedExports())
 })
 render(<InsightDelivery projectId="p1" result={ora}/>)
 fireEvent.click(screen.getByRole('button',{name:'准备详细报告'}))
 await screen.findByRole('button',{name:'下载 Bulk 完整分析复现包'})
 const prepare=vi.mocked(apiFetch).mock.calls.find(([url])=>String(url).endsWith('/bio-reader-reports/prepare'))
 expect(JSON.parse(String(prepare?.[1]?.body)).selection).toEqual({kind:'insight',result_version_id:'ora',figure_version_ids:[]})
 expect(vi.mocked(apiFetch).mock.calls.some(([url])=>String(url).includes('/report.docx'))).toBe(false)
 await waitFor(()=>expect(screen.getByRole('link',{name:/下载.*docx/})).toBeTruthy())
})

it('opens the formal report panel for a successful imported external differential result',async()=>{
 const imported={...result,id:'external-de',kind:'result_import' as const,summary:{},provenance:'external_result',inference_scope:'external_result'}
 const restored=fixedContext({title:'External differential report',language:'en',
  selection:{kind:'insight',result_version_id:imported.id,figure_version_ids:[]}})
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).endsWith('/context1')?restored:
  String(url).endsWith('/reports?page=1')?fixedExports():{items:[]}))
 render(<InsightDelivery projectId="p1" result={imported} reportContextId="context1"/>)
 expect((await screen.findByRole('link',{name:/下载.*docx/})).getAttribute('href')).toContain('/context1/reports/formal1/members/docx/download')
 expect(screen.getByRole('link',{name:'下载原分析复现包'}).getAttribute('href')).toBe(base+'/bio-insight-results/external-de/reproducibility-package')
})
