import { useEffect, useRef, useState, type FormEvent } from 'react'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { safeError, useI18n } from '../../shared/i18n'
import type { FilePage } from '../files/fileLibraryApi'
import ManuscriptImage from '../manuscripts/ManuscriptImage'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { IntakeError, intakeRequest, projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'
import useResearchDraft from '../research-results/useResearchDraft'
import { paperMaterialKind, paperMaterialsUrl, type PaperFile, type PaperMaterialNote, type PaperMaterialTarget, type PaperWorksheet } from './paperMaterials'

type Edit = { id: string; revision: number; file: PaperFile; result: string; targetId: string | null; worksheetNames?: string[] }

export default function PaperMaterialEditor({ projectId, original, note, targets, prefill, onBack, onSaved, onRequirements, registerLeaveGuard }: {
  projectId: string; original: PaperFile; note: PaperMaterialNote | undefined; targets: PaperMaterialTarget[]
  /** Suggested main result for a file without one, e.g. where an analysis result came from; saved only with the form. */
  prefill?: string
  onBack: () => void; onSaved: () => void; onRequirements?: () => void; registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  const [current, setCurrent] = useState({ file: original, note })
  const [id] = useState(() => note?.id ?? crypto.randomUUID())
  const [edit, setEdit] = useResearchDraft<Edit | null>(projectId, `paper-material-${original.id}`, () => null)
  const [selecting, setSelecting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const request = useRef<AbortController | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus()
    return () => request.current?.abort()
  }, [])

  const baseline: Edit = { id: current.note?.id ?? id, revision: current.note?.revision ?? 0, file: current.file,
    result: current.note?.result ?? prefill ?? '', targetId: current.note?.target_available ? current.note.target_id : null,
    worksheetNames: current.note?.worksheet_names ?? undefined }
  const draft = edit ?? baseline
  const outdated = !!edit && (edit.revision !== baseline.revision || !!current.note && edit.id !== current.note.id)
  useDraftLeaveGuard(registerLeaveGuard, !!edit, busy)
  const kind = paperMaterialKind(original)
  const fileUrl = `${projectBase(projectId)}/files/${encodeURIComponent(draft.file.id)}`
  const excel = draft.file.file_type === 'xlsx'
  const worksheetRead = useResearchRead<{ sheets: PaperWorksheet[] }>(
    `${paperMaterialsUrl(projectId)}/worksheets/${encodeURIComponent(draft.file.id)}`, excel && !selecting)
  const sheets = worksheetRead.data?.sheets ?? []
  const worksheetNames = draft.worksheetNames ?? (sheets.length === 1 && sheets[0].values_ready ? [sheets[0].name] : [])
  const currentTarget = targets.find(target => target.id === draft.targetId)

  function change(update: Partial<Edit>) {
    setEdit({ ...draft, ...update })
    setError('')
    setSaved(false)
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (request.current || outdated) return
    const result = draft.result.trim()
    if (!result) { setError('请填写这份图表资料的主要结果。'); return }
    if (draft.targetId && !currentTarget) { setError('请重新选择当前项目中的关联。'); return }
    if (excel && draft.targetId && !worksheetNames.length) { setError('请选择要入稿的工作表。'); return }
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setSaved(false)
    setError('')
    try {
      const next = await intakeRequest<PaperMaterialNote>(`${paperMaterialsUrl(projectId)}/${encodeURIComponent(draft.id)}`, {
        method: 'PUT', signal: controller.signal, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_revision: draft.revision, file_id: draft.file.id, result, target_id: draft.targetId,
          ...(excel ? { worksheet_names: worksheetNames.length ? worksheetNames : null } : {}) }),
      })
      if (controller.signal.aborted) return
      if (!next || next.id !== draft.id || next.file_id !== draft.file.id || next.result !== result ||
          ![draft.revision, draft.revision + 1].includes(next.revision)) {
        throw new Error('图表资料保存结果待确认，请重试。')
      }
      setCurrent({ file: draft.file, note: next })
      setEdit(null)
      setSaved(true)
      onSaved()
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(safeError(cause, '图表资料保存失败，请重试。'))
        if (cause instanceof IntakeError && cause.status === 409) onSaved()
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false)
      request.current = null
    }
  }

  return <section className="paper-material-editor" aria-label={t('图表资料')}>
    <div className="customer-section-heading">
      <h3 ref={heading} tabIndex={-1}>{t(selecting ? '选择替换文件' : '图表资料')}</h3>
      <button type="button" className="button-quiet" disabled={busy} onClick={selecting ? () => setSelecting(false) : onBack}>
        {t(selecting ? '返回图表资料' : '返回项目文件')}
      </button>
    </div>
    {selecting ? <ReplacementFiles projectId={projectId} current={draft.file} onSelect={file => {
      change({ file, worksheetNames: undefined })
      setSelecting(false)
    }} /> : <>
      <div className="paper-material-original">
        <strong>{draft.file.filename}</strong>
        <div className="sci-inline-controls">
          <ProjectDownloadLink href={`${fileUrl}/download`} filename={draft.file.filename}>{t('下载原文件')}</ProjectDownloadLink>
          <button type="button" className="button-quiet" disabled={busy || outdated} onClick={() => setSelecting(true)}>{t('更换文件')}</button>
        </div>
      </div>
      <div className={kind === 'figure' ? 'paper-material-layout has-figure' : 'paper-material-layout'}>
        {kind === 'figure' && <div className="paper-material-preview">
          <ManuscriptImage key={draft.file.id} url={`${fileUrl}/image-preview`} title={t('预览 {name}', { name: draft.file.filename })} />
          {draft.file.file_type === 'tiff' && <p className="muted">{t('TIFF 预览和 Word 使用第一页，可下载完整原件。')}</p>}
        </div>}
        <form className="paper-material-form" noValidate aria-busy={busy} onSubmit={event => void save(event)}>
          <fieldset disabled={busy || outdated}>
            <label>{t('主要结果')}<textarea required rows={5} maxLength={20000} value={draft.result}
              onChange={event => change({ result: event.target.value })} /></label>
            <label>{t('关联到')}<select value={currentTarget?.id ?? ''} onChange={event => change({ targetId: event.target.value || null })}>
              <option value="">{t('待关联')}</option>
              {targets.map(target => <option key={target.id} value={target.id}>{target.label}</option>)}
            </select></label>
            {excel && <fieldset>
              <legend>{t('入稿工作表')}</legend>
              {worksheetRead.error && <p role="alert" className="error-panel">{t(worksheetRead.error)}{' '}
                <button type="button" onClick={worksheetRead.refresh}>{t('重试')}</button></p>}
              {!worksheetRead.data && !worksheetRead.error && <p role="status">{t('正在读取工作表……')}</p>}
              {worksheetRead.data && !sheets.length && <p>{t('文件中没有可入稿的工作表。')}</p>}
              {sheets.map(sheet => <WorksheetChoice key={sheet.name} sheet={sheet} selected={worksheetNames.includes(sheet.name)}
                onChange={checked => change({ worksheetNames: sheets
                  .filter(item => item.name === sheet.name ? checked : worksheetNames.includes(item.name)).map(item => item.name) })} />)}
            </fieldset>}
          </fieldset>
          {(current.note?.target_label && !current.note.target_available) &&
            <p className="muted">{t('原关联 · {name}', { name: current.note.target_label })}</p>}
          {!targets.length && onRequirements && <p>{t('请在项目资料添加发现、小标题或结果章节，再关联此文件。')}{' '}
            <button type="button" className="button-quiet" disabled={busy} onClick={onRequirements}>{t('前往项目资料')}</button>
          </p>}
          {outdated && <p className="warning-panel" role="status">{t('图表资料已更新，请核对当前资料。')}{' '}
            <button type="button" onClick={() => { setEdit(null); setError('') }}>{t('使用当前资料')}</button>
          </p>}
          {error && <p role="alert" className="error-panel">{t(error)}</p>}
          {saved && <p role="status">{t('图表资料已保存。')}</p>}
          <button type="submit" className="button-primary" disabled={busy || outdated}>{t(busy ? '正在保存……' : '保存图表资料')}</button>
        </form>
      </div>
    </>}
  </section>
}

function WorksheetChoice({ sheet, selected, onChange }: { sheet: PaperWorksheet; selected: boolean; onChange: (checked: boolean) => void }) {
  const { t } = useI18n()
  return <div>
    <label><input type="checkbox" checked={selected} disabled={!sheet.values_ready}
      onChange={event => onChange(event.target.checked)} />{sheet.name}</label>
    {!sheet.values_ready && <p className="muted">{t('此工作表包含公式或错误单元格。请使用核对后的固定值。')}</p>}
    {selected && <div className="field-table-scroll">
      <table className="field-table">
        <caption>{t('工作表预览 · {name}', { name: sheet.name })}</caption>
        <thead><tr>{sheet.columns.map((value, index) => <th key={index}>{value}</th>)}</tr></thead>
        <tbody>{sheet.preview_rows.map((row, index) => <tr key={index}>
          {row.map((value, column) => <td key={column}>{value}</td>)}
        </tr>)}</tbody>
      </table>
      {sheet.row_count > sheet.preview_rows.length && <small>{t('共 {count} 行，仅预览前几行。', { count: sheet.row_count })}</small>}
    </div>}
  </div>
}

const replacementPageSize = 10

function ReplacementFiles({ projectId, current, onSelect }: { projectId: string; current: PaperFile; onSelect: (file: PaperFile) => void }) {
  const { t } = useI18n()
  const [page, setPage] = useState(1)
  const read = useResearchRead<FilePage>(`${projectBase(projectId)}/files?page=${page}&page_size=${replacementPageSize}`, true)
  const choices = read.data?.items.filter(file => file.id !== current.id && paperMaterialKind(file) === paperMaterialKind(current)) ?? []
  const pages = Math.max(1, Math.ceil((read.data?.total ?? 0) / replacementPageSize))
  return <>
    {read.error && <p role="alert" className="error-panel">{t(read.error)}{' '}<button type="button" onClick={read.refresh}>{t('重试')}</button></p>}
    {!read.data && !read.error && <p role="status">{t('正在读取文件列表……')}</p>}
    {read.data && (choices.length ? <ul className="customer-list" aria-label={t('可替换的项目文件')}>
      {choices.map(file => <li key={file.id}><span>{file.filename}</span>
        <button type="button" onClick={() => onSelect({ id: file.id, filename: file.filename, file_type: file.file_type })}
          aria-label={t('使用 {name}', { name: file.filename })}>{t('使用此文件')}</button></li>)}
    </ul> : <p>{t('本页没有同类文件。')}</p>)}
    {read.data && pages > 1 && <nav className="customer-pagination" aria-label={t('替换文件分页')}>
      <button type="button" onClick={() => setPage(page - 1)} disabled={page === 1 || read.loading}>{t('上一页')}</button>
      <span>{t('第 {page} / {pages} 页', { page, pages })}</span>
      <button type="button" onClick={() => setPage(page + 1)} disabled={page >= pages || read.loading}>{t('下一页')}</button>
    </nav>}
  </>
}
