import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import InsightResults from './InsightResults'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',onApiSessionChanged:()=>()=>{}}))
vi.mock('./InsightShared',async importOriginal=>{const actual=await importOriginal<typeof import('./InsightShared')>();return{...actual,Members:()=> <p>complete downloads</p>}})
afterEach(cleanup)
it('keeps readable feature and contrast identities in new sample comparison row citations',async()=>{
 const hash='b'.repeat(64),select=vi.fn()
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('/tables/')?
  {key:'comparison_results',columns:['row_key','feature_id','contrast_id','p_value','reason'],items:[{row_key:'opaque-row',feature_id:'bovine',contrast_id:'primary',p_value:'0',reason:'NA'}],page:1,page_size:50,total:1,matched_total:1,sha256:hash,raw_text_values:true}:
  {id:'r2',kind:'comparison',provenance:'system_computed',inference_scope:'sample_exploratory',summary:{},methods:{config:{kind:'comparison',schema_version:2}},manifest:{},manifest_sha256:hash,task_id:'t2',task:{id:'t2',status:'succeeded'},members:[{id:'m2',key:'comparison_results',format:'tsv',role:'table',sha256:hash,size_bytes:12,download_url:'/download'}]}))
 render(<InsightResults projectId="p1" resultId="r2" active onResearch={select}/>)
 const table=await screen.findByRole('table',{name:'完整结果表'})
 expect(within(table).getByText('0')).toBeTruthy();expect(within(table).getByText('NA')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'引用此行到研究发现'}))
 expect(select).toHaveBeenCalledWith(expect.objectContaining({source_kind:'bio_insight_result_member',source_id:'m2',sha256:hash,locator:{kind:'row',table:'comparison_results',row_key:{row_key:'opaque-row',feature_id:'bovine',contrast_id:'primary'},column:'p_value'}}))
})
it('keeps raw zero/NA with full-table count, server search and exact B03 row handoff',async()=>{
 const hash='a'.repeat(64),select=vi.fn();vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('/tables/')?{key:'differential',columns:['row_key','feature_id','q_within_contrast','reason'],items:[{row_key:'row0',feature_id:'GENE0',q_within_contrast:'0',reason:'NA'}],page:1,page_size:50,total:2000,matched_total:1,sha256:hash,raw_text_values:true}:{id:'r1',kind:'comparison',provenance:'system_computed',inference_scope:'spot_exploratory',summary:{synthetic:true},methods:{},manifest:{},manifest_sha256:hash,task_id:'t1',task:{id:'t1',status:'succeeded'},members:[{id:'m1',key:'differential',format:'tsv',role:'table',sha256:hash,size_bytes:12,download_url:'/download'}]}));render(<InsightResults projectId="p1" resultId="r1" active onResearch={select}/>);const table=await screen.findByRole('table',{name:'完整结果表'});expect(within(table).getByText('0')).toBeTruthy();expect(within(table).getByText('NA')).toBeTruthy();expect(screen.getByText(/2000/)).toBeTruthy();expect(screen.getByText('spot_exploratory',{exact:true})).toBeTruthy();fireEvent.change(screen.getByLabelText('搜索完整结果'),{target:{value:'GENE0'}});fireEvent.click(screen.getByRole('button',{name:'搜索'}));await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(([url])=>String(url).includes('search=GENE0'))).toBe(true));fireEvent.click(screen.getByRole('button',{name:'引用此行到研究发现'}));expect(select).toHaveBeenCalledWith(expect.objectContaining({source_kind:'bio_insight_result_member',source_id:'m1',locator:expect.objectContaining({kind:'row',table:'differential',row_key:{row_key:'row0'}})}))
})
