import { useI18n, apiError, safeError } from './i18n'
import { workflowNotice } from './i18n/workflowMessages'
import { apiFetch } from './api'
import { useEffect, useRef, useState } from 'react'
import type { Check, Selection } from './AnalysisSetup'
import BoxplotFigure from './BoxplotFigure'

type Summary = { n: number; mean: number; std: number | null; min: number; q1: number; median: number
  q3: number; max: number; iqr: number | null; warnings: string[] }
type Result = { id: string; filename: string; source_sha256: string; setup_revision: number; selection: Selection
  check: Check; numeric_name: string; group_name: string | null; started_at: string; completed_at: string
  engine: { id: string; python_version: string; openpyxl_version: string }; overall: Summary
  groups: { label: string; statistics: Summary }[] }
type ResultState = { current_revision: number | null; is_current: boolean; result: Result | null }

function formatted(value: number | null, locale: string) {
  if (value === null) return '—'
  return new Intl.NumberFormat(locale, { maximumSignificantDigits: 6,
    notation: value !== 0 && (Math.abs(value) < 0.0001 || Math.abs(value) >= 1e9) ? 'scientific' : 'standard',
    useGrouping: false }).format(value)
}

async function request<T>(url: string, signal: AbortSignal, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, { ...init, signal })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(apiError(body, '统计请求失败，请重新读取结果后重试。'))
  return body
}

function explain(cause: unknown, timedOut: boolean) {
  if (timedOut) return '等待统计请求超时。后端可能仍在处理，请先重新读取统计结果，再决定是否重试。'
  if (cause instanceof TypeError) return '无法连接后端，请确认服务正常并重新读取统计结果。'
  return safeError(cause, '统计请求失败，请重新读取结果后重试。')
}

export default function StatisticsResults({ base, savedRevision, fieldsMatch, disabled, onBusyChange }: {
  base: string; savedRevision: number | null; fieldsMatch: boolean; disabled: boolean; onBusyChange: (value: boolean) => void
}) {
  const { t, locale } = useI18n()
  const [state, setState] = useState<ResultState | null>(null)
  const [loading, setLoading] = useState(!!savedRevision)
  const [running, setRunning] = useState(false)
  const [plotBusy, setPlotBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [attempt, setAttempt] = useState(0)
  const action = useRef<AbortController | null>(null)
  const result = state?.result
  const revisionMatches = !!savedRevision && state?.current_revision === savedRevision

  useEffect(() => {
    if (!savedRevision) return
    const controller = new AbortController()
    let active = true
    const timeout = window.setTimeout(() => controller.abort(), 30_000)
    request<ResultState>(`${base}/analysis-result`, controller.signal)
      .then(value => { if (active && !controller.signal.aborted) setState(value) })
      .catch(cause => { if (active) { setState(null); setError(explain(cause, controller.signal.aborted)) } })
      .finally(() => { window.clearTimeout(timeout); if (active) setLoading(false) })
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [base, savedRevision, attempt])
  useEffect(() => () => action.current?.abort(), [])
  useEffect(() => { onBusyChange(running || plotBusy) }, [running, plotBusy, onBusyChange])

  async function execute() {
    if (action.current || loading || disabled || plotBusy || !fieldsMatch || !revisionMatches) return
    const controller = new AbortController()
    action.current = controller
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort() }, 120_000)
    setRunning(true)
    setError('')
    setNotice('')
    try {
      const value = await request<Result>(`${base}/analysis-runs`, controller.signal, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: savedRevision }) })
      if (!controller.signal.aborted) {
        setState({ current_revision: savedRevision, is_current: true, result: value })
        setNotice('结果已保存，刷新或重启后可再次查看。重复执行同一配置会返回已保存结果。')
      }
    } catch (cause) {
      if (!controller.signal.aborted || timedOut) setError(explain(cause, timedOut))
    } finally {
      window.clearTimeout(timeout)
      if (action.current === controller) action.current = null
      if (!controller.signal.aborted || timedOut) setRunning(false)
    }
  }

  const rows = result ? [{ label: t('总体（完整记录）'), statistics: result.overall }, ...result.groups] : []
  return <section className="statistics-results" aria-labelledby="statistics-title" aria-busy={loading || running}>
    <div className="section-heading"><span className="step-label">{t("第二步 · 统计计算")}</span>
      <h3 id="statistics-title">{t("描述统计")}</h3>
      <p>{t("按已保存的字段配置读取整张工作表，计算总体和各分组的统计量。")}</p>
    </div>
    {!savedRevision ? <p className="muted">{t("请先检查字段并保存分析配置。")}</p>
      : !fieldsMatch && <p className="warning-panel">{t("当前字段尚未保存，请先检查并保存，再执行统计。已有结果对应其标注的配置。")}</p>}
    {state && savedRevision && !revisionMatches && <p className="warning-panel">{t("配置已在其他页面变化，请点击“重新载入分析配置”后再执行。")}</p>}
    <div className="analysis-actions">
      <button type="button" disabled={disabled || plotBusy || loading || running || !fieldsMatch || !revisionMatches} onClick={() => void execute()}>{t("执行描述统计")}</button>
      <button type="button" disabled={disabled || plotBusy || loading || running || !savedRevision} onClick={() => {
        setNotice(''); setError(''); setLoading(true); setAttempt(value => value + 1)
      }}>{t("重新读取统计结果")}</button>
    </div>
    {loading && <p role="status">{t("正在读取统计结果……")}</p>}
    {running && <p role="status">{t("正在计算描述统计，请稍候……")}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {notice && <p role="status" className="saved-notice">{t(notice)}</p>}
    {state && !result && <p>{t("尚未执行当前配置的描述统计。")}</p>}
    {result && <>
      {!state.is_current && <p className="warning-panel">{t("以下为旧配置的统计结果，当前配置尚未计算。执行后将显示新结果，旧结果仍保留。")}</p>}
      <p>{t("配置版本：")}{result.setup_revision}{t("；工作表：")}{result.selection.sheet_name}{t("；完成时间：")}{new Date(result.completed_at).toLocaleString(locale)}</p>
      <p>{t("数值：")}{result.selection.numeric_column} · {result.numeric_name}{t("；单位：")}{result.selection.unit || t("未填写")}{t("； 分组：")}{result.selection.group_column ? `${result.selection.group_column} · ${result.group_name}` : t("不分组")}</p>
      <p>{t('本次使用 {valid} 行，排除 {excluded} 行；原始数据共 {total} 行。', { valid: result.check.valid_count, excluded: result.check.excluded_count, total: result.check.row_count })}</p>
      <div className="field-table-scroll" role="region" aria-label={t("统计结果，可横向滚动")} tabIndex={0}>
        <table className="field-table statistics-table"><caption>{t("描述统计结果")}</caption>
          <thead><tr>{[t("范围 / 分组"), t("样本数 n"), t("均值"), t("样本标准差"), t("最小值"), 'Q1', t("中位数"), 'Q3', t("最大值"), t("四分位距")].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>{rows.map((row, index) => <tr key={index}><th scope="row">{row.label}</th><td>{row.statistics.n}</td>
            {(['mean', 'std', 'min', 'q1', 'median', 'q3', 'max', 'iqr'] as const).map(metric =>
              <td key={metric} title={row.statistics[metric] === null ? t("无法计算，详见下方提示") : String(row.statistics[metric])}>{formatted(row.statistics[metric], locale)}</td>)}
          </tr>)}</tbody>
        </table>
      </div>
      {rows.some(row => row.statistics.warnings.length > 0) && <ul className="warning-panel">{rows.flatMap((row, index) => row.statistics.warnings.map(note =>
        <li key={`${index}:${note}`}><strong>{row.label}：</strong><span>{workflowNotice(note, t)}</span></li>))}</ul>}
      {result.check.warnings.length > 0 && <ul className="warning-panel">{result.check.warnings.map(note => <li key={note}>{workflowNotice(note, t)}</li>)}</ul>}
      <p className="muted">{t("样本标准差使用 n−1 分母；Q1、中位数、Q3 按位置 (n−1)p 线性插值；四分位距 = Q3 − Q1。 有效样本不足 2 条时标准差为“—”。数值溢出也显示“—”并提示。总体与分组使用相同的完整记录规则，未插补、未去重、未剔除离群值。")}</p>
      <p className="muted">{t("表格显示最多 6 位有效数字，悬停可查看保存值。此步仅描述数据分布，未进行显著性检验。")}</p>
      <details className="statistics-provenance"><summary>{t("计算来源与方法记录")}</summary>
        <p>{t("文件：")}{result.filename}{t("；结果编号：")}{result.id}</p><p>{t("原文件 SHA256：")}{result.source_sha256}</p>
        <p>{t("工具：")}{result.engine.id}；Python {result.engine.python_version}；openpyxl {result.engine.openpyxl_version}</p>
        <p>{t("开始时间：")}{result.started_at}{t("；完成时间：")}{result.completed_at}</p>
      </details>
      <BoxplotFigure base={base} runId={result.id} revision={result.setup_revision}
        canGenerate={fieldsMatch && revisionMatches && state.is_current} disabled={disabled || loading || running} onBusyChange={setPlotBusy} />
    </>}
  </section>
}
