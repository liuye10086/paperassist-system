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
export default function BioInsightsWorkspace(props:Props){return props.active&&isInsightView(props.navigation.view)?<Content key={props.projectId} {...props}/>:null}
function Content({projectId,navigation:n,active,onNavigate,registerLeaveGuard}:Props){const{t}=useI18n(),[valid,setValid]=useState(true),[page,setPage]=useState(1),[runPage,setRunPage]=useState(1),[newKind,setNewKind]=useState<InsightKind>('comparison'),[history,setHistory]=useState(''),base=projectBase(projectId),capabilities=useInsightRead<Record<string,unknown>>(`${base}/bio-insights/capabilities`,active),plans=useInsightRead<Page<Plan>>(`${base}/bio-insight-plans?page=${page}&page_size=20`,active),runs=useInsightRead<Page<Run>>(`${base}/bio-insight-runs?page=${runPage}&page_size=20`,active,false,v=>v.items.some(r=>['queued','running'].includes(r.task.status))),plan=useInsightRead<Plan>(n.planId&&n.planVersionId?`${base}/bio-insight-plans/${n.planId}/versions/${n.planVersionId}`:'',active&&!!n.planVersionId,true)
 useEffect(()=>onApiSessionChanged(()=>setValid(false)),[])
 const area=n.view==='bio-resources'?'resources':n.view==='bio-candidates'?'candidates':n.view==='bio-insight-result'?'figures':plan.data?.kind==='figure'?'figures':plan.data?.kind==='candidate'?'candidates':plan.data&&['ora','gsea_prerank'].includes(plan.data.kind)?'resources':'comparison',kind=plan.data?.kind??(area==='candidates'?'candidate':area==='figures'?'figure':area==='resources'?(newKind==='gsea_prerank'?'gsea_prerank':'ora'):(['result_import','feature_extract','integration'] as InsightKind[]).includes(newKind)?newKind:'comparison')
 function openPlan(v:Plan){onNavigate({view:'bio-insight-plan',fileId:'',planId:v.plan_id,planVersionId:v.id})}
 function openRun(v:Run){onNavigate({view:'bio-insight-plan',fileId:'',runId:v.id})}
 function result(id:string){onNavigate({view:'bio-insight-result',fileId:'',resultVersionId:id})}
 function research(s:ResearchSource){queueResearchSource(projectId,s);onNavigate({view:'research-findings',fileId:''})}
 if(!valid)return <p role="alert">{t('会话已改变，请重新打开项目。')}</p>
 return <section className="insight-workspace" hidden={!active}><header><h2>{t('差异与功能分析')}</h2><p>{t('确认新版本后手动开始计算，历史版本保留。')}</p></header><nav className="intake-actions" aria-label={t('差异与功能工作区')}>{([['comparison','比较设计与差异','bio-insights'],['resources','资源与富集','bio-resources'],['candidates','候选配方','bio-candidates'],['figures','图件与承接','bio-insight-result']] as const).map(([key,label,view])=><button key={key} type="button" aria-current={area===key?'page':undefined} onClick={()=>onNavigate({view,fileId:'',...(view==='bio-insights'&&n.processedId?{processedId:n.processedId}:{})})}>{t(label)}</button>)}</nav>

 {n.runId&&<InsightRun key={n.runId} projectId={projectId} runId={n.runId} active={active} onResult={result} onPlan={(planId,planVersionId)=>onNavigate({view:'bio-insight-plan',fileId:'',planId,planVersionId})}/>}<ReadState {...plan}/>{n.resultVersionId&&<InsightResults key={n.resultVersionId} projectId={projectId} resultId={n.resultVersionId} active={active} onResearch={research}/>}
 {area==='resources'&&<InsightResources projectId={projectId} active={active} selectedId={n.resourceVersionId} onSelect={id=>onNavigate({view:'bio-resources',fileId:'',resourceVersionId:id||undefined})}/>}
 {!n.planVersionId&&area!=='candidates'&&area!=='figures'&&<Field label="新计划类型" value={kind} onChange={v=>setNewKind(v as InsightKind)}>{(area==='resources'?['ora','gsea_prerank']:['comparison','result_import','feature_extract','integration']).map(k=><option key={k} value={k}>{t(kindLabels[k as InsightKind])}</option>)}</Field>}
 {(!n.runId||n.planVersionId)&&(!n.planVersionId||plan.data)&&<InsightPlanEditor key={`${plan.data?.id??kind}:${n.processedId??n.resultVersionId??''}`} projectId={projectId} kind={kind} active={active} initial={plan.data} initialProcessedId={n.processedId} initialResultId={n.resultVersionId} onSaved={v=>{plans.refresh();openPlan(v)}} onRun={v=>{runs.refresh();openRun(v)}} registerLeaveGuard={registerLeaveGuard}/>}
 {plan.data&&<section><button type="button" onClick={()=>onNavigate({view:plan.data!.kind==='candidate'?'bio-candidates':plan.data!.kind==='figure'?'bio-insight-result':['ora','gsea_prerank'].includes(plan.data!.kind)?'bio-resources':'bio-insights',fileId:''})}>{t('另建独立计划，保留当前版本')}</button><Field label="历史计划版本 ID" value={history} onChange={setHistory}/><button type="button" disabled={!/^[A-Za-z0-9_-]{1,64}$/.test(history)} onClick={()=>onNavigate({view:'bio-insight-plan',fileId:'',planId:plan.data!.plan_id,planVersionId:history})}>{t('打开精确历史计划版本')}</button><DataDetails title="当前计划固定来源与原配置" value={{sources:plan.data.sources,config:plan.data.config,source_digest:plan.data.source_digest}}/></section>}
 <section className="analysis-detail"><header className="analysis-section-heading"><h3>{t('已有计划与运行记录')}</h3><button type="button" onClick={()=>{plans.refresh();runs.refresh()}}>{t('刷新计划与运行')}</button></header><ReadState {...plans}/>{plans.data&&!plans.data.items.length&&<p>{t('暂无已保存计划')}</p>}<ul>{plans.data?.items.map(v=><li key={v.id}><button type="button" onClick={()=>openPlan(v)}>{v.name} · {t(kindLabels[v.kind])} · v{v.revision} · {v.decision} · {v.id.slice(0,8)}</button></li>)}</ul>{plans.data&&<Paging page={page} total={plans.data.total} size={20} onPage={setPage}/>}<ReadState {...runs}/>{runs.data&&!runs.data.items.length&&<p>{t('暂无运行记录')}</p>}<ul>{runs.data?.items.map(v=><li key={v.id}><button type="button" onClick={()=>openRun(v)}>{t(kindLabels[v.kind])} · {v.task.status} · {v.id.slice(0,8)}</button>{v.result_version_id&&<button type="button" onClick={()=>result(v.result_version_id!)}>{t('查看固定结果')}</button>}</li>)}</ul>{runs.data&&<Paging page={runPage} total={runs.data.total} size={20} onPage={setRunPage}/>}</section><ReadState {...capabilities}/><DataDetails title="计算能力、环境身份与限制" value={capabilities.data}/>
 <footer><p>{t('研究发现中继续单图／组图、完整表报告、SCI／学校 Results/Methods 候选与显式发布。')}</p><button type="button" onClick={()=>onNavigate({view:'research-findings',fileId:''})}>{t('进入研究发现与核对')}</button></footer></section>
}
