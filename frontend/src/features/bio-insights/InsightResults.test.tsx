import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import InsightResults from './InsightResults'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',captureApiSession:()=>()=>{},onApiSessionChanged:()=>()=>{}}))
vi.mock('./InsightShared',async importOriginal=>{const actual=await importOriginal<typeof import('./InsightShared')>();return{...actual,Members:()=> <p>complete downloads</p>}})
afterEach(cleanup)
it('labels the verified visualization scope of a saved figure in both languages',async()=>{
 const {setLocale}=await import('../../shared/i18n')
 vi.mocked(apiFetch).mockImplementation(async()=>Response.json({id:'plot',kind:'figure',provenance:'system_computed',inference_scope:'visualization',summary:{},methods:{},manifest:{},task:{id:'task',status:'succeeded'},members:[]}))
 render(<InsightResults projectId="p1" resultId="plot" active onResearch={()=>{}}/>)
 await screen.findByText('固定结果绘图')
 try {
  act(()=>setLocale('en'))
  expect(screen.getByText('Plot of saved results')).toBeTruthy()
 } finally {act(()=>setLocale('zh-CN'))}
})
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
 const hash='a'.repeat(64),select=vi.fn();vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('/tables/')?{key:'differential',columns:['row_key','feature_id','q_within_contrast','reason'],items:[{row_key:'row0',feature_id:'GENE0',q_within_contrast:'0',reason:'NA'}],page:1,page_size:50,total:2000,matched_total:1,sha256:hash,raw_text_values:true}:{id:'r1',kind:'comparison',provenance:'system_computed',inference_scope:'spot_exploratory',summary:{synthetic:true},methods:{},manifest:{},manifest_sha256:hash,task_id:'t1',task:{id:'t1',status:'succeeded'},members:[{id:'m1',key:'differential',format:'tsv',role:'table',sha256:hash,size_bytes:12,download_url:'/download'}]}));render(<InsightResults projectId="p1" resultId="r1" active onResearch={select}/>);const table=await screen.findByRole('table',{name:'完整结果表'});expect(within(table).getByText('0')).toBeTruthy();expect(within(table).getByText('NA')).toBeTruthy();expect(screen.getByText(/2000/)).toBeTruthy();expect(screen.getByText('区域探索',{exact:true})).toBeTruthy();fireEvent.change(screen.getByLabelText('搜索完整结果'),{target:{value:'GENE0'}});fireEvent.click(screen.getByRole('button',{name:'搜索'}));await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(([url])=>String(url).includes('search=GENE0'))).toBe(true));fireEvent.click(screen.getByRole('button',{name:'引用此行到研究发现'}));expect(select).toHaveBeenCalledWith(expect.objectContaining({source_kind:'bio_insight_result_member',source_id:'m1',locator:expect.objectContaining({kind:'row',table:'differential',row_key:{row_key:'row0'}})}))
})

it('identifies descriptive composition, donor n and cell n while preserving the formal report entry',async()=>{
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).endsWith('/figures')?{items:[]}:{id:'comp',kind:'comparison',provenance:'system_computed',inference_scope:'sample_exploratory',summary:{total_cells:120,unit_count:4,labels_confirmed:false,inference_status:'descriptive',inference_reason:'donor_missing',actual_units:[{contrast_id:'composition',observation_level:'donor',n_numerator:2,n_denominator:1,spots_numerator:80,spots_denominator:40}]},methods:{config:{schema_version:5,method:'single_cell_composition',mode:'descriptive'}},manifest:{},manifest_sha256:'c'.repeat(64),task:{id:'task',status:'succeeded'},members:[]}))
 render(<InsightResults projectId="p1" resultId="comp" active onResearch={()=>{}}/>)
 await screen.findByText('供者组成仅描述；不生成 P 值。')
 expect(screen.getByText('分母细胞 n = 120 · donor × condition 单元数 = 4')).toBeTruthy()
 expect(screen.getByRole('columnheader',{name:'分子组供者 n'})).toBeTruthy()
 expect(screen.getByRole('columnheader',{name:'分子组细胞 n'})).toBeTruthy()
 expect(screen.getByRole('button',{name:'准备详细报告'})).toHaveProperty('disabled',false)
 expect(screen.queryByRole('link',{name:'下载 Word 分析报告'})).toBeNull()
})

it('opens the saved Propeller table in the regular results and explains the contrast', async () => {
 const manifest = 'c'.repeat(64), tableHash = 'd'.repeat(64)
 const table = {id:'table',key:'composition_results',role:'table',format:'tsv',sha256:tableHash,size_bytes:70,download_url:'/download'}
 const counts = {...table,id:'counts',key:'composition_counts'}
 const result = {id:'comp',kind:'comparison',provenance:'system_computed',inference_scope:'donor_inference',
  summary:{actual_units:[{contrast_id:'composition',observation_level:'donor',numerator:'stim',denominator:'ctrl',n_numerator:4,n_denominator:4}]},
  methods:{name:'speckle_propeller',config:{schema_version:5,method:'single_cell_composition',mode:'donor_unpaired',numerator:'stim',denominator:'ctrl'}},
  manifest:{},manifest_sha256:manifest,task:{id:'task',status:'succeeded'},members:[counts,table]}
 const row = {label_id:'T',mean_proportion_denominator:'0.3300',mean_proportion_numerator:'0.5875',
  proportion_difference:'0.2575',p_adjust:'0.00048353808306252034',inference_status:'tested'}
 vi.mocked(apiFetch).mockImplementation(async url => {
  if (url.includes('/tables/composition_results?')) return Response.json({columns:Object.keys(row),items:[row],total:1,matched_total:1,page:1,page_size:50})
  if (url.includes('/tables/')) return Response.json({columns:[],items:[],total:0,matched_total:0,page:1,page_size:50})
  if (url.endsWith('/figures')) return Response.json({items:[]})
  return Response.json(result)
 })
 render(<InsightResults projectId="p1" resultId="comp" active onResearch={()=>{}}/>)
 const view = await screen.findByRole('table',{name:'完整结果表'})
 expect(screen.getByRole('combobox',{name:'完整结果表'})).toHaveProperty('value','composition_results')
 expect(screen.getByText('差值为分子组减参照组。相对比例的变化不能证明绝对丰度变化或因果关系。')).toBeTruthy()
 expect(screen.getByRole('columnheader',{name:'分子组供者 n'})).toBeTruthy()
 expect(within(view).getByText('0.3300')).toBeTruthy()
 expect(within(view).getByText('0.00048353808306252034')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'查看固定组成解读'})).toBeNull()
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

it('shows methods first and mounts the large manifest only while its view is shown, without folds',async()=>{
 const value={id:'lazy1',kind:'comparison',provenance:'system_computed',inference_scope:'spot_exploratory',summary:{note:'VISIBLE SUMMARY'},methods:{note:'METHOD DETAIL'},manifest:{members:Array.from({length:250},(_,i)=>({note:'MANIFEST MEMBER '+i}))},manifest_sha256:'f'.repeat(64),task:{id:'task',status:'succeeded'},members:[]}
 vi.mocked(apiFetch).mockImplementation(async()=>Response.json(value))
 const {container}=render(<InsightResults projectId="p1" resultId="lazy1" active onResearch={()=>{}}/>)
 await screen.findByText('VISIBLE SUMMARY')
 expect(container.querySelector('details, summary, [aria-expanded]')).toBeNull()
 expect(screen.getByText('METHOD DETAIL')).toBeTruthy()
 expect(screen.queryByText('MANIFEST MEMBER 249')).toBeNull()
 expect(screen.getByText('complete downloads')).toBeTruthy()
 const views=within(screen.getByRole('navigation',{name:'固定结果详情视图'}))
 fireEvent.click(views.getByRole('button',{name:'完整来源、环境、限制与清单'}))
 expect(screen.getByText('MANIFEST MEMBER 249')).toBeTruthy()
 fireEvent.click(views.getByRole('button',{name:'方法、统计单位与校正族'}))
 expect(screen.getByText('METHOD DETAIL')).toBeTruthy()
 expect(screen.queryByText('MANIFEST MEMBER 249')).toBeNull()
})
it('resets the detail view on result changes and supports English controls',async()=>{
 const {setLocale}=await import('../../shared/i18n')
 const value=(id:string)=>({id,kind:'comparison',provenance:'system_computed',inference_scope:'spot_exploratory',summary:{note:'SUMMARY '+id},methods:{note:'METHOD '+id},manifest:{note:'MANIFEST '+id},manifest_sha256:'a'.repeat(64),task:{id:'task',status:'succeeded'},members:[]})
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(value(String(url).includes('/new')?'new':'old')))
 const view=render(<InsightResults projectId="p1" resultId="old" active onResearch={()=>{}}/>)
 await screen.findByText('SUMMARY old')
 fireEvent.click(screen.getByRole('button',{name:'完整来源、环境、限制与清单'}))
 expect(screen.getByText('MANIFEST old')).toBeTruthy()
 view.rerender(<InsightResults projectId="p1" resultId="new" active onResearch={()=>{}}/>)
 await screen.findByText('SUMMARY new')
 expect(screen.queryByText('MANIFEST old')).toBeNull()
 expect(screen.queryByText('MANIFEST new')).toBeNull()
 expect(screen.getByText('METHOD new')).toBeTruthy()
 act(()=>setLocale('en'))
 fireEvent.click(screen.getByRole('button',{name:'Full sources, environment, limitations, and manifest'}))
 expect(screen.getByText('MANIFEST new')).toBeTruthy()
 expect(screen.getByRole('button',{name:'Full sources, environment, limitations, and manifest'}).getAttribute('aria-pressed')).toBe('true')
 act(()=>setLocale('zh-CN'))
})
