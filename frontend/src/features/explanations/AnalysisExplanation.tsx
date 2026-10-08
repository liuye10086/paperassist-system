import { useI18n, apiError, safeError } from '../../shared/i18n'
import { apiFetch } from '../../shared/api/client'
import { useEffect, useRef, useState } from 'react'
import { WorkflowStage, WorkflowReadStatus } from '../analysis/AnalysisWorkflow'
import '../figures/artifactPanels.css'
import WordReport from '../reports/WordReport'

type Config = { configured: boolean; model: string | null; message: string; message_code?: string; message_params?: Record<string, string | number> }
type Explanation = {
  id: string; analysis_run_id: string; figure_id: string; setup_revision: number; language: 'zh-CN' | 'en'
  figure_sha256: string; source_sha256: string; created_at: string
  sections: { key: string; title: string; text: string; evidence: { key: string; label: string; value: string }[] }[]
  limitations: string[]; engine: { id: string; provider: string; model: string }
  verification: { status: string; note: string }; provenance: Record<string, unknown>
}
type Task = { id: string; status: 'queued' | 'running' | 'waiting_input' | 'waiting_confirmation' | 'succeeded' | 'failed'
  revision: number; reason_code: string | null; error_code: string | null; result_explanation_id?: string | null }
type State = { current_revision: number | null; is_current: boolean; figure_id: string | null; explanation: Explanation | null; task?: Task | null
  job: { id: string; status: 'submitting' | 'running' | 'failed' | 'uncertain' | 'completed'; message: string; message_code?: string; message_params?: Record<string, string | number>; response_id: string | null; created_at: string } | null }
type Props = { base: string; runId: string; revision: number; figureId: string; canGenerate: boolean; disabled: boolean
  onBusyChange: (busy: boolean) => void; configuration?: Config | null; configurationError?: string; onReloadConfiguration?: () => void }
class RequestError extends Error {
  status: number
  constructor(text: string, status: number) { super(text); this.status = status }
}
async function request<T>(url: string, controller: AbortController, init?: RequestInit): Promise<T> {
  let timer = 0
  try {
    return await Promise.race([apiFetch(url, { ...init, signal: controller.signal }).then(async response => {
      const body = await response.json().catch(() => null)
      if (!response.ok) throw new RequestError(apiError(body, '解释请求失败，请重新读取解释。'), response.status)
      return body as T
    }), new Promise<never>((_, reject) => {
      timer = window.setTimeout(() => { controller.abort(); reject(new Error('解释请求超时，后端可能仍在处理。请先重新读取解释，确认状态。')) }, 30_000)
    })])
  } finally { window.clearTimeout(timer) }
}
function message(cause: unknown) {
  return cause instanceof TypeError ? '无法连接后端，请确认服务正常后重新读取解释。' : safeError(cause, '解释请求失败，请重新读取解释。')
}
export default function AnalysisExplanation(props: Props) {
  return <ExplanationPanel key={`${props.base}:${props.runId}:${props.figureId}`} {...props} />
}
const outputFailures = new Set(['explanation_invalid', 'explanation_invalid_json', 'explanation_refused', 'explanation_output_limit', 'explanation_incomplete'])
function needsPoll(value: State) {
  if (value.explanation) return false
  return value.task ? ['queued', 'running'].includes(value.task.status) || (value.task.status === 'succeeded' && !value.explanation)
    : value.job?.status === 'submitting' || value.job?.status === 'running'
}
function ExplanationPanel({ base, runId, revision, figureId, canGenerate, disabled, onBusyChange }: Props) {
  const { t } = useI18n()
  const endpoint = `${base}/analysis-runs/${runId}/explanation`
  const [state, setState] = useState<State | null>(null)
  const [localConfig, setLocalConfig] = useState<Config | null>(null)
  const [localConfigError, setLocalConfigError] = useState('')
  const [configAttempt, setConfigAttempt] = useState(0)
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [reportBusy, setReportBusy] = useState(false)
  const [error, setError] = useState('')
  const active = useRef(true)
  const action = useRef<AbortController | null>(null)
  const reading = useRef<AbortController | null>(null)
  const config = localConfig
  const configError = localConfigError
  const task = state?.task
  const running = !!state && needsPoll(state)
  const unknown = !state?.explanation && (task ? task.reason_code === 'submission_unknown' : state?.job?.status === 'uncertain')
  const unavailable = !state?.explanation && task?.error_code === 'model_response_not_found'
  const budgetWait = !state?.explanation && task?.status === 'waiting_confirmation' && task.reason_code === 'budget_exceeded'
  const resume = !state?.explanation && !unavailable && (budgetWait || (task?.status === 'failed' && !!task.error_code && !outputFailures.has(task.error_code)))
  const retry = !state?.explanation && (task ? task.status === 'failed' && !resume && !unavailable : state?.job?.status === 'failed')
  const busy = submitting
  const explanation = state?.explanation
  const current = !!state?.is_current && state.current_revision === revision && state.figure_id === figureId
    && (!explanation || (explanation.setup_revision === revision && explanation.figure_id === figureId && explanation.analysis_run_id === runId))
  const ready = current && canGenerate && !disabled && !loading && !busy && !reportBusy && !error
  const allowed = !!config?.configured && ready && !running && !unknown && !resume && !unavailable
    && (!task || task.status === 'failed' || task.status === 'succeeded')

  useEffect(() => { active.current = true; return () => { active.current = false; action.current?.abort(); reading.current?.abort() } }, [])
  useEffect(() => { onBusyChange(busy || reportBusy); return () => onBusyChange(false) }, [busy, reportBusy, onBusyChange])
  useEffect(() => {
    const controller = new AbortController(); let disposed = false
    request<Config>('/api/v1/ai/explanation-config', controller).then(value => { if (!disposed && !controller.signal.aborted) setLocalConfig(value) })
      .catch(cause => { if (!disposed) setLocalConfigError(message(cause)) })
    return () => { disposed = true; controller.abort() }
  }, [configAttempt])
  useEffect(() => {
    let disposed = false; let poll = 0
    async function read() {
      if (disposed || reading.current || action.current) return
      const controller = new AbortController(); reading.current = controller
      try {
        const value = await request<State>(endpoint, controller)
        if (disposed || controller.signal.aborted) return
        setState(value); setError('')
        if (needsPoll(value)) poll = window.setTimeout(() => void read(), 3000)
      } catch (cause) { if (!disposed) {
        setError(message(cause))
        if (cause instanceof RequestError && cause.status === 409) setState(previous => previous ? { ...previous, is_current: false } : previous)
      } } finally { if (reading.current === controller) reading.current = null; if (!disposed) setLoading(false) }
    }
    void read()
    return () => { disposed = true; window.clearTimeout(poll); reading.current?.abort(); reading.current = null }
  }, [endpoint, attempt])
  async function generate() {
    if (!(resume ? ready && !unknown : allowed) || action.current) return
    const controller = new AbortController(); action.current = controller
    reading.current?.abort(); reading.current = null
    setSubmitting(true); setError(''); setAttempt(value => value + 1)
    try {
      const value = resume && task
        ? { ...state!, task: await request<Task>(`/api/v1/tasks/${encodeURIComponent(task.id)}/retry`, controller, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: task.revision }) }) }
        : await request<State>(endpoint, controller, { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ expected_revision: revision, figure_id: figureId, ...(retry ? { retry: true } : {}) }) })
      if (!active.current || controller.signal.aborted) return
      setState(value)
      if (needsPoll(value)) setAttempt(value => value + 1)
    } catch (cause) { if (active.current) {
      setError(message(cause))
      if (cause instanceof RequestError && cause.status === 409) setState(previous => previous ? { ...previous, is_current: false } : previous)
    } } finally { if (action.current === controller) action.current = null; if (active.current) setSubmitting(false) }
  }
  function reloadConfig() {
    setLocalConfig(null); setLocalConfigError(''); setConfigAttempt(value => value + 1)
  }
  function reload() {
    setLoading(true); setError(''); setAttempt(value => value + 1)
  }
  return <>
    <WorkflowReadStatus stages={['report']} loading={loading} error={error}
      loadingMessage="正在读取解释……" reloadLabel="重新读取解释" onReload={reload} disabled={submitting || reportBusy} />
    <WorkflowStage stage="explanation"><section className="analysis-explanation artifact-panel" aria-label={t("AI 分析解释")} aria-busy={loading || busy}>
    <div className="section-heading"><span className="step-label">{t("分析解释")}</span><h3>{t("分析解释与论文表述")}</h3></div>
    <p className="warning-panel">{t("AI 草稿，必须人工审核后使用。解释基于已保存的分析配置、描述统计与图表；不代表因果结论或显著性检验。")}</p>
    <p className="muted">{t("点击生成会调用收费 OpenAI API；重新读取已保存解释不会再次生成。")}</p>
    {!config && !configError && <p role="status">{t("正在读取解释 OpenAI 配置……")}</p>}
    {config && !config.configured && <p className="warning-panel">{t(apiError({ code: config.message_code ?? 'openai_not_configured', params: config.message_params }, '请联系管理员配置 OpenAI API。'))}</p>}
    {configError && <p role="alert" className="error-panel">{t(configError)}</p>}
    {(!config?.configured || configError) && <button type="button" onClick={reloadConfig}>{t("重新读取解释 OpenAI 配置")}</button>}
    {!canGenerate && <p className="warning-panel">{t("请保存当前字段并完成对应配置的描述统计和图表后，再生成解释。")}</p>}
    {explanation && (!current || !canGenerate) && <p className="warning-panel">{t('以下解释对应旧配置或旧图表，仅供查看，请使用当前结果重新生成。')}</p>}
    {retry && <p className="warning-panel">{t("上次解释生成失败。")}{t("再次调用 API 可能产生额外费用，请确认后点击重试。")}</p>}
    {unknown && <p className="warning-panel">{t('提交结果尚未核实，已停止再次调用。请联系管理员核对。')}</p>}
    {unavailable && <p className="warning-panel">{t('已提交的解释无法恢复，请联系管理员核对。')}</p>}
    {budgetWait && <p className="warning-panel">{t('解释正在等待预算或模型配置；请联系管理员配置后继续。')}</p>}
    <div className="analysis-actions">
      {resume ? <button type="button" disabled={!ready || unknown} onClick={() => void generate()}>{t(budgetWait ? '预算已配置，继续生成解释' : '继续解释任务')}</button>
        : <button type="button" disabled={!allowed} onClick={() => void generate()}>{retry ? t("重试生成解释（再次调用 API）") : t("使用 OpenAI 生成解释")}</button>}
      <button type="button" disabled={loading || submitting || reportBusy} onClick={reload}>{t("重新读取解释")}</button>
    </div>
    {loading && <p role="status">{t("正在读取解释……")}</p>}
    {(submitting || running) && <p role="status">{task ? t(task.status === 'queued' ? '解释任务已排队，可继续浏览工作台。' : task.status === 'succeeded' ? '正在读取已保存的解释……' : '正在生成解释，可继续浏览工作台。')
      : state?.job ? t(apiError({ code: state.job.message_code ?? `task_${state.job.status}`, params: state.job.message_params }, '任务状态暂不可用。')) : t("正在提交 OpenAI 解释任务，请稍候……")}</p>}
    {(retry || resume) && task?.error_code && <p role="status">{t(apiError({ code: task.error_code }, '任务状态暂不可用。'))}</p>}
    {retry && !task && state?.job && <p role="status">{t(apiError({ code: state.job.message_code ?? `task_${state.job.status}`, params: state.job.message_params }, '任务状态暂不可用。'))}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {explanation && <>
      <p className="artifact-status">{t(current && canGenerate ? "当前结果" : "历史结果")}</p>
      {explanation.sections.map(section => <section className="explanation-section" key={section.key}>
        <h4>{section.title}</h4><p className="explanation-text">{section.text}</p>
        <details><summary>{t("依据：已保存配置、统计结果与图表")}</summary><ul>{section.evidence.map(evidence => <li key={evidence.key}>{evidence.label}：{evidence.value}</li>)}</ul></details>
      </section>)}
      <h4>{t("解释限制")}</h4><ul>{explanation.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul>
      <details className="artifact-details"><summary>{t("解释来源与核对记录")}</summary>
        <p>{t("语言：")}{t(explanation.language === 'zh-CN' ? '中文' : '英文')}</p>
        <p>{explanation.verification.note}</p>
        <p>{t("保存时间：")}{explanation.created_at}</p>
      </details>
    </>}
    {state && !explanation && !state.job && !task && <p>{t("尚未生成此图表的分析解释。")}</p>}
  </section></WorkflowStage>
    {explanation ? <WordReport key={explanation.id} base={base} runId={runId} revision={revision} figureId={figureId} explanationId={explanation.id}
      canGenerate={canGenerate && current} disabled={disabled || loading || busy || !!error} onBusyChange={setReportBusy} />
      : !loading && !error && <WorkflowStage stage="report"><section className="word-report artifact-panel">
        <div className="section-heading"><span className="step-label">{t("Word 报告")}</span><h3>{t("Word 分析报告导出")}</h3></div>
        <p>{t("请先生成并保存分析解释，再生成 Word 报告。")}</p>
      </section></WorkflowStage>}
  </>
}
