import type {ProjectFile} from '../files/fileLibraryApi'
import type {MaterialRef,Version} from '../research-intake/contracts'
import type {AnalysisNavigation} from './analysisViews'
import {materialPurposes} from '../research-intake/state'
import {bulkRoute} from '../bio-insights/bulkWorkflow'
import {analysisTypes,deliveryChoices} from '../customer/customerRequirementChoices'

export type AnalysisScope={id:string;title:string;status:string;delivery_kind:string}
export type EntryImport={id:string;status:string;fileIds:string[];datasetId:string;versionId?:string;createdAt:string}
export type EntrySource={key:string;label:string;status:string;ready:boolean;kind:'table'|'evidence'|'bio-original'|'bio-version'|'missing';purpose:string;fileId?:string;datasetId?:string;versionId?:string;importId?:string}
export type EntryMethod={id:string;label:string;source:'table'|'bio'|'module';help:string;navigation:AnalysisNavigation}
export function analysisScopes(version:Version):AnalysisScope[]{
 return ((version.content.scope_items??[]) as AnalysisScope[]).filter(item=>item.delivery_kind==='analysis'&&item.status!=='not_included')
}
export const scopeKind=(scope:AnalysisScope)=>scope.id.startsWith('questionnaire.analysis.')?scope.id.slice('questionnaire.analysis.'.length):scope.id.startsWith('customer.delivery.')?'delivery':'custom'

type RnaAction = { label: string; navigation: AnalysisNavigation }
const singleCellResults: AnalysisNavigation = {view:'bio-datasets',fileId:'',intent:'single_cell_results'}
const rnaActions = {
 single_cell: {
  primary: [
   {label:'导入并核对单细胞矩阵',navigation:{view:'bio-datasets',fileId:'',intent:'single_cell_import'}},
   {label:'查看单细胞处理结果',navigation:singleCellResults},
  ],
  choices: {
   'customer.analysis.single_cell.differential':{label:'配置单细胞差异表达',navigation:{view:'bio-insights',fileId:'',intent:'single_cell_differential'}},
   'customer.analysis.single_cell.enrichment':{label:'核对单细胞富集来源',navigation:{view:'bio-insight-runs',fileId:'',intent:'single_cell_enrichment'}},
   'customer.analysis.single_cell.pseudotime':{label:'核对拟时分析前提',navigation:singleCellResults},
   'customer.figure.single_cell.umap':{label:'查看 UMAP 来源',navigation:singleCellResults},
   'customer.figure.single_cell.heatmap':{label:'查看单细胞热图来源',navigation:singleCellResults},
   'customer.delivery.word':{label:'准备单细胞 Word',navigation:singleCellResults},
  },
 },
 bulk: {
  primary: [
   {label:'进入 Bulk RNA-seq 工作流',navigation:bulkRoute('design')},
   {label:'查看 Bulk 固定结果',navigation:bulkRoute('differential')},
  ],
  choices: {
   'customer.analysis.bulk.differential':{label:'配置 Bulk 差异表达',navigation:bulkRoute('differential')},
   'customer.analysis.bulk.enrichment':{label:'核对 Bulk 富集来源',navigation:bulkRoute('functional')},
   'customer.figure.bulk.volcano':{label:'查看 Bulk 火山图来源',navigation:bulkRoute('differential')},
   'customer.figure.bulk.heatmap':{label:'查看 Bulk 热图来源',navigation:bulkRoute('differential')},
   'customer.delivery.word':{label:'准备 Bulk Word',navigation:bulkRoute('delivery')},
  },
 },
} satisfies Record<string,{primary:RnaAction[];choices:Record<string,RnaAction>}>

export function rnaRequestGroups(scopes: AnalysisScope[], scopeId?: string) {
 return Object.entries(rnaActions).flatMap(([assay,{primary,choices}])=>{
  const parent=scopes.find(scope=>scope.id===`customer.type.${assay}`)
  if(!parent)return []
  const group=analysisTypes.find(item=>item.type.id===parent.id)
  const declared=[...(group?.analyses??[]),...(group?.figures??[]),...deliveryChoices]
  const matching=scopes.flatMap(scope=>{
   const action=Object.hasOwn(choices,scope.id)?(choices as Record<string,RnaAction>)[scope.id]:undefined
   return action ? [{...action,scope,title:declared.find(choice=>choice.id===scope.id)?.label??scope.title}] : []
  })
  if(scopeId&&scopeId!==parent.id&&!matching.some(({scope})=>scope.id===scopeId))return []
  const main=(!scopeId||scopeId===parent.id)?primary.map(action=>({...action,scope:parent})):[]
  return [{assay,parent,title:group?.type.label??parent.title,primary:main,choices:matching.filter(({scope})=>!scopeId||scopeId===scope.id)}]
 })
}
const importStatus=(item:EntryImport)=>item.status==='waiting_confirmation'?'等待核对确认':item.status==='succeeded'&&item.versionId?'原件已有发布版本，可选择复用':item.status==='failed'?'导入失败，可查看原任务':item.status==='queued'?'导入已排队':item.status==='running'?'导入处理中':'查看已有导入状态'
export function filePreparation(file:ProjectFile,imports:EntryImport[]=[]):Pick<EntrySource,'kind'|'ready'> & {label:string}{
 if(file.parse_status==='stored'){const related=imports.filter(item=>item.fileIds.includes(file.id));return {kind:'bio-original',ready:false,label:related.length===1?importStatus(related[0]):related.length>1?'存在多次导入，请选择记录':'原件已保存，待导入核对'}}
 const kind=file.file_type==='xlsx'?'table':'evidence'
 const labels={queued:'已保存，等待解析',parsing:'解析中',failed:'解析失败',parsed:kind==='table'?'可进入表格配置':'可预览，作为证据材料'}
 return {kind,ready:file.parse_status==='parsed'&&kind==='table',label:labels[file.parse_status]}
}
const purposes:Record<string,string[]>={qc:['raw_data'],differential:['raw_data'],multiomics:['raw_data'],validation:['raw_data','existing_results'],enrichment:['existing_results'],candidates:['existing_results'],evidence:['existing_results','protocol','other'],visualization:['existing_results','figures'],delivery:['existing_results','figures','protocol']}
export function entrySources(version:Version,kind:string,files:ProjectFile[],imports:EntryImport[]=[]):EntrySource[]{
 const refs=[...(version.material_refs??[])]
 for(const item of (version.content.material_checklist??[]) as MaterialRef[]){if(!refs.some(ref=>ref.purpose===item.purpose))refs.push(item)}
 return refs.filter(ref=>!purposes[kind]||purposes[kind].includes(ref.purpose)).map((ref,index)=>{
  const base={key:`pending:${index}`,label:ref.note||materialPurposes.find(([key])=>key===ref.purpose)?.[1]||ref.purpose,status:'待补充材料关联',ready:false,kind:'missing' as const,purpose:ref.purpose}
  if(ref.availability!=='provided')return {...base,status:ref.availability==='none'?'尚无材料':'待补充材料'}
  if(ref.file_id){
   const file=files.find(f=>f.id===ref.file_id)
   if(!file)return {...base,key:'file:'+ref.file_id,label:'关联文件',fileId:ref.file_id,status:'来源不可用，请重新核对材料关联'}
   const state=filePreparation(file)
   return {...base,key:'file:'+file.id,label:file.filename,fileId:file.id,kind:state.kind,ready:state.ready,status:state.label}
  }
  if(ref.bio_dataset_version_id){
   const source=version.material_sources?.find(s=>s.bio_dataset_version_id===ref.bio_dataset_version_id)
   if(source)return {...base,key:'bio:'+source.bio_dataset_version_id,label:`${source.dataset_name} · v${source.version}`,kind:'bio-version' as const,ready:true,status:'已发布固定版本，可核对配置',datasetId:source.dataset_id,versionId:source.bio_dataset_version_id}
   return {...base,key:'bio:'+ref.bio_dataset_version_id,label:'关联数据集版本',versionId:ref.bio_dataset_version_id,status:'来源不可用，请重新核对材料关联'}
  }
  return base
 }).filter((source,index,all)=>all.findIndex(other=>other.key===source.key)===index).flatMap((source):EntrySource[]=>{
  if(source.kind!=='bio-original')return [source]
  const related=imports.filter(item=>item.fileIds.includes(source.fileId!))
  if(!related.length)return [source]
  return related.map(item=>({...source,key:`${source.key}:import:${item.id}`,label:related.length>1?`${source.label} · ${new Date(item.createdAt).toLocaleString()}`:source.label,importId:item.id,datasetId:item.datasetId,versionId:item.versionId,kind:item.status==='succeeded'&&item.versionId?'bio-version':'bio-original',ready:item.status==='succeeded'&&!!item.versionId,status:importStatus(item)}))
 })
}
const table=(view:AnalysisNavigation['view']='setup'):EntryMethod=>({id:'table',label:'表格统计',source:'table',help:'选择已解析的 Excel；分组和原始／整理版本在配置中核对。',navigation:{view,fileId:'',intent:'table'}})
const bio:EntryMethod={id:'bio',label:'生信数据准备',source:'bio',help:'原件先导入核对；已发布版本可继续配置和处理。',navigation:{view:'bio-datasets',fileId:'',intent:'bio'}}
const method=(id:string,label:string,view:AnalysisNavigation['view'],intent:AnalysisNavigation['intent'],help:string):EntryMethod=>({id,label,source:'module',help,navigation:{view,fileId:'',intent}})
const comparison=method('comparison','生信比较分析','bio-insights','comparison','在现有计划中选择固定定量层，核对分组与重复单位，再预检。')
export function entryMethods(kind:string):EntryMethod[]{
 switch(kind){
  case 'qc':return [table('profile'),bio]
  case 'differential':return [table(),comparison,bio]
  case 'enrichment':return [method('ora','ORA 富集','bio-resources','ora','选择适用的比较结果与背景资源，再预检。'),method('gsea_prerank','GSEA 排序富集','bio-resources','gsea_prerank','选择完整排序结果与基因集资源，再预检。')]
  case 'candidates':return [method('candidate','候选对象筛选','bio-candidates','candidate','在现有来源选择器中选用固定比较结果。')]
  case 'multiomics':return [method('integration','多组学整合','bio-insights','integration','选择固定定量层、样本对应表和对象对应表；缺失资源可在“资源与富集”补充。')]
  case 'evidence':return [method('evidence','外部证据整合','bio-candidates','evidence','选择明确的证据类型、来源和适用范围，不自动外部检索。')]
  case 'validation':return [method('qpcr','qPCR 验证','bio-insights','qpcr','选择 qPCR 数据与参照信息，核对实验设计后预检。'),table()]
  case 'visualization':return [method('table-figure','表格结果绘图','figure','figure','先选择已有表格分析结果；进入页面不会生成新图。'),method('bio-figure','生信结果绘图','bio-insight-result','figure','在来源选择器中选用固定分析结果；缺少结果时先完成对应分析。')]
  case 'delivery':return [method('report','表格报告与集合','report','report','选择已有结果后整理报告；不会自动导出。'),method('findings','研究报告与成果包','research-findings','report','在研究发现中选用已有结果，进入现有报告与成果包。')]
  default:return [table(),bio,comparison,method('integration','多组学整合','bio-insights','integration','先选择固定来源与对应资源，再预检。')]
 }
}
export function sourceNavigation(source:EntrySource):AnalysisNavigation|undefined{
 if(source.kind==='bio-version')return {view:'bio-dataset',fileId:'',datasetId:source.datasetId,versionId:source.versionId}
 if(source.importId)return {view:'bio-import',fileId:'',importId:source.importId}
 if(source.kind==='bio-original')return {view:'bio-datasets',fileId:source.fileId??''}
 return undefined
}
