import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import InsightResults from './InsightResults'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',captureApiSession:()=>()=>{},onApiSessionChanged:()=>()=>{}}))
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

it('identifies descriptive composition, donor n, cell n and Word download without suggesting sample inference',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'comp',kind:'comparison',provenance:'system_computed',inference_scope:'sample_exploratory',summary:{total_cells:120,unit_count:4,labels_confirmed:false,inference_status:'descriptive',inference_reason:'donor_missing',actual_units:[{contrast_id:'composition',observation_level:'donor',n_numerator:2,n_denominator:1,spots_numerator:80,spots_denominator:40}]},methods:{config:{schema_version:5,method:'single_cell_composition',mode:'descriptive'}},manifest:{},manifest_sha256:'c'.repeat(64),task:{id:'task',status:'succeeded'},members:[]}))
 render(<InsightResults projectId="p1" resultId="comp" active onResearch={()=>{}}/>)
 await screen.findByText('供者组成仅描述；不生成 P 值。')
 expect(screen.getByText('分母细胞 n = 120 · donor × condition 单元数 = 4')).toBeTruthy()
 expect(screen.getByRole('columnheader',{name:'分子组供者 n'})).toBeTruthy()
 expect(screen.getByRole('columnheader',{name:'分子组细胞 n'})).toBeTruthy()
 expect(screen.getByRole('link',{name:'下载 Word 分析报告'}).getAttribute('href')).toBe('/api/v1/projects/p1/bio-insight-results/comp/report.docx')
})

it('renders donor units from the actual DE methods shape without a config wrapper',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'de',kind:'comparison',provenance:'system_computed',inference_scope:'donor_inference',summary:{actual_units:[{contrast_id:'contrast_1',observation_level:'donor',n_numerator:4,n_denominator:4,spots_numerator:60,spots_denominator:70}]},methods:{name:'PyDESeq2_0.5.4_Wald',single_cell_selection:{processed_source_id:'p',annotation_source_id:'ann',label_ids:['T'],labels_confirmed:true,label_basis:'manual'}},manifest:{},manifest_sha256:'d'.repeat(64),task:{id:'task',status:'succeeded'},members:[]}))
 render(<InsightResults projectId="p1" resultId="de" active onResearch={()=>{}}/>)
 await screen.findByText('同类型供者比较与推断边界')
 expect(screen.getByRole('columnheader',{name:'分子组供者 n'})).toBeTruthy()
 expect(screen.getByRole('columnheader',{name:'分子组细胞 n'})).toBeTruthy()
 expect(screen.queryByText('供者组成仅描述；不生成 P 值。')).toBeNull()
})

it('shows a single actual donor and cell column for one-condition description',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'one',kind:'comparison',provenance:'system_computed',inference_scope:'sample_exploratory',summary:{total_cells:20,unit_count:1,labels_confirmed:false,actual_units:[{contrast_id:'composition',observation_level:'donor',numerator:'healthy',denominator:'healthy',n_numerator:0,n_denominator:1,spots_numerator:0,spots_denominator:20}]},methods:{config:{schema_version:5,mode:'descriptive',numerator:'healthy',denominator:'healthy'},single_condition_description:true},manifest:{},manifest_sha256:'e'.repeat(64),task:{id:'task',status:'succeeded'},members:[]}))
 render(<InsightResults projectId="p1" resultId="one" active onResearch={()=>{}}/>)
 await screen.findByText('单条件组成描述；相同条件只计数一次，不计算组间差值、比值或 P 值。')
 expect(screen.getByRole('columnheader',{name:'实际供者 n'})).toBeTruthy()
 expect(screen.getByRole('columnheader',{name:'实际细胞 n'})).toBeTruthy()
 expect(screen.queryByRole('columnheader',{name:'分子组供者 n'})).toBeNull()
})

it('lazily mounts methods and large manifest only while expanded, retaining summary and downloads',async()=>{
 const value={id:'lazy1',kind:'comparison',provenance:'system_computed',inference_scope:'spot_exploratory',summary:{note:'VISIBLE SUMMARY'},methods:{note:'METHOD DETAIL'},manifest:{members:Array.from({length:250},(_,i)=>({note:'MANIFEST MEMBER '+i}))},manifest_sha256:'f'.repeat(64),task:{id:'task',status:'succeeded'},members:[]}
 vi.mocked(apiFetch).mockImplementation(async()=>Response.json(value))
 render(<InsightResults projectId="p1" resultId="lazy1" active onResearch={()=>{}}/>)
 await screen.findByText('VISIBLE SUMMARY')
 expect(screen.queryByText('METHOD DETAIL')).toBeNull()
 expect(screen.queryByText('MANIFEST MEMBER 249')).toBeNull()
 expect(screen.getByText('complete downloads')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'展开方法详情'}))
 expect(screen.getByText('METHOD DETAIL')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'展开完整来源与清单'}))
 expect(screen.getByText('MANIFEST MEMBER 249')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'收起方法详情'}))
 fireEvent.click(screen.getByRole('button',{name:'收起完整来源与清单'}))
 expect(screen.queryByText('METHOD DETAIL')).toBeNull()
 expect(screen.queryByText('MANIFEST MEMBER 249')).toBeNull()
})
it('resets expanded details on result changes and supports English controls',async()=>{
 const {setLocale}=await import('../../shared/i18n')
 const value=(id:string)=>({id,kind:'comparison',provenance:'system_computed',inference_scope:'spot_exploratory',summary:{note:'SUMMARY '+id},methods:{note:'METHOD '+id},manifest:{note:'MANIFEST '+id},manifest_sha256:'a'.repeat(64),task:{id:'task',status:'succeeded'},members:[]})
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(value(String(url).includes('/new')?'new':'old')))
 const view=render(<InsightResults projectId="p1" resultId="old" active onResearch={()=>{}}/>)
 await screen.findByText('SUMMARY old')
 fireEvent.click(screen.getByRole('button',{name:'展开完整来源与清单'}))
 expect(screen.getByText('MANIFEST old')).toBeTruthy()
 view.rerender(<InsightResults projectId="p1" resultId="new" active onResearch={()=>{}}/>)
 await screen.findByText('SUMMARY new')
 expect(screen.queryByText('MANIFEST old')).toBeNull()
 expect(screen.queryByText('MANIFEST new')).toBeNull()
 act(()=>setLocale('en'))
 fireEvent.click(screen.getByRole('button',{name:'Expand full sources and manifest'}))
 expect(screen.getByText('MANIFEST new')).toBeTruthy()
 expect(screen.getByRole('button',{name:'Collapse full sources and manifest'})).toBeTruthy()
 act(()=>setLocale('zh-CN'))
})
