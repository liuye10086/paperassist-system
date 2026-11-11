import {act, cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import {afterEach, expect, it, vi} from 'vitest'
import {apiFetch} from '../../shared/api/client'
import {setLocale} from '../../shared/i18n'
import {parseNavigation, serializeNavigation} from '../projects/projectNavigation'
import BioInsightsWorkspace from './BioInsightsWorkspace'
import InsightResults from './InsightResults'
import type {Config} from './contracts'
import {defaultConfig} from './state'
import {rawFixture} from '../bioinformatics/spatialFixtures'
import TabularAnalysisResult from '../bioinformatics/TabularAnalysisResult'
import type {TabularProcessed} from '../bioinformatics/tabularContracts'

vi.mock('../../shared/api/client', () => ({
  apiFetch: vi.fn(), getApiUserId: () => 'owner', onApiSessionChanged: () => () => {},
  captureApiSession: () => () => {},
}))
afterEach(() => { cleanup(); sessionStorage.clear(); setLocale('zh-CN') })

const sha = 'a'.repeat(64)
const primary = {contrast_id:'forward', numerator:'treated', denominator:'control', total:3, tested:2, excluded:1, not_computable:1, missing_metric:2, deg:1, up:1, down:0}
const reverse = {...primary, contrast_id:'reverse', numerator:'control', denominator:'treated', deg:0, up:0, down:0}
const columns = ['feature_id','contrast_id','effect_value','q_within_contrast','q_global_family','reason']
const row = {feature_id:'ENS0001', contrast_id:'forward', effect_value:'2', q_within_contrast:'0', q_global_family:'0.02', reason:'NA', tested:'true', test_status:'computed'}
const allRows = [row, {...row, feature_id:'ENS0002', effect_value:'NA', q_within_contrast:'NA', q_global_family:'NA', test_status:'not_computable'}]
const comparison = {
  id:'fixed', run_id:'comparison-run', kind:'comparison', provenance:'system_computed', inference_scope:'sample_inference',
  methods:{config:{schema_version:2, mode:'bulk_counts', bulk_model:'shared_wald_v1'}},
  summary:{}, manifest:{}, manifest_sha256:sha, task:{id:'comparison-task', status:'succeeded'},
  members:[{id:'table', key:'comparison_results', format:'tsv', role:'table', sha256:sha, size_bytes:17, download_url:'/full-table.tsv'}],
}
const writeCalls = () => vi.mocked(apiFetch).mock.calls.filter(([,init]) => init?.method === 'POST')
function mockBulkResult(result = comparison) {
  vi.mocked(apiFetch).mockImplementation(async (url, init) => {
    const path = String(url)
    if (init?.method === 'POST') {
      const design = {executable:true, blocking_reasons:[]}
      const body = JSON.parse(String(init.body))
      if (path.endsWith('/preview')) return Response.json(design)
      if (path.endsWith('/bio-insight-runs')) return Response.json({id:'fixed-plot-run', task:{status:'queued'}, kind:'figure'})
      return Response.json({...body, id:'fixed-plan-version', plan_id:'fixed-plan', revision:1, current_revision:1, design, source_digest:sha})
    }
    if (path.includes('/bulk-comparisons')) {
      const query = new URL(path, 'http://localhost').searchParams
      const contrast = query.get('contrast_id') === 'reverse' ? reverse : primary
      const items = query.get('subset') === 'down' ? [] : query.get('subset') === 'all' ? allRows : [row]
      return Response.json({
        contrast_id:contrast.contrast_id, contrasts:[primary, reverse], columns, items, total:3, matched_total:items.length, page:1, page_size:50, sha256:sha,
        feature_matches:query.get('search') === 'ENS0001' ? [row, {...row, contrast_id:'reverse', effect_value:'-2'}] : [],
      })
    }
    if (path.includes('/tables/')) return Response.json({items:allRows, columns, total:3, matched_total:2, page:1, page_size:50})
    if (path.endsWith('/fixed')) return Response.json(result)
    return Response.json({items:[],total:0})
  })
}
const openResult = () => render(<BioInsightsWorkspace projectId="p1" active navigation={{view:'bio-insight-result',fileId:'',resultVersionId:'fixed'}} onNavigate={vi.fn()}/>)

it('reads the default contrast, preserves raw zero and NA, and searches exact stable IDs across comparisons with GET', async () => {
  mockBulkResult()
  openResult()
  const table = await screen.findByRole('table',{name:'Bulk 比较结果'})
  expect(within(table).getByText('0')).toBeTruthy()
  expect(within(table).getAllByText('NA').length).toBeGreaterThan(0)
  expect(screen.getByRole('combobox',{name:'固定比较'})).toHaveProperty('value','forward')
  expect(screen.getByRole('option',{name:'control vs treated (reverse)'})).toBeTruthy()
  fireEvent.change(screen.getByLabelText('特征搜索'),{target:{value:'ENS0001'}})
  fireEvent.click(screen.getByRole('button',{name:'应用筛选'}))
  const across = await screen.findByRole('table',{name:'同一稳定 ID 的跨比较结果'})
  expect(within(across).getByText('-2')).toBeTruthy()
  expect(screen.getByRole('link',{name:/comparison_results · tsv/}).getAttribute('href')).toBe('/full-table.tsv')
  act(() => setLocale('en'))
  expect(screen.getByRole('combobox',{name:'Fixed contrast'})).toHaveProperty('value','forward')
  expect(screen.getByRole('button',{name:'Apply filters'})).toBeTruthy()
  expect(writeCalls()).toHaveLength(0)
})

it('requires valid thresholds, preserves zero DEG, and passes the applied scope to a fixed candidate plan', async () => {
  mockBulkResult()
  openResult()
  await screen.findByRole('table',{name:'Bulk 比较结果'})
  fireEvent.change(screen.getByLabelText('结果范围'),{target:{value:'down'}})
  fireEvent.change(screen.getByLabelText('q 值口径'),{target:{value:'q_global_family'}})
  fireEvent.change(screen.getByLabelText('q 阈值'),{target:{value:'-0.1'}})
  expect(screen.getByRole('button',{name:'应用筛选'})).toHaveProperty('disabled',true)
  fireEvent.change(screen.getByLabelText('q 阈值'),{target:{value:'0.025'}})
  fireEvent.change(screen.getByLabelText('最小绝对 log2FC'),{target:{value:'1.5'}})
  fireEvent.click(screen.getByRole('button',{name:'应用筛选'}))
  await screen.findByText('当前比较在此阈值和方向下有 0 个 DEG。')
  expect(writeCalls()).toHaveLength(0)
  fireEvent.click(screen.getByRole('button',{name:'保存当前筛选为候选计划'}))
  fireEvent.change(await screen.findByLabelText('候选展示 Top N'),{target:{value:'10'}})
  fireEvent.click(screen.getByRole('button',{name:'保存不可变草稿版本'}))
  await waitFor(() => expect(writeCalls()).toHaveLength(1))
  expect(JSON.parse(String(writeCalls()[0][1]?.body))).toMatchObject({
    kind:'candidate', decision:'draft',
    sources:[{source_kind:'bio_insight_result_version',source_id:'fixed',sha256:sha,role:'result'}],
    config:{result_source_ids:['fixed'],primary_result_source_id:'fixed',source_contrasts:{fixed:'forward'},steps:[],bulk_top_n:10,
      bulk_selection:{contrast_id:'forward',q_column:'q_global_family',q_threshold:0.025,minimum_absolute_effect:1.5,direction:'down'}},
  })
})

it('binds one expression feature and the chosen comparison without submitting a comparison run', async () => {
  mockBulkResult()
  openResult()
  const table = await screen.findByRole('table',{name:'Bulk 比较结果'})
  fireEvent.click(within(within(table).getByText('ENS0001').closest('tr')!).getByRole('button',{name:/绘制表达/}))
  await screen.findByRole('heading',{name:'单基因样本表达图'})
  fireEvent.click(screen.getByRole('button',{name:'保存不可变草稿版本'}))
  await waitFor(() => expect(writeCalls()).toHaveLength(1))
  expect(JSON.parse(String(writeCalls()[0][1]?.body))).toMatchObject({
    kind:'figure', decision:'draft',
    sources:[{source_kind:'bio_insight_result_version',source_id:'fixed',sha256:sha,role:'result'}],
    config:{result_source_id:'fixed',figure_type:'bulk_expression',feature_ids:['ENS0001'],
      bulk_selection:{contrast_id:'forward',q_column:'q_within_contrast',q_threshold:0.05,minimum_absolute_effect:1,direction:'both'}},
  })
})

it('renders with style and the reversed comparison while bounding the variable heatmap Top N', async () => {
  mockBulkResult()
  openResult()
  await screen.findByRole('table',{name:'Bulk 比较结果'})
  fireEvent.change(screen.getByLabelText('固定比较'),{target:{value:'reverse'}})
  await screen.findByText('当前比较在此阈值和方向下有 0 个 DEG。')
  fireEvent.change(screen.getByLabelText('Bulk 图型'),{target:{value:'bulk_variable_heatmap'}})
  fireEvent.click(screen.getByRole('button',{name:'按当前筛选绘图'}))
  const top = await screen.findByLabelText('高变基因展示 Top N')
  expect(top).toHaveProperty('value','100')
  fireEvent.change(top,{target:{value:'101'}})
  expect(screen.getByRole('button',{name:'保存不可变草稿版本'})).toHaveProperty('disabled',true)
  fireEvent.change(top,{target:{value:'10'}})
  fireEvent.click(screen.getByLabelText('行 z-score（仅图上展示）'))
  fireEvent.change(screen.getByLabelText('宽度 inches'),{target:{value:'6'}})
  fireEvent.change(screen.getByLabelText('配色（逐行 #RRGGBB）'),{target:{value:'#336699\n#cc5500'}})
  fireEvent.click(screen.getByRole('button',{name:'下一步：检查与运行'}))
  fireEvent.click(screen.getByRole('button',{name:'生成固定图件'}))
  await waitFor(() => expect(writeCalls()).toHaveLength(3))
  const [preview,plan,run] = writeCalls().map(([url,init])=>({url:String(url),body:JSON.parse(String(init?.body))}))
  expect(preview.body.kind).toBe('figure')
  expect(plan.body).toMatchObject({kind:'figure',decision:'confirmed',config:{
    result_source_id:'fixed',figure_type:'bulk_variable_heatmap',bulk_selection:{contrast_id:'reverse'},
    top_n:10,z_score:true,width_inches:6,palette:['#336699','#cc5500'],
  }})
  expect(run.url).toMatch(/\/bio-insight-runs$/)
  expect(run.body).toMatchObject({plan_version_id:'fixed-plan-version',expected_plan_revision:1,source_digest:sha})
})

it('shows the actual short candidate count and opens the same fixed source', async () => {
  const navigate = vi.fn()
  const candidate = {...comparison,id:'candidate-version',run_id:'candidate-run',kind:'candidate',
    summary:{candidate_count:3,top_n:20,displayed_count:3},
    methods:{bulk_selection:{contrast_id:'forward',numerator:'treated',denominator:'control',direction:'up',
      q_column:'original_method_adjustment',q_threshold:0.05,minimum_absolute_effect:1,source_result_version_id:'fixed'}},
    members:[{...comparison.members[0],key:'candidate_results'}, {...comparison.members[0],id:'top',key:'bulk_candidate_top'}],
  }
  vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('/tables/')
    ?{items:[],columns:['feature_id'],total:3,matched_total:3,page:1,page_size:50}
    :candidate))
  render(<InsightResults projectId="p1" resultId="candidate-version" active onResearch={vi.fn()} onNavigate={navigate}/>)
  await screen.findByText('实际展示 3 项，设定 Top N 为 20。')
  expect(screen.getByText('完整候选共 3 项。')).toBeTruthy()
  expect(screen.getByRole('combobox',{name:'候选结果表'})).toHaveProperty('value','bulk_candidate_top')
  fireEvent.click(screen.getByRole('button',{name:'打开此版本的固定来源'}))
  expect(navigate).toHaveBeenLastCalledWith({view:'bio-insight-result',fileId:'',resultVersionId:'fixed'})
})

it('shows published plot methods, its complete data download and a route to edit its fixed plan', async () => {
  const navigate = vi.fn()
  const figure = {...comparison,id:'figure-version',run_id:'figure-run',kind:'figure',inference_scope:'visualization',
    summary:{figure_type:'bulk_ma',requested_top_n:20,displayed_feature_count:1,displayed_count:42,numerator:'treated',denominator:'control'},
    methods:{axes:{x:'base_mean',y:'effect_value'},source_id:'fixed',input_member:'comparison_results',
      config:{bulk_selection:{contrast_id:'forward',direction:'both',q_column:'q_within_contrast',q_threshold:0.05,minimum_absolute_effect:1}}},
    members:[{...comparison.members[0],key:'plot_data',format:'json',download_url:'/full-plot.json'}],
  }
  vi.mocked(apiFetch).mockImplementation(async()=>Response.json(figure))
  render(<InsightResults projectId="p1" resultId="figure-version" active onResearch={vi.fn()} onNavigate={navigate}/>)
  await screen.findByRole('heading',{name:'Bulk MA 图'})
  expect(screen.getByText('实际标注 1 个基因，设定 Top N 为 20。')).toBeTruthy()
  expect(screen.getByText(/treated vs control \(forward\)/)).toBeTruthy()
  expect(screen.getByRole('link',{name:/plot_data · json/}).getAttribute('href')).toBe('/full-plot.json')
  fireEvent.click(screen.getByRole('button',{name:'打开固定计划修改样式'}))
  expect(navigate).toHaveBeenLastCalledWith({view:'bio-insight-plan',fileId:'',runId:'figure-run'})
})

it('creates a new figure plan version when editing the style of the published plan', async () => {
  mockBulkResult()
  const other = vi.mocked(apiFetch).getMockImplementation()!
  const frozen:Config = {
    ...defaultConfig('figure'),result_source_id:'fixed',figure_type:'bulk_ma',top_n:20,
    bulk_selection:{contrast_id:'forward',direction:'both',q_column:'q_within_contrast',q_threshold:0.05,minimum_absolute_effect:1},
  }
  delete frozen.contrast_id
  const sources = [{source_kind:'bio_insight_result_version',source_id:'fixed',sha256:sha,role:'result',locator:{kind:'object'}}]
  vi.mocked(apiFetch).mockImplementation(async (url, init) => String(url).endsWith('/figure-root/versions/first')
    ?Response.json({id:'first',plan_id:'figure-root',kind:'figure',name:'Previous MA',decision:'confirmed',revision:1,current_revision:1,config:frozen,
      design:{executable:true,blocking_reasons:[]},sources,source_digest:sha})
    :other(url,init))
  render(<BioInsightsWorkspace projectId="p1" active navigation={{view:'bio-insight-plan',fileId:'',planId:'figure-root',planVersionId:'first'}} onNavigate={vi.fn()}/>)
  await screen.findByRole('heading',{name:'Previous MA'})
  fireEvent.click(screen.getByRole('button',{name:'配置分析'}))
  fireEvent.change(screen.getByLabelText('宽度 inches'),{target:{value:'8'}})
  fireEvent.click(screen.getByRole('button',{name:'检查与运行'}))
  fireEvent.click(screen.getByRole('button',{name:'生成固定图件'}))
  await waitFor(()=>expect(writeCalls()).toHaveLength(3))
  const [url,init] = writeCalls()[1]
  expect(String(url)).toMatch(/\/bio-insight-plans\/figure-root\/versions$/)
  expect(JSON.parse(String(init?.body))).toMatchObject({
    expected_revision:1,kind:'figure',sources,
    config:{width_inches:8,result_source_id:'fixed',bulk_selection:frozen.bulk_selection,figure_type:'bulk_ma'},
  })
})

it('keeps historical bulk results on the complete table path', async () => {
  mockBulkResult({...comparison, methods:{config:{schema_version:2,mode:'bulk_counts',bulk_model:''}}})
  openResult()
  expect(await screen.findByRole('table',{name:'完整结果表'})).toBeTruthy()
  expect(vi.mocked(apiFetch).mock.calls.some(([url]) => String(url).includes('/bulk-comparisons'))).toBe(false)
})

const b03:TabularProcessed = {
  id:'processed1', source:{kind:'bio_processed_dataset_version',schema_version:2,project_id:'p1',processed_dataset_version_id:'processed1',
    analysis_run_id:'processed-run',recipe_version_id:'recipe1',raw_source:{...rawFixture, parser_version:'tabular_assay_import_v1'},
    manifest_sha256:sha,engine_version:'tabular_quantitative_v1.0.0',environment_digest:sha,assay:'bulk_rna_counts',observation_level:'sample'},
  manifest_sha256:sha, shape:{}, manifest:{}, steps:[{key:'pca',status:'completed',reason:null,params:{}}],
  tables:[{key:'pca_scores',label:'PCA',status:'completed',reason:null},{key:'pca_variance_ratio',label:'Variance',status:'completed',reason:null}],
  members:[], figures:[],
}

it('opens the fixed PCA replot from a validated deep link without selecting or reading a matrix', async () => {
  const navigate = vi.fn()
  vi.mocked(apiFetch).mockImplementation(async (url, init) => {
    if (init?.method === 'POST') return Response.json({id:'fixed-plan-version',plan_id:'fixed-plan',revision:1})
    if (String(url).endsWith('/bio-processed-datasets/processed1')) return Response.json(b03)
    return Response.json({items:[],columns:[],total:0})
  })
  const result = render(<TabularAnalysisResult projectId="p1" result={b03} tab="embedding" onNavigate={navigate}/>)
  fireEvent.click(screen.getByRole('button',{name:'重绘样本 PCA 得分'}))
  const hash = '#project=p1&section=analysis&view=bio-insight-result&processed=processed1&bulkPanel=pca_scores'
  const parsed = parseNavigation(hash)
  expect(parsed).not.toBeNull()
  expect(serializeNavigation(parsed!)).toBe(hash)
  expect(navigate).toHaveBeenCalledWith(parsed!.analysisNavigation)
  expect(parseNavigation(hash.replace('pca_scores','invalid'))).toBeNull()
  result.unmount()
  render(<BioInsightsWorkspace projectId="p1" active navigation={parsed!.analysisNavigation} onNavigate={vi.fn()}/>)
  await screen.findByRole('heading',{name:'样本 PCA 得分'})
  fireEvent.click(screen.getByRole('button',{name:'保存不可变草稿版本'}))
  await waitFor(() => expect(writeCalls()).toHaveLength(1))
  expect(JSON.parse(String(writeCalls()[0][1]?.body))).toMatchObject({
    kind:'figure', sources:[{source_kind:'bio_processed_dataset_version',source_id:'processed1',sha256:sha,role:'processed'}],
    config:{figure_type:'bulk_pca',bulk_panel:'pca_scores',result_source_id:'processed1'},
  })
  expect(JSON.parse(String(writeCalls()[0][1]?.body)).config).not.toHaveProperty('bulk_selection')
  expect(vi.mocked(apiFetch).mock.calls.some(([url]) => String(url).includes('matrix-preview'))).toBe(false)
})
