import { useI18n, apiError, safeError } from '../../shared/i18n'
import { workflowNotice } from '../../shared/i18n/workflowMessages'
import { apiFetch } from '../../shared/api/client'
import { useEffect, useRef, useState } from 'react'
import { WorkflowStage } from '../analysis/AnalysisWorkflow'
import '../figures/artifactPanels.css'
import { artifactFilename } from '../../shared/components/artifactFilename'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
type Report = { id: string; analysis_run_id: string; figure_id: string; explanation_id: string; setup_revision: number; source_sha256: string; figure_sha256: string; created_at: string; filename: string; size_bytes: number; sha256: string; language: 'zh-CN' | 'en'; engine: { id: string; python_docx: string }; input_sha256: string }
type Task = { id: string; status: 'queued' | 'running' | 'succeeded' | 'failed' | 'waiting_input' | 'waiting_confirmation'; revision: number; error_code: string | null; result_report_id: string | null }
type State = { current_revision: number | null; is_current: boolean; ready: boolean; issues: string[]; report: Report | null; task?: Task | null }
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
  const [pollTick, setPollTick] = useState(0)
  const active = useRef(true)
  const action = useRef<AbortController | null>(null)
  const report = state?.report
  const task = state?.task
  const pending = task?.status === 'queued' || task?.status === 'running'
  const needsReport = task?.status === 'succeeded' && !report
  const failed = task?.status === 'failed'
  const filename = report ? artifactFilename(report.filename, 'report', report.id, report.setup_revision, locale) : ''
  const current = !!state?.is_current && state.current_revision === revision && (!report || (report.setup_revision === revision && report.analysis_run_id === runId && report.figure_id === figureId && report.explanation_id === explanationId))
  const allowed = !!state?.ready && current && !!figureId && !!explanationId && canGenerate && !disabled && !loading && !submitting && !pending && !needsReport && !error
  useEffect(() => { active.current = true; return () => { active.current = false; action.current?.abort() } }, [])
  useEffect(() => { onBusyChange(submitting); return () => onBusyChange(false) }, [submitting, onBusyChange])
  async function request<T>(controller: AbortController, url = endpoint, init?: RequestInit): Promise<T> {
    let timer = 0
    try { return await Promise.race([apiFetch(url, { ...init, signal: controller.signal }).then(async response => {
      const body = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiError(body, '报告请求失败，请重新读取报告。'))
      return body as T
    }), new Promise<never>((_, reject) => { timer = window.setTimeout(() => { controller.abort(); reject(new Error('报告请求超时，后端可能仍在保存。请先重新读取报告，确认状态。')) }, 30_000) })]) }
    finally { window.clearTimeout(timer) }
  }
  useEffect(() => {
    const controller = new AbortController(); let disposed = false; action.current = controller
    request<State>(controller).then(value => { if (!disposed && !controller.signal.aborted) { setState(value); setError('') } }).catch(cause => { if (!disposed) setError(cause instanceof TypeError ? '无法连接后端，请重新读取报告。' : safeError(cause, '报告读取失败。')) }).finally(() => { if (action.current === controller) action.current = null; if (!disposed) setLoading(false) })
    return () => { disposed = true; controller.abort(); if (action.current === controller) action.current = null }
    // The panel key fixes source IDs and endpoint for its lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt])
  useEffect(() => {
    if (!task || (!pending && !needsReport) || loading || submitting || error) return
    const controller = new AbortController(); let disposed = false
    const timer = window.setTimeout(async () => {
      try {
        const value = needsReport ? task : await request<Task>(controller, `/api/v1/tasks/${encodeURIComponent(task.id)}`)
        // Keep completion and its report read in one response generation so an
        // effect cleanup cannot abort between the two state updates.
        const completed = value.status === 'succeeded' ? await request<State>(controller) : null
        if (disposed || controller.signal.aborted) return
        if (completed) setState(completed)
        else setState(previous => previous ? { ...previous, task: value } : previous)
        setPollTick(value => value + 1)
      } catch (cause) { if (!disposed) setError(cause instanceof TypeError ? '无法连接后端，请重新读取报告。' : safeError(cause, '报告读取失败。')) }
    }, 3000)
    return () => { disposed = true; window.clearTimeout(timer); controller.abort() }
    // The panel key fixes endpoint and source IDs for this mounted instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id, task?.status, task?.revision, pending, needsReport, loading, submitting, error, pollTick])
  async function generate() {
    if (!allowed || action.current) return
    const controller = new AbortController(); action.current = controller; setSubmitting(true)
    try {
      const value = failed && task
        ? { ...state!, task: await request<Task>(controller, `/api/v1/tasks/${encodeURIComponent(task.id)}/retry`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: task.revision }) }) }
        : await request<State>(controller, endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json',
          'Idempotency-Key': `word-report-v1:${explanationId}:${revision}` },
          body: JSON.stringify({ expected_revision: revision, figure_id: figureId, explanation_id: explanationId }) })
      if (active.current && !controller.signal.aborted) { setState(value); setError('') }
    }
    catch (cause) { if (active.current) setError(cause instanceof TypeError ? '无法连接后端，请重新读取报告。' : safeError(cause, '报告生成失败。')) }
    finally { if (action.current === controller) action.current = null; if (active.current) setSubmitting(false) }
  }
  return <WorkflowStage stage="report"><section className="word-report artifact-panel" aria-label={t("Word 分析报告")} aria-busy={loading || submitting || ((pending || needsReport) && !error)}>
    <div className="section-heading"><span className="step-label">{t("Word 报告")}</span><h3>{t("Word 分析报告导出")}</h3></div>
    <p className="muted">{t("直接整理已有统计、图表和解释，不再次调用 OpenAI API，无需 API 密钥。")}</p>
    <p className="warning-panel">{t("AI 文字需人工审核后使用；图中像素尚未经过自动核验。")}</p>
    {!canGenerate && <p className="warning-panel">{t("请保存当前配置并完成对应统计、图表和解释后生成报告。")}</p>}
    {report && (!current || !canGenerate) && <p className="warning-panel">{t('以下报告对应旧配置或旧来源，可继续下载历史报告。')}</p>}
    <div className="analysis-actions"><button type="button" disabled={!allowed} onClick={() => void generate()}>{t(failed ? "重试生成 Word 报告" : "生成 Word 报告")}</button><button type="button" disabled={loading || submitting || disabled} onClick={() => { setLoading(true); setAttempt(value => value + 1) }}>{t("重新读取报告")}</button></div>
    {(loading || (needsReport && !error)) && <p role="status">{t("正在读取报告……")}</p>}{submitting && <p role="status">{t("正在提交 Word 报告任务……")}</p>}
    {pending && <p role="status">{t(task?.status === 'queued' ? '等待生成 Word 报告……' : '正在生成 Word 报告……')}{t('可以离开页面，回来后继续查看。')}</p>}
    {failed && <p className="warning-panel">{t('Word 报告生成失败。')}{t(apiError({ code: task?.error_code }, '请重新读取报告，核对来源后重试。'))}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {state?.issues?.length ? <ul>{state.issues.map((issue, index) => <li key={index}>{workflowNotice(issue, t)}</li>)}</ul> : null}
    {report && <><p className="artifact-status">{t(current && canGenerate ? "当前结果" : "历史结果")}</p><p><ProjectDownloadLink href={`${endpoint}/${encodeURIComponent(report.id)}/download`} filename={filename}>{t("下载 Word 报告")}</ProjectDownloadLink></p><p>{t("文件：")}{filename}{t("；生成时间：")}{report.created_at}{t("；文件大小：")}{t('{count} 字节', { count: report.size_bytes })}</p>
      <details className="artifact-details"><summary>{t("报告来源记录")}</summary><p>{t("内容来自已保存的描述统计、箱线图和分析解释。")}</p><p>{t("语言：")}{t(report.language === 'zh-CN' ? '中文' : '英文')}</p></details></>}
    {state && !report && <p className="artifact-empty">{t("尚未生成 Word 报告。完成当前结果后，可将统计、图表和解释整理为可编辑文档。")}</p>}
  </section></WorkflowStage>
}
