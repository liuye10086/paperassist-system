import { useI18n, apiError, safeError } from './i18n'
import { workflowNotice } from './i18n/workflowMessages'
import { apiFetch } from './api'
import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'

type CellValue = string | number | boolean | null
type SheetPreview = {
  name: string
  columns: string[]
  row_count: number
  column_count: number
  preview_rows: CellValue[][]
  warnings: string[]
}
type WorkbookPreview = { filename: string; sheets: SheetPreview[] }
type PreviewConfig = { max_upload_bytes: number; preview_row_limit: number }

function fileSize(bytes: number, t: (source: string, params?: Record<string, string | number>) => string) {
  return bytes >= 1024 * 1024
    ? `${Number((bytes / (1024 * 1024)).toFixed(2))} MiB`
    : t('{count} 字节', { count: bytes })
}

type PreviewProps = {
  projectId?: string
  savedFile?: { id: string; request: number } | null
  onSaved?: () => void
  onBusyChange?: (busy: boolean) => void
}

export default function ExcelPreview({ projectId, savedFile, onSaved, onBusyChange }: PreviewProps) {
  const { t } = useI18n()
  const [config, setConfig] = useState<PreviewConfig | null>(null)
  const [configError, setConfigError] = useState('')
  const [configAttempt, setConfigAttempt] = useState(0)
  const [file, setFile] = useState<File | null>(null)
  const [workbook, setWorkbook] = useState<WorkbookPreview | null>(null)
  const [sheetIndex, setSheetIndex] = useState(0)
  const [error, setError] = useState('')
  const [savedFailure, setSavedFailure] = useState(false)
  const [busy, setBusy] = useState(Boolean(savedFile))
  const [notice, setNotice] = useState('')
  const [requestedFile, setRequestedFile] = useState(savedFile)
  const uploadController = useRef<AbortController | null>(null)
  const sheet = workbook?.sheets[sheetIndex]

  // Clear the previous result before rendering a newly selected remote file.
  if (savedFile !== requestedFile) {
    setRequestedFile(savedFile)
    if (savedFile) {
      setBusy(true)
      setWorkbook(null)
      setError('')
      setSavedFailure(false)
      setNotice('')
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 15_000)
    let active = true
    async function loadConfig() {
      setConfigError('')
      try {
        const response = await apiFetch('/api/v1/excel/config', { signal: controller.signal })
        if (!response.ok) throw new Error('config')
        const data: PreviewConfig = await response.json()
        if (!Number.isSafeInteger(data.max_upload_bytes) || data.max_upload_bytes <= 0) throw new Error('config')
        if (active) setConfig(data)
      } catch {
        if (active) setConfigError('无法读取上传限制，请确认后端正在运行后重试。')
      } finally {
        window.clearTimeout(timeout)
      }
    }
    void loadConfig()
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [configAttempt])

  useEffect(() => () => uploadController.current?.abort(), [])
  useEffect(() => { onBusyChange?.(busy) }, [busy, onBusyChange])

  useEffect(() => {
    if (!projectId || !savedFile) return
    const controller = new AbortController()
    let active = true
    uploadController.current = controller
    const timeout = window.setTimeout(() => controller.abort(), 15_000)
    async function loadSaved() {
      try {
        const response = await apiFetch(`/api/v1/projects/${projectId}/files/${savedFile!.id}/preview`, { signal: controller.signal })
        const result = await response.json().catch(() => null)
        if (!response.ok) throw new Error(apiError(result, '读取已保存文件失败，请刷新后重试。'))
        if (active && !controller.signal.aborted) { setWorkbook(result); setSheetIndex(0) }
      } catch (cause) {
        if (active) setError(cause instanceof TypeError ? '无法连接后端，请确认服务正常后重试。'
          : controller.signal.aborted ? '读取预览超时，请重试。' : safeError(cause, '读取预览失败。'))
      } finally {
        window.clearTimeout(timeout)
        if (uploadController.current === controller) uploadController.current = null
        if (active) setBusy(false)
      }
    }
    void loadSaved()
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [projectId, savedFile])

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null
    setWorkbook(null)
    setSheetIndex(0)
    setError('')
    setSavedFailure(false)
    setNotice('')
    setFile(null)
    if (!selected) return
    if (!selected.name.toLowerCase().endsWith('.xlsx')) {
      setError('仅支持 .xlsx 文件，请将文件另存为 .xlsx 后上传。')
    } else if (selected.size === 0) {
      setError('所选文件为空，请选择有效的 .xlsx 工作簿。')
    } else if (config && selected.size > config.max_upload_bytes) {
      setError('文件超过 {limit} 的上传限制。')
    } else {
      setFile(selected)
    }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || !config || uploadController.current) return
    const controller = new AbortController()
    uploadController.current = controller
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort() }, 120_000)
    setBusy(true)
    setError('')
    setSavedFailure(false)
    setNotice('')
    setWorkbook(null)
    const body = new FormData()
    body.append('file', file)
    try {
      const response = await apiFetch(projectId ? `/api/v1/projects/${projectId}/files` : '/api/v1/excel/preview', {
        method: 'POST', body, signal: controller.signal,
      })
      const result = await response.json().catch(() => null)
      if (!response.ok) {
        const message = apiError(result, response.status === 413 ? '文件超过上传限制，请缩小文件后重试。'
            : '上传或解析失败，请检查文件和后端服务后重试。')
        throw new Error(message)
      }
      if (controller.signal.aborted) return
      if (projectId) {
        onSaved?.()
        if (result?.file?.parse_status === 'failed') {
          setSavedFailure(true)
          setError(apiError(result.file.error, '请检查文件后重新上传。'))
          return
        }
        setNotice('文件已保存到当前项目，可从项目文件列表再次打开。')
      }
      const preview = projectId ? result?.preview : result
      if (!Array.isArray(preview?.sheets) || preview.sheets.length === 0) {
        throw new Error('后端返回的工作表信息不完整，请重试。')
      }
      if (!controller.signal.aborted) {
        setWorkbook(preview)
        setSheetIndex(0)
      }
    } catch (cause) {
      if (timedOut) {
        setError(projectId ? '上传或解析超时，请先刷新文件列表确认是否已保存，再决定是否重新上传。' : '上传或解析超时，请缩小文件或稍后重试。')
      } else if (!controller.signal.aborted) {
        setError(cause instanceof TypeError ? '无法连接后端，请确认服务和网络正常后重试。'
          : safeError(cause, '上传失败，请重试。'))
      }
    } finally {
      window.clearTimeout(timeout)
      uploadController.current = null
      if (!controller.signal.aborted || timedOut) setBusy(false)
    }
  }

  return (
    <section className="excel-preview" aria-labelledby="excel-title">
      <div className="section-heading">
        <span className="step-label">{t("数据准备")}</span>
        <h2 id="excel-title">{t("Excel 上传与预览")}</h2>
        <p>{t("上传研究数据，检查工作表、字段与原始记录。")}</p>
      </div>
      <form onSubmit={upload} className="upload-panel" aria-busy={busy}>
        <label htmlFor="excel-file">{t("选择 Excel 文件")}</label>
        <p id="upload-help" className="muted">
          {config ? t('支持 .xlsx · 单文件上限 {limit}', { limit: fileSize(config.max_upload_bytes, t) }) : t("正在读取上传配置……")}
          {projectId ? t(" · 原文件将保存在当前项目中，同名上传不会覆盖已有文件。") : t(" · 文件仅用于本次预览，刷新页面后需重新上传。")}
        </p>
        <div className="upload-controls">
          <input id="excel-file" type="file" accept=".xlsx" onChange={chooseFile}
            disabled={busy || !config} aria-describedby="upload-help" />
          <button type="submit" disabled={!file || !config || busy}>
            {busy ? t("正在处理……") : t("上传并预览")}
          </button>
        </div>
        {file && <p className="muted">{t('已选择：{filename}（{size}）', { filename: file.name, size: fileSize(file.size, t) })}</p>}
        {busy && <p role="status">{t("正在读取文件数据，请稍候。")}</p>}
      </form>
      {configError && <div className="error-panel" role="alert">{t(configError)}{' '}
        <button type="button" onClick={() => setConfigAttempt(value => value + 1)}>{t("重试读取配置")}</button>
      </div>}
      {error && <p className="error-panel" role="alert">{savedFailure && t('文件已保存，但解析失败：')}{t(error, { limit: config ? fileSize(config.max_upload_bytes, t) : '' })}</p>}
      {notice && <p className="saved-notice" role="status">{t(notice)}</p>}
      {workbook && sheet && <div className="preview-panel">
        <div className="preview-heading">
          <div><h3>{workbook.filename}</h3><p className="muted">{t('已识别 {count} 个工作表', { count: workbook.sheets.length })}</p></div>
          <div className="sheet-control">
            <label htmlFor="sheet-select">{t("工作表")}</label>
            <select id="sheet-select" value={sheetIndex} onChange={event => setSheetIndex(Number(event.target.value))}>
              {workbook.sheets.map((item, index) => <option key={index} value={index}>{item.name}</option>)}
            </select>
          </div>
        </div>
        <div aria-live="polite">
          <p className="data-count">{t('{rows} 行 × {columns} 列', { rows: sheet.row_count, columns: sheet.column_count })}</p>
          <p className="muted">{t("第 1 行作为列名；数据行数不含表头，保留中间空行，忽略尾部空白。最多展示前 20 行。")}</p>
          {sheet.warnings.length > 0 && <ul className="warning-panel">
            {sheet.warnings.map((warning, index) => <li key={index}>{workflowNotice(warning, t)}</li>)}
          </ul>}
          {sheet.column_count > 0 && <div className="table-scroll" tabIndex={0} role="region" aria-label={t("数据预览，可横向滚动")}>
            <table>
              <caption>{sheet.name} · {t('当前展示 {shown} / {total} 行（— 表示空值）', { shown: sheet.preview_rows.length, total: sheet.row_count })}</caption>
              <thead><tr><th scope="col">{t("Excel 行号")}</th>{sheet.columns.map((column, index) => <th scope="col" key={index}>{column}</th>)}</tr></thead>
              <tbody>{sheet.preview_rows.map((row, rowIndex) => <tr key={rowIndex}>
                <th scope="row">{rowIndex + 2}</th>
                {row.map((value, columnIndex) => <td key={columnIndex} className={value === null ? 'empty-cell' : undefined}>
                  {value === null ? '—' : typeof value === 'boolean' ? (value ? 'TRUE' : 'FALSE') : String(value)}
                </td>)}
              </tr>)}</tbody>
            </table>
          </div>}
        </div>
      </div>}
      {!workbook && !busy && !error && <p className="empty-preview">{projectId
        ? t("上传文件，或点击项目文件中的“预览”，查看工作表和数据。")
        : t("选择并上传文件后，这里将显示工作表和数据预览。")}</p>}
    </section>
  )
}
