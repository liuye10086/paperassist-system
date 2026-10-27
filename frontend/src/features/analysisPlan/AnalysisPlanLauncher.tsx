import {useWorkflowNavigation} from '../analysis/analysisWorkflowContext'
import {useAnalysisLeaveGuard} from '../analysis/analysisActivityContext'
import OriginRecommendation from './OriginRecommendation'
import type {Recommendation} from './recommendationApi'
import RequirementReview from './RequirementReview'
import ModelSelectionForm from '../analysis/ModelSelectionForm'
import {initialModelSelection,modelMethods,type ModelMethod} from '../analysis/modelSelection'
import ComparisonSelectionForm from '../analysis/ComparisonSelectionForm'
import AnalysisRecommendation from './AnalysisRecommendation'
import CorrelationSelectionForm, { type AnalysisField } from '../analysis/CorrelationSelectionForm'
import { initialCorrelation, initialComparison, comparisonMethods, isAnalysisSelection, type AnalysisSelection, type ComparisonMethod } from '../analysis/analysisSelection'
import ResearchRequestForm from './ResearchRequestForm'
import { emptyResearchRequest, isResearchRequest } from './researchRequest'
import { useEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import { isTask, statusNames, type AnalysisPlanInputVersion, type TaskView } from '../tasks/taskTypes'
import { taskRequest, TaskRequestError } from '../tasks/taskApi'
import { sameSource, type PreparedDatasetAnalysisSource } from '../analysis/datasetSource'
import { type Selection } from '../analysis/AnalysisSetup'
import { isPlanPage, type PlanPage } from './analysisPlanApi'
import AnalysisPlanReview from './AnalysisPlanReview'
import { independentPlanMessage } from '../datasetPreparation/QualitySummary'

type Props = { projectId: string; fileId: string; source: PreparedDatasetAnalysisSource; selection: Selection; initialSelection?:AnalysisSelection; fields?:AnalysisField[]; onSelectionChange?:(v:AnalysisSelection)=>void; setupRevision: number; disabled: boolean; onPublished: (id: string, revision: number) => void }
export default function AnalysisPlanLauncher(props: Props) { return <Launcher key={`${props.projectId}:${props.fileId}:${JSON.stringify(props.source)}`} {...props} /> }

function Launcher({ projectId, fileId, source, selection, initialSelection, fields=[], onSelectionChange, setupRevision, disabled, onPublished }: Props) {
  const { t } = useI18n()
  const taskLayout=!!useWorkflowNavigation()
  const [view,setView]=useState<'create'|'recommendations'|'history'|'review'>('create')
  const [recommendationBusy,setRecommendationBusy]=useState(false)
  const [originRef,setOriginRef]=useState<{task_id:string;sha256:string}|null>(null)
  const [recommendationRef,setRecommendationRef]=useState<{task_id:string;sha256:string}|null>(null)
  const parentSignature=JSON.stringify(selection)
  const [candidateState,setCandidateState]=useState<{value:AnalysisSelection;parentSignature:string}>(()=>({value:initialSelection??selection,parentSignature}))
  const [method,setMethod]=useState(initialSelection&&initialSelection.task_type!=='descriptive_boxplot'?initialSelection.method:'descriptive')
  const candidate=method==='descriptive'&&candidateState.parentSignature!==parentSignature?selection:candidateState.value
  function change(v:AnalysisSelection) {setMethod(v.task_type!=='descriptive_boxplot'?v.method:'descriptive');setCandidateState({value:v,parentSignature});onSelectionChange?.(v)}
  const [research, setResearch] = useState(emptyResearchRequest)
  const [page, setPage] = useState(1)
  const [list, setList] = useState<PlanPage | null>(null)
  const [selected, setSelected] = useState<{ taskId: string; inputVersion: AnalysisPlanInputVersion } | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const [listError,setListError]=useState('')
  const action = useRef<AbortController | null>(null)
  const replay = useRef<{ signature: string; key: string } | null>(null)
  useAnalysisLeaveGuard(() => !!replay.current || JSON.stringify(research) !== JSON.stringify(emptyResearchRequest()) || JSON.stringify(candidate) !== JSON.stringify(initialSelection ?? selection) || !!originRef || !!recommendationRef, busy || recommendationBusy)
  const [visitedReviews, setVisitedReviews] = useState<NonNullable<typeof selected>[]>([])
  if (selected && !visitedReviews.some(item => item.taskId === selected.taskId)) setVisitedReviews(items => [...items, selected])
  const base = `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}/analysis-plans`
  useEffect(() => () => action.current?.abort(), [])
  useEffect(() => {
    const controller = new AbortController(); let active = true
    taskRequest(`${base}?page=${page}&page_size=5`, controller,
      (v): v is PlanPage => isPlanPage(v, projectId, fileId, page), '分析计划列表读取失败，请重试。')
      .then(value => { if (active && !controller.signal.aborted) { setList(value); setListError(''); const first=value.items.find(item=>sameSource(item.source,source)); if (first) setSelected(current => current ?? { taskId: first.task.id, inputVersion: first.input_version }) } })
      .catch(cause => { if (active && !controller.signal.aborted) setListError(safeError(cause, '分析计划列表读取失败，请重试。')) })
    return () => { active = false; controller.abort() }
  }, [base, projectId, fileId, source, page, refresh])

  async function create() {
    if (disabled || busy || recommendationBusy || action.current || !isResearchRequest(research) || method!=='descriptive'&&!isAnalysisSelection(candidate)) return
    const body = {schema_version:5,input_kind:'data',file_id:fileId,dataset_id:source.dataset_id,expected_setup_revision:setupRevision,selection:method==='descriptive'&&!recommendationRef?selection:candidate,research_request:research,evidence_version_ids:[],recommendation_ref:recommendationRef,origin_recommendation_ref:recommendationRef?null:originRef}
    const signature = JSON.stringify(body)
    if (replay.current?.signature !== signature) replay.current = { signature, key: crypto.randomUUID() }
    const controller = new AbortController(); action.current = controller; setBusy(true); setActionError('')
    try {
      const task = await taskRequest(base, controller, (v): v is TaskView => isTask(v, projectId) && v.task_type === 'analysis_plan' && v.input_version.kind === 'analysis_plan' && v.input_version.workflow_version === 'analysis_plan_v5' && sameSource(v.input_version.source, source), '计划创建结果尚未确认，请重新读取列表。',
        { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': replay.current.key }, body: signature })
      if (controller.signal.aborted || task.input_version.kind !== 'analysis_plan') return
      setActionError('');setSelected({ taskId: task.id, inputVersion: task.input_version }); setPage(1); setRefresh(n => n + 1); replay.current = null
    } catch (cause) {
      if (cause instanceof TaskRequestError && cause.status === 409) replay.current = null
      setActionError(cause instanceof TaskRequestError && cause.status === 409 ? '分析配置或数据来源已更新，请重新载入配置后重试。' : safeError(cause, '计划创建结果尚未确认，请重新读取列表。'))
      setRefresh(n => n + 1)
    } finally { if (action.current === controller) action.current = null; setBusy(false) }
  }
  async function adoptMissing(r:Recommendation){
    if(busy||action.current)return
    const candidateResearch={...research,question:research.question.trim()?research.question:r.intent?.objective||'',output_language:r.output_language}
    if(!isResearchRequest(candidateResearch)){setActionError('请先填写研究问题，再采纳待补充需求。');return}
    const body=JSON.stringify({schema_version:5,input_kind:'data',file_id:fileId,dataset_id:source.dataset_id,expected_setup_revision:setupRevision,selection:null,research_request:candidateResearch,evidence_version_ids:[],recommendation_ref:{task_id:r.task_id,sha256:r.sha256},origin_recommendation_ref:null})
    if(replay.current?.signature!==body)replay.current={signature:body,key:crypto.randomUUID()}
    const c=new AbortController();action.current=c;setBusy(true);setActionError('')
    try{const task=await taskRequest(base,c,(v):v is TaskView=>isTask(v,projectId)&&v.input_version.kind==='analysis_plan'&&v.input_version.workflow_version==='analysis_plan_v5'&&sameSource(v.input_version.source,source),'需求创建尚未确认，请使用同一请求重试。',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':replay.current.key},body});if(!c.signal.aborted&&task.input_version.kind==='analysis_plan'){setActionError('');setSelected({taskId:task.id,inputVersion:task.input_version});setResearch(candidateResearch);setRefresh(n=>n+1);replay.current=null}}catch(e){if(!c.signal.aborted)setActionError(safeError(e,'需求创建尚未确认，请使用同一请求重试。'))}finally{if(action.current===c)action.current=null;if(!c.signal.aborted)setBusy(false)}
  }
  const visible = list?.items.filter(item => sameSource(item.source, source)) ?? []
  return <section className="preparation-panel" aria-label={t('分析计划')}>
    <h4>{t('分析计划')}</h4><p className="muted">{t('生成后须逐项处理检查问题并确认发布，才能将该计划用于统计分析。')}</p>
    {taskLayout&&<nav className="analysis-workflow-nav" aria-label={t('方案任务')}>
      {([['create','编写方案'],['recommendations','方案建议'],['history','方案历史'],['review','审核所选方案']] as const).map(([key,label])=><button type="button" key={key} aria-current={view===key?'step':undefined} disabled={key==='review'&&!selected} onClick={()=>setView(key)}>{t(label)}</button>)}
    </nav>}
    <div hidden={taskLayout&&view!=='create'}>
    {source.schema_version >= 2 && <p>{t(independentPlanMessage)}</p>}
    <label>{t('计划方法')}<select value={method} disabled={disabled||busy||recommendationBusy} onChange={e=>{const m=e.target.value;setMethod(m);change(Object.hasOwn(modelMethods,m)?initialModelSelection(source.sheet_name,m as ModelMethod):m==='descriptive'?selection:Object.hasOwn(comparisonMethods,m)?initialComparison(source.sheet_name,m as ComparisonMethod):{...initialCorrelation(source.sheet_name),method:m as 'pearson'|'spearman'})}}><option value="descriptive">{t('描述统计＋箱线图')}</option><option value="pearson">Pearson</option><option value="spearman">Spearman</option>{Object.entries(comparisonMethods).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}{Object.entries(modelMethods).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}</select></label>
    {method!=='descriptive'&&candidate.task_type==='correlation'&&<CorrelationSelectionForm value={candidate} fields={fields} onChange={change} disabled={disabled||busy||recommendationBusy}/>}
    {candidate.task_type==='group_comparison'&&method!=='descriptive'&&<ComparisonSelectionForm projectId={projectId} fileId={fileId} source={source} value={candidate} fields={fields} onChange={change} disabled={disabled||busy||recommendationBusy}/>}
    {['regression','roc','survival'].includes(candidate.task_type)&&candidate.task_type!=='correlation'&&candidate.task_type!=='group_comparison'&&candidate.task_type!=='descriptive_boxplot'&&<ModelSelectionForm value={candidate} fields={fields} onChange={change} disabled={disabled||busy||recommendationBusy}/>}
    <ResearchRequestForm selection={method==='descriptive'&&!recommendationRef?selection:candidate} value={research} onChange={setResearch} disabled={disabled || busy || recommendationBusy} />
    <div className="analysis-actions"><button type="button" className="button-primary" disabled={disabled || busy || recommendationBusy || !isResearchRequest(research)||method!=='descriptive'&&!isAnalysisSelection(candidate)} onClick={() => void create()}>{t('生成分析计划')}</button><button type="button" disabled={busy} onClick={() => { setListError(''); setRefresh(n => n + 1) }}>{t('刷新分析计划列表')}</button></div>
    </div>
    {actionError && <p role="alert" className="error-panel">{t(actionError)}</p>}
    {listError && <p role="alert" className="error-panel">{t(listError)}</p>}
    <div hidden={taskLayout&&view!=='history'}>
    {list && <><div className="analysis-actions"><button type="button" disabled={page <= 1} onClick={() => setPage(n => n - 1)}>{t('上一页')}</button><span>{t('共 {total} 项 · 第 {page} / {pages} 页', { total: list.total, page, pages: Math.max(1, Math.ceil(list.total / 5)) })}</span><button type="button" disabled={page * 5 >= list.total} onClick={() => setPage(n => n + 1)}>{t('下一页')}</button></div>
      {visible.map(item => <button type="button" key={item.task.id} onClick={() => { setSelected({ taskId: item.task.id, inputVersion: item.input_version }); setView('review') }} aria-pressed={selected?.taskId === item.task.id}>{t('分析计划第 {revision} 版 · {status}', { revision: item.plan_revision, status: t(statusNames[item.task.status]) })}</button>)}</>}
    </div>
    <div hidden={taskLayout&&view!=='recommendations'}>
    {source.schema_version===3&&<OriginRecommendation projectId={projectId} source={source} value={originRef} onChange={v=>{setOriginRef(v);setRecommendationRef(null)}} disabled={disabled||busy||recommendationBusy}/>}
    <AnalysisRecommendation schemaVersion={5} onAdoptRequirement={r=>void adoptMissing(r)} projectId={projectId} fileId={fileId} source={source} fields={fields} language={research.output_language} onBusyChange={setRecommendationBusy} disabled={disabled||busy||recommendationBusy} descriptiveSelection={selection} onAdopt={(v,ref,language)=>{change(v);setMethod(v.task_type!=='descriptive_boxplot'?v.method:'descriptive');setRecommendationRef(ref);setOriginRef(null);setResearch({...research,output_language:language})}}/>
    </div>
    <div hidden={taskLayout&&view!=='review'}>
    {visitedReviews.map(item => <div key={item.taskId} hidden={selected?.taskId !== item.taskId}>{['analysis_plan_v4','analysis_plan_v5'].includes(item.inputVersion.workflow_version) ? <RequirementReview projectId={projectId} taskId={item.taskId} onChanged={()=>setRefresh(n=>n+1)} onPublished={onPublished}/> : <AnalysisPlanReview projectId={projectId} taskId={item.taskId} expectedSource={source} expectedInputVersion={item.inputVersion} onChanged={() => setRefresh(n => n + 1)} onPublished={onPublished} />}</div>)}
    </div>
  </section>
}
