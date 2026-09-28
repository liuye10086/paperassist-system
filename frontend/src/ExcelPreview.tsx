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

function fileSize(bytes: number) {
  return bytes >= 1024 * 1024
    ? `${Number((bytes / (1024 * 1024)).toFixed(2))} MiB`
    : `${bytes} 字节`
}

export default function ExcelPreview() {
  const [config, setConfig] = useState<PreviewConfig | null>(null)
  const [configError, setConfigError] = useState('')
  const [configAttempt, setConfigAttempt] = useState(0)
  const [file, setFile] = useState<File | null>(null)
  const [workbook, setWorkbook] = useState<WorkbookPreview | null>(null)
  const [sheetIndex, setSheetIndex] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const uploadController = useRef<AbortController | null>(null)
  const sheet = workbook?.sheets[sheetIndex]

  useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 15_000)
    let active = true
    async function loadConfig() {
      setConfigError('')
      try {
        const response = await fetch('/api/v1/excel/config', { signal: controller.signal })
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

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null
    setWorkbook(null)
    setSheetIndex(0)
    setError('')
    setFile(null)
    if (!selected) return
    if (!selected.name.toLowerCase().endsWith('.xlsx')) {
      setError('仅支持 .xlsx 文件，请将文件另存为 .xlsx 后上传。')
    } else if (selected.size === 0) {
      setError('所选文件为空，请选择有效的 .xlsx 工作簿。')
    } else if (config && selected.size > config.max_upload_bytes) {
      setError(`文件超过 ${fileSize(config.max_upload_bytes)} 的上传限制。`)
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
    setWorkbook(null)
    const body = new FormData()
    body.append('file', file)
    try {
      const response = await fetch('/api/v1/excel/preview', {
        method: 'POST', body, signal: controller.signal,
      })
      const result = await response.json().catch(() => null)
      if (!response.ok) {
        const detail = result?.detail
        const message = typeof detail?.message === 'string' ? detail.message
          : response.status === 413 ? '文件超过上传限制，请缩小文件后重试。'
            : '上传或解析失败，请检查文件和后端服务后重试。'
        throw new Error(message)
      }
      if (!Array.isArray(result?.sheets) || result.sheets.length === 0) {
        throw new Error('后端返回的工作表信息不完整，请重试。')
      }
      if (!controller.signal.aborted) {
        setWorkbook(result)
        setSheetIndex(0)
      }
    } catch (cause) {
      if (timedOut) {
        setError('上传或解析超时，请缩小文件或稍后重试。')
      } else if (!controller.signal.aborted) {
        setError(cause instanceof TypeError ? '无法连接后端，请确认服务和网络正常后重试。'
          : cause instanceof Error ? cause.message : '上传失败，请重试。')
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
        <span className="step-label">数据准备</span>
        <h2 id="excel-title">Excel 上传与预览</h2>
        <p>上传研究数据，检查工作表、字段与原始记录。</p>
      </div>
      <form onSubmit={upload} className="upload-panel" aria-busy={busy}>
        <label htmlFor="excel-file">选择 Excel 文件</label>
        <p id="upload-help" className="muted">
          {config ? `支持 .xlsx · 单文件上限 ${fileSize(config.max_upload_bytes)}` : '正在读取上传配置……'}
          {' · 文件仅用于本次预览，刷新页面后需重新上传。'}
        </p>
        <div className="upload-controls">
          <input id="excel-file" type="file" accept=".xlsx" onChange={chooseFile}
            disabled={busy || !config} aria-describedby="upload-help" />
          <button type="submit" disabled={!file || !config || busy}>
            {busy ? '正在上传并解析……' : '上传并预览'}
          </button>
        </div>
        {file && <p className="muted">已选择：{file.name}（{fileSize(file.size)}）</p>}
        {busy && <p role="status">正在读取工作表并统计行列，请稍候。</p>}
      </form>
      {configError && <div className="error-panel" role="alert">{configError}{' '}
        <button type="button" onClick={() => setConfigAttempt(value => value + 1)}>重试读取配置</button>
      </div>}
      {error && <p className="error-panel" role="alert">{error}</p>}
      {workbook && sheet && <div className="preview-panel">
        <div className="preview-heading">
          <div><h3>{workbook.filename}</h3><p className="muted">已识别 {workbook.sheets.length} 个工作表</p></div>
          <div className="sheet-control">
            <label htmlFor="sheet-select">工作表</label>
            <select id="sheet-select" value={sheetIndex} onChange={event => setSheetIndex(Number(event.target.value))}>
              {workbook.sheets.map((item, index) => <option key={index} value={index}>{item.name}</option>)}
            </select>
          </div>
        </div>
        <div aria-live="polite">
          <p className="data-count">{sheet.row_count} 行 × {sheet.column_count} 列</p>
          <p className="muted">第 1 行作为列名；数据行数不含表头，保留中间空行，忽略尾部空白。最多展示前 20 行。</p>
          {sheet.warnings.length > 0 && <ul className="warning-panel">
            {sheet.warnings.map((warning, index) => <li key={index}>{warning}</li>)}
          </ul>}
          {sheet.column_count > 0 && <div className="table-scroll" tabIndex={0} role="region" aria-label="数据预览，可横向滚动">
            <table>
              <caption>{sheet.name} · 当前展示 {sheet.preview_rows.length} / {sheet.row_count} 行（— 表示空值）</caption>
              <thead><tr><th scope="col">Excel 行号</th>{sheet.columns.map((column, index) => <th scope="col" key={index}>{column}</th>)}</tr></thead>
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
      {!workbook && !busy && !error && <p className="empty-preview">选择并上传文件后，这里将显示工作表和数据预览。</p>}
    </section>
  )
}
