import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import {afterEach, expect, it, vi} from 'vitest'
import {apiFetch} from '../../shared/api/client'
import BioInsightsWorkspace from './BioInsightsWorkspace'
import {ResourceForm} from './InsightResources'
import {defaultConfig, defaultResource} from './state'
import type {ResourceBody,Result} from './contracts'
import {useState} from 'react'

vi.mock('../../shared/api/client', () => ({
  apiFetch: vi.fn(), getApiUserId: () => 'owner', onApiSessionChanged: () => () => {},
  captureApiSession: () => () => {},
}))
afterEach(() => {cleanup();sessionStorage.clear()})

const sha = 'a'.repeat(64)
const sourceIdentity = {species_taxon_id:null, namespace:'Ensembl gene ID', reference_version:'airway package release data'}
const selectedContrast = {contrast_id:'reverse', numerator:'untreated', denominator:'treated', total:3, tested:3,
  excluded:0, not_computable:0, missing_metric:0, deg:0, up:0, down:0}
const member = (key:string,format='tsv') => ({id:key,key,format,role:'table',sha256:sha,size_bytes:16,download_url:`/${key}.${format}`})
const comparison:Result = {
  id:'fixed-b04', run_id:'comparison-run', kind:'comparison', provenance:'system_computed', inference_scope:'sample_inference',
  plan_version_id:'reviewed-plan',task_id:'comparison-task',summary:{}, manifest:{}, manifest_sha256:sha,
  task:{id:'comparison-task',status:'succeeded'}, members:[member('comparison_results')],
  methods:{...sourceIdentity,config:{...sourceIdentity,schema_version:2,mode:'bulk_counts',bulk_model:'shared_wald_v1'}},
}
const frozen = (source_id:string,role:string) => ({source_id,role,sha256:sha,locator:{kind:'object'},
  source_kind:role==='result'?'bio_insight_result_version':'bio_resource_version'})
const resources = [
  {source_id:'go-local',kind:'gene_sets',title:'Local GO',release:'go-r1',version:2,sha256:sha,species_taxon_id:9606},
  {source_id:'mapping-local',kind:'id_mapping',title:'Local ID map',release:'id-r1',version:1,sha256:sha},
  {source_id:'not-a-gene-set',kind:'sequence',title:'Unrelated sequence',release:'seq-r1',version:1,sha256:sha},
  {source_id:'less-common',kind:'gene_sets',title:'Project-specific set',release:'local-r1',version:1,sha256:sha,species_taxon_id:12345},
]
const compatibility = {
  source:{...sourceIdentity,species_taxon_id:9606,taxon_origin:'explicit_enrichment_declaration'},
  resources:[{resource_id:'go-local',species_taxon_id:9606,namespace:'UniProtKB',release:'go-r1',
    reference_version:null,reference_status:'resource_reference_not_declared',mapping_source_id:'mapping-local'}],
  note:'An undeclared reference is visible in the audit.',
}
const design = {executable:true,blocking_reasons:[],enrichment_compatibility:compatibility}
const table = (items:Record<string,unknown>[],columns:string[]) => ({items,columns,total:items.length,matched_total:items.length,page:1,page_size:50,sha256:sha})
const term = {row_key:'term-stable-key',term_id:'GO:00001',term_name:'Local term',es:-0.3,nes:-1.2,fdr_q_value:0.21,leading_edge:'["G1"]'}
const gsea:Result = {
  ...comparison,id:'fixed-gsea',run_id:'enrichment-run',kind:'gsea_prerank',inference_scope:'derived',
  summary:{enrichment_status:'no_significant_terms',significant_terms:0,not_applicable_reason:null},
  methods:{config:{...defaultConfig('gsea_prerank'),bulk_enrichment:{},result_source_id:comparison.id,contrast_id:'reverse'},
    bulk_enrichment:{source_reference:compatibility.source,resource_references:{'go-local':compatibility.resources[0]},
      coverage:[{result_source_id:comparison.id,contrast_id:'reverse',resource_id:'joint',not_applicable_reason:null,
        ranking:{original_count:10,unmapped_count:2,ambiguous_count:1,mapped_count:7,effective_count:6}}]}},
  members:[member('mapping_rows'),member('mapping_exclusions'),member('enrichment_results'),member('gsea_ranking'),member('gsea_curves','json')],
}
const postCalls = () => vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')
const requestBody = (index:number) => JSON.parse(String(postCalls()[index][1]?.body))

function mockRequests({knownTaxon=false,result=gsea}={}) {
  vi.mocked(apiFetch).mockImplementation(async (url,init) => {
    const path = String(url)
    if (init?.method==='POST') {
      const body = JSON.parse(String(init.body))
      if (path.endsWith('/preview')) return Response.json(design)
      if (path.endsWith('/bio-insight-runs')) return Response.json({id:'new-run',kind:'figure',task:{status:'queued'}})
      return Response.json({...body,id:'saved-version',plan_id:'saved-plan',revision:1,current_revision:1,design,source_digest:sha})
    }
    if (path.includes('/sources?source_kind=bio_resource_version')) return Response.json(table(resources,['title']))
    if (path.includes('/bulk-comparisons')) return Response.json({
      ...table([],['feature_id']),contrast_id:'reverse',contrasts:[selectedContrast],feature_matches:[],total:3,
    })
    if (path.endsWith('/fixed-b04')) return Response.json(knownTaxon?{...comparison,methods:{...comparison.methods,species_taxon_id:9606}}:comparison)
    if (path.endsWith('/fixed-gsea')) return Response.json(result)
    if (path.includes('/tables/enrichment_results')) return Response.json(table([term],Object.keys(term)))
    return Response.json(table([],[]))
  })
}

function openResult(resultVersionId=comparison.id) {
  return render(<BioInsightsWorkspace projectId="p1" active navigation={{view:'bio-insight-result',fileId:'',resultVersionId}} onNavigate={vi.fn()}/>)
}

async function addResource(id:string,name:RegExp) {
  await screen.findByRole('option',{name})
  fireEvent.change(screen.getByRole('combobox',{name:'选择固定来源版本'}),{target:{value:id}})
  fireEvent.click(screen.getByRole('button',{name:'加入固定来源'}))
}

it('previews ORA from the fixed comparison with the applied native q rule and explicit taxon evidence',async () => {
  mockRequests()
  openResult()
  await screen.findByRole('table',{name:'Bulk 比较结果'})
  fireEvent.change(screen.getByLabelText('结果范围'),{target:{value:'down'}})
  fireEvent.change(screen.getByLabelText('q 值口径'),{target:{value:'original_method_adjustment'}})
  fireEvent.change(screen.getByLabelText('q 阈值'),{target:{value:'0.1'}})
  fireEvent.change(screen.getByLabelText('最小绝对 log2FC'),{target:{value:'1.5'}})
  fireEvent.click(screen.getByRole('button',{name:'应用筛选'}))
  fireEvent.click(await screen.findByRole('button',{name:'用当前筛选配置 ORA'}))
  await screen.findByRole('heading',{name:'固定 Bulk ORA'})
  const taxon = await screen.findByRole('combobox',{name:'补充来源物种 taxonomy ID'})
  expect(taxon).toHaveProperty('value','')
  expect(within(taxon).getByRole('option',{name:'人类（NCBI Taxonomy 9606）'})).toBeTruthy()
  expect(within(taxon).getByRole('option',{name:'小鼠（NCBI Taxonomy 10090）'})).toBeTruthy()
  expect(screen.getByText('airway package release data')).toBeTruthy()
  await addResource('go-local',/Local GO · go-r1 · v2/)
  expect(screen.queryByRole('option',{name:/Unrelated sequence/})).toBeNull()
  expect(screen.getByRole('button',{name:'下一步：检查与运行'})).toHaveProperty('disabled',true)
  fireEvent.change(taxon,{target:{value:'9606'}})
  fireEvent.change(screen.getByRole('textbox',{name:'物种依据'}),{target:{value:'  '}})
  expect(screen.getByRole('button',{name:'下一步：检查与运行'})).toHaveProperty('disabled',true)
  fireEvent.change(screen.getByRole('textbox',{name:'物种依据'}),{target:{value:'airway package sample metadata'}})
  fireEvent.change(screen.getByRole('combobox',{name:'来源使用角色'}),{target:{value:'id_mapping'}})
  await addResource('mapping-local',/Local ID map · id-r1 · v1/)
  fireEvent.click(screen.getByRole('button',{name:'下一步：检查与运行'}))
  expect(screen.getByRole('button',{name:'运行固定富集'})).toHaveProperty('disabled',true)
  fireEvent.click(screen.getByRole('button',{name:'预检当前设计'}))
  const compatibilityTable = await screen.findByRole('table',{name:'固定资源兼容性'})
  expect(within(compatibilityTable).getByText('go-r1')).toBeTruthy()
  expect(within(compatibilityTable).getByText('UniProtKB')).toBeTruthy()
  expect(postCalls()).toHaveLength(1)
  expect(requestBody(0)).toMatchObject({kind:'ora',decision:'draft',sources:[frozen('fixed-b04','result'),frozen('go-local','gene_sets'),frozen('mapping-local','id_mapping')],
    config:{result_source_ids:['fixed-b04'],contrast_ids:['reverse'],resource_source_ids:['go-local'],mapping_source_ids:['mapping-local'],
      direction:'down',q_column:'original_method_adjustment',q_threshold:0.1,minimum_absolute_effect:1.5,
      bulk_enrichment:{source_taxon_id:9606,taxon_evidence:'airway package sample metadata'}}})
  expect(requestBody(0).config).not.toHaveProperty('foreground_member_key')
})

it('uses the complete Wald ranking even with zero DEG and un-applied filter edits',async () => {
  mockRequests({knownTaxon:true})
  openResult()
  await screen.findByText('当前比较在此阈值和方向下有 0 个 DEG。')
  fireEvent.change(screen.getByLabelText('最小绝对 log2FC'),{target:{value:'12'}})
  expect(screen.getByRole('button',{name:'用当前筛选配置 ORA'})).toHaveProperty('disabled',true)
  fireEvent.click(screen.getByRole('button',{name:'用完整 Wald 排名配置 GSEA'}))
  await screen.findByRole('heading',{name:'固定 Bulk GSEA'})
  await addResource('go-local',/Local GO/)
  expect(screen.queryByRole('combobox',{name:'补充来源物种 taxonomy ID'})).toBeNull()
  expect(screen.queryByRole('textbox',{name:'完整有符号排名列'})).toBeNull()
  fireEvent.click(screen.getByRole('button',{name:'保存不可变草稿版本'}))
  await waitFor(()=>expect(postCalls()).toHaveLength(1))
  const config = requestBody(0).config
  expect(config).toMatchObject({kind:'gsea_prerank',result_source_id:'fixed-b04',contrast_id:'reverse',
    ranking_column:'wald_statistic',complete_ranking:true,signed_ranking:true,bulk_enrichment:{}})
  for (const key of ['q_column','q_threshold','direction','minimum_absolute_effect','top_n','foreground_member_key','bulk_selection']) {
    expect(config).not.toHaveProperty(key)
  }
})

it('reopens a saved B06 plan with its fixed comparison and saved compatibility check',async () => {
  mockRequests()
  const fallback = vi.mocked(apiFetch).getMockImplementation()!
  vi.mocked(apiFetch).mockImplementation(async (url,init) => String(url).endsWith('/fixed-plan/versions/frozen-version')
    ?Response.json({id:'frozen-version',plan_id:'fixed-plan',name:'Saved ORA',kind:'ora',decision:'confirmed',revision:1,current_revision:1,
      sources:[frozen('fixed-b04','result'),frozen('go-local','gene_sets')],source_digest:sha,design,
      config:{...defaultConfig('ora'),result_source_ids:['fixed-b04'],contrast_ids:['reverse'],resource_source_ids:['go-local'],
        bulk_enrichment:{source_taxon_id:9606,taxon_evidence:'airway package sample metadata'}}})
    :fallback(url,init))
  render(<BioInsightsWorkspace projectId="p1" active navigation={{view:'bio-insight-plan',fileId:'',planId:'fixed-plan',planVersionId:'frozen-version'}} onNavigate={vi.fn()}/>)
  await screen.findByRole('heading',{name:'Saved ORA'})
  expect(screen.getByRole('table',{name:'固定资源兼容性'})).toBeTruthy()
  fireEvent.click(screen.getByRole('button',{name:'配置分析'}))
  const parameters = screen.getByRole('heading',{name:'固定 Bulk ORA'}).closest('section')!
  expect(within(parameters).getByText('reverse')).toBeTruthy()
  expect(screen.queryByRole('textbox',{name:'比较 ID（逐行）'})).toBeNull()
  expect(postCalls()).toHaveLength(0)
})

it('shows a no-significance GSEA outcome, mapping audit and a stable saved-curve plan',async () => {
  mockRequests()
  openResult(gsea.id)
  await screen.findByText('无显著富集条目')
  expect(screen.getByText('GSEA FDR')).toBeTruthy()
  const mapping = screen.getByRole('table',{name:'富集 ID 映射覆盖'})
  expect(within(mapping).getByText('2')).toBeTruthy()
  expect(screen.getByRole('link',{name:/mapping_exclusions · tsv/})).toBeTruthy()
  expect(screen.getByRole('link',{name:/gsea_ranking · tsv/})).toBeTruthy()
  expect(screen.getByRole('link',{name:/gsea_curves · json/})).toBeTruthy()
  expect(screen.getByRole('button',{name:'绘制富集点图'})).toBeTruthy()
  expect(screen.getByRole('button',{name:'绘制富集条图'})).toBeTruthy()
  fireEvent.click(await screen.findByRole('button',{name:/绘制已保存 GSEA 曲线.*GO:00001/}))
  await screen.findByRole('heading',{name:'固定 GSEA 曲线'})
  fireEvent.click(screen.getByRole('button',{name:'保存不可变草稿版本'}))
  await waitFor(()=>expect(postCalls()).toHaveLength(1))
  expect(requestBody(0)).toMatchObject({kind:'figure',decision:'draft',sources:[frozen(gsea.id,'result')],config:{
    figure_type:'gsea',result_source_id:gsea.id,contrast_id:'reverse',term_row_key:'term-stable-key',bulk_enrichment_render:true}})
})

it('shows an empty ORA foreground as not applicable and labels its term adjustment as BH',async () => {
  mockRequests({result:{...gsea,kind:'ora',summary:{enrichment_status:'not_applicable',not_applicable_reason:'empty_foreground',significant_terms:0}}})
  openResult(gsea.id)
  await screen.findByText('富集不适用')
  expect(screen.getByText('固定筛选得到空前景。')).toBeTruthy()
  expect(screen.getByText('ORA BH q')).toBeTruthy()
  expect(screen.queryByText('无显著富集条目')).toBeNull()
})

it('generates an enrichment bar figure from the published result and the saved adjustment order',async () => {
  mockRequests()
  openResult(gsea.id)
  fireEvent.click(await screen.findByRole('button',{name:'绘制富集条图'}))
  await screen.findByRole('heading',{name:'固定富集图'})
  expect(screen.getByRole('combobox',{name:'富集图样式'})).toHaveProperty('value','bar')
  fireEvent.click(screen.getByRole('button',{name:'下一步：检查与运行'}))
  fireEvent.click(screen.getByRole('button',{name:'生成固定图件'}))
  await waitFor(()=>expect(postCalls()).toHaveLength(3))
  for (const index of [0,1]) expect(requestBody(index)).toMatchObject({kind:'figure',sources:[frozen(gsea.id,'result')],config:{
    figure_type:'enrichment',result_source_id:gsea.id,contrast_id:'reverse',enrichment_style:'bar',
    enrichment_order:'adjusted_metric_term_id',bulk_enrichment_render:true,
  }})
  expect(requestBody(2)).toMatchObject({plan_version_id:'saved-version',expected_plan_revision:1})
})

it('offers ORA plotting only for contrasts with computed enrichment terms',async () => {
  const scope = {result_source_id:comparison.id,resource_id:'go-local',background:{original_count:10},foreground:{original_count:0}}
  mockRequests({result:{...gsea,kind:'ora',summary:{enrichment_status:'completed',significant_terms:2},methods:{bulk_enrichment:{
    source_reference:compatibility.source,resource_references:{'go-local':compatibility.resources[0]},coverage:[
      {...scope,contrast_id:'empty-contrast',eligible_term_count:0,not_applicable_reason:'empty_foreground'},
      {...scope,contrast_id:'forward',eligible_term_count:2,not_applicable_reason:null},
      {...scope,contrast_id:'reverse',eligible_term_count:1,not_applicable_reason:null},
    ],
  }}}})
  openResult(gsea.id)
  const plots = await screen.findByRole('combobox',{name:'绘图固定比较'})
  expect(plots).toHaveProperty('value','forward')
  expect(within(plots).getAllByRole('option').map(option=>option.textContent)).toEqual(['forward','reverse'])
  expect(within(screen.getByRole('table',{name:'富集 ID 映射覆盖'})).getAllByText('empty-contrast')).toHaveLength(2)
  fireEvent.click(screen.getByRole('button',{name:'绘制富集点图'}))
  await screen.findByRole('heading',{name:'固定富集图'})
  fireEvent.click(screen.getByRole('button',{name:'保存不可变草稿版本'}))
  await waitFor(()=>expect(postCalls()).toHaveLength(1))
  expect(requestBody(0)).toMatchObject({kind:'figure',config:{result_source_id:gsea.id,contrast_id:'forward',enrichment_style:'dot'}})
})

it('requires an explicit species choice for new offline gene-set resources and omits offline metadata for other kinds',async () => {
  mockRequests()
  let last:ResourceBody = defaultResource()
  function Harness() {
    const [value,setValue] = useState(last)
    return <ResourceForm projectId="p1" value={value} onChange={next=>{last=next;setValue(next)}}/>
  }
  render(<Harness/>)
  fireEvent.click(screen.getByRole('checkbox',{name:'用于离线 Bulk 富集'}))
  const taxon = screen.getByRole('combobox',{name:'资源物种 taxonomy ID'})
  expect(taxon).toHaveProperty('value','')
  expect(await within(taxon).findByRole('option',{name:/已登记物种.*12345/})).toBeTruthy()
  fireEvent.change(taxon,{target:{value:'10116'}})
  fireEvent.change(screen.getByRole('textbox',{name:'资源参考版本（可选）'}),{target:{value:'GRCh38'}})
  expect(last).toMatchObject({offline_enrichment:true,reference_version:'GRCh38',species_taxon_id:10116})
  fireEvent.change(screen.getByRole('combobox',{name:'资源类别'}),{target:{value:'sequence'}})
  expect(JSON.parse(JSON.stringify(last))).not.toHaveProperty('offline_enrichment')
  expect(JSON.parse(JSON.stringify(last))).not.toHaveProperty('reference_version')
})
