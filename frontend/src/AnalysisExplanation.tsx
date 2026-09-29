import { useEffect, useRef, useState } from 'react'
import WordReport from './WordReport'

type Config = { configured: boolean; model: string | null; message: string }
type Explanation = {
  id: string; analysis_run_id: string; figure_id: string; setup_revision: number; language: 'zh-CN'
  figure_sha256: string; source_sha256: string; created_at: string
  sections: { key: string; title: string; text: string; evidence: { key: string; label: string; value: string }[] }[]
  limitations: string[]; engine: { id: string; provider: string; model: string }
  verification: { status: string; note: string }; provenance: Record<string, unknown>
}
type State = { current_revision: number | null; is_current: boolean; figure_id: string | null; explanation: Explanation | null
  job: { id: string; status: 'submitting' | 'running' | 'failed' | 'uncertain' | 'completed'; message: string; response_id: string | null; created_at: string } | null }
type Props = { base: string; runId: string; revision: number; figureId: string; canGenerate: boolean; disabled: boolean
  onBusyChange: (busy: boolean) => void; configuration?: Config | null; configurationError?: string; onReloadConfiguration?: () => void }
class RequestError extends Error {
  status: number
  constructor(text: string, status: number) { super(text); this.status = status }
}
async function request<T>(url: string, controller: AbortController, init?: RequestInit): Promise<T> {
  let timer = 0
  try {
    return await Promise.race([fetch(url, { ...init, signal: controller.signal }).then(async response => {
      const body = await response.json().catch(() => null)
      if (!response.ok) throw new RequestError(typeof body?.detail?.message === 'string' ? body.detail.message : '解释请求失败，请重新读取解释。', response.status)
      return body as T
    }), new Promise<never>((_, reject) => {
      timer = window.setTimeout(() => { controller.abort(); reject(new Error('解释请求超时，后端可能仍在处理。请先重新读取解释，确认状态。')) }, 30_000)
    })])
  } finally { window.clearTimeout(timer) }
}
function message(cause: unknown) {
  return cause instanceof TypeError ? '无法连接后端，请确认服务正常后重新读取解释。' : cause instanceof Error ? cause.message : '解释请求失败，请重新读取解释。'
}
export default function AnalysisExplanation(props: Props) {
  return <ExplanationPanel key={`${props.base}:${props.runId}:${props.figureId}`} {...props} />
}
function ExplanationPanel({ base, runId, revision, figureId, canGenerate, disabled, onBusyChange, configuration, configurationError, onReloadConfiguration }: Props) {
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
  const sharedConfig = !!onReloadConfiguration
  const config = sharedConfig ? configuration : localConfig
  const configError = sharedConfig ? configurationError : localConfigError
  const running = state?.job?.status === 'submitting' || state?.job?.status === 'running'
  const retry = state?.job?.status === 'failed' || state?.job?.status === 'uncertain'
  const busy = submitting || (running && !error)
  const explanation = state?.explanation
  const current = !!state?.is_current && state.current_revision === revision && state.figure_id === figureId
    && (!explanation || (explanation.setup_revision === revision && explanation.figure_id === figureId && explanation.analysis_run_id === runId))
  const allowed = !!config?.configured && current && canGenerate && !disabled && !loading && !busy && !reportBusy && !error

  useEffect(() => { active.current = true; return () => { active.current = false; action.current?.abort(); reading.current?.abort() } }, [])
  useEffect(() => { onBusyChange(busy || reportBusy); return () => onBusyChange(false) }, [busy, reportBusy, onBusyChange])
  useEffect(() => {
    if (sharedConfig) return
    const controller = new AbortController(); let disposed = false
    request<Config>('/api/v1/ai/config', controller).then(value => { if (!disposed && !controller.signal.aborted) setLocalConfig(value) })
      .catch(cause => { if (!disposed) setLocalConfigError(message(cause)) })
    return () => { disposed = true; controller.abort() }
  }, [configAttempt, sharedConfig])
  useEffect(() => {
    let disposed = false; let poll = 0
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
      } } finally { if (reading.current === controller) reading.current = null; if (!disposed) setLoading(false) }
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
        body: JSON.stringify({ expected_revision: revision, figure_id: figureId, ...(retry ? { retry: true } : {}) }) })
      if (!active.current || controller.signal.aborted) return
      setState(value)
      if (value.job?.status === 'submitting' || value.job?.status === 'running') setAttempt(value => value + 1)
    } catch (cause) { if (active.current) {
      setError(message(cause))
      if (cause instanceof RequestError && cause.status === 409) setState(previous => previous ? { ...previous, is_current: false } : previous)
    } } finally { if (action.current === controller) action.current = null; if (active.current) setSubmitting(false) }
  }
  function reloadConfig() {
    if (onReloadConfiguration) onReloadConfiguration()
    else { setLocalConfig(null); setLocalConfigError(''); setConfigAttempt(value => value + 1) }
  }
  return <section className="analysis-explanation" aria-label="AI 分析解释" aria-busy={loading || busy}>
    <div className="section-heading"><span className="step-label">第四步 · AI 分析解释</span><h3>分析解释与论文表述</h3></div>
    <p className="warning-panel">AI 草稿，必须人工审核后使用。解释基于已保存的分析配置、描述统计与图表；不代表因果结论或显著性检验。</p>
    <p className="muted">点击生成会调用收费 OpenAI API；重新读取已保存解释不会再次生成。</p>
    {!sharedConfig && !config && !configError && <p role="status">正在读取解释 OpenAI 配置……</p>}
    {!sharedConfig && config && !config.configured && <p className="warning-panel">{config.message || '请在 backend/.env 配置 OpenAI API。'}</p>}
    {!sharedConfig && configError && <p role="alert" className="error-panel">{configError}</p>}
    {(!config?.configured || configError) && <button type="button" onClick={reloadConfig}>重新读取解释 OpenAI 配置</button>}
    {!canGenerate && <p className="warning-panel">请保存当前字段并完成对应配置的描述统计和图表后，再生成解释。</p>}
    {explanation && (!current || !canGenerate) && <p className="warning-panel">以下解释对应旧配置或旧图表（版本 {explanation.setup_revision}），仅供查看，请使用当前结果重新生成。</p>}
    {retry && <p className="warning-panel">{state.job?.status === 'uncertain' ? '上次解释提交状态不确定，不能确认是否已计费。' : '上次解释生成失败。'}再次调用 API 可能产生额外费用，请确认后点击重试。</p>}
    <div className="analysis-actions">
      <button type="button" disabled={!allowed} onClick={() => void generate()}>{retry ? '重试生成解释（再次调用 API）' : '使用 OpenAI 生成解释'}</button>
      <button type="button" disabled={loading || submitting || reportBusy} onClick={() => { setLoading(true); setAttempt(value => value + 1) }}>重新读取解释</button>
    </div>
    {loading && <p role="status">正在读取解释……</p>}
    {(submitting || running) && <p role="status">{state?.job?.message || '正在提交 OpenAI 解释任务，请稍候……'}</p>}
    {retry && state.job?.message && <p role="status">{state.job.message}</p>}
    {error && <p role="alert" className="error-panel">{error}</p>}
    {explanation && <>
      {explanation.sections.map(section => <section className="explanation-section" key={section.key}>
        <h4>{section.title}</h4><p className="explanation-text">{section.text}</p>
        <details><summary>依据：已保存配置、统计结果与图表</summary><ul>{section.evidence.map(evidence => <li key={evidence.key}>{evidence.label}：{evidence.value}</li>)}</ul></details>
      </section>)}
      <h4>解释限制</h4><ul>{explanation.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul>
      <details className="statistics-provenance"><summary>解释来源与核对记录</summary>
        <p>解释编号：{explanation.id}；配置版本：{explanation.setup_revision}；语言：{explanation.language}</p>
        <p>统计结果编号：{explanation.analysis_run_id}；图表编号：{explanation.figure_id}</p>
        <p>模型：{explanation.engine.model}；提供方：{explanation.engine.provider}；工具：{explanation.engine.id}</p>
        <p>核对状态：{explanation.verification.status}；{explanation.verification.note}</p>
        <p>原文件 SHA256：{explanation.source_sha256}</p><p>图片 SHA256：{explanation.figure_sha256}</p><p>保存时间：{explanation.created_at}</p>
        <pre>{JSON.stringify(explanation.provenance, null, 2)}</pre>
      </details>
    </>}
    {explanation && <WordReport key={explanation.id} base={base} runId={runId} revision={revision} figureId={figureId} explanationId={explanation.id} canGenerate={canGenerate && current} disabled={disabled || loading || busy} onBusyChange={setReportBusy} />}
    {state && !explanation && !state.job && <p>尚未生成此图表的分析解释。</p>}
  </section>
}
