import {useEffect,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {useI18n} from '../../shared/i18n'
import type {AnalysisNavigation} from '../projects/analysisViews'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import type {Source as ResearchSource} from '../research-results/contracts'
import {projectBase} from './api'
import {useInsightRead} from './hooks'
import {kindLabels,type InsightKind,type Page,type Plan,type Run} from './contracts'
import {isInsightView} from './state'
import {DataDetails,Field,Paging,ReadState} from './InsightShared'
import InsightPlanEditor,{InsightRun} from './InsightPlanEditor'
import InsightResults from './InsightResults'
import InsightResources from './InsightResources'
import {queueResearchSource} from './researchHandoff'
import './insights.css'
type Props={projectId:string;navigation:AnalysisNavigation;active:boolean;onNavigate:(n:AnalysisNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}
export default function BioInsightsWorkspace(props:Props){return props.active&&isInsightView(props.navigation.view)?<Content key={`${props.projectId}:${props.navigation.entry?.requirementVersionId??''}:${props.navigation.entry?.scopeItemId??''}:${props.navigation.intent??''}`} {...props}/>:null}
function Content({projectId,navigation:n,active,onNavigate,registerLeaveGuard}:Props){const{t}=useI18n(),[valid,setValid]=useState(true),[page,setPage]=useState(1),[runPage,setRunPage]=useState(1),[newKind,setNewKind]=useState<InsightKind>(navigationKind(n)??'comparison'),base=projectBase(projectId),capabilities=useInsightRead<Record<string,unknown>>(`${base}/bio-insights/capabilities`,active),plans=useInsightRead<Page<Plan>>(`${base}/bio-insight-plans?page=${page}&page_size=20`,active),runs=useInsightRead<Page<Run>>(`${base}/bio-insight-runs?page=${runPage}&page_size=20`,active,false,v=>v.items.some(r=>['queued','running'].includes(r.task.status))),plan=useInsightRead<Plan>(n.planId&&n.planVersionId?`${base}/bio-insight-plans/${n.planId}/versions/${n.planVersionId}`:'',active&&!!n.planVersionId,true)
 useEffect(()=>onApiSessionChanged(()=>setValid(false)),[])
 const intentKind=navigationKind(n),area=n.view==='bio-resources'?'resources':n.view==='bio-candidates'?'candidates':n.view==='bio-insight-result'?'figures':plan.data?.kind==='figure'?'figures':plan.data?.kind==='candidate'?'candidates':plan.data&&['ora','gsea_prerank'].includes(plan.data.kind)?'resources':!plan.data&&intentKind==='candidate'?'candidates':!plan.data&&intentKind==='figure'?'figures':!plan.data&&['ora','gsea_prerank'].includes(intentKind??'')?'resources':'comparison',kind=plan.data?.kind??(area==='candidates'?'candidate':area==='figures'?'figure':area==='resources'?(newKind==='gsea_prerank'?'gsea_prerank':'ora'):(['result_import','feature_extract','integration'] as InsightKind[]).includes(newKind)?newKind:'comparison')
 const entry={...(n.entry?{entry:n.entry,intent:n.intent}:{})}
 function openPlan(v:Plan){onNavigate({...entry,view:'bio-insight-plan',fileId:'',planId:v.plan_id,planVersionId:v.id})}
 function openRun(v:Run){onNavigate({...entry,view:'bio-insight-plan',fileId:'',runId:v.id})}
 function result(id:string){onNavigate({...entry,view:'bio-insight-result',fileId:'',resultVersionId:id})}
 function research(s:ResearchSource){queueResearchSource(projectId,s);onNavigate({...entry,view:'research-findings',fileId:''})}
 const routeKey=[n.view,n.planVersionId,n.runId,n.resultVersionId,n.resourceVersionId].join(':')
 const [resourcesVisited,setResourcesVisited]=useState(area==='resources');if((area==='resources'||!!n.resourceVersionId)&&!resourcesVisited)setResourcesVisited(true)
 const defaultPanel=n.resourceVersionId?'resources':n.view==='bio-insight-plan'&&!n.planVersionId&&!n.runId?'history':'current'
 const [panel,setPanel]=useState(defaultPanel),[panelRoute,setPanelRoute]=useState(routeKey),[historyPanel,setHistoryPanel]=useState('plans')
 if(panelRoute!==routeKey){setPanelRoute(routeKey);setPanel(defaultPanel)}
 if(!valid)return <p role="alert">{t('会话已改变，请重新打开项目。')}</p>
 return <section className="insight-workspace" hidden={!active}>
 <nav className="analysis-page-tabs" aria-label={t('分析工作视图')}>{[['current','当前分析'],...(n.resultVersionId?[['plot','基于结果绘图']]:[]),['history','历史记录'],['resources','资源管理'],['environment','运行环境']].map(([key,label])=><button type="button" key={key} aria-pressed={panel===key} onClick={()=>{setPanel(key);if(key==='resources')setResourcesVisited(true)}}>{t(label)}</button>)}</nav>
 <div className="insight-current" hidden={panel!=='current'&&panel!=='plot'}>
 <header className="analysis-section-heading"><h2>{t('差异与功能分析')}</h2>{intentKind&&<span className="analysis-kind-summary">{t(kindLabels[kind])}</span>}{!n.entry&&!n.planVersionId&&!n.runId&&!n.resultVersionId&&<nav className="insight-kind-nav" aria-label={t('差异与功能工作区')}>{([['comparison','比较设计与差异','bio-insights'],['resources','资源与富集','bio-resources'],['candidates','候选配方','bio-candidates'],['figures','图件与承接','bio-insight-result']] as const).map(([key,label,view])=><button key={key} type="button" aria-current={area===key?'page':undefined} onClick={()=>onNavigate({...entry,...(n.entry?{intent:key==='comparison'?'comparison':key==='resources'?(n.intent==='gsea_prerank'?'gsea_prerank':'ora'):key==='candidates'?(n.intent==='evidence'?'evidence':'candidate'):'figure'}:{}),view,fileId:'',...(view==='bio-insights'&&n.processedId?{processedId:n.processedId}:{})})}>{t(label)}</button>)}</nav>}</header>
 {n.runId&&<div className="insight-read-panel"><InsightRun key={n.runId} projectId={projectId} runId={n.runId} active={active} onResult={result} onPlan={(planId,planVersionId)=>onNavigate({...entry,view:'bio-insight-plan',fileId:'',planId,planVersionId})}/></div>}
 <ReadState {...plan}/>{n.resultVersionId&&<div className="insight-read-panel" hidden={panel==='plot'}><InsightResults key={n.resultVersionId} projectId={projectId} resultId={n.resultVersionId} active={active} onResearch={research}/></div>}
 {!n.planVersionId&&!n.runId&&!n.resultVersionId&&area!=='candidates'&&area!=='figures'&&!intentKind&&<div className="insight-kind-selection"><Field label="新计划类型" value={kind} onChange={v=>setNewKind(v as InsightKind)}>{(area==='resources'?['ora','gsea_prerank']:['comparison','result_import','feature_extract','integration']).map(k=><option key={k} value={k}>{t(kindLabels[k as InsightKind])}</option>)}</Field></div>}
 <div className="insight-editor-host" hidden={!!n.resultVersionId&&panel!=='plot'}>{(!n.runId||n.planVersionId)&&(!n.planVersionId||plan.data)&&<InsightPlanEditor key={`${plan.data?.id??kind}:${n.processedId??n.resultVersionId??''}`} projectId={projectId} kind={kind} active={active} initial={plan.data} initialProcessedId={n.processedId} initialResultId={n.resultVersionId} entryIntent={n.intent} onSaved={v=>{plans.refresh();openPlan(v)}} onRun={v=>{runs.refresh();openRun(v)}} registerLeaveGuard={registerLeaveGuard}/>}</div>
 </div>
 <div className="insight-history" hidden={panel!=='history'}><header className="analysis-section-heading"><h2>{t('已有计划与运行记录')}</h2><button type="button" onClick={()=>{plans.refresh();runs.refresh()}}>{t('刷新计划与运行')}</button></header>
 <nav className="analysis-page-tabs" aria-label={t('分析历史视图')}>{[['plans','计划版本'],['runs','运行记录']].map(([key,label])=><button type="button" key={key} aria-pressed={historyPanel===key} onClick={()=>setHistoryPanel(key)}>{t(label)}</button>)}</nav><div className="insight-read-panel" hidden={historyPanel!=='plans'}>
 {plan.data&&<div className="intake-actions"><button type="button" onClick={()=>onNavigate({...entry,view:plan.data!.kind==='candidate'?'bio-candidates':plan.data!.kind==='figure'?'bio-insight-result':['ora','gsea_prerank'].includes(plan.data!.kind)?'bio-resources':'bio-insights',fileId:''})}>{t('另建独立计划，保留当前版本')}</button>{plan.data.parent_id&&<button type="button" onClick={()=>onNavigate({...entry,view:'bio-insight-plan',fileId:'',planId:plan.data!.plan_id,planVersionId:plan.data!.parent_id!})}>{t('查看上一计划版本')}</button>}</div>}
 <ReadState {...plans}/>{plans.data&&!plans.data.items.length&&<p>{t('暂无已保存计划')}</p>}<ul className="insight-history-list">{plans.data?.items.map(v=><li key={v.id}><button type="button" onClick={()=>openPlan(v)}>{v.name} · {t(kindLabels[v.kind])} · v{v.revision} · {t(v.decision==='confirmed'?'已确认':'草稿')}</button></li>)}</ul>{plans.data&&<Paging page={page} total={plans.data.total} size={20} onPage={setPage}/>}
 </div><div className="insight-read-panel" hidden={historyPanel!=='runs'}><ReadState {...runs}/>{runs.data&&!runs.data.items.length&&<p>{t('暂无运行记录')}</p>}<ul className="insight-history-list">{runs.data?.items.map(v=><li key={v.id}><button type="button" onClick={()=>openRun(v)}>{t(kindLabels[v.kind])} · {t(v.task.status)} · {v.id.slice(0,8)}</button>{v.result_version_id&&<button type="button" onClick={()=>result(v.result_version_id!)}>{t('查看固定结果')}</button>}</li>)}</ul>{runs.data&&<Paging page={runPage} total={runs.data.total} size={20} onPage={setRunPage}/>}</div></div>
 <div className="insight-read-panel" hidden={panel!=='resources'}>{resourcesVisited&&<InsightResources projectId={projectId} active={active&&panel==='resources'} selectedId={n.resourceVersionId} onSelect={id=>{setPanel('resources');setPanelRoute(['bio-resources','','','',id??''].join(':'));onNavigate({...entry,view:'bio-resources',fileId:'',resourceVersionId:id||undefined})}}/>}</div>
 <div className="insight-read-panel" hidden={panel!=='environment'}><ReadState {...capabilities}/><DataDetails title="计算能力、环境身份与限制" value={capabilities.data}/></div>
 </section>
}

function navigationKind(n:AnalysisNavigation):InsightKind|undefined{if(n.intent==='evidence')return 'candidate';if(n.intent==='qpcr')return 'comparison';if(['integration','ora','gsea_prerank','comparison','candidate','figure'].includes(n.intent??''))return n.intent as InsightKind;return undefined}
