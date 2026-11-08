import {useI18n} from '../../shared/i18n'
import useResearchDraft from '../research-results/useResearchDraft'
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

type Props={allowNewAnalysis?:boolean;projectId:string;source:RawBioSource;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard;initialParams?:BioRecipeParameters;observationMapVersionId?:string|null;designVersionId?:string|null}
type Draft={params:BioRecipeParameters|null;name:string;step:'parameters'|'review'}
export default function SingleCellDirectStart(props:Props){
 const scope=`single-cell-analysis:${props.source.dataset_id}:${props.source.dataset_version_id}:${props.observationMapVersionId??''}:${props.designVersionId??''}:${JSON.stringify(props.initialParams??null)}`
 return <SingleCellStartForm key={`${props.projectId}:${scope}`} {...props} scope={scope}/>
}
function SingleCellStartForm({allowNewAnalysis=true,projectId,source,onNavigate,registerLeaveGuard,initialParams,observationMapVersionId,designVersionId,scope}:Props&{scope:string}){
 const {t}=useI18n(),base=projectBase(projectId)
 const read=useBioRead<BioCapabilities>(`${base}/bio-analysis-capabilities?dataset_id=${encodeURIComponent(source.dataset_id)}&version_id=${encodeURIComponent(source.dataset_version_id)}`)
 const [saved,setSaved]=useResearchDraft<Draft>(projectId,scope,()=>({params:initialParams??null,name:'Single-cell exploratory analysis',step:'parameters'}))
 const {params:draft,name,step}=saved
 const setDraft=(params:BioRecipeParameters)=>setSaved(value=>({...value,params}))
 const setName=(name:string)=>setSaved(value=>({...value,name}))
 const setStep=(step:Draft['step'])=>setSaved(value=>({...value,step}))
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
  <p>{t('来源和参数相同时使用已有分析；修改后建立新分析，已有结果保留。')}</p>
  <p>{t('未知供者不影响探索；cell 不代表独立供者，marker 仅为探索性 cell 群关联。')}</p>
  {read.error&&<p role="alert">{t(read.error)}</p>}
  {read.value&&<><ul>{blockers.map(v=><li key={v}>{t(resourceReasons[v]??v)}</li>)}</ul>
   {estimate&&<section aria-label="资源估算"><h4>{t('矩阵规模与资源估算')}</h4>
    <p>{number(estimate.matrix.observations)} {t('个细胞')} × {number(estimate.matrix.features)} {t('个基因')}；{resourceAvailable?t('当前资源可用'):t('当前资源不足')}</p>
    <section className="customer-advanced-details"><h4>{t('高级资源详情')}</h4>
      <p>{t('矩阵非零元素')}：{number(estimate.matrix.nnz)}；{t('原始 CSR')}：{memory(estimate.sparse_bytes)}；{t('当前 HVG 密集块上界')}：{memory(denseValues===null?null:denseValues*4)}（{number(denseValues)} values）</p>
      <p>{t('当前上限')}：{number(estimate.configured_limits.max_observations)} {t('个细胞')} / {number(estimate.configured_limits.max_features)} {t('个基因')} / {number(estimate.configured_limits.max_entries)} nnz；HVG {number(estimate.configured_limits.max_dense_values)} values；{t('进程内存限制')} {memory(selectedLimits?.memory_bytes??null)}</p>
      <p>{t('仅为估算：原始 CSR 按 int64 counts 与索引计算，HVG 按当前参数和 float32 计算，QC 后可能减少。未包含 R 模型及校正副本、标准化副本、PCA、邻居、绘图和运行环境开销，不是进程峰值承诺。')}</p>
    </section>
   </section>}
   {params&&<form onSubmit={event=>{event.preventDefault();if(blocked||!resourceAvailable)return;if(step==='parameters'){setSaved(value=>({...value,params,step:'review'}));return}if(!allowNewAnalysis)return;void writer.submit(`${base}/single-cell-analysis-runs`,{name,raw_source:source,...(observationMapVersionId?{observation_map_version_id:observationMapVersionId}:{}),...(designVersionId?{design_version_id:designVersionId}:{}),params:{...params,in_tissue_only:false}})}}>
    <fieldset hidden={step!=='parameters'} disabled={blocked||step!=='parameters'}><legend>{t('分析参数')}</legend>
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
    {step==='review'&&<section aria-label={t('分析前核对')}>
     <h4>{t('检查并运行')}</h4><p>{name}</p>
     <dl className="bio-source"><dt>{t('最低 counts')}</dt><dd>{params.min_counts}</dd><dt>{t('最低检测基因数')}</dt><dd>{params.min_genes}</dd><dt>{t('HVG 数量')}</dt><dd>{params.hvg_count}</dd><dt>{t('输出语言')}</dt><dd>{params.output_language==='en'?'English':'简体中文'}</dd></dl>
     <p>{t('流程：细胞质控 → 标准化 → 降维与聚类 → 图表与 Word。')}</p>
     <p>{t('点击开始后才会提交计算；任务按顺序排队，完成后可查看结果和下载 Word。')}</p>
     <ul>{params.doublet?.enabled&&<li>{t('运行 scDblFinder 双细胞检测')}</li>}{params.decontx?.enabled&&<li>{t('运行 decontX 环境 RNA 校正')}</li>}{params.harmony?.enabled&&<li>{t('启用 Harmony 批次整合')}</li>}{!!params.technical_covariates?.length&&<li>{t('技术协变量处理')}：{params.technical_covariates.join('、')}</li>}</ul>
    </section>}
    <footer className="bio-confirmation-actions">
     {step==='review'&&<button type="button" disabled={blocked} onClick={()=>setStep('parameters')}>{t('上一步：调整参数')}</button>}
     <button type="submit" className="button-primary" disabled={blocked||!resourceAvailable||step==='review'&&!allowNewAnalysis}>{t(step==='parameters'?'下一步：检查并运行':'开始单细胞分析')}</button>
    </footer>
   </form>}
  </>}
  {!allowNewAnalysis&&<p role="status">{t('新分析条件尚未就绪；已有结果仍可查看下载，请先核对材料并保存需求。')}</p>}<BioWriteStatus writer={writer}/>
 </section>
}
