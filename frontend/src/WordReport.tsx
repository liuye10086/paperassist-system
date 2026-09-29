import { useEffect, useRef, useState } from 'react'
type Report = { id: string; analysis_run_id: string; figure_id: string; explanation_id: string; setup_revision: number; source_sha256: string; figure_sha256: string; created_at: string; filename: string; size_bytes: number; sha256: string; language: 'zh-CN'; engine: { id: string; python_docx: string }; input_sha256: string }
type State = { current_revision: number | null; is_current: boolean; ready: boolean; issues: string[]; report: Report | null }
type Props = { base: string; runId: string; revision: number; figureId: string; explanationId: string; canGenerate: boolean; disabled: boolean; onBusyChange: (busy: boolean) => void }
export default function WordReport(props: Props) { return <ReportPanel key={`${props.base}:${props.runId}:${props.figureId}:${props.explanationId}:${props.revision}`} {...props} /> }
function ReportPanel({ base, runId, revision, figureId, explanationId, canGenerate, disabled, onBusyChange }: Props) {
  const endpoint = `${base}/analysis-runs/${runId}/report`
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const active = useRef(true)
  const action = useRef<AbortController | null>(null)
  const report = state?.report
  const current = !!state?.is_current && state.current_revision === revision && (!report || (report.setup_revision === revision && report.analysis_run_id === runId && report.figure_id === figureId && report.explanation_id === explanationId))
  const allowed = !!state?.ready && current && !!figureId && !!explanationId && canGenerate && !disabled && !loading && !submitting && !error
  useEffect(() => { active.current = true; return () => { active.current = false; action.current?.abort() } }, [])
  useEffect(() => { onBusyChange(submitting); return () => onBusyChange(false) }, [submitting, onBusyChange])
  async function request(controller: AbortController, post: boolean): Promise<State> {
    let timer = 0
    try { return await Promise.race([fetch(endpoint, { signal: controller.signal, ...(post ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: revision, figure_id: figureId, explanation_id: explanationId }) } : {}) }).then(async response => {
      const body = await response.json().catch(() => null)
      if (!response.ok) throw new Error(typeof body?.detail?.message === 'string' ? body.detail.message : '报告请求失败，请重新读取报告。')
      return body as State
    }), new Promise<never>((_, reject) => { timer = window.setTimeout(() => { controller.abort(); reject(new Error('报告请求超时，后端可能仍在保存。请先重新读取报告，确认状态。')) }, 30_000) })]) }
    finally { window.clearTimeout(timer) }
  }
  useEffect(() => {
    const controller = new AbortController(); let disposed = false; action.current = controller
    request(controller, false).then(value => { if (!disposed && !controller.signal.aborted) { setState(value); setError('') } }).catch(cause => { if (!disposed) setError(cause instanceof TypeError ? '无法连接后端，请重新读取报告。' : cause instanceof Error ? cause.message : '报告读取失败。') }).finally(() => { if (action.current === controller) action.current = null; if (!disposed) setLoading(false) })
    return () => { disposed = true; controller.abort(); if (action.current === controller) action.current = null }
    // The panel key fixes source IDs and endpoint for its lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt])
  async function generate() {
    if (!allowed || action.current) return
    const controller = new AbortController(); action.current = controller; setSubmitting(true)
    try { const value = await request(controller, true); if (active.current && !controller.signal.aborted) { setState(value); setError('') } }
    catch (cause) { if (active.current) setError(cause instanceof TypeError ? '无法连接后端，请重新读取报告。' : cause instanceof Error ? cause.message : '报告生成失败。') }
    finally { if (action.current === controller) action.current = null; if (active.current) setSubmitting(false) }
  }
  return <section className="word-report" aria-label="Word 分析报告" aria-busy={loading || submitting}>
    <div className="section-heading"><span className="step-label">第五步 · Word 分析报告</span><h3>Word 分析报告导出</h3></div>
    <p className="muted">直接整理已有统计、图表和解释，不再次调用 OpenAI API，无需 API 密钥。</p>
    <p className="warning-panel">AI 文字需人工审核后使用；图中像素尚未经过自动核验。</p>
    {!canGenerate && <p className="warning-panel">请保存当前配置并完成对应统计、图表和解释后生成报告。</p>}
    {report && (!current || !canGenerate) && <p className="warning-panel">以下报告对应旧配置或旧来源（版本 {report.setup_revision}），可继续下载历史报告。</p>}
    <div className="analysis-actions"><button type="button" disabled={!allowed} onClick={() => void generate()}>生成 Word 报告</button><button type="button" disabled={loading || submitting || disabled} onClick={() => { setLoading(true); setAttempt(value => value + 1) }}>重新读取报告</button></div>
    {loading && <p role="status">正在读取报告……</p>}{submitting && <p role="status">正在生成 Word 报告……</p>}
    {error && <p role="alert" className="error-panel">{error}</p>}
    {state?.issues?.length ? <ul>{state.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul> : null}
    {report && <><p><a href={`${endpoint}/${encodeURIComponent(report.id)}/download`}>下载 Word 报告</a></p><p>文件：{report.filename}；配置版本：{report.setup_revision}；生成时间：{report.created_at}；文件大小：{report.size_bytes} 字节</p>
      <details className="statistics-provenance"><summary>报告来源记录</summary><p>报告编号：{report.id}；统计结果编号：{report.analysis_run_id}；图表编号：{report.figure_id}；解释编号：{report.explanation_id}</p><p>原文件 SHA256：{report.source_sha256}</p><p>图片 SHA256：{report.figure_sha256}</p><p>报告 SHA256：{report.sha256}</p><p>输入 SHA256：{report.input_sha256}</p><p>语言：{report.language}；工具：{report.engine.id}；python-docx：{report.engine.python_docx}</p></details></>}
  </section>
}
