import {isAnalysisSelection, sameSelection as sameAnalysisSelection, type AnalysisSelection} from './analysisSelection'
import { fileBase, isPreparedVersion, preparationRequest, type PreparedVersion, type PreparedPage } from '../datasetPreparation/preparationApi'
import SourceSummary from './SourceSummary'
import DatasetProfile from '../datasetProfile/DatasetProfile'
import { isDatasetSource, sameSource, type DatasetAnalysisSource } from './datasetSource'
import { datasetRequest, isStructurePage, isStructure, type DatasetSummary, type StructureVersion, type StructurePage } from '../datasets/datasetApi'
import { useI18n, apiError, safeError } from '../../shared/i18n'
import { workflowNotice } from '../../shared/i18n/workflowMessages'
import { apiFetch } from '../../shared/api/client'
import { useEffect, useRef, useState } from 'react'
import StatisticsResults from './StatisticsResults'
import AnalysisPlanLauncher from '../analysisPlan/AnalysisPlanLauncher'
import { WorkflowProvider, WorkflowStage, WorkflowNavigation, WorkflowEmptyResults } from './AnalysisWorkflow'
import { useWorkflowNavigation } from './analysisWorkflowContext'

type FileSummary = { id: string; filename: string; file_type: string; uploaded_at: string; parse_status: 'queued' | 'parsing' | 'parsed' | 'failed' }
type Column = {
  id: string; name: string; type: string; non_missing_count: number; missing_count: number
  unit?: { status: 'confirmed' | 'unconfirmed'; value: string | null }; numeric_count: number; can_be_numeric: boolean; can_be_group: boolean; issue_cells: string[]
}
type Profile = { sheet_name: string; row_count: number; columns: Column[]; warnings: string[] }
export type Selection = { task_type: 'descriptive_boxplot'; sheet_name: string; numeric_column: string
  group_column: string | null; unit: string; missing_policy: 'exclude_selected_missing' }
export type Check = { ready: boolean; row_count: number; valid_count: number; excluded_count: number
  groups: { label: string; count: number }[]; issues: string[]; warnings: string[] }
type Saved = { source?: DatasetAnalysisSource; file_id: string; source_sha256: string; status: 'configured'; revision: number
  analysis_plan?: { plan_id: string; sha256: string; resolutions: Record<string, string> }
  updated_at: string; selection: AnalysisSelection; check: Check }
const typeNames: Record<string, string> = { number: '数值', text: '文本', boolean: '布尔', datetime: '日期/时间',
  formula: '公式', error: 'Excel 错误', mixed: '混合类型', empty: '空列' }

function matchesStructureSource(source: DatasetAnalysisSource, structure: StructureVersion) {
  const input = structure.task.input_version
  return input.kind === 'excel_structure' && input.source_sha256 === source.source_sha256 && input.parser_version === source.parser_version
}


async function request<T>(url: string, signal: AbortSignal, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, { ...init, signal })
  const result = await response.json().catch(() => null)
  if (!response.ok) { const error = new Error(apiError(result, '分析配置请求失败，请检查字段选择后重试。')); Object.assign(error, { status: response.status }); throw error }
  return result
}

function errorMessage(cause: unknown, aborted: boolean) {
  return aborted ? '请求超时，请重新载入配置确认结果后重试。'
    : cause instanceof TypeError ? '无法连接后端，请确认服务正常后重试。'
      : safeError(cause, '读取分析配置失败，请重试。')
}

type AnalysisDataset = Pick<DatasetSummary, 'id' | 'file_id' | 'structure_id' | 'version' | 'sheet_index' | 'sheet_name'>
function SheetAnalysis({ base, projectId, fileId, sheetName, dataset, structure, expectedSource, saved, onSaved, onBusyChange, onMatchChange, onConflict, onPlanPublished, running }: {
  base: string; projectId: string; fileId: string; sheetName: string; dataset: AnalysisDataset; structure: StructureVersion | null; expectedSource?: DatasetAnalysisSource; running: boolean; onMatchChange: (match: boolean) => void; onConflict: (message: string) => void; onPlanPublished: (id: string, revision: number) => void; saved: Saved | null; onSaved: (value: Saved) => void; onBusyChange: (value: boolean) => void
}) {
  const { t } = useI18n()
  const previous = saved?.selection.task_type==='descriptive_boxplot' && saved?.selection.sheet_name === sheetName && isDatasetSource(expectedSource) && sameSource(saved.source, expectedSource) ? saved.selection : null
  const [planSelection,setPlanSelection]=useState<AnalysisSelection|null>(saved?.selection??null)
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
  const actionController = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timeout = window.setTimeout(() => controller.abort(), 120_000)
    request<Profile>(`${base}/analysis-profile?sheet=${encodeURIComponent(sheetName)}&dataset_id=${encodeURIComponent(dataset.id)}`, controller.signal)
      .then(result => { if (active && !controller.signal.aborted) { if (result.sheet_name !== sheetName) throw new Error('数据来源或版本不一致，请重新载入配置。'); setProfile(result) } })
      .catch(cause => { if (active) setLoadError(errorMessage(cause, controller.signal.aborted)) })
      .finally(() => { window.clearTimeout(timeout); if (active) setLoading(false) })
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [base, sheetName, dataset.id, attempt])
  useEffect(() => () => actionController.current?.abort(), [])
  useEffect(() => { onBusyChange(busy); return () => onBusyChange(false) }, [busy, onBusyChange])

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
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...selection, dataset_id: dataset.id, expected_revision: saved?.revision ?? 0 }) })
        if (!controller.signal.aborted) {
          if (!isDatasetSource(result.source) || result.source_sha256 !== result.source.source_sha256 || result.file_id !== dataset.file_id || result.source.dataset_id !== dataset.id || result.source.structure_id !== dataset.structure_id || result.source.file_id !== dataset.file_id || result.source.dataset_version !== dataset.version || result.source.sheet_index !== dataset.sheet_index || result.source.sheet_name !== sheetName || result.selection.sheet_name !== sheetName) throw new Error('数据来源或版本不一致，请重新载入配置。')
          if (result.revision !== (saved?.revision ?? 0) + 1 || !sameAnalysisSelection(result.selection, selection) || !(structure ? matchesStructureSource(result.source, structure) : sameSource(result.source, expectedSource))
            || saved?.source?.dataset_id === dataset.id && !sameSource(saved.source, result.source)) throw new Error('数据来源或版本不一致，请重新载入配置。')
          onSaved(result)
          setChecked(result.check)
          setNotice('已保存分析配置，可前往描述统计。')
        }
      } else {
        const result = await request<Check>(`${base}/analysis-check`, controller.signal, { method: 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...selection, dataset_id: dataset.id }) })
        if (!controller.signal.aborted) setChecked(result)
      }
    } catch (cause) {
      if (!controller.signal.aborted && cause && typeof cause === 'object' && 'status' in cause && cause.status === 409) { onConflict(errorMessage(cause, false)); return }
      if (!controller.signal.aborted || timedOut) setError(errorMessage(cause, timedOut))
    } finally {
      window.clearTimeout(timeout)
      if (actionController.current === controller) actionController.current = null
      if (!controller.signal.aborted || timedOut) setBusy(false)
    }
  }

  const fieldsMatch = saved&&saved.selection.task_type!=='descriptive_boxplot'?!!profile&&!loading&&!loadError&&!!expectedSource&&sameSource(saved.source,expectedSource)&&sameAnalysisSelection(saved.selection,planSelection):!!profile && !loading && !loadError && !!previous && saved?.source?.dataset_id === dataset.id && numeric === previous.numeric_column && (group || null) === previous.group_column && unit === previous.unit
  useEffect(() => { onMatchChange(fieldsMatch); return () => onMatchChange(false) }, [fieldsMatch, onMatchChange])
  if (loading) return <p role="status">{t("正在检查整张工作表……")}</p>
  if (loadError || !profile) return <div className="error-panel" role="alert">{t(loadError || '字段信息不可用。')}{' '}
    <button type="button" onClick={() => { setLoading(true); setLoadError(''); setAttempt(value => value + 1) }}>{t("重试字段检查")}</button>
  </div>
  const numericColumn = profile.columns.find(column => column.id === numeric)
  const structureSource = structure?.task.input_version.kind === 'excel_structure' ? structure.task.input_version : null
  return <div className="analysis-fields" aria-busy={busy}>
    <WorkflowStage stage="setup">
    <div className="analysis-config-layout"><div className="analysis-config-form">
    <div className="analysis-field-grid">
      <label>{t("数值列")}<select value={numeric} disabled={busy || running} onChange={event => {
        setNumeric(event.target.value); const metadata = profile.columns.find(c => c.id === event.target.value)?.unit; setUnit(metadata?.status === 'confirmed' ? metadata.value ?? '' : ''); if (group === event.target.value) setGroup(''); changed()
      }}>
        <option value="">{t("请选择数值列")}</option>
        {profile.columns.map(column => <option key={column.id} value={column.id} disabled={!column.can_be_numeric}>
          {column.id} · {column.name}（{typeNames[column.type] ? t(typeNames[column.type]) : column.type}）
        </option>)}
      </select></label>
      <label>{t("分组列（可选）")}<select value={group} disabled={busy || running} onChange={event => { setGroup(event.target.value); changed() }}>
        <option value="">{t("不分组")}</option>
        {profile.columns.filter(column => column.can_be_group && column.id !== numeric).map(column =>
          <option key={column.id} value={column.id}>{column.id} · {column.name}</option>)}
      </select></label>
      <label>{t("数值单位（可选）")}<input value={unit} maxLength={80} disabled={busy || running} onChange={event => { setUnit(event.target.value); changed() }} /></label>
    </div>
    <p className="muted">{t("数值列仅接受实际数值，文本数字、布尔、日期、公式、错误及混合类型需先在原文件中核对。分组最多 20 组。")}</p>
    <p className="missing-policy">{t("缺失值规则：后续计算只使用数值列及所选分组列均非缺失的行，原文件保持不变。")}</p>
    <div className="analysis-actions">
      <button type="button" disabled={busy || running || !numericColumn?.can_be_numeric || !profile.row_count} onClick={() => void perform(false)}>{t("检查字段")}</button>
      <button type="button" className="button-primary" disabled={busy || running || !checked?.ready} onClick={() => void perform(true)}>{t("保存分析配置")}</button>
    </div>
    {busy && <p role="status">{t("正在核对数据，请稍候……")}</p>}
    {error && <p className="error-panel" role="alert">{t(error)}</p>}
    {checked && <div className="selection-check" aria-live="polite">
      {checked.ready ? <p>{t('可用 {valid} 行，排除 {excluded} 行。', { valid: checked.valid_count, excluded: checked.excluded_count })}</p>
        : <ul className="error-panel">{checked.issues.map(issue => <li key={issue}>{workflowNotice(issue, t)}</li>)}</ul>}
      {checked.ready && checked.groups.length > 0 && <ul>{checked.groups.map(group => <li key={group.label}>{group.label}：{t('{count} 行', { count: group.count })}</li>)}</ul>}
      {checked.warnings.length > 0 && <ul className="warning-panel">{checked.warnings.map(note => <li key={note}>{workflowNotice(note, t)}</li>)}</ul>}
    </div>}
    {notice && <p className="saved-notice" role="status">{t(notice)}</p>}
    {expectedSource?.kind === 'prepared_dataset_version' && <AnalysisPlanLauncher projectId={projectId} fileId={fileId} source={expectedSource} selection={{ task_type: 'descriptive_boxplot', sheet_name: sheetName, numeric_column: numeric, group_column: group || null, unit, missing_policy: 'exclude_selected_missing' }} initialSelection={saved?.selection} fields={profile.columns.map(c=>({column:c.id,name:c.name,numeric:c.can_be_numeric,unit:c.unit?.status==='confirmed'?c.unit.value??'':''}))} onSelectionChange={value=>{setPlanSelection(value);if(value.task_type==='descriptive_boxplot'){setNumeric(value.numeric_column);setGroup(value.group_column??'');setUnit(value.unit);changed()}}} setupRevision={saved?.revision ?? 0} disabled={busy || running || !profile.row_count} onPublished={onPlanPublished} />}
    {saved?.analysis_plan && <p className="saved-notice">{t('当前配置已关联已确认分析计划。')}</p>}
    </div><aside className="analysis-data-overview" aria-label={t("数据概况")}>
    <p className="data-count">{t('整表检查：{count} 行数据', { count: profile.row_count })}</p>
    <p className="muted">{t(expectedSource?.kind === 'prepared_dataset_version' ? '使用已确认的数据区域。单位是可编辑的分析标签，不会转换数值。' : "使用完整工作表。空单元格、空字符串和纯空白字符串视为缺失；NA 等文本保持原义。")}</p>
    {profile.row_count === 0 && <p className="warning-panel">{t("当前工作表没有数据行，请选择其他工作表。")}</p>}
    {profile.warnings.length > 0 && <ul className="warning-panel">{profile.warnings.map(note => <li key={note}>{workflowNotice(note, t)}</li>)}</ul>}
    {profile.columns.length > 0 && <div className="field-table-scroll" tabIndex={0} role="region" aria-label={t("字段概况，可横向滚动")}>
      <table className="field-table"><caption>{t("字段概况（Excel 列字母用于区分同名字段）")}</caption>
        <thead><tr><th scope="col">{t("列")}</th><th scope="col">{t("字段名称")}</th><th scope="col">{t("类型")}</th><th scope="col">{t("非缺失")}</th><th scope="col">{t("缺失")}</th><th scope="col">{t("实际数值")}</th></tr></thead>
        <tbody>{profile.columns.map(column => <tr key={column.id}>
          <th scope="row">{column.id}</th><td>{column.name}</td><td>{typeNames[column.type] ? t(typeNames[column.type]) : column.type}</td>
          <td>{column.non_missing_count}</td><td>{column.missing_count}</td><td>{column.numeric_count}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    {(expectedSource || structureSource) && <DatasetProfile base={base} projectId={projectId} binding={{
      kind: expectedSource?.kind ?? 'dataset_version', dataset_id: dataset.id, structure_id: dataset.structure_id,
      dataset_version: dataset.version, file_id: dataset.file_id, sheet_index: dataset.sheet_index, sheet_name: sheetName,
      source_sha256: expectedSource?.source_sha256 ?? String(structureSource?.source_sha256),
      parser_version: expectedSource?.parser_version ?? String(structureSource?.parser_version), source: expectedSource,
    }} />}
    </aside></div>
    </WorkflowStage>
  </div>
}

function FileAnalysis({ projectId, fileId, filename }: { projectId: string; fileId: string; filename: string }) {
  const { t } = useI18n()
  const base = `/api/v1/projects/${projectId}/files/${fileId}`
  const [saved, setSaved] = useState<Saved | null>(null)
  const [ready, setReady] = useState(false)
  const [list, setList] = useState<StructurePage | null>(null)
  const [selected, setSelected] = useState<StructureVersion | null>(null)
  const [datasetId, setDatasetId] = useState('')
  const [page, setPage] = useState(1)
  const [refresh, setRefresh] = useState(0)
  const [attempt, setAttempt] = useState(0)
  const [error, setError] = useState('')
  const [listError, setListError] = useState('')
  const [busy, setBusy] = useState(false)
  const [running, setRunning] = useState(false)
  const [fieldsMatch, setFieldsMatch] = useState(false)
  const [sourceKind, setSourceKind] = useState<'raw' | 'prepared'>('raw')
  const [preparedList, setPreparedList] = useState<PreparedPage | null>(null)
  const [prepared, setPrepared] = useState<PreparedVersion | null>(null)
  const [preparedError, setPreparedError] = useState('')
  const refreshedPlans = useRef(new Set<string>())
  const dataset: AnalysisDataset | undefined = sourceKind === 'prepared' ? prepared ? { id: prepared.id, file_id: prepared.file_id, structure_id: prepared.source.structure_id, version: prepared.version, sheet_index: prepared.source.sheet_index, sheet_name: prepared.source.sheet_name } : undefined : selected?.datasets.find(d => d.id === datasetId)
  useEffect(() => {
    const controller = new AbortController(); let active = true
    const timeout = window.setTimeout(() => controller.abort(), 30_000)
    request<Saved | null>(`${base}/analysis-setup`, controller.signal).then(async value => {
      if (value && (!isAnalysisSelection(value.selection) || value.file_id !== fileId || Object.hasOwn(value, 'source') && (!isDatasetSource(value.source) || value.source_sha256 !== value.source.source_sha256 || value.source.file_id !== fileId || value.source.sheet_name !== value.selection.sheet_name))) throw new Error('数据来源或版本不一致，请重新载入配置。')
      let bound: StructureVersion | null = null
      let boundPrepared: PreparedVersion | null = null
      if (value?.source) {
        const source = value.source
        if (source.kind === 'prepared_dataset_version') {
          boundPrepared = await preparationRequest(`${base}/prepared-dataset-versions/${encodeURIComponent(source.dataset_id)}`, controller, (v): v is PreparedVersion => isPreparedVersion(v, fileId) && sameSource(v.source, source), '数据来源或版本不一致，请重新载入配置。')
        } else bound = await datasetRequest(`${base}/structure-versions/${encodeURIComponent(source.structure_id)}`, controller,
          (v): v is StructureVersion => isStructure(v, projectId, fileId) && v.id === source.structure_id && v.task.status === 'succeeded' && matchesStructureSource(source, v) && v.datasets.some(d => d.id === source.dataset_id && d.version === source.dataset_version && d.sheet_name === source.sheet_name && d.sheet_index === source.sheet_index), () => {})
      }
      if (!active || controller.signal.aborted) return
      setSaved(value); setSelected(bound); setPrepared(boundPrepared); setSourceKind(boundPrepared ? 'prepared' : 'raw'); setDatasetId(value?.source?.dataset_id ?? ''); setReady(true)
    }).catch(cause => { if (active) setError(errorMessage(cause, controller.signal.aborted)) })
      .finally(() => window.clearTimeout(timeout))
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [base, projectId, fileId, attempt])
  useEffect(() => {
    const controller = new AbortController(); let active = true
    datasetRequest(`${base}/structure-versions?page=${page}&page_size=5`, controller,
      (v): v is StructurePage => isStructurePage(v, projectId, fileId, page), () => {}).then(value => {
        if (active && !controller.signal.aborted) { setList(value); setListError('') }
      }).catch(cause => { if (active && !controller.signal.aborted) setListError(errorMessage(cause, false)) })
    return () => { active = false; controller.abort() }
  }, [base, page, projectId, fileId, refresh])
  useEffect(() => {
    if (sourceKind !== 'prepared') return
    const controller = new AbortController(); let active = true
    preparationRequest(`${fileBase(projectId, fileId)}/prepared-dataset-versions?page=${page}&page_size=5`, controller,
      (v): v is PreparedPage => !!v && typeof v === 'object' && 'items' in v && Array.isArray(v.items) && v.items.every(x => isPreparedVersion(x, fileId)) && 'page' in v && v.page === page && 'page_size' in v && v.page_size === 5, '整理版本读取失败，请重试。').then(value => {
        if (active && !controller.signal.aborted) { setPreparedList(value); setPreparedError('') }
      }).catch(cause => { if (active) setPreparedError(safeError(cause, '整理版本读取失败，请重试。')) })
    return () => { active = false; controller.abort() }
  }, [sourceKind, projectId, fileId, page, refresh])
  function reload() { setReady(false); setError(''); setFieldsMatch(false); setAttempt(n => n + 1) }
  const options = list?.items.filter(v => v.task.status === 'succeeded' && v.datasets.length > 0) ?? []
  if (selected && !options.some(v => v.id === selected.id)) options.push(selected)
  const preparedOptions = [...(preparedList?.items ?? [])]
  if (prepared && !preparedOptions.some(v => v.id === prepared.id)) preparedOptions.push(prepared)
  return <>
    <WorkflowStage stage="setup">
      <div className="analysis-actions"><button type="button" disabled={busy || running} onClick={reload}>{t('重新载入分析配置')}</button>
        <button type="button" disabled={busy || running} onClick={() => setRefresh(n => n + 1)}>{t('刷新数据版本')}</button></div>
      {error && <p className="error-panel" role="alert">{t(error)}</p>}
      {listError && <p className="error-panel" role="alert">{t(listError)}</p>}{preparedError && <p role="alert" className="error-panel">{t(preparedError)}</p>}
      {!ready && !error && <p role="status">{t('正在载入工作表和已保存配置……')}</p>}
      {ready && <>
        {saved && <><SourceSummary source={saved.source} filename={filename} />{!saved.source && saved.selection.task_type==='descriptive_boxplot' && <p>{t('历史字段配置：工作表 {sheet}；数值列 {numeric}；分组列 {group}；单位 {unit}。', { sheet: saved.selection.sheet_name, numeric: saved.selection.numeric_column, group: saved.selection.group_column ?? t('不分组'), unit: saved.selection.unit || t('未填写') })}</p>}</>}
        <div className="analysis-field-grid"><label>{t('数据来源类型')}<select value={sourceKind} disabled={busy || running} onChange={e => { setFieldsMatch(false); setSourceKind(e.target.value as 'raw' | 'prepared'); setPage(1) }}><option value="raw">{t('原始数据')}</option><option value="prepared">{t('整理数据')}</option></select></label></div>
        {sourceKind === 'prepared' ? <div className="analysis-field-grid"><label>{t('整理数据版本')}<select value={prepared?.id ?? ''} disabled={busy || running} onChange={e => { setFieldsMatch(false); setPrepared(preparedOptions.find(v => v.id === e.target.value) ?? null) }}><option value="">{t('请选择整理版本')}</option>{preparedOptions.map(v => <option key={v.id} value={v.id}>{t('原始数据 v{raw} · 整理数据 v{prepared}', { raw: v.parent_dataset_version, prepared: v.version })} · {v.source.sheet_name}</option>)}</select></label></div> : <div className="analysis-field-grid"><label>{t('原始数据版本')}<select value={selected?.id ?? ''} disabled={busy || running} onChange={event => {
          const value = options.find(v => v.id === event.target.value) ?? null
          setFieldsMatch(false); setSelected(value); setDatasetId('')
        }}><option value="">{t('请选择成功的数据版本')}</option>{options.map(v => <option key={v.id} value={v.id}>{t('原始数据版本 v{version}', { version: v.version })}</option>)}</select></label>
        <label>{t('分析工作表')}<select value={datasetId} disabled={!selected || busy || running} onChange={event => { setFieldsMatch(false); setDatasetId(event.target.value) }}>
          <option value="">{t(selected ? '请选择工作表' : '请先选择数据版本')}</option>{selected?.datasets.map(d => <option key={d.id} value={d.id}>{d.sheet_name}</option>)}</select></label></div>}
        <p className="muted">{t(sourceKind === 'prepared' ? '使用已确认的数据区域。单位是可编辑的分析标签，不会转换数值。' : '第一行用作字段名；从第 2 行至最后含值行分析完整数据，保留中间空行，不自动清洗。')}</p>
        {!dataset && <p className="warning-panel">{t(sourceKind === 'prepared' ? '新分析需明确选择整理数据版本，检查并保存配置。' : '新分析需明确选择原始数据版本，检查并保存配置。')}</p>}
      </>}
      <div className="analysis-actions"><button type="button" disabled={page <= 1 || busy || running} onClick={() => { setList(null); setPage(n => n - 1) }}>{t('上一页数据版本')}</button>
        <span>{t('第 {page} 页', { page })}</span><button type="button" disabled={sourceKind === 'prepared' ? !preparedList || page * 5 >= preparedList.total || busy || running : !list || page * 5 >= list.total || busy || running} onClick={() => { setList(null); setPage(n => n + 1) }}>{t('下一页数据版本')}</button></div>
    </WorkflowStage>
    {ready && dataset && (selected || prepared) && <SheetAnalysis key={dataset.id} base={base} projectId={projectId} fileId={fileId} sheetName={dataset.sheet_name} dataset={dataset} structure={sourceKind === 'raw' ? selected : null} expectedSource={sourceKind === 'prepared' ? prepared?.source : saved?.source?.kind === 'dataset_version' && saved.source.dataset_id === dataset.id ? saved.source : undefined} saved={saved}
      running={running} onSaved={setSaved} onBusyChange={setBusy} onMatchChange={setFieldsMatch} onConflict={message => { reload(); setError(message) }} onPlanPublished={(id, revision) => {
        if ((saved?.revision ?? 0) >= revision || refreshedPlans.current.has(id)) return
        refreshedPlans.current.add(id); reload()
      }} />}
    {ready && <StatisticsResults key={`${base}:${saved?.revision ?? 0}`} base={base} savedRevision={saved?.revision ?? null} savedSelection={saved?.selection} savedSource={saved?.source} savedPlan={saved?.analysis_plan}
      fieldsMatch={fieldsMatch && !!saved?.source} disabled={busy} onBusyChange={setRunning} />}
  </>
}

function AnalysisSetupContent({ projectId, files, onOpenFiles, filesLoading = false, filesError = '', onReloadFiles }: {
  projectId: string; files: FileSummary[]; onOpenFiles?: () => void
  filesLoading?: boolean; filesError?: string; onReloadFiles?: () => void
}) {
  const { t, locale } = useI18n()
  const navigation = useWorkflowNavigation()
  const [selectedId, setSelectedId] = useState('')
  const available = files.filter(file => file.file_type === 'xlsx' && file.parse_status === 'parsed')
  const selected = available.find(file => file.id === selectedId)
  return <section className="analysis-setup" aria-label={t('数据分析')}>
    <WorkflowNavigation onOpenFiles={onOpenFiles} />
    {(filesLoading || filesError) && <div className="analysis-file-status">
      {filesLoading ? <p role="status">{t('正在读取文件列表……')}</p> : <p role="alert" className="error-panel">{t(filesError)}</p>}
      {onReloadFiles && <button type="button" disabled={filesLoading} onClick={onReloadFiles}>{t('刷新文件列表')}</button>}
    </div>}
    <WorkflowStage stage="setup">
    <div className="section-heading">
      <h2 id="analysis-title">{t("字段配置")}</h2>
      <p>{t("保存字段选择和数据检查结果，后续步骤将据此计算、绘图和生成报告。")}</p>
      <p className="muted">{t("每个文件保存一份当前配置；保存新选择会更新该文件的配置。")}</p>
    </div>
    <div className="analysis-field-grid">
      <p>{t("描述统计、相关分析或组间比较：在所选整理版本的分析计划中选择方法与图型。")}</p>
      <label>{t("用于分析的文件")}<select value={selected?.id ?? ''} onChange={event => setSelectedId(event.target.value)}>
        <option value="">{t("请选择已保存文件")}</option>
        {available.map(file => <option key={file.id} value={file.id}>{file.filename} · {new Date(file.uploaded_at).toLocaleString(locale)}</option>)}
      </select></label>
    </div>
    {!filesLoading && !filesError && !available.length && <p className="muted">{t("请先在当前项目上传一份可预览的 Excel。")}</p>}
    </WorkflowStage>
    {!selected && !filesLoading && !filesError && navigation && <><WorkflowStage stage="statistics"><p className="workflow-empty">{t("请先选择文件并保存字段配置。")}</p></WorkflowStage><WorkflowEmptyResults message="请先选择文件并完成描述统计。" /></>}
    {selected && <FileAnalysis key={`${projectId}:${selected.id}`} projectId={projectId} fileId={selected.id} filename={selected.filename} />}
  </section>
}

export default function AnalysisSetup(props: Parameters<typeof AnalysisSetupContent>[0]) {
  return <WorkflowProvider><AnalysisSetupContent {...props} /></WorkflowProvider>
}
