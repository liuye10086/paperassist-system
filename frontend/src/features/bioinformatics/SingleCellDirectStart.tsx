import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import type {AnalysisNavigation} from '../projects/analysisViews'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {projectBase} from './api'
import {BioWriteStatus} from './BioSpatialShared'
import type {BioCapabilities,BioRecipeParameters,BioRun,RawBioSource} from './spatialContracts'
import {useBioRead} from './spatialHooks'
import useBioWrite from './useBioWrite'
import SingleCellQcFields from './SingleCellQcFields'
import SingleCellIntegrationFields from './SingleCellIntegrationFields'

const fields:[keyof BioRecipeParameters,string,number,number,number][]=[
 ['min_counts','最低 counts',0,2147483647,1],['min_genes','最低检测基因数',0,100000,1],['min_spots','基因最低 cell 数',1,20000,1],
 ['target_sum','标准化 target sum',1,1000000,1],['hvg_count','HVG 数量',3,10000,1],['pca_components','PCA 成分数',2,100,1],
 ['neighbors','邻居数',2,100,1],['resolution','Leiden resolution',0.01,10,0.01],['seed','随机 seed',0,2147483647,1],['marker_top_n','每 cluster Top marker 数',1,100,1],
]
const number=(value:number|null)=>value===null?'未知':value.toLocaleString('en-US')
const memory=(bytes:number|null)=>bytes===null?'未知':`${(bytes/1024**2).toFixed(1)} MiB`
const resourceReasons:Record<string,string>={single_cell_observations_limit:'细胞数超过当前上限。',single_cell_features_limit:'基因数超过当前上限。',single_cell_nnz_limit:'非零元素数超过当前上限。',single_cell_dense_hvg_limit:'HVG 密集块超过当前上限，请减少 HVG 数量或导入较小矩阵。',single_cell_matrix_dimensions_unknown:'矩阵规模未明确，无法估算资源。'}

export default function SingleCellDirectStart({projectId,source,onNavigate,registerLeaveGuard,initialParams,observationMapVersionId,designVersionId}:{projectId:string;source:RawBioSource;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard;initialParams?:BioRecipeParameters;observationMapVersionId?:string|null;designVersionId?:string|null}){
 const {t}=useI18n(),base=projectBase(projectId)
 const read=useBioRead<BioCapabilities>(`${base}/bio-analysis-capabilities?dataset_id=${encodeURIComponent(source.dataset_id)}&version_id=${encodeURIComponent(source.dataset_version_id)}`)
 const [draft,setDraft]=useState<BioRecipeParameters|null>(initialParams??null),[name,setName]=useState('Single-cell exploratory analysis')
 const params=draft??read.value?.default_params
 const estimate=read.value?.resource_estimate
 const selectedLimits=(params?.doublet?.enabled||params?.decontx?.enabled||params?.harmony?.enabled)?estimate?.optional_r_limits??estimate?.configured_limits:estimate?.configured_limits
 const denseValues=estimate&&params&&estimate.matrix.observations!==null&&estimate.matrix.features!==null?estimate.matrix.observations*Math.min(params.hvg_count,estimate.matrix.features):null
 const blockers=read.value?.blockers.filter(code=>!estimate||code!=='single_cell_dense_hvg_limit')??[]
 if(estimate&&denseValues!==null&&denseValues>estimate.configured_limits.max_dense_values)blockers.push('single_cell_dense_hvg_limit')
 const resourceAvailable=estimate?blockers.length===0:!!read.value?.available
 const open=(id:string)=>onNavigate({view:'bio-analysis',fileId:'',runId:id})
 const writer=useBioWrite<BioRun>(projectId,'run',v=>open(v.id),v=>open(v.id))
 const dirty=!!draft||name!=='Single-cell exploratory analysis'
 useDraftLeaveGuard(registerLeaveGuard,dirty&&!writer.completed,writer.busy||writer.unknown)
 const blocked=writer.busy||writer.unknown||!writer.valid||!read.valid
 const update=<K extends keyof BioRecipeParameters>(key:K,value:BioRecipeParameters[K])=>{if(params)setDraft({...params,[key]:value})}
 const changeMtRule=(rule:BioRecipeParameters['mt_rule'])=>{
  if(!params)return
  const library_qc_overrides=(params.library_qc_overrides??[]).map(entry=>{const value={...entry};delete value.max_mt_fraction;return value}).filter(entry=>Object.keys(entry).length>1)
  setDraft({...params,mt_rule:rule,max_mt_fraction:null,library_qc_overrides,technical_covariates:rule.confirmed?params.technical_covariates:(params.technical_covariates??[]).filter(value=>value!=='mt_fraction')})
 }
 return <section className="bio-workspace intake-form"><h3>{t('单细胞探索分析')}</h3>
  <p>{t('填写参数后开始分析，任务会连续执行 QC、标准化、降维和聚类，完成后查看图表与结果。')}</p>
  <p>{t('未知供者不影响探索；cell 不代表独立供者，marker 仅为探索性 cell 群关联。')}</p>
  {read.error&&<p role="alert">{t(read.error)}</p>}
  {read.value&&<><ul>{blockers.map(v=><li key={v}>{t(resourceReasons[v]??v)}</li>)}</ul>
   {estimate&&<section aria-label="资源估算"><h4>{t('矩阵规模与资源估算')}</h4>
    <p>{number(estimate.matrix.observations)} cells × {number(estimate.matrix.features)} features；nnz {number(estimate.matrix.nnz)}</p>
    <p>{t('原始 CSR')}：{memory(estimate.sparse_bytes)}；{t('当前 HVG 密集块上界')}：{memory(denseValues===null?null:denseValues*4)}（{number(denseValues)} values）</p>
    <p>{t('当前上限')}：{number(estimate.configured_limits.max_observations)} cells / {number(estimate.configured_limits.max_features)} features / {number(estimate.configured_limits.max_entries)} nnz；HVG {number(estimate.configured_limits.max_dense_values)} values；{t('进程内存限制')} {memory(selectedLimits?.memory_bytes??null)}</p>
    <p>{t('仅为估算：原始 CSR 按 int64 counts 与索引计算，HVG 按当前参数和 float32 计算，QC 后可能减少。未包含 R 模型及校正副本、标准化副本、PCA、邻居、绘图和运行环境开销，不是进程峰值承诺。')}</p>
   </section>}
   {params&&<form onSubmit={event=>{event.preventDefault();void writer.submit(`${base}/single-cell-analysis-runs`,{name,raw_source:source,...(observationMapVersionId?{observation_map_version_id:observationMapVersionId}:{}),...(designVersionId?{design_version_id:designVersionId}:{}),params:{...params,in_tissue_only:false}})}}>
    <fieldset disabled={blocked}><legend>{t('分析参数')}</legend>
     <label>{t('分析名称')}<input required maxLength={200} value={name} onChange={e=>setName(e.target.value)}/></label>
     <div className="intake-rows">{fields.map(([key,label,min,max,step])=><label key={key}>{t(label)}<input required type="number" min={min} max={max} step={step} value={String(params[key])} onChange={e=>update(key,Number(e.target.value) as never)}/></label>)}</div>
     <label>{t('最高 counts（留空为不设限）')}<input type="number" min={1} value={params.max_counts??''} onChange={e=>update('max_counts',e.target.value===''?null:Number(e.target.value))}/></label>
     <label>{t('排除条码，每行一个')}<textarea value={params.exclude_barcodes.join('\n')} onChange={e=>update('exclude_barcodes',e.target.value.split(/\s+/).filter(Boolean))}/></label>
     <label>{t('线粒体规则')}<select value={params.mt_rule.kind} onChange={e=>changeMtRule({kind:e.target.value as BioRecipeParameters['mt_rule']['kind'],feature_ids:[],prefix:null,confirmed:false})}><option value="unknown">{t('未知')}</option><option value="feature_ids">{t('稳定基因 ID 列表')}</option><option value="prefix">{t('基因符号前缀')}</option></select></label>
     {params.mt_rule.kind==='feature_ids'&&<label>{t('线粒体稳定基因 ID')}<textarea required value={params.mt_rule.feature_ids.join('\n')} onChange={e=>changeMtRule({...params.mt_rule,feature_ids:e.target.value.split(/\s+/).filter(Boolean),confirmed:false})}/></label>}
     {params.mt_rule.kind==='prefix'&&<label>{t('线粒体符号前缀')}<input required value={params.mt_rule.prefix??''} onChange={e=>changeMtRule({...params.mt_rule,prefix:e.target.value,confirmed:false})}/></label>}
     {params.mt_rule.kind!=='unknown'&&<label><input type="checkbox" checked={params.mt_rule.confirmed} onChange={e=>changeMtRule({...params.mt_rule,confirmed:e.target.checked})}/>{t('已核对并确认此线粒体规则')}</label>}
     <label>{t('最高线粒体比例（0–1）')}<input type="number" min={0} max={1} step="any" disabled={!params.mt_rule.confirmed} value={params.max_mt_fraction??''} onChange={e=>update('max_mt_fraction',e.target.value===''?null:Number(e.target.value))}/></label>
     <SingleCellQcFields params={params} libraries={read.value.single_cell_libraries??[]} onChange={setDraft}/>
     <SingleCellIntegrationFields params={params} onChange={setDraft}/>
     <label>{t('输出语言')}<select value={params.output_language} onChange={e=>update('output_language',e.target.value as 'en'|'zh-CN')}><option value="en">English</option><option value="zh-CN">简体中文</option></select></label>
    </fieldset>
    <button type="submit" disabled={blocked||!resourceAvailable}>{t('开始单细胞分析')}</button>
   </form>}
  </>}
  <BioWriteStatus writer={writer}/>
 </section>
}
