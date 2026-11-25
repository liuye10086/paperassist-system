import {useEffect, useId, useRef, useState, type ReactNode, type Ref} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {apiError, safeError, useI18n} from '../../shared/i18n'
import ManuscriptImage from '../manuscripts/ManuscriptImage'
import {WorkspaceIcon} from '../projects/WorkspaceShell'
import useDraftLeaveGuard, {type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {IntakeError, intakeRequest, jsonRequest, projectBase} from '../research-intake/api'
import {RESEARCH_TIMEOUT_MS, useResearchRead} from '../research-results/api'
import type {Figure} from '../research-results/contracts'
import {statusNames, type TaskStatus} from '../tasks/taskTypes'
import type {PaperFile} from './paperMaterials'
import './sciFigures.css'

const pageSize = 20
const maxPanels = 10
type Original = Pick<PaperFile, 'id'> & Partial<Pick<PaperFile, 'filename' | 'file_type'>>
type Layout = 'horizontal' | 'vertical' | 'grid2' | 'grid3'
type Page<T> = {items: T[]; page: number; page_size: number; total: number}
type AssemblyVersion = {revision: number; title: string; columns: number; originals: Original[]}
type AssemblyGroup = {
  root_id: string; latest_revision: number; current: AssemblyVersion | null
  pending_title: string | null; pending_originals: Original[]
}
type AssemblyLibrary = {available: Page<Original>; groups: Page<AssemblyGroup>; has_pending: boolean}
type EditVersion = AssemblyVersion & {rootId: string; expectedRevision: number}
type SavedFigure = Figure & {latest_revision?: number}
const pending = (figure: Figure) => ['queued', 'running'].includes(figure.task.status)
const failed = (figure: Figure) => ['failed', 'cancelled'].includes(figure.task.status)
const revisionConflict = '此正图已有更新。请在已保存正图中重新打开。'
const letter = (index: number) => String.fromCharCode(65 + index)
const layouts = [
  {id:'horizontal', label:'横排', min:2, max:3},
  {id:'vertical', label:'竖排', min:2, max:maxPanels},
  {id:'grid2', label:'两列网格', min:3, max:maxPanels},
  {id:'grid3', label:'三列网格', min:4, max:maxPanels},
] as const

function figureFailureMessage(figure: Figure, fallback: string) {
  const code = figure.task.error_code
  return code === 'research_figure_renderer_retired' ? apiError({code}, fallback) : fallback
}

function columnsFor(layout: Layout, count: number) {
  if (count <= 1 || layout === 'vertical') return 1
  if (layout === 'horizontal') return Math.min(count, 3)
  return layout === 'grid2' ? 2 : 3
}

function layoutFor(columns: number, count: number): Layout {
  if (columns === 1) return count > 1 ? 'vertical' : 'horizontal'
  if (columns === count && count <= 3) return 'horizontal'
  return columns === 2 ? 'grid2' : 'grid3'
}

function preferReceipt(receipt: Figure, row?: SavedFigure) {
  if (!row) return true
  const latestRevision = row.latest_revision ?? row.revision
  if (latestRevision > receipt.revision) return false
  if (row.id === receipt.id) return pending(row)
  // The list falls back to the previous successful result when an update fails.
  return pending(receipt) ? latestRevision < receipt.revision : receipt.task.status === 'succeeded'
}

function FigurePane({title, children}: {title: string; children: ReactNode}) {
  const headingId = useId()
  return <section className="sci-figure-pane" aria-labelledby={headingId}>
    <h2 id={headingId}>{title}</h2>
    <div className="sci-figure-pane-body">{children}</div>
  </section>
}

function FigurePager({page, total, busy, label, onPage}: {
  page: number; total: number; busy: boolean; label: string; onPage: (page: number) => void
}) {
  const {t} = useI18n()
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (page === 1 && pages === 1) return null
  return <nav className="customer-pagination" aria-label={t(label)}>
    <button type="button" onClick={() => onPage(page - 1)} disabled={page === 1 || busy}>{t('上一页')}</button>
    <span>{t('第 {page} / {pages} 页', {page, pages})}</span>
    <button type="button" onClick={() => onPage(page + 1)} disabled={page >= pages || busy}>{t('下一页')}</button>
  </nav>
}

export default function CustomerSciFigures({projectId, projectType = 'sci', headingRef, registerLeaveGuard, onContinue}: {
  projectId: string; projectType?: 'sci' | 'thesis'; headingRef?: Ref<HTMLHeadingElement>
  registerLeaveGuard: RegisterLeaveGuard; onContinue: () => void
}) {
  const {t} = useI18n()
  const base = projectBase(projectId)
  const url = base + (projectType === 'thesis' ? '/thesis-figures' : '/sci-figures')
  const [view, setView] = useState<'compose' | 'saved'>('compose')
  const [originalPage, setOriginalPage] = useState(1)
  const [groupPage, setGroupPage] = useState(1)
  const [figurePage, setFigurePage] = useState(1)
  const [openRoot, setOpenRoot] = useState('')
  const [selected, setSelected] = useState<Original[]>([])
  const [editing, setEditing] = useState<EditVersion | null>(null)
  const [saved, setSaved] = useState<Figure | null>(null)
  const [title, setTitle] = useState('')
  const [layout, setLayout] = useState<Layout>('horizontal')
  const [saving, setSaving] = useState(false)
  const [cancelingRoot, setCancelingRoot] = useState('')
  const [error, setError] = useState('')
  const [cancelError, setCancelError] = useState<{rootId: string; message: string} | null>(null)
  const [dropTarget, setDropTarget] = useState<number | null>(null)
  const dragging = useRef<number | null>(null)
  const request = useRef<AbortController | null>(null)
  const attempt = useRef<{body: string; key: string} | null>(null)
  const lookup = useResearchRead<Figure>(saved ? `${url}/${encodeURIComponent(saved.id)}` : '', !!saved, pending)
  const receipt = lookup.valid ? lookup.data ?? saved : null
  const savedFinished = !!receipt && !pending(receipt)
  const figures = useResearchRead<Page<SavedFigure>>(`${url}?page=${figurePage}&page_size=${pageSize}`, view === 'saved',
    result => result.items.some(pending), Number(savedFinished))
  const listed = figures.data?.items ?? []
  const listedReceipt = listed.find(row => row.root_id === receipt?.root_id)
  const optimistic = receipt && figurePage === 1 && preferReceipt(receipt, listedReceipt) ? receipt : null
  const available: SavedFigure[] = !optimistic ? listed : listedReceipt
    ? listed.map(row => row === listedReceipt ? optimistic : row)
    : [optimistic, ...listed]
  const figure = available.find(row => row.root_id === openRoot)
  const openReceipt = receipt?.root_id === openRoot ? receipt : null
  const waitingForNewFigure = !!openReceipt && pending(figure ?? openReceipt)
  const failedReplacement = figure?.task.status === 'succeeded' && openReceipt && openReceipt.id !== figure.id &&
    openReceipt.revision >= (figure.latest_revision ?? figure.revision) && failed(openReceipt)
  const library = useResearchRead<AssemblyLibrary>(`${url}/assembly?page=${originalPage}&group_page=${groupPage}&page_size=${pageSize}`,
    true, result => result.has_pending, Number(savedFinished))
  const unusedOriginals = library.data?.available
  const groups = library.data?.groups
  const savedGroup = groups?.items.find(group => group.root_id === openRoot)
  const busy = saving || !!cancelingRoot
  const canChoose = library.valid && !!library.data && !library.loading && !library.error && !busy
  const choices = layouts.filter(item => item.min <= selected.length && selected.length <= item.max)
  const columns = columnsFor(layout, selected.length)
  const dirty = editing ? title !== editing.title || columns !== editing.columns ||
    selected.length !== editing.originals.length || selected.some((file, i) => file.id !== editing.originals[i].id)
    : !!(title || selected.length)
  const editingSaved = !!figure && editing?.rootId === figure.root_id
  const editingVisible = view === 'saved' ? editingSaved
    : groups?.items.some(group => group.root_id === editing?.rootId && !!group.current)
  useDraftLeaveGuard(registerLeaveGuard, dirty, busy)
  useEffect(() => {
    const abort = () => request.current?.abort()
    const unsubscribe = onApiSessionChanged(abort)
    return () => {abort(); unsubscribe()}
  }, [])

  function toggle(file: Original) {
    setError('')
    if (selected.some(row => row.id === file.id)) {
      const remaining = selected.filter(row => row.id !== file.id)
      setSelected(remaining)
      if (!remaining.length && !editing) setTitle('')
      if (remaining.length >= 2 && !choices.some(choice => choice.id === layout && choice.min <= remaining.length && choice.max >= remaining.length)) {
        setLayout(layoutFor(Math.min(columns, remaining.length), remaining.length))
      }
      return
    }
    if (selected.length >= maxPanels) return
    setSelected([...selected, file])
    if (!title) setTitle((file.filename ?? '').replace(/\.[^.]+$/, '').slice(0, 200))
    if (layout === 'horizontal' && selected.length === 3) setLayout('grid2')
  }

  function move(from: number, to: number) {
    if (busy || from === to || to < 0 || to >= selected.length) return
    const next = [...selected]
    const [panel] = next.splice(from, 1)
    next.splice(to, 0, panel)
    setSelected(next)
  }

  function clearDrag() {
    dragging.current = null
    setDropTarget(null)
  }

  function reset() {
    setError(''); setSelected([]); setTitle(''); setLayout('horizontal'); setEditing(null)
  }

  function cancelEdit() {
    clearDrag()
    reset()
  }

  function revise(previous: AssemblyVersion, rootId: string, expectedRevision: number) {
    setError('')
    setEditing({...previous, rootId, expectedRevision})
    setSelected(previous.originals)
    setTitle(previous.title)
    setLayout(layoutFor(previous.columns, previous.originals.length))
    setOpenRoot(rootId)
    setView('compose')
  }

  function reviseSaved(previous: SavedFigure) {
    const group = groups?.items.find(row => row.root_id === previous.root_id)
    const latestRevision = previous.latest_revision ?? previous.revision
    if (group?.current && (failed(previous) || group.current.revision > previous.revision ||
      group.current.revision === previous.revision && group.latest_revision >= latestRevision)) {
      revise(group.current, group.root_id, group.latest_revision)
      return
    }
    const knownFiles = [...(unusedOriginals?.items ?? []), ...(group?.current?.originals ?? [])]
    const originals = previous.config.panels.map(({source}) =>
      knownFiles.find(file => file.id === source.source_id) ?? {id:source.source_id})
    revise({revision:previous.revision, title:previous.config.title, columns:previous.config.columns, originals},
      previous.root_id, latestRevision)
  }

  function originalChoice(file: Original, name: string) {
    const checked = selected.some(row => row.id === file.id)
    return <label><input type="checkbox" checked={checked} aria-label={name}
      disabled={!canChoose || !checked && selected.length >= maxPanels} onChange={() => toggle(file)} />{name}</label>
  }

  function originalName(file: Original, index: number) {
    return file.filename ?? t('原图 {letter}', {letter:letter(index)})
  }

  async function save() {
    if (!canChoose || !selected.length || !title.trim() || !dirty || request.current) return
    // Retrying the latest failed attempt can change the current figure without advancing the revision.
    if (editing && editing.revision < editing.expectedRevision) {
      const current = groups?.items.find(group => group.root_id === editing.rootId)?.current
      const savedCurrent = available.find(row => row.root_id === editing.rootId && row.task.status === 'succeeded')
      if (current?.revision === editing.expectedRevision || savedCurrent?.revision === editing.expectedRevision) {
        setError(revisionConflict)
        return
      }
    }
    const body = JSON.stringify({title:title.trim(), file_ids:selected.map(file => file.id), columns,
      ...(editing && {root_id:editing.rootId, expected_revision:editing.expectedRevision, base_revision:editing.revision})})
    if (attempt.current?.body !== body) attempt.current = {body, key:crypto.randomUUID()}
    const controller = new AbortController()
    request.current = controller
    setSaving(true); setError('')
    try {
      const value = await intakeRequest<Figure>(url, {method:'POST', body, signal:controller.signal,
        headers:{'Content-Type':'application/json', 'Idempotency-Key':attempt.current.key}}, RESEARCH_TIMEOUT_MS)
      if (controller.signal.aborted) return
      if (!value?.id || !value.task || value.config?.title !== title.trim() ||
          editing && (value.root_id !== editing.rootId || value.revision !== editing.expectedRevision + 1)) {
        throw new Error('正图保存结果待确认，请重试。')
      }
      attempt.current = null
      setSaved(value); setOpenRoot(value.root_id); setFigurePage(1)
      setOriginalPage(1); setGroupPage(1)
      reset(); setView('saved'); figures.refresh(); library.refresh()
    } catch (cause) {
      if (controller.signal.aborted) return
      if (cause instanceof IntakeError && cause.code === 'paper_figure_original_in_use') {
        const conflictIds = (cause.params as {file_ids?: unknown} | null)?.file_ids
        if (Array.isArray(conflictIds)) {
          const remaining = selected.filter(file => !conflictIds.includes(file.id))
          setSelected(remaining)
          setLayout(layoutFor(Math.min(columns, remaining.length), remaining.length))
        }
        library.refresh()
      }
      setError(cause instanceof IntakeError && cause.code === 'research_revision_conflict' && editing
        ? revisionConflict : safeError(cause, '保存正图失败，请重试。'))
    } finally {
      request.current = null
      if (!controller.signal.aborted) setSaving(false)
    }
  }

  async function cancelAssembly(group: AssemblyGroup) {
    if (!canChoose || !group.current || group.pending_title || request.current) return
    const editingThisGroup = editing?.rootId === group.root_id
    let confirmation = t('取消“{name}”的拼版？该组将释放所用原图，并从已保存正图和可选资源中移除。', {name:group.current.title})
    if (editingThisGroup && dirty) confirmation += '\n\n' + t('本组的未保存修改将被放弃。')
    if (!window.confirm(confirmation)) return

    const controller = new AbortController()
    request.current = controller
    setCancelingRoot(group.root_id)
    setCancelError(null)
    try {
      await intakeRequest<void>(`${url}/${encodeURIComponent(group.root_id)}/cancel`, {
        ...jsonRequest({expected_revision:group.latest_revision}), signal:controller.signal,
      }, RESEARCH_TIMEOUT_MS)
      if (controller.signal.aborted) return
      if (editingThisGroup) {
        attempt.current = null
        clearDrag()
        reset()
      }
      if (saved?.root_id === group.root_id) {
        setSaved(null)
        lookup.refresh('invalidate')
      }
      if (openRoot === group.root_id) setOpenRoot('')
      if (groupPage > 1 && groups?.items.length === 1) setGroupPage(groupPage - 1)
      if (figurePage > 1 && listed.length === 1 && listed[0].root_id === group.root_id) setFigurePage(figurePage - 1)
      library.refresh('invalidate')
      figures.refresh('invalidate')
    } catch (cause) {
      if (controller.signal.aborted) return
      library.refresh()
      setCancelError({rootId:group.root_id, message:cause instanceof IntakeError && cause.code === 'research_revision_conflict'
        ? '此正图已有更新或正在生成。请核对最新列表后重试。' : safeError(cause, '取消拼版失败，请重试。')})
    } finally {
      request.current = null
      if (!controller.signal.aborted) setCancelingRoot('')
    }
  }

  const activeFigures = figure?.members.filter(member => ['png','jpeg','tiff'].includes(member.format) && member.download_url.startsWith(base + '/')) ?? []
  const preview = activeFigures.find(member => member.format === 'png' && member.role === 'preview') ??
    activeFigures.find(member => ['png','jpeg'].includes(member.format))
  return <section className="customer-section sci-figures">
    <h1 ref={headingRef} tabIndex={-1} className="visually-hidden">{t('图件拼版')}</h1>
    <div className="customer-switches" role="group" aria-label={t('图件拼版')}>
      <button type="button" className="button-quiet" aria-pressed={view === 'compose'} disabled={busy}
        onClick={() => {setView('compose'); library.refresh()}}>{t('编辑拼版')}</button>
      <button type="button" className="button-quiet" aria-pressed={view === 'saved'} disabled={busy}
        onClick={() => setView('saved')}>{t('已保存正图')}</button>
    </div>
    {view === 'compose' ? <div className="sci-figure-columns sci-figure-compose">
      <div className="sci-assembly-sidebar">
        <FigurePane title={t('待拼原图')}>
          {library.error ? <p role="alert" className="error-panel">{t(library.error)} <button type="button" onClick={library.refresh}>{t('重试')}</button></p>
            : !unusedOriginals ? <p role="status">{t('正在读取文件列表……')}</p>
            : <>
              {unusedOriginals.items.length ? <ul className="sci-figure-choices">
                {unusedOriginals.items.map((file, index) => <li key={file.id}>{originalChoice(file, originalName(file, index))}</li>)}
              </ul> : <p>{t(unusedOriginals.total || groups?.total ? '暂无待拼原图。' : '请在上传资料中添加 PNG、JPEG 或 TIFF 原图。')}</p>}
              <FigurePager page={originalPage} total={unusedOriginals.total} busy={!canChoose} label="原图分页" onPage={setOriginalPage} />
            </>}
        </FigurePane>
        <FigurePane title={t('已拼图')}>
          {cancelError && !groups?.items.some(group => group.root_id === cancelError.rootId) &&
            <p role="alert" className="error-panel">{t(cancelError.message)}</p>}
          {!groups && !library.error && <p role="status">{t('正在读取拼版列表……')}</p>}
          {groups && <>
            {groups.items.length ? <ul className="sci-assembly-groups">
              {groups.items.map(group => {
                const current = group.current
                const name = current?.title ?? group.pending_title ?? ''
                const editingGroup = editing?.rootId === group.root_id
                const pendingFiles = group.pending_originals.filter(file => !current?.originals.some(original => original.id === file.id))
                return <li key={group.root_id}>
                  <div className="sci-assembly-group-heading">
                    <h3>{name}</h3>
                    {current && <div className="sci-assembly-group-actions">
                      <button type="button" className="button-quiet" aria-label={t(editingGroup ? '取消编辑 {name}' : '编辑 {name}', {name})}
                        disabled={editingGroup ? busy : dirty || !canChoose || !!group.pending_title}
                        onClick={editingGroup ? cancelEdit : () => revise(current, group.root_id, group.latest_revision)}>
                        {t(editingGroup ? '取消' : '编辑')}</button>
                      <button type="button" className="button-quiet sci-cancel-assembly" aria-label={t('取消拼版 {name}', {name})}
                        disabled={!canChoose || !!group.pending_title} aria-busy={cancelingRoot === group.root_id || undefined}
                        onClick={() => void cancelAssembly(group)}>{t(cancelingRoot === group.root_id ? '正在取消拼版……' : '取消拼版')}</button>
                    </div>}
                  </div>
                  {cancelError?.rootId === group.root_id && <p role="alert" className="error-panel">{t(cancelError.message)}</p>}
                  {current && <ul className="sci-assembly-originals">
                    {current.originals.map((file, index) => <li key={file.id}>{editingGroup
                      ? originalChoice(file, originalName(file, index)) : originalName(file, index)}</li>)}
                  </ul>}
                  {group.pending_title && <p className="muted">{t('生成中')}
                    {pendingFiles.length > 0 && ` · ${pendingFiles.map(originalName).join(' · ')}`}</p>}
                </li>
              })}
            </ul> : <p className="muted">{t('暂无已拼图件。')}</p>}
            <FigurePager page={groupPage} total={groups.total} busy={!canChoose} label="已拼图分页" onPage={setGroupPage} />
          </>}
        </FigurePane>
      </div>
      <FigurePane title={t('拼版预览')}>
        {selected.length > 0 && <>
          <div className="sci-figure-options">
            <label>{t('正图名称')}<input value={title} maxLength={200} disabled={busy} onChange={event => setTitle(event.target.value)} /></label>
            {selected.length > 1 && <label>{t('拼版布局')}
              <select value={layout} disabled={busy} onChange={event => setLayout(event.target.value as Layout)}>
                {choices.map(choice => <option key={choice.id} value={choice.id}>{t(choice.label)}</option>)}
              </select>
            </label>}
          </div>
          {selected.some(file => file.file_type === 'tiff') && <p className="muted">{t('TIFF 拼版使用第一页。')}</p>}
          <ol className="sci-figure-grid" data-columns={columns} aria-label={t('拼版预览')}>
            {selected.map((file, index) => {
              const filename = originalName(file, index)
              const fileUrl = `${base}/files/${encodeURIComponent(file.id)}`
              return <li key={file.id} data-drop-target={dropTarget === index || undefined}
                onDragOver={event => {
                  if (busy || dragging.current === null) return
                  event.preventDefault()
                  event.dataTransfer.dropEffect = 'move'
                  setDropTarget(index)
                }} onDrop={event => {
                  if (dragging.current === null) return
                  event.preventDefault()
                  move(dragging.current, index)
                  clearDrag()
                }}>
                <div className="sci-figure-tile">{selected.length > 1 && <strong>{letter(index)}</strong>}
                  <ManuscriptImage url={fileUrl + (!file.file_type || file.file_type === 'tiff' ? '/image-preview' : '/download')} title={t('预览 {name}', {name:filename})} />
                </div>
                <div className="sci-figure-panel-tools"><span title={filename}>{filename}</span>
                  {selected.length > 1 && <button type="button" className="button-quiet sci-panel-grip" aria-label={t('拖动 {heading}', {heading:filename})}
                    draggable={!busy} disabled={busy} aria-keyshortcuts="ArrowUp ArrowDown" title={t('拖动排序，或按方向键 ↑/↓')}
                    onDragStart={event => {
                      dragging.current = index
                      event.dataTransfer.effectAllowed = 'move'
                      event.dataTransfer.setData('text/plain', '')
                    }} onDragEnd={clearDrag} onKeyDown={event => {
                      if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
                      event.preventDefault()
                      move(index, index + (event.key === 'ArrowUp' ? -1 : 1))
                    }}><WorkspaceIcon name="menu" /></button>}
                  <button type="button" className="button-quiet" disabled={busy} aria-label={t('移除 {name}', {name:filename})} onClick={() => toggle(file)}>×</button>
                </div>
              </li>
            })}
          </ol>
        </>}
        {error && <p role="alert" className="error-panel">{t(error)}</p>}
      </FigurePane>
    </div> : <div className="sci-figure-columns">
      <FigurePane title={t('已保存正图')}>
        {figures.error && <p role="alert" className="error-panel">{t(figures.error)} <button type="button" onClick={figures.refresh}>{t('重试')}</button></p>}
        {!figures.data && !figures.error && !available.length && <p role="status">{t('正在读取正图……')}</p>}
        {figures.data && !available.length && <p>{t('此项目还没有保存正图。')}</p>}
        {!!available.length && <ul className="sci-formal-figures">{available.map(row => <li key={row.root_id}>
          <button type="button" className="button-quiet" aria-pressed={openRoot === row.root_id} onClick={() => setOpenRoot(row.root_id)}>
            <strong>{row.config.title}</strong>
            <small>{t(statusNames[row.task.status as TaskStatus] ?? '待核对')}</small>
          </button>
        </li>)}</ul>}
        {figures.data && <FigurePager page={figurePage} total={figures.data.total} busy={figures.loading} label="正图分页" onPage={page => {
          setFigurePage(page); setOpenRoot('')
        }} />}
      </FigurePane>
      <FigurePane title={figure?.config.title ?? t('正图预览')}>
        {openReceipt && lookup.error && <p role="alert" className="error-panel">{t(lookup.error)} <button type="button" onClick={lookup.refresh}>{t('重试')}</button></p>}
        {!figure && openRoot && figures.loading && <p role="status">{t('正在读取正图……')}</p>}
        {figure && pending(figure) && <p role="status">{t('正图正在生成，完成后可在资源配置中选用。')}</p>}
        {failedReplacement && <p role="alert" className="error-panel">{t(figureFailureMessage(openReceipt, '正图更新失败。仍可使用上一次生成的正图。'))}</p>}
        {figure && failed(figure) && <p role="alert" className="error-panel">{t(figureFailureMessage(figure, '正图生成未完成。可检查原图后重新保存。'))}</p>}
        {preview && figure && <div className="sci-figure-preview">
          <ManuscriptImage url={preview.download_url} title={t('预览 {name}', {name:figure.config.title})} timeoutMs={RESEARCH_TIMEOUT_MS} />
        </div>}
        {figure && <div className="sci-inline-controls">
          {activeFigures.map(member => {
            const format = member.format.toUpperCase()
            const name = figure.config.title.replace(/[\\/]/g, '-') + '.' + member.format
            return <ProjectDownloadLink key={member.id} href={member.download_url} filename={name} timeoutMs={RESEARCH_TIMEOUT_MS}
              ariaLabel={t('下载 {name}（{format}）', {name:figure.config.title, format})}>{t('下载 {format}', {format})}</ProjectDownloadLink>
          })}
          {(editingSaved || !pending(figure) && !dirty) && <button type="button" className="button-quiet"
            aria-label={t(editingSaved ? '取消编辑 {name}' : '编辑 {name}', {name:figure.config.title})}
            disabled={busy || !editingSaved && !!savedGroup?.pending_title}
            onClick={editingSaved ? cancelEdit : () => reviseSaved(figure)}>{t(editingSaved ? '取消' : '编辑')}</button>}
        </div>}
      </FigurePane>
    </div>}
    <footer className="customer-step-actions sci-figure-actions">
      {editing && !editingVisible && <button type="button" className="button-quiet" disabled={busy}
        aria-label={t('取消编辑 {name}', {name:editing.title})} onClick={cancelEdit}>{t('取消')}</button>}
      {view === 'compose' && dirty && !editing && <button type="button" className="button-quiet" disabled={busy} onClick={reset}>{t('取消修改')}</button>}
      {view === 'compose' && !!selected.length && <button type="button" className="button-primary" disabled={!canChoose || !title.trim() || !dirty}
        onClick={() => void save()}>{t(saving ? '正在保存……' : editing ? '保存修改' : '保存为正图')}</button>}
      <button type="button" className={view === 'compose' && selected.length ? 'button-quiet' : 'button-primary'} disabled={busy || waitingForNewFigure}
        onClick={onContinue}>{t(projectType === 'thesis' ? '下一步 模板与资料整理' : '下一步 模板设定和资源配置')}</button>
    </footer>
  </section>
}
