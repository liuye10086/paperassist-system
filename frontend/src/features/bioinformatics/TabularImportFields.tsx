import {useI18n} from '../../shared/i18n'
import type {TabularAssay, TabularScale, TabularTable, TableRole, TabularImportRequest} from './tabularContracts'
import {assayLabels,tabularAssays} from './tabularContracts'

export type ImportFile = {id:string;filename:string;file_type:string}
export type TabularDraft = {assay:TabularAssay;files:Record<TableRole,string>;sheets:Record<TableRole,string>;featureColumn:string;samples:string;scale:TabularScale;naTokens:string}
export function newTabularDraft():TabularDraft {return {assay:'bulk_rna_counts',files:{quantitative_matrix:'',sample_metadata:'',feature_metadata:''},sheets:{quantitative_matrix:'',sample_metadata:'',feature_metadata:''},featureColumn:'feature_id',samples:'',scale:{kind:'raw_counts',unit:'counts',upstream_method:'',upstream_transforms:[],namespace:'unknown',reference_version:'unknown',species_taxon_id:null,zero_meaning:'measured_zero'},naTokens:'NA\nN/A'}}
const roles:TableRole[]=['quantitative_matrix','sample_metadata','feature_metadata']
const labels:Record<TableRole,string>={quantitative_matrix:'定量矩阵原件',sample_metadata:'样本信息原件',feature_metadata:'特征注释原件（可选）'}
const sheetLabels:Record<TableRole,string>={quantitative_matrix:'定量矩阵工作表名称',sample_metadata:'样本信息工作表名称',feature_metadata:'特征注释工作表名称'}
const format=(file:ImportFile|undefined)=>file?.filename.toLowerCase().match(/\.(csv|tsv|xlsx)$/)?.[1] as TabularTable['format']|undefined
const lines=(text:string)=>text.split(/\r?\n/).map(s=>s.trim()).filter(Boolean)
export function tabularImportBody(draft:TabularDraft, files:ImportFile[], name:string, target:{id:string;revision:number}|null):TabularImportRequest|null {
 const tables:TabularTable[]=[]
 for(const role of roles) {
  const fileId=draft.files[role]
  if(!fileId&&role==='feature_metadata'&&draft.assay!=='microbiome')continue
  const kind=format(files.find(f=>f.id===fileId)),sheet=draft.sheets[role].trim()
  if(!kind||kind==='xlsx'&&!sheet)return null
  tables.push({file_id:fileId,role,format:kind,sheet:kind==='xlsx'?sheet:null,header_row:1,encoding:'utf-8-sig',delimiter:kind==='csv'?',':kind==='tsv'?'\t':null})
 }
 const samples=lines(draft.samples),fileIds=tables.map(t=>t.file_id)
 if(!name.trim()||!draft.featureColumn.trim()||!samples.length||samples.length>(draft.assay==='microbiome'?500:255)||samples.includes(draft.featureColumn.trim())||new Set(samples).size!==samples.length||new Set(fileIds).size!==fileIds.length||!draft.scale.unit.trim()||!draft.scale.upstream_method.trim())return null
 return {workflow_version:'bio_import_v3',file_ids:fileIds,assay:draft.assay,name:name.trim(),dataset_id:target?.id??null,expected_dataset_revision:target?.revision??0,tables,feature_id_column:draft.featureColumn.trim(),sample_columns:samples,scale:{...draft.scale,unit:draft.scale.unit.trim(),upstream_method:draft.scale.upstream_method.trim()},na_values:['',...lines(draft.naTokens)]}
}
export default function TabularImportFields({draft,onChange,files}:{draft:TabularDraft;onChange:(draft:TabularDraft)=>void;files:ImportFile[]}) {
 const {t}=useI18n(),change=<K extends keyof TabularDraft>(key:K,value:TabularDraft[K])=>onChange({...draft,[key]:value}),scale=(value:Partial<TabularScale>)=>change('scale',{...draft.scale,...value})
 const choices=draft.assay==='microbiome'?['raw_counts','relative_abundance']:draft.assay==='bulk_rna_counts'?['raw_counts']:draft.assay==='normalized_expression'?['tpm','fpkm','normalized','log2','ln','log10']:['intensity','concentration','relative_abundance','normalized','log2','ln','log10']
 function assay(value:TabularAssay) {onChange({...draft,assay:value,scale:{...draft.scale,kind:value==='microbiome'?'relative_abundance':value==='bulk_rna_counts'?'raw_counts':value==='normalized_expression'?'normalized':'intensity',unit:value==='bulk_rna_counts'?'counts':'',zero_meaning:value==='bulk_rna_counts'?'measured_zero':'unknown'}})}
 return <div className="intake-form">
  <label>{t('数据类型')}<select value={draft.assay} onChange={e=>assay(e.target.value as TabularAssay)}>{tabularAssays.map(key=><option key={key} value={key}>{t(assayLabels[key])}</option>)}</select></label>
  <p>{t('矩阵每行一个特征、每列一个样本；样本表须有 sample_id 并与矩阵列完整对应。技术重复不能作为独立生物重复。')}</p>
  {roles.map(role=><div key={role}><label>{t(labels[role])}<select value={draft.files[role]} onChange={e=>change('files',{...draft.files,[role]:e.target.value})}><option value="">{t(role==='feature_metadata'?'不提供特征注释':'请选择原件')}</option>{files.filter(file=>format(file)).map(file=><option key={file.id} value={file.id}>{file.filename}</option>)}</select></label>{format(files.find(file=>file.id===draft.files[role]))==='xlsx'&&<label>{t(sheetLabels[role])}<input value={draft.sheets[role]} maxLength={200} onChange={e=>change('sheets',{...draft.sheets,[role]:e.target.value})}/></label>}</div>)}
  <label>{t('特征标识列名')}<input value={draft.featureColumn} maxLength={200} onChange={e=>change('featureColumn',e.target.value)}/></label>
  <label>{t('样本列名（每行一个，保留原始顺序）')}<textarea value={draft.samples} onChange={e=>change('samples',e.target.value)} rows={6}/></label>
  <label>{t('输入数值尺度')}<select value={draft.scale.kind} onChange={e=>scale({kind:e.target.value as TabularScale['kind']})}>{choices.map(key=><option key={key} value={key}>{key}</option>)}</select></label>
  <label>{t('数值单位')}<input value={draft.scale.unit} maxLength={200} onChange={e=>scale({unit:e.target.value})}/></label>
  <label>{t('上游定量与处理方法')}<textarea value={draft.scale.upstream_method} maxLength={4000} onChange={e=>scale({upstream_method:e.target.value})}/></label>
  <label>{t('已有变换（每行一个）')}<textarea value={draft.scale.upstream_transforms.join('\n')} onChange={e=>scale({upstream_transforms:lines(e.target.value)})}/></label>
  <label>{t('特征标识命名空间')}<input value={draft.scale.namespace} maxLength={200} onChange={e=>scale({namespace:e.target.value})}/></label>
  <label>{t('参考版本')}<input value={draft.scale.reference_version} maxLength={200} onChange={e=>scale({reference_version:e.target.value})}/></label>
  <label>{t('物种 Taxon ID（未知留空）')}<input type="number" min={1} value={draft.scale.species_taxon_id??''} onChange={e=>scale({species_taxon_id:e.target.value?Number(e.target.value):null})}/></label>
  <label>{t('零值含义')}<select value={draft.scale.zero_meaning} onChange={e=>scale({zero_meaning:e.target.value as TabularScale['zero_meaning']})}><option value="measured_zero">{t('测量零值')}</option><option value="unknown">{t('未知')}</option><option value="below_lod">{t('低于检测限')}</option></select></label>
  <label>{t('缺失标记（每行一个，空单元格始终保留为缺失）')}<textarea value={draft.naTokens} onChange={e=>change('naTokens',e.target.value)}/></label>
  <p>{t('CSV/TSV 使用 UTF-8、首行表头；XLSX 须指定工作表，不执行公式。原件最多 10 MiB，单表最多 100000 行、256 列，合计最多 100 万单元格。')}</p>
  <p>{t('不自动插补、不把零改为缺失、不添加伪计数。已 log 的矩阵保留原尺度；TPM、FPKM 和标准化表达不进入 counts 模型。')}</p>
 </div>
}
