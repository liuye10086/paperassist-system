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

function formatted(value: number | null) {
  if (value === null) return '—'
  return new Intl.NumberFormat('zh-CN', { maximumSignificantDigits: 6,
    notation: value !== 0 && (Math.abs(value) < 0.0001 || Math.abs(value) >= 1e9) ? 'scientific' : 'standard',
    useGrouping: false }).format(value)
}

async function request<T>(url: string, signal: AbortSignal, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, signal })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(typeof body?.detail?.message === 'string' ? body.detail.message : '统计请求失败，请重新读取结果后重试。')
  return body
}

function explain(cause: unknown, timedOut: boolean) {
  if (timedOut) return '等待统计请求超时。后端可能仍在处理，请先重新读取统计结果，再决定是否重试。'
  if (cause instanceof TypeError) return '无法连接后端，请确认服务正常并重新读取统计结果。'
  return cause instanceof Error ? cause.message : '统计请求失败，请重新读取结果后重试。'
}

export default function StatisticsResults({ base, savedRevision, fieldsMatch, disabled, onBusyChange }: {
  base: string; savedRevision: number | null; fieldsMatch: boolean; disabled: boolean; onBusyChange: (value: boolean) => void
}) {
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

  const rows = result ? [{ label: '总体（完整记录）', statistics: result.overall }, ...result.groups] : []
  return <section className="statistics-results" aria-labelledby="statistics-title" aria-busy={loading || running}>
    <div className="section-heading"><span className="step-label">第二步 · 统计计算</span>
      <h3 id="statistics-title">描述统计</h3>
      <p>按已保存的字段配置读取整张工作表，计算总体和各分组的统计量。</p>
    </div>
    {!savedRevision ? <p className="muted">请先检查字段并保存分析配置。</p>
      : !fieldsMatch && <p className="warning-panel">当前字段尚未保存，请先检查并保存，再执行统计。已有结果对应其标注的配置。</p>}
    {state && savedRevision && !revisionMatches && <p className="warning-panel">配置已在其他页面变化，请点击“重新载入分析配置”后再执行。</p>}
    <div className="analysis-actions">
      <button type="button" disabled={disabled || plotBusy || loading || running || !fieldsMatch || !revisionMatches} onClick={() => void execute()}>执行描述统计</button>
      <button type="button" disabled={disabled || plotBusy || loading || running || !savedRevision} onClick={() => {
        setNotice(''); setError(''); setLoading(true); setAttempt(value => value + 1)
      }}>重新读取统计结果</button>
    </div>
    {loading && <p role="status">正在读取统计结果……</p>}
    {running && <p role="status">正在计算描述统计，请稍候……</p>}
    {error && <p role="alert" className="error-panel">{error}</p>}
    {notice && <p role="status" className="saved-notice">{notice}</p>}
    {state && !result && <p>尚未执行当前配置的描述统计。</p>}
    {result && <>
      {!state.is_current && <p className="warning-panel">以下为旧配置的统计结果，当前配置尚未计算。执行后将显示新结果，旧结果仍保留。</p>}
      <p>配置版本：{result.setup_revision}；工作表：{result.selection.sheet_name}；完成时间：{new Date(result.completed_at).toLocaleString('zh-CN')}</p>
      <p>数值：{result.selection.numeric_column} · {result.numeric_name}；单位：{result.selection.unit || '未填写'}；
        分组：{result.selection.group_column ? `${result.selection.group_column} · ${result.group_name}` : '不分组'}</p>
      <p>本次使用 {result.check.valid_count} 行，排除 {result.check.excluded_count} 行；原始数据共 {result.check.row_count} 行。</p>
      <div className="field-table-scroll" role="region" aria-label="统计结果，可横向滚动" tabIndex={0}>
        <table className="field-table statistics-table"><caption>描述统计结果</caption>
          <thead><tr>{['范围 / 分组', '样本数 n', '均值', '样本标准差', '最小值', 'Q1', '中位数', 'Q3', '最大值', '四分位距'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>{rows.map((row, index) => <tr key={index}><th scope="row">{row.label}</th><td>{row.statistics.n}</td>
            {(['mean', 'std', 'min', 'q1', 'median', 'q3', 'max', 'iqr'] as const).map(metric =>
              <td key={metric} title={row.statistics[metric] === null ? '无法计算，详见下方提示' : String(row.statistics[metric])}>{formatted(row.statistics[metric])}</td>)}
          </tr>)}</tbody>
        </table>
      </div>
      {rows.some(row => row.statistics.warnings.length > 0) && <ul className="warning-panel">{rows.flatMap((row, index) => row.statistics.warnings.map(note =>
        <li key={`${index}:${note}`}><strong>{row.label}：</strong><span>{note}</span></li>))}</ul>}
      {result.check.warnings.length > 0 && <ul className="warning-panel">{result.check.warnings.map(note => <li key={note}>{note}</li>)}</ul>}
      <p className="muted">样本标准差使用 n−1 分母；Q1、中位数、Q3 按位置 (n−1)p 线性插值；四分位距 = Q3 − Q1。
        有效样本不足 2 条时标准差为“—”。数值溢出也显示“—”并提示。总体与分组使用相同的完整记录规则，未插补、未去重、未剔除离群值。</p>
      <p className="muted">表格显示最多 6 位有效数字，悬停可查看保存值。此步仅描述数据分布，未进行显著性检验。</p>
      <details className="statistics-provenance"><summary>计算来源与方法记录</summary>
        <p>文件：{result.filename}；结果编号：{result.id}</p><p>原文件 SHA256：{result.source_sha256}</p>
        <p>工具：{result.engine.id}；Python {result.engine.python_version}；openpyxl {result.engine.openpyxl_version}</p>
        <p>开始时间：{result.started_at}；完成时间：{result.completed_at}</p>
      </details>
      <BoxplotFigure base={base} runId={result.id} revision={result.setup_revision}
        canGenerate={fieldsMatch && revisionMatches && state.is_current} disabled={disabled || loading || running} onBusyChange={setPlotBusy} />
    </>}
  </section>
}
