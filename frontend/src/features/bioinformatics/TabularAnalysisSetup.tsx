import {useEffect,useState} from 'react'
import {useI18n} from '../../shared/i18n'
import type {AnalysisNavigation} from '../projects/analysisViews'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {projectBase} from './api'
import {useBioRead} from './spatialHooks'
import {isRawBioSource,type BioRun} from './spatialContracts'
import type {TabularCapabilities,TabularParams,TabularRecipe,TabularSetup,TabularSetupRequest} from './tabularContracts'
import {assayLabels} from './tabularContracts'
import {BioJson,BioSource,BioWriteStatus} from './BioSpatialShared'
import useBioWrite from './useBioWrite'
import ModuleViews,{ModuleView} from '../../shared/components/ModuleViews'
import type {Version} from '../research-intake/contracts'
import BioDesignLinks from './BioDesignLinks'
import './bioLayout.css'

export default function TabularAnalysisSetup({projectId,data,valid,error,reload,onNavigate,registerLeaveGuard}:{projectId:string;data:TabularSetup;valid:boolean;error:string;reload:()=>void;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}) {
 const {t}=useI18n(),base=projectBase(projectId)
 const capability=useBioRead<TabularCapabilities>(`${base}/bio-analysis-capabilities?dataset_id=${encodeURIComponent(data.raw_source.dataset_id)}&version_id=${encodeURIComponent(data.raw_source.dataset_version_id)}`)
 const [draft,setDraft]=useState<TabularParams|null>(null),[design,setDesign]=useState<string|null>(null),[reconciliation,setReconciliation]=useState<{recipeId:string;from:TabularSetup}|null>(null)
 const params=draft??data.current_recipe.params,designVersion=design??data.current_recipe.design_version_id??''
 const reconcile=(recipeId:string,setupId:string)=>{setDraft(null);setDesign(null);if(setupId!==data.id){onNavigate({view:'bio-analysis-setup',fileId:'',setupId});return}setReconciliation({recipeId,from:data});reload()}
 const writer=useBioWrite<TabularRecipe>(projectId,'recipe',value=>reconcile(value.id,value.setup_id),value=>reconcile(value.id,value.root_id!))
 const run=useBioWrite<BioRun>(projectId,'run',value=>onNavigate({view:'bio-analysis',fileId:'',runId:value.id}),value=>onNavigate({view:'bio-analysis',fileId:'',runId:value.id}))
 const dirty=JSON.stringify(params)!==JSON.stringify(data.current_recipe.params)||designVersion!==(data.current_recipe.design_version_id??'')
 useDraftLeaveGuard(registerLeaveGuard,dirty&&!writer.completed,writer.busy||writer.unknown||run.busy||run.unknown)
 useEffect(()=>{if(reconciliation&&data!==reconciliation.from&&data.current_recipe.id===reconciliation.recipeId)setReconciliation(null)},[data,reconciliation])
 if(!isRawBioSource(data.raw_source,projectId))return <p role="alert">{t('固定来源身份不匹配，请重新打开。')}</p>
 const blocked=!valid||!writer.valid||!run.valid||writer.busy||writer.unknown||run.busy||run.unknown
 const awaiting=!!reconciliation&&data===reconciliation.from
 const advanced=!!reconciliation&&!awaiting&&data.current_recipe.id!==reconciliation.recipeId
 const current=!awaiting&&!advanced
 const info=capability.value,logged=!!info&&['log2','ln','log10'].includes(info.scale?.kind??'')
 const update=<K extends keyof TabularParams>(key:K,value:TabularParams[K])=>setDraft({...params,[key]:value})
 const lines=(value:string)=>value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean)
 const save=()=>void writer.submit(`${base}/bio-analysis-setups/${encodeURIComponent(data.id)}/recipes`,{recipe_code:'tabular_quantitative_v1',name:data.name,raw_source:data.raw_source,expected_revision:data.revision,observation_map_version_id:null,design_version_id:designVersion||null,params} satisfies TabularSetupRequest)
 return <section className="bio-workspace intake-form bio-module-workspace">
  <header className="bio-workspace-header"><h2>{t('定量分析配置')}</h2><span>{data.name} · {t('配方版本')} {data.current_recipe.version}</span></header>
  {error&&<p role="alert">{t(error)}</p>}
  <ModuleViews label={t('分析配置模块')} lazy>
  <ModuleView id="parameters" title={t('分析参数')}>
  <fieldset disabled={blocked||!current}><legend>{t('不可变分析配方')}</legend>
   <label>{t('标准化处理')}<select value={params.normalization} onChange={e=>update('normalization',e.target.value as TabularParams['normalization'])}><option value="none">{t('保持输入尺度，不归一化')}</option><option value="already_normalized">{t('上游已归一化（见尺度记录）')}</option>{!logged&&info?.assay!=='bulk_rna_counts'&&<option value="median">{t('正值矩阵中位数校正')}</option>}{info?.assay==='bulk_rna_counts'&&<option value="display_library_size">{t('按文库大小归一化显示层')}</option>}</select></label>
   <label>{t('数值变换')}<select value={params.transform} disabled={logged} onChange={e=>update('transform',e.target.value as TabularParams['transform'])}>{['none','log2','ln','log10',...(info?.assay==='bulk_rna_counts'?['log1p']:[])].map(v=><option value={v} key={v}>{v}</option>)}</select></label>
   {params.transform==='log1p'&&<p>{t('显式 counts 展示变换 ln(1+x)，固定偏移 1；原始 counts 和差异模型输入不变。')}</p>}{logged&&<p>{t('输入已为对数尺度，保持原尺度，不再次取对数。')}</p>}
   <label>{t('缩放处理')}<select value={params.scaling} onChange={e=>update('scaling',e.target.value as TabularParams['scaling'])}><option value="none">{t('不缩放')}</option><option value="unit_variance">{t('按特征单位方差缩放')}</option></select></label>
   <label>{t('排除样本 ID（每行一个）')}<textarea value={params.exclude_samples.join('\n')} onChange={e=>update('exclude_samples',lines(e.target.value))}/></label>
   <label>{t('排除特征 ID（每行一个）')}<textarea value={params.exclude_features.join('\n')} onChange={e=>update('exclude_features',lines(e.target.value))}/></label>
   <label>{t('PCA 成分数')}<input type="number" min={2} max={100} value={params.pca_components} onChange={e=>update('pca_components',Number(e.target.value))}/></label>
   <label>{t('随机 seed')}<input type="number" min={0} step={1} value={params.seed} onChange={e=>update('seed',Number(e.target.value))}/></label>
   <label>{t('输出语言')}<select value={params.output_language} onChange={e=>update('output_language',e.target.value as 'en'|'zh-CN')}><option value="zh-CN">简体中文</option><option value="en">English</option></select></label>
  </fieldset>
  </ModuleView>
  <ModuleView id="design" title={t('实验设计')}><DesignVersionPicker key={projectId} projectId={projectId} value={designVersion} onChange={setDesign} disabled={blocked||!current}/><BioDesignLinks projectId={projectId}/></ModuleView>
  <ModuleView id="capability" title={t('能力与来源')}>
   <BioSource source={data.raw_source}/>
   {capability.error&&<p role="alert">{t(capability.error)}</p>}
   {info&&<><p>{info.assay?t(assayLabels[info.assay]):''} · {info.scale?.kind} · {info.scale?.unit}</p>{info.scale?.upstream_method&&<p>{info.scale.upstream_method}</p>}<ul>{[...info.blockers,...info.design_gaps].map(item=><li key={item}>{item}</li>)}</ul><h3>{t('资源上限')}</h3><BioJson value={info.limits}/></>}
   <p>{t('缺失值保留；每特征比较使用实际有效样本。PCA 仅使用完整特征，不自动插补；不足时记录不可计算原因。')}</p>
  </ModuleView>
  </ModuleViews>
  {dirty&&<p className="warning-panel">{t('有未保存的配方变更；保存新版本后才能启动运行。')}</p>}{awaiting&&<p role="status">{t('正在读取已保存的配方版本……')}</p>}
  {advanced&&<div className="warning-panel"><p>{t('当前配方已前进到其他版本。请核对上方参数，再采用当前版本。')}</p><button type="button" disabled={blocked} onClick={()=>{setReconciliation(null);setDraft(null);setDesign(null)}}>{t('核对并采用当前配方版本')}</button></div>}
  <BioWriteStatus writer={writer}/><BioWriteStatus writer={run}/>
  <div className="intake-actions"><button type="button" disabled={blocked||!current||!dirty} onClick={save}>{t('保存新配方版本')}</button><button type="button" disabled={blocked||!current||dirty||!info?.available} onClick={()=>void run.submit(`${base}/bio-analysis-runs`,{raw_source:data.raw_source,recipe_version_id:data.current_recipe_version_id,expected_setup_revision:data.revision})}>{t('启动 QC 运行')}</button><button type="button" disabled={blocked} onClick={reload}>{t('重新读取最新版本（保留草稿）')}</button></div>
 </section>
}

type DesignVersion=Pick<Version,'id'|'version'|'operation'>
function DesignVersionPicker({projectId,value,onChange,disabled}:{projectId:string;value:string;onChange:(id:string)=>void;disabled:boolean}){
 const {t}=useI18n(),[page,setPage]=useState(1)
 const read=useBioRead<{items:DesignVersion[];total:number}>(`${projectBase(projectId)}/research-designs?page=${page}&page_size=5`)
 const options=read.value?.items??[]
 return <><label>{t('关联实验设计')}<select value={value} disabled={disabled||!read.valid} onChange={e=>onChange(e.target.value)}>
  <option value="">{t('未关联实验设计')}</option>
  {value&&!options.some(option=>option.id===value)&&<option value={value}>{t('当前关联设计')}</option>}
  {options.map(option=><option key={option.id} value={option.id}>{t('版本 {number}',{number:option.version})} · {t(option.operation==='confirm'?'已确认':'已保存')}</option>)}
 </select></label>{read.error&&<p role="alert">{t('实验设计读取失败，请重试。')}</p>}
 {read.error&&<button type="button" disabled={!read.valid} onClick={read.reload}>{t('重新读取')}</button>}
 <div className="intake-actions">{page>1&&<button type="button" disabled={disabled||!read.valid} onClick={()=>setPage(current=>current-1)}>{t('上一页')}</button>}{!!read.value&&page*5<read.value.total&&<button type="button" disabled={disabled||!read.valid} onClick={()=>setPage(current=>current+1)}>{t('下一页')}</button>}</div>
 <p>{t('未关联实验设计时，供体及独立重复保持未知。')}</p></>
}
