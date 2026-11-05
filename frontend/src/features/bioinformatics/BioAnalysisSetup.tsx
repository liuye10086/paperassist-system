import SingleCellSetup from './SingleCellSetup'
import TabularAnalysisSetup from './TabularAnalysisSetup'
import type {TabularSetup} from './tabularContracts'
import type {BioSetupRequest,BioRunRequest} from './spatialContracts'
import {useBioRead} from './spatialHooks'
import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import type {AnalysisNavigation} from '../projects/analysisViews'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {projectBase} from './api'
import {BioJson,BioSource,BioWriteStatus} from './BioSpatialShared'
import type {BioCapabilities,BioRecipe,BioRecipeParameters,BioRun,BioSetup} from './spatialContracts'
import {isRawBioSource} from './spatialContracts'
import useBioWrite from './useBioWrite'
import BioObservationMapping from './BioObservationMapping'
import ModuleViews,{ModuleView} from '../../shared/components/ModuleViews'
import './bioLayout.css'

type SetupProps={projectId:string;setupId:string;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}
export default function BioAnalysisSetup(props:SetupProps){
 const read=useBioRead<BioSetup|TabularSetup>(`${projectBase(props.projectId)}/bio-analysis-setups/${encodeURIComponent(props.setupId)}`)
 if(read.value?.current_recipe.recipe_code==='tabular_quantitative_v1')return <TabularAnalysisSetup {...props} data={read.value as TabularSetup} valid={read.valid} error={read.error} reload={read.reload}/>
 return <VisiumAnalysisSetup {...props} read={{...read,value:read.value as BioSetup|null}}/>
}
function VisiumAnalysisSetup({projectId,setupId,onNavigate,registerLeaveGuard,read}:SetupProps&{read:ReturnType<typeof useBioRead<BioSetup>>}){
 const {t}=useI18n(),base=projectBase(projectId)
 const [paramsDraft,setParams]=useState<BioRecipeParameters|null>(null),[baseline,setBaseline]=useState(''),[mapDraft,setMapVersion]=useState<string|null|undefined>(),[designDraft,setDesignVersion]=useState<string|undefined>()
 const data=read.value,source=data?.raw_source,singleCell=data?.current_recipe.recipe_code==='single_cell_explore_v1'
 const params=paramsDraft??data?.current_recipe.params??null,mapVersion=mapDraft===undefined?data?.current_recipe.observation_map_version_id??null:mapDraft,designVersion=designDraft??data?.current_recipe.design_version_id??''
 const capability=useBioRead<BioCapabilities>(source?`${base}/bio-analysis-capabilities?dataset_id=${encodeURIComponent(source.dataset_id)}&version_id=${encodeURIComponent(source.dataset_version_id)}`:'')
 const saved=(v:BioRecipe)=>{setParams(v.params);setBaseline(JSON.stringify(v.params));read.reload()}
 const writer=useBioWrite<BioRecipe>(projectId,'recipe',saved,()=>{setBaseline(JSON.stringify(params));read.reload()})
 const run=useBioWrite<BioRun>(projectId,'run',v=>onNavigate({view:'bio-analysis',fileId:'',runId:v.id}),v=>onNavigate({view:'bio-analysis',fileId:'',runId:v.id}))
 const dirty=!!data&&!!params&&(JSON.stringify(params)!==(baseline||JSON.stringify(data.current_recipe.params))||mapVersion!==data.current_recipe.observation_map_version_id||designVersion!==(data.current_recipe.design_version_id??''))
 useDraftLeaveGuard(registerLeaveGuard,dirty&&!writer.completed,writer.busy||writer.unknown||run.busy||run.unknown)
 if(!data)return <section className="bio-workspace"><h2>{t(singleCell?'单细胞分析配置':'空间分析配置')}</h2>{read.error?<p role="alert">{t(read.error)}</p>:<p role="status">{t('正在读取固定版本……')}</p>}<button onClick={read.reload}>{t('重新读取')}</button></section>
 if(!isRawBioSource(data.raw_source,projectId))return <p role="alert">{t('固定来源身份不匹配，请重新打开。')}</p>
 const blocked=writer.busy||writer.unknown||run.busy||run.unknown||!read.valid
 const update=<K extends keyof BioRecipeParameters>(key:K,value:BioRecipeParameters[K])=>{if(params){if(!baseline)setBaseline(JSON.stringify(data.current_recipe.params));setParams({...params,[key]:value})}}
 const fields:[keyof BioRecipeParameters,string,number,number|undefined][]=[['min_counts','最低 counts',0,undefined],['min_genes','最低检测基因数',0,undefined],['min_spots','基因最低 spot 数',1,undefined],['target_sum','标准化 target sum',1,undefined],['hvg_count','HVG 数量',1,undefined],['pca_components','PCA 成分数',1,undefined],['neighbors','邻居数',2,undefined],['resolution','Leiden resolution',0.01,undefined],['seed','随机 seed',0,undefined],['marker_top_n','每 cluster Top marker 数',1,undefined]]
 return <section className="bio-workspace intake-form bio-module-workspace"><header className="bio-workspace-header"><h2>{t(singleCell?'单细胞分析配置':'空间分析配置')}</h2><span>{data.name} · {t('配方版本')} {data.current_recipe.version}</span></header>{read.error&&<p role="alert">{t(read.error)}</p>}
 <ModuleViews label={t('分析配置模块')}>
 <ModuleView id="parameters" title={t('分析参数')}>
 <fieldset disabled={blocked||!params}><legend>{t('不可变分析配方')}</legend><div className="intake-rows">{params&&fields.map(([key,label,min,max])=><label key={key}>{t(singleCell&&key==='min_spots'?'基因最低 cell 数':label)}<input type="number" min={min} max={max} step={key==='resolution'?'any':1} value={String(params[key])} onChange={e=>update(key,Number(e.target.value) as never)}/></label>)}</div>{params&&<>{singleCell&&<SingleCellSetup value={{cell_labels:params.cell_labels??[],donor_design_confirmed:params.donor_design_confirmed??false,independence_basis:params.independence_basis??''}} onChange={value=>setParams({...params,...value,in_tissue_only:false})}/>}<label hidden={singleCell} className="intake-check"><input type="checkbox" disabled={singleCell} checked={params.in_tissue_only} onChange={e=>update('in_tissue_only',e.target.checked)}/>{t('仅保留组织内 spot')}</label><label>{t('最高 counts（留空为不设限）')}<input type="number" min="1" value={params.max_counts??''} onChange={e=>update('max_counts',e.target.value===''?null:Number(e.target.value))}/></label><label>{t('排除条码，每行一个')}<textarea value={params.exclude_barcodes.join('\n')} onChange={e=>update('exclude_barcodes',e.target.value.split(/\s+/).filter(Boolean))}/></label><label>{t('线粒体规则')}<select value={params.mt_rule.kind} onChange={e=>update('mt_rule',{kind:e.target.value as BioRecipeParameters['mt_rule']['kind'],feature_ids:[],prefix:null,confirmed:false})}><option value="unknown">{t('未知')}</option><option value="feature_ids">{t('稳定基因 ID 列表')}</option><option value="prefix">{t('基因符号前缀')}</option></select></label>{params.mt_rule.kind==='feature_ids'&&<label>{t('线粒体稳定基因 ID')}<textarea value={params.mt_rule.feature_ids.join('\n')} onChange={e=>update('mt_rule',{...params.mt_rule,feature_ids:e.target.value.split(/\s+/).filter(Boolean),confirmed:false})}/></label>}{params.mt_rule.kind==='prefix'&&<label>{t('线粒体符号前缀')}<input value={params.mt_rule.prefix??''} onChange={e=>update('mt_rule',{...params.mt_rule,prefix:e.target.value,confirmed:false})}/></label>}{params.mt_rule.kind!=='unknown'&&<label className="intake-check"><input type="checkbox" checked={params.mt_rule.confirmed} onChange={e=>update('mt_rule',{...params.mt_rule,confirmed:e.target.checked})}/>{t('已核对并确认此线粒体规则')}</label>}<p>{t('规则未确认时，线粒体比例为未知，不能据此过滤。')}</p><label>{t('最高线粒体比例（0–1）')}<input type="number" min="0" max="1" step="any" disabled={!params.mt_rule.confirmed} value={params.max_mt_fraction??''} onChange={e=>update('max_mt_fraction',e.target.value===''?null:Number(e.target.value))}/></label><label>{t('输出语言')}<select value={params.output_language} onChange={e=>update('output_language',e.target.value as 'en'|'zh-CN')}><option value="en">English</option><option value="zh-CN">简体中文</option></select></label></>}</fieldset>
 </ModuleView>
 <ModuleView id="mapping" title={t('观测映射')}><fieldset disabled={blocked||!params}><label>{t('固定实验设计版本 ID')}<input value={designVersion} onChange={e=>setDesignVersion(e.target.value)}/></label><p>{t('未关联实验设计时，供体及独立重复保持未知。')}</p></fieldset><BioObservationMapping projectId={projectId} source={data.raw_source} designVersionId={designVersion||null} currentVersionId={mapVersion} currentSetId={data.current_recipe.observation_map_set_id??null} onSaved={v=>setMapVersion(v.id)} registerLeaveGuard={registerLeaveGuard}/></ModuleView>
 <ModuleView id="capability" title={t('能力与来源')}><BioSource source={data.raw_source}/><p className="warning-panel">{t(singleCell?'cell 不代表独立供体；marker 仅为探索性 cell 群关联。':'spot 或组织片段不代表独立供体；marker 仅为探索性区域或 cluster 关联。')}</p>{capability.error&&<p role="alert">{t(capability.error)}</p>}{capability.value&&<><h3>{t('计算能力与设计缺口')}</h3><ul>{capability.value.blockers.map(s=><li key={s}>{s}</li>)}{capability.value.design_gaps.map(s=><li key={s}>{s}</li>)}</ul><h3>{t('资源上限')}</h3><BioJson value={capability.value.limits}/></>}</ModuleView>
 </ModuleViews>
 {dirty&&<p className="warning-panel">{t('有未保存的配方变更；保存新版本后才能启动运行。')}</p>}<BioWriteStatus writer={writer}/><BioWriteStatus writer={run}/><div className="intake-actions"><button type="button" disabled={blocked||!dirty} onClick={()=>params&&void writer.submit(`${base}/bio-analysis-setups/${encodeURIComponent(setupId)}/recipes`,{name:data.name,raw_source:data.raw_source,expected_revision:data.revision,...(singleCell?{recipe_code:'single_cell_explore_v1'}:{}),observation_map_version_id:mapVersion,design_version_id:designVersion||null,params} satisfies BioSetupRequest)}>{t('保存新配方版本')}</button><button type="button" disabled={blocked||dirty||!capability.value?.available} onClick={()=>void run.submit(`${base}/bio-analysis-runs`,{raw_source:data.raw_source,recipe_version_id:data.current_recipe_version_id,expected_setup_revision:data.revision} satisfies BioRunRequest)}>{t('启动 QC 运行')}</button><button type="button" disabled={blocked} onClick={read.reload}>{t('重新读取最新版本（保留草稿）')}</button></div></section>
}
