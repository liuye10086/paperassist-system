import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import BioNewAnalysis from './BioNewAnalysis'
import BioAnalysisSetup from './BioAnalysisSetup'
import BioAnalysisResult from './BioAnalysisResult'
import BioDatasetDetail from './BioDatasetDetail'
import BioFigureDetail from './BioFigureDetail'
import {rawFixture} from './spatialFixtures'
import type {TabularCapabilities,TabularProcessed,TabularSetup} from './tabularContracts'

vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{},captureApiSession:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear()})
it('keeps quantitative QC results in the pre-analysis flow',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(url)=>Response.json(String(url).includes('/tables/')?{key:'sample_qc',columns:[],items:[],total:0,page:1,page_size:50}:processed))
 render(<BioAnalysisResult projectId="p1" processedId="processed1" tab="qc" qualityMode onNavigate={()=>{}}/>)
 await screen.findByText('定量分析处理结果')
 expect(screen.queryByRole('button',{name:'差异与功能分析'})).toBeNull()
 expect(screen.queryByRole('button',{name:'整理研究发现与报告'})).toBeNull()
})
const raw={...rawFixture,parser_version:'tabular_assay_import_v1',source_file_ids:['matrix','samples']}
const capability:TabularCapabilities={raw_source:raw,available:true,blockers:[],limits:{memory_bytes:2147483648},recipes:['tabular_quantitative_v1'],design_gaps:[],assay:'metabolomics',scale:{kind:'log10',unit:'log10 intensity',upstream_method:'LC-HRMS, normalized and log10',upstream_transforms:['log10'],namespace:'HMDB',reference_version:'sacurine',species_taxon_id:9606,zero_meaning:'measured_zero'},default_params:{normalization:'already_normalized',transform:'none',scaling:'none',exclude_samples:[],exclude_features:[],pca_components:3,seed:0,output_language:'en'}}
const setup:TabularSetup={id:'setup1',name:'Measured metabolites',revision:1,raw_source:raw,current_recipe_version_id:'recipe1',current_recipe:{id:'recipe1',setup_id:'setup1',version:1,revision:1,raw_source:raw,observation_map_version_id:null,design_version_id:null,recipe_code:'tabular_quantitative_v1',params:capability.default_params}}
const processed:TabularProcessed={id:'processed1',source:{kind:'bio_processed_dataset_version',schema_version:2,project_id:'p1',processed_dataset_version_id:'processed1',analysis_run_id:'run1',raw_source:raw,recipe_version_id:'recipe1',setup_id:'setup1',manifest_sha256:'a'.repeat(64),engine_version:'tabular_quantitative_v1.0.0',environment_digest:'b'.repeat(64),assay:'metabolomics',observation_level:'sample'},manifest_sha256:'a'.repeat(64),shape:{observations:8,features:3},steps:[{key:'pca',status:'not_computable',reason:'insufficient_complete_features',params:{}}],tables:[{key:'sample_qc',label:'样本QC',status:'completed',reason:null}],members:[],figures:[],manifest:{assay:'metabolomics',scale:capability.scale,summary:{raw_observations:8,retained_observations:8,excluded_observations:0,raw_features:3,retained_features:3,excluded_features:0}}}

it('creates the tabular recipe from the fixed raw version without a spatial mapping',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(_url,init)=>Response.json(init?.method==='POST'?setup.current_recipe:capability))
 const nav=vi.fn();render(<BioNewAnalysis projectId="p1" source={raw} onNavigate={nav}/>)
 fireEvent.click(await screen.findByText('新建定量分析配置'))
 await waitFor(()=>expect(nav).toHaveBeenCalledWith({view:'bio-analysis-setup',fileId:'',setupId:'setup1'}))
 const body=JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body))
 expect(body).toMatchObject({recipe_code:'tabular_quantitative_v1',raw_source:raw,observation_map_version_id:null,params:capability.default_params})
 expect(body.params).not.toHaveProperty('in_tissue_only')
})
it('preserves a frozen log scale while allowing final start to save a changed recipe',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>Response.json(init?.method==='POST'?{...setup.current_recipe,version:2}:String(url).includes('/bio-analysis-capabilities')?capability:setup))
 render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>)
 await screen.findByText('定量分析配置')
 const transform=await screen.findByLabelText('数值变换') as HTMLSelectElement
 await waitFor(()=>expect(transform.disabled).toBe(true))
 expect(transform.value).toBe('none')
 expect(Array.from(transform.options).map(option=>option.value)).not.toContain('log1p')
 fireEvent.change(screen.getByLabelText('排除样本 ID（每行一个）'),{target:{value:'sample-outlier'}})
 expect((screen.getByText('开始分析') as HTMLButtonElement).disabled).toBe(false)
 fireEvent.click(screen.getByText('保存新配方版本'))
 await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(c=>c[1]?.method==='POST')).toBe(true))
 const body=JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body))
 expect(body).toMatchObject({recipe_code:'tabular_quantitative_v1',expected_revision:1,params:{exclude_samples:['sample-outlier'],transform:'none'}})
 expect(screen.queryByText('spot 或组织片段不代表独立供体；marker 仅为探索性区域或 cluster 关联。')).toBeNull()
})
it('offers an explicit counts-only ln(1+x) display transform and saves its fixed offset',async()=>{
 const counts={...capability,assay:'bulk_rna_counts',scale:{...capability.scale,kind:'raw_counts'},default_params:{...capability.default_params,normalization:'display_library_size',log1p_offset:1}}
 const initial={...setup,current_recipe:{...setup.current_recipe,params:counts.default_params}}
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>Response.json(init?.method==='POST'?{...initial.current_recipe,id:'recipe2'}:String(url).includes('/bio-analysis-capabilities')?counts:initial))
 render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>);await screen.findByRole('option',{name:'log1p'})
 fireEvent.change(screen.getByLabelText('数值变换'),{target:{value:'log1p'}});expect(screen.getByText(/显式 counts 展示变换 ln/)).toBeTruthy()
 fireEvent.click(screen.getByText('保存新配方版本'));await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(c=>c[1]?.method==='POST')).toBe(true))
 const body=JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body));expect(body.params).toMatchObject({transform:'log1p',log1p_offset:1,normalization:'display_library_size'})
})
it('shows sample QC, unavailable PCA and the actual quantitative layers without spatial controls',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(url)=>Response.json(String(url).includes('/tables/')?{key:'sample_qc',columns:['sample_id','missing_count'],items:[{sample_id:'S1',missing_count:1}],total:1,page:1,page_size:50}:processed))
 render(<BioAnalysisResult projectId="p1" processedId="processed1" tab="qc" onNavigate={()=>{}}/>)
 await screen.findByText('定量分析处理结果')
 expect(await screen.findByText('S1')).toBeTruthy()
 expect(screen.getByText('insufficient_complete_features')).toBeTruthy()
 const options=Array.from((screen.getByLabelText('有界矩阵数据层') as HTMLSelectElement).options).map(o=>o.value)
 expect(options).toEqual(['analysis','display'])
 expect(screen.queryByText('空间与人工注释')).toBeNull()
 expect(screen.queryByText('探索性 marker')).toBeNull()
})

it('shows B03 QC metrics, explicit normalized/VST layers, heatmap outputs and manual outlier review',async()=>{
 const b03={...processed,source:{...processed.source,recipe_version_id:'recipe1',setup_id:'setup1'},manifest:{...processed.manifest,layers:{raw:'raw_counts',filtered:'filtered_counts',normalized:'normalized_counts',vst:'vst'},
  summary:{raw_observations:4,retained_observations:4,excluded_observations:0,raw_features:3,retained_features:3,excluded_features:0,
   qc_metrics:{total_counts:{S1:100,S2:200},detected_features:{S1:2,S2:3},zero_fraction:{S1:0.2,S2:0.1},expression_distribution:{quantiles:{p50:2,p90:8}}},
   outlier_advisories:[{sample_id:'S2',reasons:['library_size_low']}],
   layers:{raw:'raw_counts',filtered:'filtered_counts',normalized:'normalized_counts',vst:'vst'},analysis_object:{format:'paperassist_tabular_object_v1',round_trip:'verified'}}},
  tables:[{key:'sample_qc',label:'样本 QC',status:'completed',reason:null}],
  figures:[{id:'corr',config:{kind:'sample_correlation_heatmap',title:'样本相关性热图'},members:[]},{id:'dist',config:{kind:'expression_distribution',title:'表达分布'},members:[]}]} as TabularProcessed
 vi.mocked(apiFetch).mockImplementation(async(url)=>Response.json(String(url).includes('/tables/')?{key:'sample_qc',columns:[],items:[],total:0,page:1,page_size:50}:b03))
 const nav=vi.fn();render(<BioAnalysisResult projectId="p1" processedId="processed1" tab="qc" onNavigate={nav}/>)
 await screen.findByText('定量分析处理结果')
 expect(screen.getAllByText('总计数').length).toBe(2)
 expect(screen.getAllByText('检测特征数').length).toBe(2)
 expect(screen.getAllByText('零比例').length).toBe(2)
 expect(screen.getAllByText('表达分布').length).toBeGreaterThanOrEqual(2)
 expect(screen.getByText('VST')).toBeTruthy()
 expect(screen.getByText('样本相关性热图')).toBeTruthy()
 expect(screen.getByText('疑似异常样本')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'进入人工排除'}))
 expect(nav).toHaveBeenCalledWith({view:'bio-analysis-setup',fileId:'',setupId:'setup1'})
})
it('opens a nonspatial raw version without requesting coordinates or calling its values raw counts',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(url)=>Response.json(String(url).includes('/bio-analysis-capabilities')?capability:{id:'v1',dataset_id:'d1',version:1,manifest_sha256:'a'.repeat(64),shape:{features:3,observations:8,stored_entries:24},checks:[],members:[],source:raw,summary:{assay:'metabolomics',scale:capability.scale}}))
 render(<BioDatasetDetail projectId="p1" datasetId="d1" versionId="v1" onNavigate={()=>{}}/>)
 await screen.findByText('新建定量分析配置')
 expect(screen.queryByText(/原始 counts 固定保存/)).toBeNull()
 expect(vi.mocked(apiFetch).mock.calls.some(call=>String(call[0]).includes('coordinate'))).toBe(false)
})
it('opens a fixed quantitative figure deep link with its source and downloads',async()=>{
 const figure={id:'figure-tabular',root_id:'figure-root',version:1,processed_source:processed.source,annotation_version_id:null,config:{kind:'qc_missing',title:'Sample missing values',output_language:'en'},manifest_sha256:'c'.repeat(64),members:[]}
 vi.mocked(apiFetch).mockImplementation(async(url)=>Response.json(String(url).includes('/bio-figures/')?figure:processed))
 const nav=vi.fn();render(<BioFigureDetail projectId="p1" figureId="figure-tabular" onNavigate={nav}/>)
 await screen.findByText('此图来自固定定量处理版本。')
 fireEvent.click(screen.getByText('查看来源处理版本与方法'))
 expect(nav).toHaveBeenCalledWith({view:'bio-result',fileId:'',processedId:'processed1',tab:'methods'})
 expect(screen.queryByText('空间基因表达')).toBeNull()
 expect(vi.mocked(apiFetch).mock.calls.filter(call=>call[1]?.method==='POST')).toHaveLength(0)
})
it('resolves a restored recipe request from another setup by navigating to its original setup',async()=>{
 sessionStorage.setItem('paperassist.bio-request.v1:owner1:p1:recipe','1a234567-1234-1234-1234-123456789abc')
 vi.mocked(apiFetch).mockImplementation(async(url)=>Response.json(String(url).includes('/bio-requests/')?{kind:'recipe',id:'recipe-other',root_id:'setup-other',request_digest:'e'.repeat(64)}:String(url).includes('capabilities')?capability:setup))
 const nav=vi.fn();render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={nav}/>)
 await screen.findByText('定量分析配置');fireEvent.click(screen.getByText('按原请求身份核对'))
 await waitFor(()=>expect(nav).toHaveBeenCalledWith({view:'bio-analysis-setup',fileId:'',setupId:'setup-other'}))
 expect(vi.mocked(apiFetch).mock.calls.filter(call=>call[1]?.method==='POST')).toHaveLength(0)
})
it('allows explicit recovery when a concurrent recipe advances past the saved version',async()=>{
 let saved=false
 const newer={...setup,revision:3,current_recipe_version_id:'recipe3',current_recipe:{...setup.current_recipe,id:'recipe3',version:3,revision:3,params:{...capability.default_params,pca_components:4}}}
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method==='POST'){saved=true;return Response.json(String(url).endsWith('/bio-analysis-runs')?{id:'run3'}:{...setup.current_recipe,id:'recipe2',version:2,revision:2})}
  return Response.json(String(url).includes('capabilities')?capability:saved?newer:setup)
 })
 render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>)
 await screen.findByText('定量分析配置');fireEvent.change(screen.getByLabelText('PCA 成分数'),{target:{value:'5'}});fireEvent.click(screen.getByText('保存新配方版本'))
 const recover=await screen.findByText('核对并采用当前配方版本')
 expect((screen.getByText('开始分析') as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(recover);await waitFor(()=>expect((screen.getByText('开始分析') as HTMLButtonElement).disabled).toBe(false))
 expect((screen.getByLabelText('PCA 成分数') as HTMLInputElement).value).toBe('4')
 fireEvent.click(screen.getByText('开始分析'))
 await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(call=>String(call[0]).endsWith('/bio-analysis-runs')&&call[1]?.method==='POST')).toBe(true))
 expect(JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(call=>String(call[0]).endsWith('/bio-analysis-runs'))?.[1]?.body))).toMatchObject({recipe_version_id:'recipe3',expected_setup_revision:3})
})
it('navigates from a quantitative result figure to its fixed detail page',async()=>{
 const result={...processed,figures:[{id:'qc-figure',config:{kind:'qc_missing',title:'Missing values'},members:[]}]}
 vi.mocked(apiFetch).mockImplementation(async(url)=>Response.json(String(url).includes('/tables/')?{key:'sample_qc',columns:[],items:[],total:0,page:1,page_size:50}:result))
 const nav=vi.fn();render(<BioAnalysisResult projectId="p1" processedId="processed1" tab="qc" onNavigate={nav}/>)
 fireEvent.click(await screen.findByText('打开固定单图版本'))
 expect(nav).toHaveBeenCalledWith({view:'bio-figure',fileId:'',figureId:'qc-figure'})
})
it('preserves quantitative recipe drafts across modules and keeps save actions outside the scroll area',async()=>{
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('/research-designs')?{items:[],total:0}:String(url).includes('capabilities')?capability:setup))
 render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>)
 const input=await screen.findByLabelText('PCA 成分数')
 fireEvent.change(input,{target:{value:'7'}})
 fireEvent.click(screen.getByRole('button',{name:'能力与来源'}))
 expect(screen.queryByRole('region',{name:'分析参数'})).toBeNull()
 expect(screen.getByRole('region',{name:'能力与来源'})).toBeTruthy()
 const save=screen.getByRole('button',{name:'保存新配方版本'})
 expect(save.closest('.module-view-content')).toBeNull()
 expect((save as HTMLButtonElement).disabled).toBe(false)
 expect((screen.getByRole('button',{name:'开始分析'}) as HTMLButtonElement).disabled).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'分析参数'}))
 expect((screen.getByLabelText('PCA 成分数') as HTMLInputElement).value).toBe('7')
 expect(document.querySelector('details,summary')).toBeNull()
})
it('selects a readable experimental design version and sends its exact internal identity',async()=>{
 const designs=[{id:'design-internal-uuid',version:3,operation:'confirm',created_at:'2026-11-05T00:00:00Z'}]
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>Response.json(init?.method==='POST'?setup.current_recipe:String(url).includes('/research-designs')?{items:designs,total:1}:String(url).includes('capabilities')?capability:setup))
 render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>)
 fireEvent.click(await screen.findByRole('button',{name:'实验设计'}))
 const design=await screen.findByLabelText('关联实验设计')
 await screen.findByRole('option',{name:'版本 3 · 已确认'})
 expect(screen.queryByText('design-internal-uuid')).toBeNull()
 fireEvent.change(design,{target:{value:'design-internal-uuid'}})
 fireEvent.click(screen.getByRole('button',{name:'保存新配方版本'}))
 await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(([,init])=>init?.method==='POST')).toBe(true))
 const call=vi.mocked(apiFetch).mock.calls.find(([,init])=>init?.method==='POST')
 expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({design_version_id:'design-internal-uuid',expected_revision:1,raw_source:raw})
})
