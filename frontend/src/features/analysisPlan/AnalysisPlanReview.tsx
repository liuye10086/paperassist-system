import { useEffect, useRef, useState } from 'react'
import { apiError, safeError, useI18n } from '../../shared/i18n'
import { onApiSessionChanged } from '../../shared/api/client'
import { sameInputVersion, isTask, statusNames, type TaskView } from '../tasks/taskTypes'
import { taskRequest, TaskRequestError } from '../tasks/taskApi'
import SourceSummary from '../analysis/SourceSummary'
import { type Selection } from '../analysis/AnalysisSetup'
import { isPlanReview, type PlanReview } from './analysisPlanApi'
import { issueDescription, limitationDescription } from './diagnostics'
import { sameSource, type PreparedDatasetAnalysisSource } from '../analysis/datasetSource'

type Props = { projectId: string; taskId: string; expectedSource?: PreparedDatasetAnalysisSource; blocked?: boolean; onChanged?: () => void; onPublished?: (id: string, revision: number) => void; refreshKey?: number }
const issueLabels: Record<string, string> = { unit_conflict: '单位冲突', unit_unconfirmed: '单位未确认', numeric_precision: '数值精度不安全', outlier: '观察到异常值', partial_metrics: '部分指标不可计算', numeric_type: '数值列类型无效', group_type: '分组列类型无效', no_complete_records: '没有完整记录', too_many_groups: '分组过多', small_sample: '样本量较小', selected_missing: '所选字段存在缺失值', invalid_column: '字段无效', sheet_not_found: '工作表不存在', invalid_analysis_selection: '分析字段选择无效' }
const resolutionLabels: Record<string, string> = { exclude_selected_missing: '排除所选字段缺失行', retain: '保留观察到的异常值', accept_partial_metrics: '接受小样本的部分指标', unknown: '保持单位未知', declare_label: '声明单位标签，不转换数值' }
const typeLabels: Record<string, string> = { number: '数值', text: '文本', boolean: '布尔', datetime: '日期/时间', formula: '公式', error: 'Excel 错误', blank: '空白', missing: '缺失', mixed: '混合类型' }
export default function AnalysisPlanReview(props: Props) { return <Review key={`${props.projectId}:${props.taskId}:${JSON.stringify(props.expectedSource)}`} {...props} /> }

function Review({ projectId, taskId, expectedSource, blocked = false, onChanged, onPublished, refreshKey = 0 }: Props) {
  const { t } = useI18n()
  const [review, setReview] = useState<PlanReview | null>(null)
  const [resolutions, setResolutions] = useState<Record<string, string>>({})
  const [draft, setDraft] = useState<Selection | null>(null)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [sessionValid, setSessionValid] = useState(true)
  const action = useRef<AbortController | null>(null)
  const replay = useRef<{ signature: string; key: string } | null>(null)
  const published = useRef<string | null>(null)
  const publishedCallback = useRef(onPublished)
  const generation = useRef('')
  const mounted = useRef(true)
  useEffect(() => { publishedCallback.current = onPublished }, [onPublished])
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; action.current?.abort() } }, [])
  useEffect(() => onApiSessionChanged(() => { action.current?.abort(); setSessionValid(false); setReview(null); setError('') }), [])
  useEffect(() => {
    if (!sessionValid) return
    const controller = new AbortController(); let active = true; let timer = 0
    async function load() {
      try {
        const value = await taskRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/analysis-plan`, controller,
          (v): v is PlanReview => isPlanReview(v, projectId, taskId) && (!expectedSource || sameSource(v.source, expectedSource)), '分析计划读取失败，请重试。')
        if (!active || controller.signal.aborted) return
        const token = `${value.checkpoint_id}:${value.plan_revision}:${value.wait_id ?? ''}`
        if (generation.current !== token) { generation.current = token; setResolutions(value.resolutions); setDraft(null); setEditing(false); replay.current = null }
        setReview(value)
        setError('')
        if (value.result && published.current !== value.result.id) { published.current = value.result.id; publishedCallback.current?.(value.result.id, value.result.setup_revision) }
        if (value.task.status === 'queued' || value.task.status === 'running') timer = window.setTimeout(() => void load(), 5000)
      } catch (cause) { if (active) { setReview(null); setError(safeError(cause, '分析计划读取失败，请重试。')) } }
    }
    void load()
    return () => { active = false; controller.abort(); window.clearTimeout(timer) }
  }, [projectId, taskId, expectedSource, refreshKey, refresh, sessionValid])

  async function decide(operation: 'approve' | 'revise') {
    if (!review || action.current || blocked || !review.wait_id || review.task.status !== 'waiting_confirmation' || !review.check || expectedSource && !sameSource(review.source, expectedSource)) return
    const body = operation === 'approve' ? { operation, expected_task_revision: review.task.revision, input_version: review.input_version,
      checkpoint_id: review.checkpoint_id, wait_id: review.wait_id, plan_revision: review.plan_revision, resolutions }
      : { operation, expected_task_revision: review.task.revision, input_version: review.input_version,
        checkpoint_id: review.checkpoint_id, wait_id: review.wait_id, plan_revision: review.plan_revision, resolutions: {}, selection: draft }
    const signature = JSON.stringify(body)
    if (replay.current?.signature !== signature) replay.current = { signature, key: crypto.randomUUID() }
    const controller = new AbortController(); action.current = controller; setBusy(true); setError('')
    try {
      const task = await taskRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/analysis-plan/decisions`, controller,
        (v): v is TaskView => isTask(v, projectId, taskId) && sameInputVersion(v.input_version, review.input_version), '分析计划决定尚未确认，请重新读取任务。',
        { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': replay.current.key }, body: signature })
      if (!mounted.current || controller.signal.aborted) return
      setReview({ ...review, task, wait_id: null }); setEditing(false); setDraft(null); replay.current = null
      setRefresh(n => n + 1); onChanged?.()
    } catch (cause) {
      if (!mounted.current) return
      if (cause instanceof TaskRequestError && cause.status === 409) { replay.current = null; setEditing(false); setDraft(null) }
      setError(cause instanceof TaskRequestError && cause.status === 409 ? '任务或分析配置已更新，请重新读取计划后再操作。' : safeError(cause, '分析计划决定尚未确认，请重新读取任务。'))
      setRefresh(n => n + 1); onChanged?.()
    } finally { if (action.current === controller) action.current = null; if (mounted.current) setBusy(false) }
  }

  const check = review?.check
  const waiting = sessionValid && !error && review?.task.status === 'waiting_confirmation' && !!review.wait_id && !!check
  const unresolved = check?.issues.filter(issue => issue.severity === 'warning' && !issue.allowed_resolutions.includes(resolutions[issue.id])) ?? []
  const blocking = check?.issues.some(issue => issue.severity === 'blocking') || !check?.selection_check?.ready
  return <section className="preparation-panel" aria-label={t('分析计划审核')} aria-busy={busy}>
    <h4>{t('分析计划审核')}</h4><button type="button" disabled={busy || !sessionValid} onClick={() => { setError(''); setRefresh(n => n + 1) }}>{t('重新读取分析计划')}</button>
    {!sessionValid && <p role="alert">{t('会话已失效，请重新登录。')}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {!review && !error && sessionValid && <p role="status">{t('正在读取分析计划……')}</p>}
    {review && <><SourceSummary source={review.source} /><p role="status">{t(statusNames[review.task.status])}</p>
      {review.task.status === 'failed' && <div role="alert" className="error-panel"><p>{t(apiError({ code: review.task.error_code }, '分析计划发布失败，请重新读取配置。'))}</p><p>{t('请重新读取配置，核对来源后重新生成分析计划。')}</p></div>}
      {check && <p>{t('数据范围 {range}；完整 {rows} 行；有效 {valid} 行；排除 {excluded} 行。', { range: check.data_range, rows: check.row_count, valid: check.selection_check?.valid_count ?? '—', excluded: check.selection_check?.excluded_count ?? '—' })}</p>}
      <p>{t('数值列 {numeric}；分组列 {group}；声明单位 {unit}。', { numeric: review.selection.numeric_column, group: review.selection.group_column ?? t('不分组'), unit: review.selection.unit || t('未知') })}</p>
      {check?.selected_fields.map(field => <div key={field.letter}><strong>{field.letter} · {field.name}</strong><p>{t('缺失 {missing}；非缺失 {present}；观察范围 {min} 至 {max}。', { missing: field.missing_count, present: field.non_missing_count, min: field.observed_min ?? '—', max: field.observed_max ?? '—' })}</p><p>{t('整理单位 {prepared}；分析声明 {declared}。', { prepared: field.prepared_unit.status === 'confirmed' ? field.prepared_unit.value || t('无单位（已确认）') : t('单位未确认'), declared: field.declared_unit.status === 'label' ? field.declared_unit.value ?? '' : t('未知') })}</p><p>{Object.entries(field.type_counts).map(([kind, count]) => `${t(typeLabels[kind] ?? '其他类型')}: ${count}`).join(' · ')}</p></div>)}
      {check?.selection_check?.groups.map(group => <p key={group.label}>{group.label}：{t('{count} 行', { count: group.count })}</p>)}
      {check?.issues.map(issue => <div key={issue.id} className={issue.severity === 'blocking' ? 'error-panel' : 'warning-panel'}><p><strong>{t(issueLabels[issue.code] ?? issue.code)}</strong> · {issue.field ?? t('数据区域')} · {issue.count}</p><p>{t(issueDescription(issue.code, issue.message))}</p><p>{issue.coordinates.join('、')}</p>
        {issue.severity === 'warning' && waiting && !editing && <label>{t('处理：{issue}（{field}）', { issue: t(issueLabels[issue.code] ?? issue.code), field: issue.field ?? t('数据区域') })}<select value={resolutions[issue.id] ?? ''} disabled={busy || blocked} onChange={e => setResolutions(current => ({ ...current, [issue.id]: e.target.value }))}><option value="">{t('请选择处理方式')}</option>{issue.allowed_resolutions.map(item => <option key={item} value={item}>{t(resolutionLabels[item] ?? item)}</option>)}</select></label>}
      </div>)}
      {check?.limitations.length ? <div className="warning-panel"><h5>{t('计划限制')}</h5><ul>{check.limitations.map((item, i) => <li key={i}>{t(limitationDescription(item))}</li>)}</ul></div> : null}
      {waiting && <>{editing && draft && <div className="analysis-field-grid"><label>{t('数值列')}<input value={draft.numeric_column} disabled={busy || blocked} onChange={e => setDraft({ ...draft, numeric_column: e.target.value })} /></label><label>{t('分组列（可选）')}<input value={draft.group_column ?? ''} disabled={busy || blocked} onChange={e => setDraft({ ...draft, group_column: e.target.value || null })} /></label><label>{t('数值单位（可选）')}<input value={draft.unit} disabled={busy || blocked} onChange={e => setDraft({ ...draft, unit: e.target.value })} /></label></div>}
        <div className="analysis-actions">{editing ? <><button type="button" className="button-primary" disabled={busy || blocked || !draft?.numeric_column} onClick={() => void decide('revise')}>{t('修改字段并重新检查')}</button><button type="button" onClick={() => setEditing(false)}>{t('取消')}</button></> : <><button type="button" className="button-primary" disabled={busy || blocked || blocking || unresolved.length > 0} onClick={() => void decide('approve')}>{t('确认并发布分析计划')}</button><button type="button" disabled={busy || blocked} onClick={() => { setDraft(review.selection); setEditing(true) }}>{t('修改字段重审')}</button></>}</div>
      </>}
      {review.result && <p role="status">{t('分析计划已发布，分析配置 v{revision} 可执行描述统计。', { revision: review.result.setup_revision })}</p>}
    </>}
  </section>
}
