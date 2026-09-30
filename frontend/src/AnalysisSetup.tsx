import { apiFetch } from './api'
import { useEffect, useRef, useState } from 'react'
import StatisticsResults from './StatisticsResults'

type FileSummary = { id: string; filename: string; uploaded_at: string; parse_status: 'parsed' | 'failed' }
type Column = {
  id: string; name: string; type: string; non_missing_count: number; missing_count: number
  numeric_count: number; can_be_numeric: boolean; can_be_group: boolean; issue_cells: string[]
}
type Profile = { sheet_name: string; row_count: number; columns: Column[]; warnings: string[] }
export type Selection = { task_type: 'descriptive_boxplot'; sheet_name: string; numeric_column: string
  group_column: string | null; unit: string; missing_policy: 'exclude_selected_missing' }
export type Check = { ready: boolean; row_count: number; valid_count: number; excluded_count: number
  groups: { label: string; count: number }[]; issues: string[]; warnings: string[] }
type Saved = { file_id: string; source_sha256: string; status: 'configured'; revision: number
  updated_at: string; selection: Selection; check: Check }
const typeNames: Record<string, string> = { number: '数值', text: '文本', boolean: '布尔', datetime: '日期/时间',
  formula: '公式', error: 'Excel 错误', mixed: '混合类型', empty: '空列' }

async function request<T>(url: string, signal: AbortSignal, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, { ...init, signal })
  const result = await response.json().catch(() => null)
  if (!response.ok) throw new Error(typeof result?.detail?.message === 'string'
    ? result.detail.message : '分析配置请求失败，请检查字段选择后重试。')
  return result
}

function errorMessage(cause: unknown, aborted: boolean) {
  return aborted ? '请求超时，请重新载入配置确认结果后重试。'
    : cause instanceof TypeError ? '无法连接后端，请确认服务正常后重试。'
      : cause instanceof Error ? cause.message : '读取分析配置失败，请重试。'
}

function SheetAnalysis({ base, sheetName, saved, onSaved, onBusyChange }: {
  base: string; sheetName: string; saved: Saved | null; onSaved: (value: Saved) => void; onBusyChange: (value: boolean) => void
}) {
  const previous = saved?.selection.sheet_name === sheetName ? saved.selection : null
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState(previous ? '已载入上次保存的配置；检查字段后可以重新保存。' : '')
  const [numeric, setNumeric] = useState(previous?.numeric_column ?? '')
  const [group, setGroup] = useState(previous?.group_column ?? '')
  const [unit, setUnit] = useState(previous?.unit ?? '')
  const [checked, setChecked] = useState<Check | null>(null)
  const [busy, setBusy] = useState(false)
  const [running, setRunning] = useState(false)
  const actionController = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timeout = window.setTimeout(() => controller.abort(), 120_000)
    request<Profile>(`${base}/analysis-profile?sheet=${encodeURIComponent(sheetName)}`, controller.signal)
      .then(result => { if (active && !controller.signal.aborted) setProfile(result) })
      .catch(cause => { if (active) setLoadError(errorMessage(cause, controller.signal.aborted)) })
      .finally(() => { window.clearTimeout(timeout); if (active) setLoading(false) })
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [base, sheetName, attempt])
  useEffect(() => () => actionController.current?.abort(), [])
  useEffect(() => { onBusyChange(busy || running) }, [busy, running, onBusyChange])

  function changed() { setChecked(null); setNotice(''); setError('') }

  async function perform(save: boolean) {
    if (actionController.current || running || !numeric) return
    const controller = new AbortController()
    actionController.current = controller
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort() }, 120_000)
    const selection: Selection = { task_type: 'descriptive_boxplot', sheet_name: sheetName,
      numeric_column: numeric, group_column: group || null, unit, missing_policy: 'exclude_selected_missing' }
    setBusy(true)
    setError('')
    setNotice('')
    setChecked(null)
    try {
      if (save) {
        const result = await request<Saved>(`${base}/analysis-setup`, controller.signal, { method: 'PUT',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...selection, expected_revision: saved?.revision ?? 0 }) })
        if (!controller.signal.aborted) {
          onSaved(result)
          setChecked(result.check)
          setNotice('已保存分析配置，刷新或重启后可再次载入。可在下方执行描述统计。')
        }
      } else {
        const result = await request<Check>(`${base}/analysis-check`, controller.signal, { method: 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(selection) })
        if (!controller.signal.aborted) setChecked(result)
      }
    } catch (cause) {
      if (!controller.signal.aborted || timedOut) setError(errorMessage(cause, timedOut))
    } finally {
      window.clearTimeout(timeout)
      if (actionController.current === controller) actionController.current = null
      if (!controller.signal.aborted || timedOut) setBusy(false)
    }
  }

  if (loading) return <p role="status">正在检查整张工作表……</p>
  if (loadError || !profile) return <div className="error-panel" role="alert">{loadError || '字段信息不可用。'}{' '}
    <button type="button" onClick={() => { setLoading(true); setLoadError(''); setAttempt(value => value + 1) }}>重试字段检查</button>
  </div>
  const numericColumn = profile.columns.find(column => column.id === numeric)
  const fieldsMatch = !!previous && numeric === previous.numeric_column && (group || null) === previous.group_column && unit === previous.unit
  return <div className="analysis-fields" aria-busy={busy}>
    <p className="data-count">整表检查：{profile.row_count} 行数据</p>
    <p className="muted">使用完整工作表。空单元格、空字符串和纯空白字符串视为缺失；NA 等文本保持原义。</p>
    {profile.row_count === 0 && <p className="warning-panel">当前工作表没有数据行，请选择其他工作表。</p>}
    {profile.warnings.length > 0 && <ul className="warning-panel">{profile.warnings.map(note => <li key={note}>{note}</li>)}</ul>}
    {profile.columns.length > 0 && <div className="field-table-scroll" tabIndex={0} role="region" aria-label="字段概况，可横向滚动">
      <table className="field-table"><caption>字段概况（Excel 列字母用于区分同名字段）</caption>
        <thead><tr><th scope="col">列</th><th scope="col">字段名称</th><th scope="col">类型</th><th scope="col">非缺失</th><th scope="col">缺失</th><th scope="col">实际数值</th></tr></thead>
        <tbody>{profile.columns.map(column => <tr key={column.id}>
          <th scope="row">{column.id}</th><td>{column.name}</td><td>{typeNames[column.type] ?? column.type}</td>
          <td>{column.non_missing_count}</td><td>{column.missing_count}</td><td>{column.numeric_count}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    <div className="analysis-field-grid">
      <label>数值列<select value={numeric} disabled={busy || running} onChange={event => {
        setNumeric(event.target.value); if (group === event.target.value) setGroup(''); changed()
      }}>
        <option value="">请选择数值列</option>
        {profile.columns.map(column => <option key={column.id} value={column.id} disabled={!column.can_be_numeric}>
          {column.id} · {column.name}（{typeNames[column.type]}）
        </option>)}
      </select></label>
      <label>分组列（可选）<select value={group} disabled={busy || running} onChange={event => { setGroup(event.target.value); changed() }}>
        <option value="">不分组</option>
        {profile.columns.filter(column => column.can_be_group && column.id !== numeric).map(column =>
          <option key={column.id} value={column.id}>{column.id} · {column.name}</option>)}
      </select></label>
      <label>数值单位（可选）<input value={unit} maxLength={80} disabled={busy || running} onChange={event => { setUnit(event.target.value); changed() }} /></label>
    </div>
    <p className="muted">数值列仅接受实际数值，文本数字、布尔、日期、公式、错误及混合类型需先在原文件中核对。分组最多 20 组。</p>
    <p className="missing-policy">缺失值规则：后续计算只使用数值列及所选分组列均非缺失的行，原文件保持不变。</p>
    <div className="analysis-actions">
      <button type="button" disabled={busy || running || !numericColumn?.can_be_numeric || !profile.row_count} onClick={() => void perform(false)}>检查字段</button>
      <button type="button" disabled={busy || running || !checked?.ready} onClick={() => void perform(true)}>保存分析配置</button>
    </div>
    {busy && <p role="status">正在核对数据，请稍候……</p>}
    {error && <p className="error-panel" role="alert">{error}</p>}
    {checked && <div className="selection-check" aria-live="polite">
      {checked.ready ? <p>可用 {checked.valid_count} 行，排除 {checked.excluded_count} 行。</p>
        : <ul className="error-panel">{checked.issues.map(issue => <li key={issue}>{issue}</li>)}</ul>}
      {checked.ready && checked.groups.length > 0 && <ul>{checked.groups.map(group => <li key={group.label}>{group.label}：{group.count} 行</li>)}</ul>}
      {checked.warnings.length > 0 && <ul className="warning-panel">{checked.warnings.map(note => <li key={note}>{note}</li>)}</ul>}
    </div>}
    {notice && <p className="saved-notice" role="status">{notice}</p>}
    <StatisticsResults key={`${base}:${saved?.revision ?? 0}`} base={base} savedRevision={saved?.revision ?? null}
      fieldsMatch={fieldsMatch} disabled={busy} onBusyChange={setRunning} />
  </div>
}

function FileAnalysis({ projectId, fileId }: { projectId: string; fileId: string }) {
  const base = `/api/v1/projects/${projectId}/files/${fileId}`
  const [data, setData] = useState<{ sheets: string[]; saved: Saved | null } | null>(null)
  const [sheetName, setSheetName] = useState('')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timeout = window.setTimeout(() => controller.abort(), 30_000)
    Promise.all([
      request<{ sheets: { name: string }[] }>(`${base}/preview`, controller.signal),
      request<Saved | null>(`${base}/analysis-setup`, controller.signal),
    ]).then(([preview, saved]) => {
      if (active && !controller.signal.aborted) {
        const sheets = preview.sheets.map(sheet => sheet.name)
        setData({ sheets, saved })
        setSheetName(saved && sheets.includes(saved.selection.sheet_name) ? saved.selection.sheet_name : sheets[0] ?? '')
      }
    }).catch(cause => { if (active) setError(errorMessage(cause, controller.signal.aborted)) })
      .finally(() => window.clearTimeout(timeout))
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [base, attempt])

  return <>
    <div className="analysis-actions"><button type="button" disabled={busy} onClick={() => {
      setData(null); setError(''); setAttempt(value => value + 1)
    }}>重新载入分析配置</button></div>
    {error && <p className="error-panel" role="alert">{error}</p>}
    {!data && !error && <p role="status">正在载入工作表和已保存配置……</p>}
    {data && <>
      <label className="analysis-sheet-label">分析工作表<select value={sheetName} disabled={busy} onChange={event => setSheetName(event.target.value)}>
        {data.sheets.map(name => <option key={name} value={name}>{name}</option>)}
      </select></label>
      {sheetName && <SheetAnalysis key={sheetName} base={base} sheetName={sheetName} saved={data.saved}
        onSaved={saved => setData(previous => previous ? { ...previous, saved } : previous)} onBusyChange={setBusy} />}
    </>}
  </>
}

export default function AnalysisSetup({ projectId, files }: { projectId: string; files: FileSummary[] }) {
  const [selectedId, setSelectedId] = useState('')
  const available = files.filter(file => file.parse_status === 'parsed')
  const selected = available.find(file => file.id === selectedId)
  return <section className="analysis-setup" aria-labelledby="analysis-title">
    <div className="section-heading"><span className="step-label">第一步 · 分析准备</span>
      <h2 id="analysis-title">选择分析任务与字段</h2>
      <p>保存字段选择和数据检查结果，后续步骤将据此计算、绘图和生成报告。</p>
      <p className="muted">每个文件保存一份当前配置；保存新选择会更新该文件的配置。</p>
    </div>
    <div className="analysis-field-grid">
      <label>分析任务<select value="descriptive_boxplot" onChange={() => {}}><option value="descriptive_boxplot">描述统计＋箱线图</option></select></label>
      <label>用于分析的文件<select value={selected?.id ?? ''} onChange={event => setSelectedId(event.target.value)}>
        <option value="">请选择已保存文件</option>
        {available.map(file => <option key={file.id} value={file.id}>{file.filename} · {new Date(file.uploaded_at).toLocaleString('zh-CN')} · {file.id.slice(0, 8)}</option>)}
      </select></label>
    </div>
    {!available.length && <p className="muted">请先在当前项目上传一份可预览的 Excel。</p>}
    {selected && <FileAnalysis key={`${projectId}:${selected.id}`} projectId={projectId} fileId={selected.id} />}
  </section>
}
