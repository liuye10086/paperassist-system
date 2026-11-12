import {useEffect,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {useI18n} from '../../shared/i18n'
import type {TabularProcessed} from '../bioinformatics/tabularContracts'
import type {AnalysisNavigation} from '../projects/analysisViews'
import type {NativeDeliveryTarget} from '../analyst/NativeDeliveryArtifact'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import useResearchDraft from '../research-results/useResearchDraft'
import type {Source as ResearchSource} from '../research-results/contracts'
import {projectBase} from './api'
import {useInsightRead} from './hooks'
import {kindLabels,type InsightKind,type Page,type Plan,type Result,type Run} from './contracts'
import {defaultConfig,isInsightView,number,strings} from './state'
import {bulkPanelFigureType,bulkPanelTab,bulkPlanScope,bulkProcessedMatches,isBulkEnrichmentFigure,isBulkEnrichmentResult,isBulkFigureType,isReviewedBulkComparison,type BulkPlanSeed} from './bulk'
import {DataDetails,Field,Paging,ReadState} from './InsightShared'
import InsightPlanEditor,{InsightRun} from './InsightPlanEditor'
import InsightResults from './InsightResults'
import InsightResources from './InsightResources'
import {queueResearchSource} from './researchHandoff'
import './insights.css'
type Props={allowExternalEvidenceRegistration?:boolean;allowNewAnalysis?:boolean;deliveryTarget?:NativeDeliveryTarget;projectId:string;navigation:AnalysisNavigation;active:boolean;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}
export default function BioInsightsWorkspace(props:Props){return props.active&&isInsightView(props.navigation.view)?<Content key={`${props.projectId}:${props.navigation.entry?.requirementVersionId??''}:${props.navigation.entry?.scopeItemId??''}:${props.navigation.intent??''}`} {...props}/>:null}
function Content({projectId,navigation:n,active,onNavigate,registerLeaveGuard,allowNewAnalysis=true,allowExternalEvidenceRegistration,deliveryTarget}:Props){
 const{t}=useI18n(),[valid,setValid]=useState(true),[page,setPage]=useState(1),[runPage,setRunPage]=useState(1),[newKind,setNewKind]=useState<InsightKind>(navigationKind(n)??'comparison')
 const [workflowSeeds,setWorkflowSeeds]=useResearchDraft<Record<string,BulkPlanSeed>>(projectId,'bulk-workflow-plan-seeds',()=>({}))
 const workflowSeed=n.bulkView&&n.resultVersionId?workflowSeeds[`${n.bulkView}:${n.resultVersionId}`]:undefined
 const singleCellEnrichment=n.intent==='single_cell_enrichment'
 const enrichmentConfig=singleCellEnrichment&&n.view==='bio-resources'&&!!n.resultVersionId
 const defaultPanel=n.resourceVersionId||n.view==='bio-resources'&&!enrichmentConfig?'resources':n.view==='bio-insight-runs'||n.view==='bio-insight-plan'&&!n.planVersionId&&!n.runId?'history':workflowSeed?'plot':'current'
 const [panel,setPanel]=useState(defaultPanel),[historyPanel,setHistoryPanel]=useState(n.view==='bio-insight-runs'?'runs':'plans')
 const base=projectBase(projectId)
 const [seedEntry,setSeedEntry]=useState<{origin:string;seed:BulkPlanSeed}|null>(null)
 const resultRead=useInsightRead<Result>(n.resultVersionId?`${base}/bio-insight-results/${encodeURIComponent(n.resultVersionId)}`:'',active&&!!n.resultVersionId,true)
 const processedRead=useInsightRead<TabularProcessed>(n.bulkPanel&&n.processedId?`${base}/bio-processed-datasets/${encodeURIComponent(n.processedId)}`:'',active&&!!n.bulkPanel,true)
 const processedSeed = n.bulkPanel&&n.processedId&&processedRead.data&&bulkProcessedMatches(processedRead.data,projectId,n.processedId,n.bulkPanel)
  ?{source:{source_kind:'bio_processed_dataset_version',source_id:n.processedId,sha256:processedRead.data.manifest_sha256,role:'processed',locator:{kind:'object'}},
   config:{...defaultConfig('figure'),contrast_id:'',figure_type:bulkPanelFigureType(n.bulkPanel),bulk_panel:n.bulkPanel,result_source_id:n.processedId}} satisfies BulkPlanSeed
  :undefined
 const resultSeed = workflowSeed??(n.resultVersionId&&seedEntry?.origin===n.resultVersionId?seedEntry.seed:undefined)
 const seed = processedSeed??resultSeed
 const fixedBulk = isReviewedBulkComparison(resultRead.data)||isBulkFigureType(resultRead.data?.summary?.figure_type)
  ||isBulkEnrichmentResult(resultRead.data)||isBulkEnrichmentFigure(resultRead.data)
 const seedTab = resultSeed?.config.kind==='candidate'?'Bulk 候选计划':resultSeed?.config.bulk_enrichment!=null?'Bulk 富集计划':'Bulk 图件计划'
 const legacyPlot = !!n.resultVersionId&&!!resultRead.data&&!fixedBulk&&!singleCellEnrichment
 const capabilities=useInsightRead<Record<string,unknown>>(`${base}/bio-insights/capabilities`,active&&(panel==='environment'||singleCellEnrichment&&panel==='current'))
 const comparison=resultRead.data
 const enrichmentSource=singleCellEnrichment&&comparison&&comparison.id===n.resultVersionId&&canUseSingleCellComparison(comparison)?comparison:undefined
 const enrichmentRuntime=capabilities.data?.configured===true&&!capabilities.error&&!capabilities.loading
 const plans=useInsightRead<Page<Plan>>(`${base}/bio-insight-plans?page=${page}&page_size=20`,active&&panel==='history'&&historyPanel==='plans')
 const runs=useInsightRead<Page<Run>>(`${base}/bio-insight-runs?page=${runPage}&page_size=20`,active&&panel==='history'&&historyPanel==='runs',false,v=>v.items.some(r=>['queued','running'].includes(r.task.status)))
 const visibleRuns=(runs.data?.items??[]).filter(run=>!singleCellEnrichment||['comparison','ora','gsea_prerank'].includes(run.kind))
 const plan=useInsightRead<Plan>(n.planId&&n.planVersionId?`${base}/bio-insight-plans/${n.planId}/versions/${n.planVersionId}`:'',active&&!!n.planVersionId&&panel!=='resources'&&panel!=='environment',true)
 useEffect(()=>onApiSessionChanged(()=>setValid(false)),[])
 const intentKind=navigationKind(n),area=n.view==='bio-resources'?'resources':n.view==='bio-candidates'?'candidates':n.view==='bio-insight-result'?'figures':plan.data?.kind==='figure'?'figures':plan.data?.kind==='candidate'?'candidates':plan.data&&['ora','gsea_prerank'].includes(plan.data.kind)?'resources':!plan.data&&intentKind==='candidate'?'candidates':!plan.data&&intentKind==='figure'?'figures':!plan.data&&['ora','gsea_prerank'].includes(intentKind??'')?'resources':'comparison',kind=plan.data?.kind??(area==='candidates'?'candidate':area==='figures'?'figure':area==='resources'?(newKind==='gsea_prerank'?'gsea_prerank':'ora'):(['result_import','feature_extract','integration'] as InsightKind[]).includes(newKind)?newKind:'comparison')
 const entry={...(n.entry?{entry:n.entry,intent:n.intent}:{})}
 function openPlan(v:Plan){onNavigate({...entry,view:'bio-insight-plan',fileId:'',planId:v.plan_id,planVersionId:v.id})}
 function openRun(v:Run){onNavigate({...entry,view:'bio-insight-plan',fileId:'',runId:v.id})}
 function result(id:string){onNavigate({...entry,view:'bio-insight-result',fileId:'',resultVersionId:id})}
 function research(s:ResearchSource){queueResearchSource(projectId,s);onNavigate({...entry,view:'research-findings',fileId:''})}
 const routeKey=[n.view,n.planVersionId,n.runId,n.resultVersionId,n.resourceVersionId,n.processedId,n.bulkPanel,n.bulkView].join(':')
 const [resourcesVisited,setResourcesVisited]=useState(area==='resources');if((area==='resources'||!!n.resourceVersionId)&&!resourcesVisited)setResourcesVisited(true)
 const [panelRoute,setPanelRoute]=useState(routeKey)
 if(panelRoute!==routeKey){setPanelRoute(routeKey);setPanel(defaultPanel);if(n.view==='bio-insight-runs')setHistoryPanel('runs')}
 if(!valid)return <p role="alert">{t('会话已改变，请重新打开项目。')}</p>
 return <section className="insight-workspace" hidden={!active}>
 {!allowNewAnalysis&&<p role="status">{t('新分析条件尚未就绪；已有结果仍可查看下载，请先核对材料并保存需求。')}</p>}
 <nav className="analysis-page-tabs" aria-label={t('分析工作视图')}>{[['current','当前分析'],...(resultSeed?[['plot',seedTab]]:legacyPlot?[['plot','基于结果绘图']]:[]),['history','历史记录'],['resources','资源管理'],['environment','运行环境']].map(([key,label])=><button type="button" key={key} aria-pressed={panel===key} onClick={()=>{setPanel(key);if(key==='resources')setResourcesVisited(true)}}>{t(label)}</button>)}</nav>
 <div className="insight-current" hidden={panel!=='current'&&panel!=='plot'}>
 <header className="analysis-section-heading"><h2>{t('差异与功能分析')}</h2>{intentKind&&<span className="analysis-kind-summary">{t(kind==='integration'&&(plan.data?.config.schema_version===2||n.intent==='single_cell_topic')?'单细胞专题':kindLabels[kind])}</span>}{!n.entry&&!n.planVersionId&&!n.runId&&!n.resultVersionId&&!n.bulkPanel&&<nav className="insight-kind-nav" aria-label={t('差异与功能工作区')}>{([['comparison','比较设计与差异','bio-insights'],['resources','资源与富集','bio-resources'],['candidates','候选配方','bio-candidates'],['figures','图件与承接','bio-insight-result']] as const).map(([key,label,view])=><button key={key} type="button" aria-current={area===key?'page':undefined} onClick={()=>onNavigate({...entry,...(n.entry?{intent:key==='comparison'?'comparison':key==='resources'?(n.intent==='gsea_prerank'?'gsea_prerank':'ora'):key==='candidates'?(n.intent==='evidence'?'evidence':'candidate'):'figure'}:{}),view,fileId:'',...(view==='bio-insights'&&n.processedId?{processedId:n.processedId}:{})})}>{t(label)}</button>)}</nav>}</header>
 {n.runId&&<div className="insight-read-panel"><InsightRun key={n.runId} projectId={projectId} runId={n.runId} active={active} onResult={result} onPlan={(planId,planVersionId)=>onNavigate({...entry,view:'bio-insight-plan',fileId:'',planId,planVersionId})}/></div>}
 <ReadState {...plan}/>
 {singleCellEnrichment&&n.resultVersionId&&(enrichmentConfig||comparison?.kind==='comparison')&&<section className="insight-read-panel">
  <h3>{t('单细胞富集条件')}</h3>
  {enrichmentConfig&&<ReadState {...resultRead}/>}
  {comparison&&!enrichmentSource?<p>{t('请选择包含完整受检基因表的单细胞供者差异结果。')}</p>:enrichmentSource&&<>
   <ReadState {...capabilities}/>
   {capabilities.data&&!enrichmentRuntime&&!capabilities.loading&&!capabilities.error&&<p>{t('当前环境未验证 ORA 运行能力。')}</p>}
   {enrichmentRuntime&&allowNewAnalysis&&!enrichmentConfig&&<button type="button"
    onClick={()=>onNavigate({...entry,view:'bio-resources',fileId:'',resultVersionId:enrichmentSource.id})}>{t('配置本地 ORA 富集')}</button>}
  </>}
 </section>}
 {n.resultVersionId&&!enrichmentConfig&&<div className="insight-read-panel" hidden={panel==='plot'}>
  <InsightResults key={n.resultVersionId} projectId={projectId} resultId={n.resultVersionId} active={active&&panel==='current'}
   resultRead={resultRead} onResearch={research} allowNewAnalysis={allowNewAnalysis} deliveryTarget={deliveryTarget}
   onNavigate={next=>onNavigate({...entry,...next})} onBulkPlan={next=>{
    if(n.bulkView) {
      const target=next.config.bulk_enrichment!=null||next.config.bulk_enrichment_render?'functional':n.bulkView
      setWorkflowSeeds(previous=>({...previous,[`${target}:${n.resultVersionId}`]:next}))
      if(target!==n.bulkView)onNavigate({...n,bulkView:target})
    } else setSeedEntry({origin:n.resultVersionId!,seed:next})
    setPanel('plot')
   }}/>
 </div>}
 {n.bulkPanel&&<div className={processedSeed?'intake-actions':'insight-read-panel'}>
  <button type="button" onClick={()=>onNavigate({...entry,view:'bio-result',fileId:'',processedId:n.processedId,tab:bulkPanelTab(n.bulkPanel!)})}>{t('返回固定处理结果')}</button>
  <ReadState {...processedRead}/>
  {processedRead.data&&!processedSeed&&<p role="alert">{t('此固定处理版本没有可重绘的 Bulk QC 或 PCA 来源。')}</p>}
 </div>}
 {!n.planVersionId&&!n.runId&&!n.resultVersionId&&area!=='candidates'&&area!=='figures'&&!intentKind&&<div className="insight-kind-selection"><Field label="新计划类型" value={kind} onChange={v=>setNewKind(v as InsightKind)}>{(area==='resources'?['ora','gsea_prerank']:['comparison','result_import','feature_extract','integration']).map(k=><option key={k} value={k}>{t(kindLabels[k as InsightKind])}</option>)}</Field></div>}
 <div className="insight-editor-host" hidden={!!n.resultVersionId&&!enrichmentConfig&&panel!=='plot'}>
  {(!n.runId||n.planVersionId)&&(!n.planVersionId||plan.data)&&(!n.bulkPanel||processedSeed)&&
   (!n.resultVersionId||seed||legacyPlot||enrichmentConfig&&enrichmentSource)&&
   <InsightPlanEditor allowExternalEvidenceRegistration={allowExternalEvidenceRegistration} allowNewAnalysis={allowNewAnalysis&&(!singleCellEnrichment||enrichmentRuntime)} key={seed?bulkPlanScope(seed):`${plan.data?.id??kind}:${n.processedId??n.resultVersionId??''}`}
    projectId={projectId} kind={seed?.config.kind??kind} active={active} initial={plan.data}
    initialProcessedId={seed?undefined:n.processedId} initialResultId={seed||enrichmentConfig?undefined:n.resultVersionId} bulkSeed={seed} entryIntent={n.intent}
    entry={n.entry} enrichmentSource={enrichmentConfig?enrichmentSource:undefined}
    onSaved={v=>{plans.refresh();openPlan(v)}} onRun={v=>{runs.refresh();openRun(v)}} registerLeaveGuard={registerLeaveGuard}/>}
 </div>
 </div>
 <div className="insight-history" hidden={panel!=='history'}><header className="analysis-section-heading"><h2>{t('已有计划与运行记录')}</h2><button type="button" onClick={()=>{plans.refresh();runs.refresh()}}>{t('刷新计划与运行')}</button></header>
 <nav className="analysis-page-tabs" aria-label={t('分析历史视图')}>{[['plans','计划版本'],['runs','运行记录']].map(([key,label])=><button type="button" key={key} aria-pressed={historyPanel===key} onClick={()=>setHistoryPanel(key)}>{t(label)}</button>)}</nav><div className="insight-read-panel" hidden={historyPanel!=='plans'}>
 {plan.data&&<div className="intake-actions"><button type="button" onClick={()=>onNavigate({...entry,view:plan.data!.kind==='candidate'?'bio-candidates':plan.data!.kind==='figure'?'bio-insight-result':['ora','gsea_prerank'].includes(plan.data!.kind)?'bio-resources':'bio-insights',fileId:''})}>{t('另建独立计划，保留当前版本')}</button>{plan.data.parent_id&&<button type="button" onClick={()=>onNavigate({...entry,view:'bio-insight-plan',fileId:'',planId:plan.data!.plan_id,planVersionId:plan.data!.parent_id!})}>{t('查看上一计划版本')}</button>}</div>}
<ReadState {...plans}/>{plans.data&&!plans.data.items.length&&!plan.data&&<p>{t('暂无已保存计划')}</p>}<ul className="insight-history-list">{(plans.data?.items??(plan.data?[plan.data]:[])).map(v=><li key={v.id}><button type="button" onClick={()=>openPlan(v)}>{v.name} · {t(kindLabels[v.kind])} · v{v.revision} · {t(v.decision==='confirmed'?'已确认':'草稿')}</button></li>)}</ul>{plans.data&&<Paging page={page} total={plans.data.total} size={20} onPage={setPage}/>}
 </div><div className="insight-read-panel" hidden={historyPanel!=='runs'}>
 {singleCellEnrichment&&<p>{t('请选择已完成的单细胞供者差异结果，并核对匹配的本地基因集。')}</p>}
 <ReadState {...runs}/>{runs.data&&!visibleRuns.length&&<p>{t('暂无运行记录')}</p>}<ul className="insight-history-list">{visibleRuns.map(v=><li key={v.id}><button type="button" onClick={()=>openRun(v)}>{t(kindLabels[v.kind])} · {t(v.task.status)} · {v.id.slice(0,8)}</button>{v.result_version_id&&<button type="button" onClick={()=>result(v.result_version_id!)}>{t('查看固定结果')}</button>}</li>)}</ul>{runs.data&&<Paging page={runPage} total={runs.data.total} size={20} onPage={setRunPage}/>}</div></div>
 <div className="insight-read-panel" hidden={panel!=='resources'}>{resourcesVisited&&<InsightResources allowNewAnalysis={allowNewAnalysis} projectId={projectId} active={active&&panel==='resources'} selectedId={n.resourceVersionId} onSelect={id=>{
  const pinned=enrichmentConfig?n.resultVersionId:undefined
  setPanel('resources');setPanelRoute(['bio-resources','','',pinned??'',id??'','','',n.bulkView??''].join(':'))
  onNavigate({...entry,view:'bio-resources',fileId:'',resourceVersionId:id||undefined,...(pinned?{resultVersionId:pinned}:{})})
 }}/>}</div>
 <div className="insight-read-panel" hidden={panel!=='environment'}><ReadState {...capabilities}/><DataDetails title="计算能力、环境身份与限制" value={capabilities.data}/></div>
 </section>
}

function navigationKind(n:AnalysisNavigation):InsightKind|undefined{if(n.intent==='single_cell_topic')return 'integration';if(n.intent==='single_cell_enrichment'&&n.view==='bio-resources')return 'ora';if(n.intent==='evidence')return 'candidate';if(n.intent==='qpcr'||n.intent==='single_cell_differential')return 'comparison';if(['integration','ora','gsea_prerank','comparison','candidate','figure'].includes(n.intent??''))return n.intent as InsightKind;return undefined}

function canUseSingleCellComparison(result:Result){
 const config=result.methods.config as Record<string,unknown>|undefined
 return result.kind==='comparison'&&result.task.status==='succeeded'&&result.inference_scope==='donor_inference'
  &&!!(result.methods.single_cell_selection??config?.single_cell_selection)&&result.summary.tested_universe_complete===true
  &&number(result.summary.row_count)>number(result.summary.not_computable_rows)
  &&strings(result.methods.family_contrast_ids??config?.family_contrast_ids).length>0
  &&result.members.some(member=>member.key==='comparison_results'&&member.format==='tsv')
}
