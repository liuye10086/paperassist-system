import {cleanup,fireEvent,render,screen,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import AnalysisGuide from './AnalysisGuide'
import {entryMethods} from './analysisEntryState'
import type {Version} from '../research-intake/contracts'

afterEach(()=>{cleanup();sessionStorage.clear()})
const version:Version={id:'r1',version:1,operation:'save',created_at:'',sha256:'x',content:{schema_version:1,scope_items:['multiomics','candidates'].map(kind=>({id:'questionnaire.analysis.'+kind,title:kind,delivery_kind:'analysis',status:'planned'}))}}
const props={version,files:[],loading:false,error:'',filesLoading:false,filesError:'',imports:[],importsUnknown:false,importsError:'',onRefresh:vi.fn(),onReloadFiles:vi.fn(),onNavigate:vi.fn(),onFile:vi.fn()}
it('focuses one saved task and separates existing analyses without new computation',()=>{
 render(<AnalysisGuide {...props}/>);
 expect(screen.getByRole('article',{name:'multiomics'})).toBeTruthy()
 expect(screen.queryByRole('article',{name:'candidates'})).toBeNull()
 expect(screen.queryByRole('button',{name:/表格数据与统计/})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'candidates'}))
 expect(screen.getByRole('article',{name:'candidates'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'已有分析'}))
 expect(screen.queryByRole('article',{name:'candidates'})).toBeNull()
 expect(screen.getByRole('button',{name:/统计结果/})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'本次任务'}))
 expect(screen.getByRole('article',{name:'candidates'})).toBeTruthy()
 expect(props.onNavigate).not.toHaveBeenCalled()
})
it('starts new table comparisons and validation with configuration rather than skipping to results',()=>{
 for(const kind of ['differential','validation'])expect(entryMethods(kind).find(m=>m.id==='table')?.navigation.view).toBe('setup')
})
it('asks for an analysis method before deciding that source material is missing',()=>{
 const differential={...version,content:{...version.content,scope_items:[{id:'questionnaire.analysis.differential',title:'差异分析',delivery_kind:'analysis' as const,status:'planned' as const}]}}
 render(<AnalysisGuide {...props} version={differential} onRequirements={vi.fn()}/>);
 expect(screen.getByText('需选择分析方式')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'补充材料关联'})).toBeNull()
 expect(screen.getByRole('button',{name:'进入配置'})).toHaveProperty('disabled',true)
 fireEvent.change(screen.getByLabelText('分析方式'),{target:{value:'table'}})
 expect(screen.getByRole('button',{name:'补充材料关联'})).toHaveProperty('disabled',false)
})

it('keeps bioinformatics history reachable independently of the current task',()=>{
 const navigate=vi.fn();render(<AnalysisGuide {...props} onNavigate={navigate}/>);
 fireEvent.click(screen.getByRole('button',{name:'已有分析'}))
 fireEvent.click(screen.getByRole('button',{name:/生信计划与运行/}))
 expect(navigate).toHaveBeenCalledWith({view:'bio-insight-plan',fileId:''})
})

it('routes both submitted RNA assays and their selected outputs from the same requirement',()=>{
 const scopes=[
  ['customer.type.single_cell','单细胞 RNA 测序数据分析'],
  ['customer.analysis.single_cell.differential','单细胞差异表达'],
  ['customer.analysis.single_cell.pseudotime','单细胞拟时分析'],
  ['customer.figure.single_cell.umap','单细胞 UMAP'],
  ['customer.type.bulk','RNA 转录组学分析（Bulk RNA-seq）'],
  ['customer.analysis.bulk.enrichment','Bulk 富集'],
  ['customer.figure.bulk.volcano','Bulk 火山图'],
  ['customer.delivery.word','Word 报告'],
  ['customer.delivery.package','交付包'],
 ]
 const submitted:Version={...version,id:'submitted',operation:'confirm',content:{...version.content,scope_items:scopes.map(([id,title])=>({id,title,delivery_kind:'analysis',status:'planned'}))}}
 const navigate=vi.fn(),deliveries=vi.fn()
 render(<AnalysisGuide {...props} assigned version={submitted} onNavigate={navigate} onDeliveries={deliveries}/>)
 const single=within(screen.getByRole('article',{name:'单细胞 RNA 测序数据分析'}))
 const bulk=within(screen.getByRole('article',{name:'RNA 转录组学分析（Bulk RNA-seq）'}))
 const check=(panel:ReturnType<typeof within>,name:string,scopeItemId:string,expected:Record<string,unknown>)=>{
  fireEvent.click(panel.getByRole('button',{name}))
  expect(navigate).toHaveBeenLastCalledWith({fileId:'',entry:{requirementVersionId:'submitted',scopeItemId},...expected})
 }
 check(single,'导入并核对单细胞矩阵','customer.type.single_cell',{view:'bio-datasets',intent:'single_cell_import'})
 check(single,'配置单细胞差异表达','customer.analysis.single_cell.differential',{view:'bio-insights',intent:'single_cell_differential'})
 check(single,'核对拟时分析前提','customer.analysis.single_cell.pseudotime',{view:'bio-datasets',intent:'single_cell_results'})
 check(single,'查看 UMAP 来源','customer.figure.single_cell.umap',{view:'bio-datasets',intent:'single_cell_results'})
 check(single,'准备单细胞 Word','customer.delivery.word',{view:'bio-datasets',intent:'single_cell_results'})
 check(bulk,'进入 Bulk RNA-seq 工作流','customer.type.bulk',{view:'bulk-workflow',bulkView:'design'})
 check(bulk,'核对 Bulk 富集来源','customer.analysis.bulk.enrichment',{view:'bulk-workflow',bulkView:'functional'})
 check(bulk,'查看 Bulk 火山图来源','customer.figure.bulk.volcano',{view:'bulk-workflow',bulkView:'differential'})
 check(bulk,'准备 Bulk Word','customer.delivery.word',{view:'bulk-workflow',bulkView:'delivery'})
 fireEvent.click(screen.getByRole('button',{name:'打开分析交付'}))
 expect(deliveries).toHaveBeenCalledOnce()
 expect(screen.queryByRole('button',{name:'进入配置'})).toBeNull()
})
