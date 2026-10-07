import { useI18n, apiError, safeError } from '../../shared/i18n'
import { apiFetch } from '../../shared/api/client'
import { useEffect, useRef, useState } from 'react'
import { WorkflowStage, WorkflowReadStatus } from '../analysis/AnalysisWorkflow'
import './artifactPanels.css'
import AnalysisExplanation from '../explanations/AnalysisExplanation'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'

type Figure = { id: string; analysis_run_id: string; setup_revision: number; title: string; caption: string
  x_label: string; y_label: string; source_sha256: string; sha256: string; created_at: string
  engine: { id: string; provider: string; model: string }; verification: { status: string; note: string } }
type Job = { id: string; status: 'submitting' | 'running' | 'failed' | 'uncertain' | 'completed'; message: string; message_code?: string; message_params?: Record<string, string | number>; response_id: string | null; created_at: string }
type State = { current_revision: number | null; is_current: boolean; figure: Figure | null; job: Job | null }
type Config = { configured: boolean; model: string | null; message: string; message_code?: string; message_params?: Record<string, string | number> }
type Props = { base: string; runId: string; revision: number; canGenerate: boolean; disabled: boolean; onBusyChange: (busy: boolean) => void }
class RequestError extends Error {
  status: number
  constructor(text: string, status: number) { super(text); this.status = status }
}

async function request<T>(url: string, controller: AbortController, init?: RequestInit): Promise<T> {
  let timer = 0
  try {
    return await Promise.race([apiFetch(url, { ...init, signal: controller.signal }).then(async response => {
      const body = await response.json().catch(() => null)
      if (!response.ok) throw new RequestError(apiError(body, '图表请求失败，请重新读取图表。'), response.status)
      return body as T
    }), new Promise<never>((_, reject) => {
      timer = window.setTimeout(() => { controller.abort(); reject(new Error('图表请求超时，后端可能仍在处理。请先重新读取图表，确认状态。')) }, 30_000)
    })])
  } finally { window.clearTimeout(timer) }
}
function message(cause: unknown) {
  return cause instanceof TypeError ? '无法连接后端，请确认服务正常后重新读取图表。' : safeError(cause, '图表请求失败，请重新读取图表。')
}

export default function BoxplotFigure(props: Props) {
  return <FigurePanel key={`${props.base}:${props.runId}`} {...props} />
}
function FigurePanel({ base, runId, revision, canGenerate, disabled, onBusyChange }: Props) {
  const { t } = useI18n()
  const endpoint = `${base}/analysis-runs/${runId}/boxplot`
  const [state, setState] = useState<State | null>(null)
  const [explanationBusy, setExplanationBusy] = useState(false)
  const [config, setConfig] = useState<Config | null>(null)
  const [configError, setConfigError] = useState('')
  const [configAttempt, setConfigAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [imageError, setImageError] = useState(false)
  const [imageAttempt, setImageAttempt] = useState(0)
  const [attempt, setAttempt] = useState(0)
  const active = useRef(true)
  const action = useRef<AbortController | null>(null)
  const reading = useRef<AbortController | null>(null)
  const running = state?.job?.status === 'submitting' || state?.job?.status === 'running'
  const retry = state?.job?.status === 'failed' || state?.job?.status === 'uncertain'
  const busy = submitting || (running && !error)
  const allowed = !!config?.configured && canGenerate && !disabled && !!state?.is_current && state.current_revision === revision && !loading && !busy && !explanationBusy && !error

  useEffect(() => { active.current = true; return () => { active.current = false; action.current?.abort(); reading.current?.abort() } }, [])
  useEffect(() => {
    if (!imageError) return
    const projectPath = /^\/api\/v1\/projects\/[^/?#]+/.exec(base)?.[0]
    if (!projectPath) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), 15_000)
    // The image request cannot distinguish a missing resource from lost project access.
    void apiFetch(projectPath, { signal: controller.signal }).catch(() => {}).finally(() => window.clearTimeout(timer))
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [base, imageError])
  useEffect(() => { onBusyChange(busy || explanationBusy); return () => onBusyChange(false) }, [busy, explanationBusy, onBusyChange])
  useEffect(() => {
    const controller = new AbortController()
    let disposed = false
    request<Config>('/api/v1/ai/config', controller).then(value => { if (!disposed && !controller.signal.aborted) setConfig(value) })
      .catch(cause => { if (!disposed) setConfigError(message(cause)) })
    return () => { disposed = true; controller.abort() }
  }, [configAttempt])

  useEffect(() => {
    let disposed = false
    let poll = 0
    async function read() {
      if (disposed || reading.current || action.current) return
      const controller = new AbortController(); reading.current = controller
      try {
        const value = await request<State>(endpoint, controller)
        if (disposed || controller.signal.aborted) return
        setState(value); setError('')
        if (value.job?.status === 'submitting' || value.job?.status === 'running') poll = window.setTimeout(() => void read(), 3000)
      } catch (cause) { if (!disposed) {
        setError(message(cause))
        if (cause instanceof RequestError && cause.status === 409) setState(previous => previous ? { ...previous, is_current: false } : previous)
      } }
      finally { if (reading.current === controller) reading.current = null; if (!disposed) setLoading(false) }
    }
    void read()
    return () => { disposed = true; window.clearTimeout(poll); reading.current?.abort(); reading.current = null }
  }, [endpoint, attempt])

  async function generate() {
    if (!allowed || action.current) return
    const controller = new AbortController(); action.current = controller
    reading.current?.abort(); reading.current = null
    setSubmitting(true); setError(''); setAttempt(value => value + 1)
    try {
      const value = await request<State>(endpoint, controller, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_revision: revision, ...(retry ? { retry: true } : {}) }) })
      if (!active.current || controller.signal.aborted) return
      setState(value); setImageError(false)
      if (value.job?.status === 'submitting' || value.job?.status === 'running') setAttempt(value => value + 1)
    } catch (cause) { if (active.current) {
      setError(message(cause))
      if (cause instanceof RequestError && cause.status === 409) setState(previous => previous ? { ...previous, is_current: false } : previous)
    } }
    finally { if (action.current === controller) action.current = null; if (active.current) setSubmitting(false) }
  }
  const figure = state?.figure
  function reload() {
    setLoading(true); setError(''); setImageError(false); setImageAttempt(value => value + 1); setAttempt(value => value + 1)
  }
  return <>
    <WorkflowReadStatus stages={['explanation', 'report']} loading={loading} error={error}
      loadingMessage="正在读取图表……" reloadLabel="重新读取图表" onReload={reload} disabled={submitting || explanationBusy} />
    <WorkflowStage stage="figure"><section className="boxplot-figure artifact-panel" aria-label={t("OpenAI 箱线图")} aria-busy={loading || busy}>
    <div className="section-heading"><span className="step-label">{t("图表")}</span><h3>{t("箱线图")}</h3></div>
    <p className="muted">{t("仅将所选数值列、分组列的完整记录及绘图标签发送给 OpenAI。生成会调用收费 API；读取已保存图表与下载不会重新生成。")}</p>
    {!config && !configError && <p role="status">{t("正在读取 OpenAI 配置……")}</p>}
    {config && !config.configured && <p className="warning-panel">{t(apiError({ code: config.message_code ?? 'openai_not_configured', params: config.message_params }, '请联系管理员配置 OpenAI API。'))}</p>}
    {configError && <p role="alert" className="error-panel">{t(configError)}</p>}
    {configError && <button type="button" onClick={() => { setConfig(null); setConfigError(''); setConfigAttempt(value => value + 1) }}>{t("重试读取 OpenAI 配置")}</button>}
    {!canGenerate && <p className="warning-panel">{t("请保存当前字段并执行对应配置的描述统计后，再生成图表。")}</p>}
    {figure && (!canGenerate || !state.is_current || state.current_revision !== revision) && <p className="warning-panel">{t('以下图表对应旧配置，仍可查看和下载。')}</p>}
    {retry && <p className="warning-panel">{state.job?.status === 'uncertain' ? t("上次提交状态不确定，不能确认是否已计费。") : t("上次生成失败。")}{t("再次调用 API 可能产生额外费用，请确认后点击重试。")}</p>}
    <div className="analysis-actions">
      <button type="button" disabled={!allowed} onClick={() => void generate()}>{retry ? t("重试生成（再次调用 API）") : t("使用 OpenAI 生成箱线图")}</button>
      <button type="button" disabled={loading || submitting || explanationBusy} onClick={reload}>{t("重新读取图表")}</button>
    </div>
    {loading && <p role="status">{t("正在读取图表……")}</p>}
    {(submitting || running) && <p role="status">{state?.job ? t(apiError({ code: state.job.message_code ?? `task_${state.job.status}`, params: state.job.message_params }, '任务状态暂不可用。')) : t("正在提交 OpenAI 绘图任务，请稍候……")}</p>}
    {retry && state.job && <p role="status">{t(apiError({ code: state.job.message_code ?? `task_${state.job.status}`, params: state.job.message_params }, '任务状态暂不可用。'))}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {imageError && <p role="alert" className="error-panel">{t("图片读取失败，请点击“重新读取图表”重试。")}</p>}
    {figure && <figure>
      <p className="artifact-status">{t(canGenerate && state?.is_current && state.current_revision === revision ? "当前结果" : "历史结果")}</p>
      <h4>{figure.title}</h4>
      {!imageError && <img key={`${figure.id}:${imageAttempt}`} src={`${endpoint}/image?v=${encodeURIComponent(figure.id)}&reload=${imageAttempt}`} alt={figure.title} onError={() => setImageError(true)} />}
      <figcaption>{figure.caption}</figcaption>
      <p><ProjectDownloadLink href={`${endpoint}/image?download=true`} filename="boxplot.png">{t("下载箱线图 PNG")}</ProjectDownloadLink></p>
      <details className="artifact-details"><summary>{t("图表来源与核对记录")}</summary>
        <p>{t("横轴：")}{figure.x_label}{t("；纵轴：")}{figure.y_label}</p>
        <p>{figure.verification.note}{t("；请同时人工核对图像与标签。")}</p>
        <p>{t("保存时间：")}{figure.created_at}</p>
      </details>
    </figure>}
    {state && !figure && !state.job && <p>{t("尚未生成此统计结果的箱线图。")}</p>}
  </section></WorkflowStage>
    {figure ? <AnalysisExplanation base={base} runId={runId} revision={revision} figureId={figure.id}
      canGenerate={canGenerate && !!state?.is_current && state.current_revision === revision && figure.setup_revision === revision}
      disabled={disabled || loading || busy || !!error} onBusyChange={setExplanationBusy}
      configuration={config} configurationError={t(configError)}
      onReloadConfiguration={() => { setConfig(null); setConfigError(''); setConfigAttempt(value => value + 1) }} />
      : !loading && !error && <>
        <WorkflowStage stage="explanation"><section className="analysis-explanation artifact-panel">
          <div className="section-heading"><span className="step-label">{t("分析解释")}</span><h3>{t("分析解释与论文表述")}</h3></div>
          <p>{t("请先生成并保存箱线图，再生成分析解释。")}</p>
        </section></WorkflowStage>
        <WorkflowStage stage="report"><section className="word-report artifact-panel">
          <div className="section-heading"><span className="step-label">{t("Word 报告")}</span><h3>{t("Word 分析报告导出")}</h3></div>
          <p>{t("请先完成图表和分析解释，再生成 Word 报告。")}</p>
        </section></WorkflowStage>
      </>}
  </>
}
