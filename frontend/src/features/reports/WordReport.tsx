import { useI18n, apiError, safeError } from '../../shared/i18n'
import { workflowNotice } from '../../shared/i18n/workflowMessages'
import { apiFetch } from '../../shared/api/client'
import { useEffect, useRef, useState } from 'react'
import { WorkflowStage } from '../analysis/AnalysisWorkflow'
import '../figures/artifactPanels.css'
import { artifactFilename } from '../../shared/components/artifactFilename'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
type Report = { id: string; analysis_run_id: string; figure_id: string; explanation_id: string; setup_revision: number; source_sha256: string; figure_sha256: string; created_at: string; filename: string; size_bytes: number; sha256: string; language: 'zh-CN' | 'en'; engine: { id: string; python_docx: string }; input_sha256: string }
type State = { current_revision: number | null; is_current: boolean; ready: boolean; issues: string[]; report: Report | null }
type Props = { base: string; runId: string; revision: number; figureId: string; explanationId: string; canGenerate: boolean; disabled: boolean; onBusyChange: (busy: boolean) => void }
export default function WordReport(props: Props) { return <ReportPanel key={`${props.base}:${props.runId}:${props.figureId}:${props.explanationId}:${props.revision}`} {...props} /> }
function ReportPanel({ base, runId, revision, figureId, explanationId, canGenerate, disabled, onBusyChange }: Props) {
  const { t, locale } = useI18n()
  const endpoint = `${base}/analysis-runs/${runId}/report`
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const active = useRef(true)
  const action = useRef<AbortController | null>(null)
  const report = state?.report
  const filename = report ? artifactFilename(report.filename, 'report', report.id, report.setup_revision, locale) : ''
  const current = !!state?.is_current && state.current_revision === revision && (!report || (report.setup_revision === revision && report.analysis_run_id === runId && report.figure_id === figureId && report.explanation_id === explanationId))
  const allowed = !!state?.ready && current && !!figureId && !!explanationId && canGenerate && !disabled && !loading && !submitting && !error
  useEffect(() => { active.current = true; return () => { active.current = false; action.current?.abort() } }, [])
  useEffect(() => { onBusyChange(submitting); return () => onBusyChange(false) }, [submitting, onBusyChange])
  async function request(controller: AbortController, post: boolean): Promise<State> {
    let timer = 0
    try { return await Promise.race([apiFetch(endpoint, { signal: controller.signal, ...(post ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: revision, figure_id: figureId, explanation_id: explanationId }) } : {}) }).then(async response => {
      const body = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiError(body, '报告请求失败，请重新读取报告。'))
      return body as State
    }), new Promise<never>((_, reject) => { timer = window.setTimeout(() => { controller.abort(); reject(new Error('报告请求超时，后端可能仍在保存。请先重新读取报告，确认状态。')) }, 30_000) })]) }
    finally { window.clearTimeout(timer) }
  }
  useEffect(() => {
    const controller = new AbortController(); let disposed = false; action.current = controller
    request(controller, false).then(value => { if (!disposed && !controller.signal.aborted) { setState(value); setError('') } }).catch(cause => { if (!disposed) setError(cause instanceof TypeError ? '无法连接后端，请重新读取报告。' : safeError(cause, '报告读取失败。')) }).finally(() => { if (action.current === controller) action.current = null; if (!disposed) setLoading(false) })
    return () => { disposed = true; controller.abort(); if (action.current === controller) action.current = null }
    // The panel key fixes source IDs and endpoint for its lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt])
  async function generate() {
    if (!allowed || action.current) return
    const controller = new AbortController(); action.current = controller; setSubmitting(true)
    try { const value = await request(controller, true); if (active.current && !controller.signal.aborted) { setState(value); setError('') } }
    catch (cause) { if (active.current) setError(cause instanceof TypeError ? '无法连接后端，请重新读取报告。' : safeError(cause, '报告生成失败。')) }
    finally { if (action.current === controller) action.current = null; if (active.current) setSubmitting(false) }
  }
  return <WorkflowStage stage="report"><section className="word-report artifact-panel" aria-label={t("Word 分析报告")} aria-busy={loading || submitting}>
    <div className="section-heading"><span className="step-label">{t("Word 报告")}</span><h3>{t("Word 分析报告导出")}</h3></div>
    <p className="muted">{t("直接整理已有统计、图表和解释，不再次调用 OpenAI API，无需 API 密钥。")}</p>
    <p className="warning-panel">{t("AI 文字需人工审核后使用；图中像素尚未经过自动核验。")}</p>
    {!canGenerate && <p className="warning-panel">{t("请保存当前配置并完成对应统计、图表和解释后生成报告。")}</p>}
    {report && (!current || !canGenerate) && <p className="warning-panel">{t('以下报告对应旧配置或旧来源，可继续下载历史报告。')}</p>}
    <div className="analysis-actions"><button type="button" disabled={!allowed} onClick={() => void generate()}>{t("生成 Word 报告")}</button><button type="button" disabled={loading || submitting || disabled} onClick={() => { setLoading(true); setAttempt(value => value + 1) }}>{t("重新读取报告")}</button></div>
    {loading && <p role="status">{t("正在读取报告……")}</p>}{submitting && <p role="status">{t("正在生成 Word 报告……")}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {state?.issues?.length ? <ul>{state.issues.map((issue, index) => <li key={index}>{workflowNotice(issue, t)}</li>)}</ul> : null}
    {report && <><p className="artifact-status">{t(current && canGenerate ? "当前结果" : "历史结果")}</p><p><ProjectDownloadLink href={`${endpoint}/${encodeURIComponent(report.id)}/download`} filename={filename}>{t("下载 Word 报告")}</ProjectDownloadLink></p><p>{t("文件：")}{filename}{t("；生成时间：")}{report.created_at}{t("；文件大小：")}{t('{count} 字节', { count: report.size_bytes })}</p>
      <details className="artifact-details"><summary>{t("报告来源记录")}</summary><p>{t("内容来自已保存的描述统计、箱线图和分析解释。")}</p><p>{t("语言：")}{t(report.language === 'zh-CN' ? '中文' : '英文')}</p></details></>}
    {state && !report && <p className="artifact-empty">{t("尚未生成 Word 报告。完成当前结果后，可将统计、图表和解释整理为可编辑文档。")}</p>}
  </section></WorkflowStage>
}
