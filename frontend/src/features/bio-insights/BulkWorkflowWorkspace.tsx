import {apiError,useI18n} from '../../shared/i18n'
import type {NativeDeliveryTarget} from '../analyst/NativeDeliveryArtifact'
import {bulkWorkflowViews, type AnalysisNavigation, type BulkWorkflowView} from '../projects/analysisViews'
import type {ProjectFile} from '../files/fileLibraryApi'
import useResearchDraft from '../research-results/useResearchDraft'
import {kindLabels} from './contracts'
import {useInsightRead} from './hooks'
import {ReadState} from './InsightShared'
import BulkSensitivity from './BulkSensitivity'
import BulkDelivery from './BulkDelivery'
import {bulkEnrichmentReason} from './BulkEnrichmentResult'
import {
  bulkRoute, bulkWorkflowBase, bulkWorkflowLabels, bulkWorkflowStatuses, publishedBulkComparisons,
  type BulkSensitivityRequest, type BulkWorkflowItem, type BulkWorkflowOverview, type BulkWorkflowRefs,
} from './bulkWorkflow'
import './bulkWorkflow.css'

type Props = {
  projectId:string
  navigation:AnalysisNavigation
  active:boolean
  allowNewAnalysis:boolean
  files:ProjectFile[]
  outputLanguage?:'zh-CN'|'en'
  onNavigate:(navigation:AnalysisNavigation)=>void
  onUpload:()=>void
  deliveryTarget?:NativeDeliveryTarget
}

export function BulkWorkflowNav({view,nested,onNavigate}:{
  view:BulkWorkflowView; nested:boolean; onNavigate:(navigation:AnalysisNavigation)=>void
}) {
  const {t}=useI18n()
  return <nav className="analysis-page-tabs bulk-workflow-nav" aria-label={t('Bulk RNA-seq 工作流')}>
    {bulkWorkflowViews.map(key=><button key={key} type="button" aria-current={key===view?'page':undefined}
      aria-pressed={key===view} onClick={()=>onNavigate(bulkRoute(key))}>{t(bulkWorkflowLabels[key])}</button>)}
    {nested&&<button className="bulk-workflow-return" type="button" onClick={()=>onNavigate(bulkRoute(view))}>{t('返回步骤概览')}</button>}
  </nav>
}

export default function BulkWorkflowWorkspace({projectId,navigation,active,allowNewAnalysis,files,outputLanguage,onNavigate,onUpload,deliveryTarget}:Props) {
  const {t}=useI18n()
  const [reviewed,setReviewed]=useResearchDraft<BulkSensitivityRequest|{byComparison:Record<string,BulkSensitivityRequest>}|null>(
    projectId,'bulk-workflow-reviewed-sensitivity',()=>null)
  const sensitivity=reviewed?'byComparison' in reviewed?reviewed.byComparison:{[reviewed.baseline_version_id]:reviewed}:{}
  const overview=useInsightRead<BulkWorkflowOverview>(bulkWorkflowBase(projectId),active,false,
    data=>data.stages.some(stage=>[stage,...stage.items].some(item=>['queued','running'].includes(item.status))))
  const data=overview.data?.project_id===projectId?overview.data:null
  const view=navigation.bulkView??'design'
  const stage=data?.stages.find(item=>item.key===view)
  const dataStage=data?.stages.find(item=>item.key==='data')
  const qcStage=data?.stages.find(item=>item.key==='qc')
  const reusableQc=qcStage?.reusable_processed_refs?.processed_version_id
  const differentialSource=reusableQc??(!qcStage?.stale?qcStage?.refs.processed_version_id:null)
  const comparisons=publishedBulkComparisons(data?.comparisons??[])
  const comparison=comparisons.find(item=>!item.stale&&item.refs.result_version_id===data?.stages.find(s=>s.key==='delivery')?.refs.result_version_id)
  if(!active) return null
  return <section className="bulk-workflow-body">
    <header className="analysis-section-heading">
      <h2>{t(bulkWorkflowLabels[view])}</h2>
      <button type="button" disabled={overview.loading} onClick={overview.refresh}>{t('刷新步骤状态')}</button>
    </header>
    <ReadState {...overview}/>
    {overview.data&&!data&&<p role="alert">{t('固定来源身份不匹配，请重新打开。')}</p>}
    {stage&&<StageVersions {...{projectId,view,stage,onNavigate}}/>}
    <div className="intake-actions">
      {view==='data'&&<>
        <button type="button" onClick={onUpload}>{t('上传 counts 矩阵与样本表')}</button>
        <button type="button" onClick={()=>onNavigate({view:'bio-datasets',fileId:'',bulkView:'data'})}>{t('导入并核对 Bulk 矩阵')}</button>
      </>}
      {view==='qc'&&dataStage?.refs.dataset_id&&dataStage.refs.dataset_version_id&&allowNewAnalysis&&
        <button type="button" onClick={()=>onNavigate({view:'bio-dataset',fileId:'',bulkView:'qc',
          datasetId:dataStage.refs.dataset_id!,versionId:dataStage.refs.dataset_version_id!})}>{t('从当前数据集配置质控')}</button>}
      {view==='differential'&&differentialSource&&allowNewAnalysis&&
        <button type="button" onClick={()=>onNavigate({view:'bio-insights',fileId:'',bulkView:'differential',
          processedId:differentialSource})}>{t('从当前质控版本配置差异分析')}</button>}
      {view==='functional'&&<>
        {comparison&&allowNewAnalysis&&<button type="button" onClick={()=>onNavigate({view:'bio-insight-result',fileId:'',bulkView:'functional',
          resultVersionId:comparison.refs.result_version_id!})}>{t('从当前比较配置 ORA 或 GSEA')}</button>}
        <button type="button" onClick={()=>onNavigate({view:'bio-resources',fileId:'',bulkView:'functional'})}>{t('管理固定功能与注释资源')}</button>
      </>}
    </div>
    {view==='differential'&&data&&<BulkSensitivity key={navigation.resultVersionId??'default'} projectId={projectId} comparisons={comparisons}
      initialId={navigation.resultVersionId} onReviewed={value=>setReviewed({byComparison:{...sensitivity,[value.baseline_version_id]:value}})}/>}
    {view==='delivery'&&data&&<BulkDelivery {...{projectId,comparisons,files,outputLanguage,onNavigate,sensitivity,deliveryTarget}}
      descendants={data.descendants} initialId={navigation.resultVersionId}/>}
  </section>
}

const versionKey = (refs:BulkWorkflowRefs) => refs.result_version_id??refs.insight_run_id??refs.plan_version_id??
  refs.processed_version_id??refs.analysis_run_id??refs.recipe_version_id??refs.observation_map_version_id??refs.dataset_version_id??
  refs.import_id??refs.setup_id??refs.design_version_id??refs.resource_version_id??refs.task_id??refs.dataset_id
const staleLabels:Record<string,string>={dataset_version:'数据集版本已变更',design_version:'研究设计版本已变更',
  observation_map_version:'样本对应版本已变更',recipe_version:'质控设置已变更',plan_version:'分析计划版本已变更',resource_version:'功能资源版本已变更'}
const workflowItemLabels:Record<string,string>={...kindLabels,design:'研究设计',import:'导入与检查',observation_map:'样本对应表',
  analysis:'质控运行',recipe:'质控设置',resource:'功能与注释资源'}
const statusLabel=(item:{status:string;operation?:'save'|'confirm'}) => item.operation==='save'?'已保存':
  item.operation==='confirm'?'已确认':bulkWorkflowStatuses[item.status]??item.status

function StageVersions({projectId,view,stage,onNavigate}:{
  projectId:string;view:BulkWorkflowView;stage:BulkWorkflowOverview['stages'][number];onNavigate:Props['onNavigate']
}) {
  const {t,locale}=useI18n()
  const currentId=versionKey(stage.refs)
  const current=stage.items.find(item=>currentId&&versionKey(item.refs)===currentId)
  const history=stage.items.filter(item=>item!==current)
  return <section className="analysis-detail bulk-stage-summary" aria-label={t('当前流程状态')}>
    <h3>{t('当前流程状态')} · {t(statusLabel(stage))}</h3>
    <VersionFreshness stale={stage.stale} reasons={stage.stale_reasons}/>
    {current?.label&&<p>{current.label}</p>}
    {currentId&&<p>{t('当前流程版本')} <code>{currentId}</code></p>}
    <Outcome reason={stage.reason} errorCode={current?.error_code}/>
    {stage.status==='dependency_blocked'&&stage.depends_on.length>0&&<div className="intake-actions">
      {stage.depends_on.map(key=><button type="button" key={key} onClick={()=>onNavigate(bulkRoute(key))}>{t(bulkWorkflowLabels[key])}</button>)}
    </div>}
    <VersionActions {...{projectId,view,onNavigate}} refs={stage.refs}/>
    {!!current?.steps?.length&&<details>
      <summary>{t('实际步骤状态和缺口')}</summary>
      <ul>{current.steps.map(step=><li key={step.key}>{t(step.key)} · {t(bulkWorkflowStatuses[step.status]??step.status)}
        {step.reason&&<> · {t(step.reason)}</>}
      </li>)}</ul>
    </details>}
    {view==='qc'&&stage.reusable_processed_refs?.processed_version_id&&<>
      <p>{t('可复用质控版本')} · <code>{stage.reusable_processed_refs.processed_version_id}</code></p>
      <VersionActions {...{projectId,view,onNavigate}} refs={stage.reusable_processed_refs}/>
    </>}
    {history.length>0&&<details className="bulk-stage-history">
      <summary>{t('固定版本与历史记录')} · {history.length}</summary>
      <ul className="bulk-history-list">{history.map((item,index)=><li key={`${item.kind}:${versionKey(item.refs)??index}`}>
        <strong>{item.label||t(workflowItemLabels[item.kind]??item.kind)}</strong>
        {' · '}{t(statusLabel(item))}
        {item.created_at&&<> · <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString(locale)}</time></>}
        <p><code>{versionKey(item.refs)}</code></p>
        <VersionFreshness stale={item.stale} reasons={item.stale_reasons} historical/>
        <Outcome reason={item.reason} errorCode={item.error_code}/>
        <VersionActions {...{projectId,view,onNavigate}} refs={item.refs}/>
      </li>)}</ul>
    </details>}
  </section>
}

function Outcome({reason,errorCode}:{reason?:string|null;errorCode?:string|null}) {
  const {t}=useI18n()
  if(errorCode) return <p role="status">{t(apiError({code:errorCode},'执行失败'))} · <code>{errorCode}</code></p>
  return reason?<p>{t(bulkEnrichmentReason(reason))}</p>:null
}

function VersionFreshness({stale,reasons,historical=false}:{stale:boolean;reasons:BulkWorkflowItem['stale_reasons'];historical?:boolean}) {
  const {t}=useI18n()
  if(!stale) return null
  return <div className="warning-panel"><p>{t(historical?'此历史版本使用旧依赖，固定结果仍可读取。':'当前流程已过期，原固定版本仍可读取。')}</p>
    {reasons.length>0&&<ul>{reasons.map(reason=><li key={`${reason.kind}:${reason.version_id}`}>
      {t(staleLabels[reason.kind]??reason.kind)} · <code>{reason.version_id}</code>{reason.current_version_id&&<> → <code>{reason.current_version_id}</code></>}
    </li>)}</ul>}
  </div>
}

function VersionActions({projectId,view,refs,onNavigate}:{
  projectId:string;view:BulkWorkflowView;refs:BulkWorkflowRefs;onNavigate:Props['onNavigate']
}) {
  const {t}=useI18n()
  const route=(next:Omit<AnalysisNavigation,'fileId'|'bulkView'>)=>onNavigate({...next,fileId:'',bulkView:view})
  return <div className="intake-actions">
    {view==='data'&&refs.import_id&&<button type="button" onClick={()=>route({view:'bio-import',importId:refs.import_id!})}>{t('打开导入核对记录')}</button>}
    {view==='data'&&refs.dataset_id&&refs.dataset_version_id&&<button type="button" onClick={()=>route({view:'bio-dataset',datasetId:refs.dataset_id!,versionId:refs.dataset_version_id!})}>{t('打开固定数据集版本')}</button>}
    {view==='qc'&&refs.setup_id&&<button type="button" onClick={()=>route({view:'bio-analysis-setup',setupId:refs.setup_id!})}>{t('打开质控设置')}</button>}
    {view==='qc'&&refs.analysis_run_id&&<button type="button" onClick={()=>route({view:'bio-analysis',runId:refs.analysis_run_id!})}>{t('打开质控运行')}</button>}
    {view==='qc'&&refs.processed_version_id&&<button type="button" onClick={()=>route({view:'bio-result',processedId:refs.processed_version_id!,tab:'qc'})}>{t('打开固定质控结果')}</button>}
    {view==='functional'&&refs.resource_version_id&&<button type="button" onClick={()=>route({view:'bio-resources',resourceVersionId:refs.resource_version_id!})}>{t('打开固定资源版本')}</button>}
    {['differential','functional','delivery'].includes(view)&&refs.plan_id&&refs.plan_version_id&&
      <button type="button" onClick={()=>route({view:'bio-insight-plan',planId:refs.plan_id!,planVersionId:refs.plan_version_id!})}>{t('打开固定计划')}</button>}
    {refs.insight_run_id&&<button type="button" onClick={()=>route({view:'bio-insight-plan',runId:refs.insight_run_id!})}>{t('打开分析运行')}</button>}
    {refs.result_version_id&&<button type="button" onClick={()=>route({view:'bio-insight-result',resultVersionId:refs.result_version_id!})}>{t('查看固定结果')}</button>}
    {refs.task_id&&<a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(refs.task_id)}`}>{t('查看任务进度与恢复')}</a>}
  </div>
}
