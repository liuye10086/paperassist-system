import {useI18n} from '../../shared/i18n'
import ModuleViews,{ModuleView} from '../../shared/components/ModuleViews'
import type {TabularAssay, TabularScale, TabularTable, TableRole, TabularImportRequest, TabularSampleMetadataMapping} from './tabularContracts'
import {assayLabels,tabularAssays} from './tabularContracts'

export type ImportFile = {id:string;filename:string;file_type:string}
export const BULK_TABULAR_LIMITS={maxFileBytes:128*1024**2,maxExpandedBytes:256*1024**2,maxSamples:512,maxCells:5_000_000,maxImportBytes:2*1024**2}
export type TabularDraft = {assay:TabularAssay;files:Record<TableRole,string>;qualityReports:string[];sheets:Record<TableRole,string>;featureColumn:string;samples:string;metadataMapping:TabularSampleMetadataMapping;scale:TabularScale;naTokens:string}
export function newTabularDraft():TabularDraft {return {assay:'bulk_rna_counts',files:{quantitative_matrix:'',sample_metadata:'',feature_metadata:''},qualityReports:[],sheets:{quantitative_matrix:'',sample_metadata:'',feature_metadata:''},featureColumn:'feature_id',samples:'',metadataMapping:{sample_id:'sample_id',condition:'condition',biological_unit_id:'biological_unit_id',pair_id:'',batch:'',donor:'',sample_role:''},scale:{kind:'raw_counts',unit:'counts',upstream_method:'',upstream_transforms:[],namespace:'unknown',reference_version:'unknown',species_taxon_id:null,zero_meaning:'measured_zero',input_origin:'bulk_rna'},naTokens:'NA\nN/A'}}

export function restoreTabularDraft(saved: (Partial<TabularDraft> & {qualityReport?:string}) | null): TabularDraft {
 const defaults=newTabularDraft()
 const {qualityReport,...fields}=saved??{}
 return {
  ...defaults,...fields,
  files:{...defaults.files,...fields.files},
  sheets:{...defaults.sheets,...fields.sheets},
  metadataMapping:{...defaults.metadataMapping,...fields.metadataMapping},
  scale:{...defaults.scale,input_origin:fields.assay&&fields.assay!=='bulk_rna_counts'?'unknown':'bulk_rna',...fields.scale},
  qualityReports:fields.qualityReports??(qualityReport?[qualityReport]:[]),
 }
}
const roles:TableRole[]=['quantitative_matrix','sample_metadata','feature_metadata']
const labels:Record<TableRole,string>={quantitative_matrix:'定量矩阵原件',sample_metadata:'样本信息原件',feature_metadata:'特征注释原件（可选）'}
const sheetLabels:Record<TableRole,string>={quantitative_matrix:'定量矩阵工作表名称',sample_metadata:'样本信息工作表名称',feature_metadata:'特征注释工作表名称'}
const format=(file:ImportFile|undefined)=>file?.filename.toLowerCase().match(/\.(csv|tsv|xlsx)$/)?.[1] as TabularTable['format']|undefined
const lines=(text:string)=>text.split(/\r?\n/).map(s=>s.trim()).filter(Boolean)
type ImportPreparation =
 | {body:TabularImportRequest; issue:null}
 | {body:null; issue:{message:string;field?:string}}

const invalidImport=(message:string,field?:string):ImportPreparation=>({body:null,issue:{message,field}})

export function prepareTabularImport(draft:TabularDraft, files:ImportFile[], name:string, target:{id:string;revision:number}|null):ImportPreparation {
 if(!name.trim())return invalidImport('请填写数据集名称。')
 const tables:TabularTable[]=[]
 for(const role of roles) {
  const fileId=draft.files[role]
  if(!fileId&&role==='feature_metadata'&&draft.assay!=='microbiome')continue
  const kind=format(files.find(f=>f.id===fileId)),sheet=draft.sheets[role].trim()
  if(!kind)return invalidImport('请选择有效的原件（{field}）。',labels[role])
  if(kind==='xlsx'&&!sheet)return invalidImport('请填写工作表名称（{field}）。',labels[role])
  tables.push({file_id:fileId,role,format:kind,sheet:kind==='xlsx'?sheet:null,header_row:1,encoding:'utf-8-sig',delimiter:kind==='csv'?',':kind==='tsv'?'\t':null})
 }
 const samples=lines(draft.samples),qualityIds=draft.qualityReports.map(id=>id.trim()).filter(Boolean)
 const fileIds=[...tables.map(t=>t.file_id),...qualityIds],mapping=draft.metadataMapping
 const sampleLimit=draft.assay==='bulk_rna_counts'?BULK_TABULAR_LIMITS.maxSamples:draft.assay==='microbiome'?500:255
 const featureColumn=draft.featureColumn.trim()
 if(!featureColumn)return invalidImport('请填写特征标识列名。')
 if(!samples.length)return invalidImport('请填写样本列名，每行一个。')
 if(samples.length>sampleLimit)return invalidImport('样本列数超过支持上限。')
 if(samples.includes(featureColumn)||new Set(samples).size!==samples.length)return invalidImport('请移除重复的样本列名和误填的特征标识列名。')
 if(!draft.scale.upstream_method.trim())return invalidImport('请填写上游定量与处理方法。')
 if(!draft.scale.unit.trim())return invalidImport('请在补充设置中填写数值单位。')
 if(new Set(fileIds).size!==fileIds.length)return invalidImport('请选择不同的矩阵、样本表和补充原件。')
 if(qualityIds.length>2||qualityIds.some(id=>!files.some(file=>file.id===id)))return invalidImport('请在补充设置中重新选择上游质量报告。')

 return {issue:null,body:{
  workflow_version:'bio_import_v3',file_ids:fileIds,assay:draft.assay,name:name.trim(),
  dataset_id:target?.id??null,expected_dataset_revision:target?.revision??0,tables,
  feature_id_column:featureColumn,sample_columns:samples,
  scale:{...draft.scale,unit:draft.scale.unit.trim(),upstream_method:draft.scale.upstream_method.trim()},
  na_values:['',...lines(draft.naTokens)],
  ...(draft.assay==='bulk_rna_counts'?{sample_metadata_mapping:{
   ...mapping,condition:String(mapping.condition??'').trim()||null,biological_unit_id:String(mapping.biological_unit_id??'').trim()||null,
   pair_id:String(mapping.pair_id??'').trim()||null,batch:String(mapping.batch??'').trim()||null,
   donor:String(mapping.donor??'').trim()||null,sample_role:String(mapping.sample_role??'').trim()||null,
  }}:{}),
  ...(qualityIds.length?{quality_reports:qualityIds.map(file_id=>({file_id,source:'user_provided',report_type:'upstream_quality_report'}))}:{}),
 }}
}
const sampleMappingLabels = {
 sample_id:'sample_id（必需）',condition:'condition（必需）',biological_unit_id:'biological_unit_id（必需）',
 pair_id:'pair_id（可选）',batch:'batch（可选）',donor:'donor（可选）',sample_role:'sample_role（可选）',
} as const

export default function TabularImportFields({draft,onChange,files,bulkOnly=false,guidedBulk=false}:{
 draft:TabularDraft;onChange:(draft:TabularDraft)=>void;files:ImportFile[];bulkOnly?:boolean;guidedBulk?:boolean
}) {
 const {t}=useI18n(),change=<K extends keyof TabularDraft>(key:K,value:TabularDraft[K])=>onChange({...draft,[key]:value}),scale=(value:Partial<TabularScale>)=>change('scale',{...draft.scale,...value}),mapping=(value:Partial<TabularSampleMetadataMapping>)=>change('metadataMapping',{...draft.metadataMapping,...value})
 const choices=draft.assay==='microbiome'?['raw_counts','relative_abundance']:draft.assay==='bulk_rna_counts'?['raw_counts']:draft.assay==='normalized_expression'?['tpm','fpkm','normalized','log2','ln','log10']:['intensity','concentration','relative_abundance','normalized','log2','ln','log10']
 function assay(value:TabularAssay) {onChange({...draft,assay:value,scale:{...draft.scale,kind:value==='microbiome'?'relative_abundance':value==='bulk_rna_counts'?'raw_counts':value==='normalized_expression'?'normalized':'intensity',unit:value==='bulk_rna_counts'?'counts':'',zero_meaning:value==='bulk_rna_counts'?'measured_zero':'unknown',input_origin:value==='bulk_rna_counts'?'bulk_rna':'unknown'}})}
 const tableFiles=files.filter(file=>format(file))
 function fileField(role:TableRole) {
  const workbook=format(tableFiles.find(file=>file.id===draft.files[role]))==='xlsx'
  return <div className={guidedBulk?'intake-fields':undefined} key={role}>
   <label>{t(labels[role])}<select value={draft.files[role]} onChange={e=>change('files',{...draft.files,[role]:e.target.value})}>
    <option value="">{t(role==='feature_metadata'?'不提供特征注释':'请选择原件')}</option>
    {tableFiles.map(file=><option key={file.id} value={file.id}>{file.filename}</option>)}
   </select></label>
   {workbook&&<label>{t(sheetLabels[role])}<input value={draft.sheets[role]} maxLength={200} onChange={e=>change('sheets',{...draft.sheets,[role]:e.target.value})}/></label>}
  </div>
 }
 function mappingField(key:keyof typeof sampleMappingLabels) {
  return <label key={key}>{t(sampleMappingLabels[key])}<input value={draft.metadataMapping[key]??''} maxLength={200} onChange={e=>mapping({[key]:e.target.value})}/></label>
 }
 const reports=['上游质量报告（可选）','第二份上游质量报告（可选）'].map((label,index)=><label key={label}>{t(label)}
    <select value={draft.qualityReports[index]??''} onChange={event=>{
     const reports=[draft.qualityReports[0]??'',draft.qualityReports[1]??'']
     reports[index]=event.target.value
     change('qualityReports',reports[1]?reports:reports[0]?[reports[0]]:[])
    }}>
     <option value="">{t('不提供')}</option>
     {files.filter(file=>!Object.values(draft.files).includes(file.id)&&file.id!==draft.qualityReports[1-index])
      .map(file=><option key={file.id} value={file.id}>{file.filename}</option>)}
    </select>
   </label>)
 const feature=<label>{t('特征标识列名')}<input value={draft.featureColumn} maxLength={200} onChange={e=>change('featureColumn',e.target.value)}/></label>
 const samples=<label>{t('样本列名（每行一个，保留原始顺序）')}<textarea value={draft.samples} onChange={e=>change('samples',e.target.value)} rows={6}/></label>
 const method=<label>{t('上游定量与处理方法')}<textarea value={draft.scale.upstream_method} maxLength={4000} onChange={e=>scale({upstream_method:e.target.value})}/></label>
 const species=<label>{t('物种 Taxon ID（未知留空）')}<input type="number" min={1} value={draft.scale.species_taxon_id??''} onChange={e=>scale({species_taxon_id:e.target.value?Number(e.target.value):null})}/></label>
 const scaleType=<>
  <label>{t('输入数值尺度')}<select value={draft.scale.kind} onChange={e=>scale({kind:e.target.value as TabularScale['kind']})}>{choices.map(key=><option key={key} value={key}>{key}</option>)}</select></label>
  <label>{t('输入来源/尺度声明')}<select value={draft.scale.input_origin??'unknown'} onChange={e=>scale({input_origin:e.target.value as TabularScale['input_origin']})}>{['bulk_rna','single_cell_expression','tpm','fpkm','log','vst','rlog','z_score','unknown'].map(key=><option key={key} value={key}>{key}</option>)}</select></label>
  <label>{t('数值单位')}<input value={draft.scale.unit} maxLength={200} onChange={e=>scale({unit:e.target.value})}/></label>
 </>
 const featureReference=<>
  <label>{t('已有变换（每行一个）')}<textarea value={draft.scale.upstream_transforms.join('\n')} onChange={e=>scale({upstream_transforms:lines(e.target.value)})}/></label>
  <label>{t('特征标识命名空间')}<input value={draft.scale.namespace} maxLength={200} onChange={e=>scale({namespace:e.target.value})}/></label>
  <label>{t('参考版本')}<input value={draft.scale.reference_version} maxLength={200} onChange={e=>scale({reference_version:e.target.value})}/></label>
 </>
 const parsingOptions=<>
  <label>{t('零值含义')}<select value={draft.scale.zero_meaning} onChange={e=>scale({zero_meaning:e.target.value as TabularScale['zero_meaning']})}><option value="measured_zero">{t('测量零值')}</option><option value="unknown">{t('未知')}</option><option value="below_lod">{t('低于检测限')}</option></select></label>
  <label>{t('缺失标记（每行一个，空单元格始终保留为缺失）')}<textarea value={draft.naTokens} onChange={e=>change('naTokens',e.target.value)}/></label>
   <p>{t('CSV/TSV 使用 UTF-8 和首行表头。XLSX 须指定工作表。Bulk 原件最多 128 MiB，展开后最多 256 MiB，最多 512 个样本列和 500 万矩阵数值。附表另计，导入设置最多 2 MiB。')}</p>
  <p>{t('不自动插补、不把零改为缺失、不添加伪计数。TPM、FPKM、log/VST/rlog/Z-score、单细胞表达和未知尺度必须在来源声明中明确标记，不能进入 Bulk raw-counts 模型。')}</p>
   {draft.assay==='bulk_rna_counts'&&<>
    <p><a download="bulk-rna-counts-matrix-template.csv" href={`data:text/csv;charset=utf-8,${encodeURIComponent('feature_id,sample_1,sample_2\nGENE0001,10,15\nGENE0002,8,4\n')}`}>{t('下载 counts 矩阵模板')}</a>{' · '}<a download="bulk-rna-sample-metadata-template.tsv" href={`data:text/tab-separated-values;charset=utf-8,${encodeURIComponent('sample_id\tcondition\tbiological_unit_id\tpair_id\tbatch\tdonor\tsample_role\nsample_1\tcontrol\tdonor_1\t\tbatch_1\tdonor_1\tbiological\nsample_2\ttreatment\tdonor_2\t\tbatch_1\tdonor_2\tbiological\n')}`}>{t('下载样本信息模板')}</a></p>
    <p>{t('示例数据仅用于演示文件格式。')}</p>
   </>}
 </>
 if(guidedBulk)return <div className="bulk-import-settings">
  <ModuleViews label={t('Bulk 导入设置')}>
   <ModuleView id="basic" title={t('基本配置')}>
    <div className="intake-form">
     <fieldset><legend>{t('原始计数文件')}</legend>
      <div className="intake-rows">{fileField('quantitative_matrix')}{fileField('sample_metadata')}</div>
     </fieldset>
     <fieldset><legend>{t('矩阵列名')}</legend>
      <p>{t('从计数矩阵首行复制列名。基因 ID 填在特征列，其他样本列按原顺序逐行填写。')}</p>
      {feature}{samples}
     </fieldset>
     <fieldset><legend>{t('样本分组与配对')}</legend>
      <p>{t('填写样本表中的对应列名。做配对分析时，映射表中已有的配对编号或供者列。')}</p>
      <div className="intake-rows">{(['sample_id','condition','biological_unit_id','pair_id','donor','sample_role'] as const).map(mappingField)}</div>
     </fieldset>
     <fieldset><legend>{t('计数来源')}</legend>
      <p>{t('按资料如实填写来源和处理方法，未知细节可以注明。')}</p>
      {method}{species}
     </fieldset>
    </div>
   </ModuleView>
   <ModuleView id="extra" title={t('补充设置')}>
    <div className="intake-form">
     {fileField('feature_metadata')}{reports}{mappingField('batch')}
     {scaleType}{featureReference}{parsingOptions}
    </div>
   </ModuleView>
  </ModuleViews>
 </div>
 return <div className="intake-form">
  {bulkOnly?<p>{t(assayLabels.bulk_rna_counts)}</p>:<label>{t('数据类型')}<select value={draft.assay} onChange={e=>assay(e.target.value as TabularAssay)}>{tabularAssays.map(key=><option key={key} value={key}>{t(assayLabels[key])}</option>)}</select></label>}
  <p>{t('矩阵每行一个特征、每列一个样本；样本表须有 sample_id 并与矩阵列完整对应。技术重复不能作为独立生物重复。')}</p>
  {roles.map(fileField)}{reports}{feature}{samples}
  {draft.assay==='bulk_rna_counts'&&<fieldset><legend>{t('Bulk 样本元数据列映射')}</legend><p>{t('映射只改 canonical 字段，不改写原始样本表；sample_id、condition、biological_unit_id 为必需列。')}</p>
   {(Object.keys(sampleMappingLabels) as (keyof typeof sampleMappingLabels)[]).map(mappingField)}
  </fieldset>}
  {scaleType}{method}{featureReference}{species}{parsingOptions}
 </div>
}
