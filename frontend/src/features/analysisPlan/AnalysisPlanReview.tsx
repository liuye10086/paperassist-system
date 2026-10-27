import {useAnalysisLeaveGuard} from '../analysis/analysisActivityContext'
import ModelSelectionSummary from '../analysis/ModelSelectionSummary'
import ModelSelectionForm from '../analysis/ModelSelectionForm'
import {initialModelSelection,modelMethods,type ModelMethod} from '../analysis/modelSelection'
import ComparisonSelectionForm from '../analysis/ComparisonSelectionForm'
import ComparisonSelectionSummary from '../analysis/ComparisonSelectionSummary'
import CorrelationSelectionForm from '../analysis/CorrelationSelectionForm'
import {initialCorrelation,initialComparison,comparisonMethods,type ComparisonMethod} from '../analysis/analysisSelection'
import { isAnalysisSelection, type AnalysisSelection } from '../analysis/analysisSelection'
import ResearchRequestForm from './ResearchRequestForm'
import ResearchRequestSummary from './ResearchRequestSummary'
import { isResearchRequest, researchFieldLabels, type ResearchRequest } from './researchRequest'
import { useEffect, useRef, useState } from 'react'
import { apiError, safeError, useI18n } from '../../shared/i18n'
import { onApiSessionChanged } from '../../shared/api/client'
import { sameInputVersion, isTask, statusNames, type AnalysisPlanInputVersion, type TaskView } from '../tasks/taskTypes'
import { taskRequest, TaskRequestError } from '../tasks/taskApi'
import SourceSummary from '../analysis/SourceSummary'
import QualityProvenance from '../datasetPreparation/QualityProvenance'
import { independentPlanMessage } from '../datasetPreparation/QualitySummary'
import { isPlanReview, type PlanReview } from './analysisPlanApi'
import { issueDescription, resolutionDescription, limitationDescription,numericIssues } from './diagnostics'
import { sameSource, type PreparedDatasetAnalysisSource } from '../analysis/datasetSource'

type Props = { active?: boolean; projectId: string; taskId: string; expectedSource?: PreparedDatasetAnalysisSource; expectedInputVersion?: AnalysisPlanInputVersion; blocked?: boolean; onChanged?: () => void; onPublished?: (id: string, revision: number) => void; refreshKey?: number }
const issueLabels: Record<string, string> = { comparison_sample_size:'比较样本量不足',comparison_input_limit:'比较输入超过规模限制',comparison_constant:'比较输入为常量',comparison_near_constant:'比较输入近常量',comparison_invalid_input:'比较输入无效',pair_id_missing:'配对 ID 缺失',pair_id_duplicate:'配对 ID 重复',pair_id_type:'配对 ID 类型无效',groups_missing:'参与组缺失',group_not_selected:'部分组未纳入', correlation_sample_size:'相关有效记录不足',correlation_input_limit:'相关输入超过规模限制',correlation_constant:'相关字段为常量',correlation_near_constant:'相关字段近常量',correlation_invalid_input:'相关输入无效', unit_conflict: '单位冲突', unit_unconfirmed: '单位未确认', numeric_precision: '数值精度不安全', outlier: '观察到异常值', partial_metrics: '部分指标不可计算', numeric_type: '数值列类型无效', group_type: '分组列类型无效', no_complete_records: '没有完整记录', too_many_groups: '分组过多', small_sample: '样本量较小', selected_missing: '所选字段存在缺失值', invalid_column: '字段无效', sheet_not_found: '工作表不存在', invalid_analysis_selection: '分析字段选择无效' }
const typeLabels: Record<string, string> = { number: '数值', text: '文本', boolean: '布尔', datetime: '日期/时间', formula: '公式', error: 'Excel 错误', blank: '空白', missing: '缺失', mixed: '混合类型' }
export default function AnalysisPlanReview(props: Props) { return <Review key={`${props.projectId}:${props.taskId}:${JSON.stringify(props.expectedSource)}`} {...props} /> }

function Review({ projectId, taskId, expectedSource, expectedInputVersion, blocked = false, onChanged, onPublished, refreshKey = 0, active: viewActive = true }: Props) {
  const { t } = useI18n()
  const [review, setReview] = useState<PlanReview | null>(null)
  const [resolutions, setResolutions] = useState<Record<string, string>>({})
  const [draft, setDraft] = useState<AnalysisSelection | null>(null)
  const [editing, setEditing] = useState(false)
  const [researchDraft, setResearchDraft] = useState<ResearchRequest | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [sessionValid, setSessionValid] = useState(true)
  const action = useRef<AbortController | null>(null)
  const replay = useRef<{ signature: string; key: string } | null>(null)
  useAnalysisLeaveGuard(() => !!replay.current || !!review && (JSON.stringify(resolutions) !== JSON.stringify(review.resolutions) || (editing || review.task.status === 'waiting_input') && (draft !== null && JSON.stringify(draft) !== JSON.stringify(review.selection) || JSON.stringify(researchDraft) !== JSON.stringify(review.research_request ?? null))), busy)
  const published = useRef<string | null>(null)
  const publishedCallback = useRef(onPublished)
  const generation = useRef('')
  const readGeneration = useRef(0)
  const latestRevision = useRef(0)
  const boundInput = useRef<AnalysisPlanInputVersion | null>(expectedInputVersion ?? null)
  const mounted = useRef(true)
  useEffect(() => { publishedCallback.current = onPublished }, [onPublished])
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; action.current?.abort() } }, [])
  useEffect(() => onApiSessionChanged(() => { action.current?.abort(); setSessionValid(false); setReview(null); setError('') }), [])
  useEffect(() => {
    if (!viewActive || !sessionValid) return
    const controller = new AbortController(); let active = true; let timer = 0
    const read = ++readGeneration.current
    async function load() {
      try {
        const value = await taskRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/analysis-plan`, controller,
          (v): v is PlanReview => isPlanReview(v, projectId, taskId) && (!expectedSource || sameSource(v.source, expectedSource)) && (!expectedInputVersion || sameInputVersion(v.input_version, expectedInputVersion)) && (!boundInput.current || sameInputVersion(v.input_version, boundInput.current)), '分析计划读取失败，请重试。')
        if (!active || controller.signal.aborted || read !== readGeneration.current) return
        if ((value.task.revision ?? 0) < latestRevision.current) return
        latestRevision.current = value.task.revision ?? 0
        if (!boundInput.current) boundInput.current = value.input_version
        const token = `${value.task.revision}:${value.checkpoint_id}:${value.plan_revision}:${value.wait_id ?? ''}`
        if (generation.current !== token) { generation.current = token; setResolutions(value.resolutions); setDraft(value.task.status==='waiting_input'&&value.input_version.workflow_version==='analysis_plan_v3'?value.selection:null); setResearchDraft(value.research_request ?? null); setEditing(false); replay.current = null }
        setReview(value)
        setError('')
        if (value.result && published.current !== value.result.id) { published.current = value.result.id; publishedCallback.current?.(value.result.id, value.result.setup_revision) }
        if (value.task.status === 'queued' || value.task.status === 'running') timer = window.setTimeout(() => void load(), 5000)
      } catch (cause) { if (active) { setReview(null); setError(safeError(cause, '分析计划读取失败，请重试。')) } }
    }
    void load()
    return () => { active = false; controller.abort(); window.clearTimeout(timer) }
  }, [projectId, taskId, expectedSource, expectedInputVersion, refreshKey, refresh, sessionValid, viewActive])

  async function decide(operation: 'approve' | 'revise') {
    if (!review || action.current || blocked || !review.wait_id || !['waiting_confirmation', 'waiting_input'].includes(review.task.status) || !review.check || expectedSource && !sameSource(review.source, expectedSource)) return
    if (operation === 'approve' && review.task.status !== 'waiting_confirmation' || operation === 'revise' && review.research_request && !isResearchRequest(researchDraft)) return
    const decisionGeneration = generation.current
    const decisionRead = readGeneration.current
    const body = operation === 'approve' ? { operation, expected_task_revision: review.task.revision, input_version: review.input_version,
      checkpoint_id: review.checkpoint_id, wait_id: review.wait_id, plan_revision: review.plan_revision, resolutions }
      : { operation, expected_task_revision: review.task.revision, input_version: review.input_version,
        checkpoint_id: review.checkpoint_id, wait_id: review.wait_id, plan_revision: review.plan_revision, resolutions: {}, ...(draft ? { selection: draft } : {}), ...(review.research_request ? { research_request: researchDraft } : {}) }
    const signature = JSON.stringify(body)
    if (replay.current?.signature !== signature) replay.current = { signature, key: crypto.randomUUID() }
    const controller = new AbortController(); action.current = controller; setBusy(true); setError('')
    try {
      const task = await taskRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/analysis-plan/decisions`, controller,
        (v): v is TaskView => isTask(v, projectId, taskId) && sameInputVersion(v.input_version, review.input_version), '分析计划决定尚未确认，请重新读取任务。',
        { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': replay.current.key }, body: signature })
      if (!mounted.current || controller.signal.aborted || (generation.current !== decisionGeneration || readGeneration.current !== decisionRead)) return
      setReview({ ...review, task, wait_id: null }); setEditing(false); setDraft(null); replay.current = null
      setRefresh(n => n + 1); onChanged?.()
    } catch (cause) {
      if (!mounted.current || (generation.current !== decisionGeneration || readGeneration.current !== decisionRead)) return
      if (cause instanceof TaskRequestError && cause.status === 409) { replay.current = null; setEditing(false); setDraft(null) }
      setError(cause instanceof TaskRequestError && cause.status === 409 ? '任务或分析配置已更新，请重新读取计划后再操作。' : safeError(cause, '分析计划决定尚未确认，请重新读取任务。'))
      setRefresh(n => n + 1); onChanged?.()
    } finally { if (action.current === controller) action.current = null; if (mounted.current) setBusy(false) }
  }

  const check = review?.check
  const waiting = sessionValid && !error && review?.task.status === 'waiting_confirmation' && !!review.wait_id && !!check
  const waitingInput = sessionValid && !error && review?.task.status === 'waiting_input' && !!review.wait_id && !!check && !!review.research_request
  const unresolved = check?.issues.filter(issue => issue.severity === 'warning' && !issue.allowed_resolutions.includes(resolutions[issue.id])) ?? []
  const blocking = !!check?.research_missing?.length || check?.issues.some(issue => issue.severity === 'blocking') || !check?.selection_check?.ready
  return <section className="preparation-panel" aria-label={t('分析计划审核')} aria-busy={busy}>
    <h4>{t('分析计划审核')}</h4><button type="button" disabled={busy || !sessionValid} onClick={() => { setError(''); setRefresh(n => n + 1) }}>{t('重新读取分析计划')}</button>
    {!sessionValid && <p role="alert">{t('会话已失效，请重新登录。')}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {!review && !error && sessionValid && <p role="status">{t('正在读取分析计划……')}</p>}
    {review && <><SourceSummary source={review.source} /><p role="status">{t(statusNames[review.task.status])}</p>
      {review.source.schema_version >= 2 && <><p>{t(independentPlanMessage)}</p><QualityProvenance projectId={projectId} source={review.source} /></>}
      {review.research_request && !(waitingInput || editing) && <ResearchRequestSummary selection={review.selection} value={review.research_request} />}
      {check?.research_missing?.length ? <div className="warning-panel"><p>{t('请补充以下研究资料；重新检查通过后仍需确认分析计划。')}</p><ul>{check.research_missing.map(field => <li key={field}>{t(researchFieldLabels[field])}</li>)}</ul></div> : null}
      {(waitingInput||editing)&&review.input_version.workflow_version==='analysis_plan_v3'&&draft&&<label>{t('计划方法')}<select value={draft.task_type!=='descriptive_boxplot'?draft.method:'descriptive'} disabled={busy||blocked} onChange={e=>{const method=e.target.value;if(Object.hasOwn(modelMethods,method)){setDraft(initialModelSelection(review.source.sheet_name,method as ModelMethod));return}if(Object.hasOwn(comparisonMethods,method)){setDraft(initialComparison(review.source.sheet_name,method as ComparisonMethod));return}if(method==='descriptive')setDraft({task_type:'descriptive_boxplot',sheet_name:review.source.sheet_name,numeric_column:draft.task_type==='correlation'?draft.columns[0]??'':draft.task_type==='descriptive_boxplot'||draft.task_type==='group_comparison'?draft.numeric_column??'':'',group_column:null,unit:draft.task_type==='correlation'?draft.units[draft.columns[0]]??'':draft.task_type==='descriptive_boxplot'||draft.task_type==='group_comparison'?draft.unit:'',missing_policy:'exclude_selected_missing'});else setDraft(draft.task_type==='correlation'?{...draft,method:method as 'pearson'|'spearman',assumptions:{...draft.assumptions,relationship_form:'unknown',inference_assumptions_confirmed:false}}:{...initialCorrelation(review.source.sheet_name),method:method as 'pearson'|'spearman'})}}><option value="descriptive">{t('描述统计＋箱线图')}</option><option value="pearson">Pearson</option><option value="spearman">Spearman</option>{Object.entries(comparisonMethods).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}{Object.entries(modelMethods).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}</select></label>}
      {(waitingInput||editing)&&draft?.task_type==='group_comparison'&&<ComparisonSelectionForm value={draft} onChange={setDraft} projectId={projectId} fileId={review.source.file_id} source={review.source} disabled={busy||blocked}/>}
      {(waitingInput||editing)&&draft&&(draft.task_type==='regression'||draft.task_type==='roc'||draft.task_type==='survival')&&<ModelSelectionForm value={draft} onChange={setDraft} disabled={busy||blocked}/>}
      {(waitingInput || editing) && researchDraft && <ResearchRequestForm selection={draft??review.selection} value={researchDraft} onChange={setResearchDraft} disabled={busy || blocked} />}
      {waitingInput&&draft?.task_type==='correlation'&&<CorrelationSelectionForm value={draft} onChange={setDraft} disabled={busy||blocked}/>}
      {waitingInput && <div className="analysis-actions"><button type="button" className="button-primary" disabled={busy || blocked || !isResearchRequest(researchDraft)||draft!==null&&!isAnalysisSelection(draft)} onClick={() => void decide('revise')}>{t('补充资料并重新检查')}</button></div>}
      {review.task.status === 'failed' && <div role="alert" className="error-panel"><p>{t(apiError({ code: review.task.error_code }, '分析计划发布失败，请重新读取配置。'))}</p><p>{t('请重新读取配置，核对来源后重新生成分析计划。')}</p></div>}
      {check && <p>{t(review.source.schema_version >= 2 ? '数据范围 {range}；当前整理保留 {rows} 行；本分析有效 {valid} 行或完整对；本分析排除 {excluded} 行。' : '数据范围 {range}；完整 {rows} 行；有效 {valid} 行；排除 {excluded} 行。', { range: check.data_range, rows: check.row_count, valid: check.selection_check?.valid_count ?? '—', excluded: check.selection_check?.excluded_count ?? '—' })}</p>}
      {review.selection.task_type==='descriptive_boxplot' ? <p>{t('数值列 {numeric}；分组列 {group}；声明单位 {unit}。', { numeric: review.selection.numeric_column, group: review.selection.group_column ?? t('不分组'), unit: review.selection.unit || t('未知') })}</p> : review.selection.task_type==='group_comparison'?<ComparisonSelectionSummary value={review.selection} fields={check?.selected_fields.map(f=>({column:f.letter,name:f.name}))} groups={check?.selection_check?.groups}/>: review.selection.task_type!=='correlation'?<ModelSelectionSummary value={review.selection}/>: <p><strong>{review.selection.method==='pearson'?'Pearson':'Spearman'}</strong> · {t(review.selection.mode==='pair'?'单对相关 / 散点图':'探索矩阵 / 热力图')} · {review.selection.columns.join('、')}</p>}
      {check?.selected_fields.map(field => <div key={field.letter}><strong>{field.letter} · {field.name}</strong><p>{t('缺失 {missing}；非缺失 {present}；观察范围 {min} 至 {max}。', { missing: field.missing_count, present: field.non_missing_count, min: field.observed_min ?? '—', max: field.observed_max ?? '—' })}</p><p>{t('整理单位 {prepared}；分析声明 {declared}。', { prepared: field.prepared_unit.status === 'confirmed' ? field.prepared_unit.value || t('无单位（已确认）') : t('单位未确认'), declared: field.declared_unit.status === 'label' ? field.declared_unit.value ?? '' : t('未知') })}</p><p>{Object.entries(field.type_counts).map(([kind, count]) => `${t(typeLabels[kind] ?? '其他类型')}: ${count}`).join(' · ')}</p></div>)}
      {check?.selection_check?.groups.map(group => <p key={group.label}>{group.label}：{t('{count} 行', { count: group.count })}</p>)}
      {check?.issues.map(issue => <div key={issue.id} className={issue.severity === 'blocking' ? 'error-panel' : 'warning-panel'}><p><strong>{t(issueLabels[issue.code] ?? numericIssues[issue.code] ?? '字段检查未通过')}</strong> · {issue.field ?? t('数据区域')} · {issue.count}</p><p>{t(issueDescription(issue.code, issue.message,review.selection))}</p><p>{issue.coordinates.join('、')}</p>
        {issue.severity === 'warning' && waiting && !editing && <label>{t('处理：{issue}（{field}）', { issue: t(issueLabels[issue.code] ?? numericIssues[issue.code] ?? '字段检查未通过'), field: issue.field ?? t('数据区域') })}<select value={resolutions[issue.id] ?? ''} disabled={busy || blocked} onChange={e => setResolutions(current => ({ ...current, [issue.id]: e.target.value }))}><option value="">{t('请选择处理方式')}</option>{issue.allowed_resolutions.map(item => <option key={item} value={item}>{t(resolutionDescription(issue.code,item,review.selection))}</option>)}</select></label>}
      </div>)}
      {check?.limitations.length ? <div className="warning-panel"><h5>{t('计划限制')}</h5><ul>{check.limitations.map((item, i) => <li key={i}>{t(limitationDescription(item))}</li>)}</ul></div> : null}
      {waiting && <>{editing && draft?.task_type==='correlation' && <CorrelationSelectionForm value={draft} onChange={setDraft} disabled={busy||blocked}/>} {editing && draft?.task_type==='descriptive_boxplot' && <div className="analysis-field-grid"><label>{t('数值列')}<input value={draft.numeric_column} disabled={busy || blocked} onChange={e => setDraft({ ...draft, numeric_column: e.target.value })} /></label><label>{t('分组列（可选）')}<input value={draft.group_column ?? ''} disabled={busy || blocked} onChange={e => setDraft({ ...draft, group_column: e.target.value || null })} /></label><label>{t('数值单位（可选）')}<input value={draft.unit} disabled={busy || blocked} onChange={e => setDraft({ ...draft, unit: e.target.value })} /></label></div>}
        <div className="analysis-actions">{editing ? <><button type="button" className="button-primary" disabled={busy || blocked || !isAnalysisSelection(draft) || !!review.research_request && !isResearchRequest(researchDraft)} onClick={() => void decide('revise')}>{t(review.research_request ? '修改计划并重新检查' : '修改字段并重新检查')}</button><button type="button" onClick={() => setEditing(false)}>{t('取消')}</button></> : <><button type="button" className="button-primary" disabled={busy || blocked || blocking || unresolved.length > 0} onClick={() => void decide('approve')}>{t('确认并发布分析计划')}</button><button type="button" disabled={busy || blocked} onClick={() => { setDraft(review.selection); setResearchDraft(review.research_request ?? null); setEditing(true) }}>{t(review.research_request ? '修改研究需求与字段' : '修改字段重审')}</button></>}</div>
      </>}
      {review.result && <p role="status">{t('分析计划已发布，分析配置 v{revision} 可执行统计。', { revision: review.result.setup_revision })}</p>}
    </>}
  </section>
}
