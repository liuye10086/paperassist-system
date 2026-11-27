import {useEffect, useRef, useState, type Ref} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError, useI18n} from '../../shared/i18n'
import ManuscriptImage from '../manuscripts/ManuscriptImage'
import {WorkspaceIcon} from '../projects/WorkspaceShell'
import useDraftLeaveGuard, {type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {IntakeError, intakeRequest, projectBase} from '../research-intake/api'
import {RESEARCH_TIMEOUT_MS, useResearchRead} from '../research-results/api'
import {useSciListDrag} from './useSciListDrag'
import './sciFigures.css'

type SciPlacement = {figure_id: string; chapter_id: string; caption: string}
type ResourceFigure = {id: string; title: string; preview_url: string}
type SciResources = {
  revision: number
  template_id: string | null
  chapters: {id: string; label: string}[]
  figures: ResourceFigure[]
  placements: SciPlacement[]
}

function samePlacements(left: SciPlacement[], right: SciPlacement[]) {
  return left.length === right.length && left.every((item, index) =>
    item.figure_id === right[index].figure_id && item.chapter_id === right[index].chapter_id && item.caption === right[index].caption)
}

type Props = {projectId: string; registerLeaveGuard: RegisterLeaveGuard; onFigures: () => void} & (
  {projectType?: 'sci'; headingRef?: Ref<HTMLHeadingElement>; onTemplate: () => void; onContinue: () => void}
  | {projectType: 'thesis'; headingRef?: never; onTemplate?: never; onContinue?: never; chapterRevision?: number; onSaved?: () => void}
)

export default function CustomerSciResources(props: Props) {
  const {projectId, projectType = 'sci', headingRef, registerLeaveGuard, onTemplate, onFigures, onContinue} = props
  const {t} = useI18n()
  const base = projectBase(projectId)
  const thesis = projectType === 'thesis'
  const chapterRevision = props.projectType === 'thesis' ? props.chapterRevision : undefined
  const lastChapterRevision = useRef(chapterRevision)
  const url = base + (thesis ? '/thesis-figure-resources' : '/sci-resources')
  const initial = useResearchRead<SciResources>(url, true)
  const refreshInitial = initial.refresh
  const [snapshot, setSnapshot] = useState<SciResources | null>(null)
  const [draft, setDraft] = useState<SciPlacement[] | null>(null)
  const [previewId, setPreviewId] = useState('')
  const [busy, setBusy] = useState<'refresh' | 'save' | 'continue' | null>(null)
  const [conflict, setConflict] = useState(false)
  const [reviewLatest, setReviewLatest] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const request = useRef<AbortController | null>(null)
  useEffect(() => {
    const abort = () => request.current?.abort()
    const unsubscribe = onApiSessionChanged(abort)
    return () => {abort(); unsubscribe()}
  }, [])

  const receipt = initial.data
  const current = initial.valid ? (snapshot && snapshot.revision >= (receipt?.revision ?? -1) ? snapshot : receipt) : null
  const chapters = current?.chapters ?? []
  const figures = current?.figures ?? []
  const planned = current?.placements ?? []
  const entries = draft ?? planned
  const chapterPositions = new Map(chapters.map((chapter, index) => [chapter.id, index]))
  const chosen = entries.filter(item => item.chapter_id).sort((left, right) =>
    (chapterPositions.get(left.chapter_id) ?? chapters.length) - (chapterPositions.get(right.chapter_id) ?? chapters.length))
  const payload = chosen.map(item => ({...item, caption:item.caption.trim()}))
  const figureById = new Map(figures.map(figure => [figure.id, figure]))
  const chapterById = new Map(chapters.map(chapter => [chapter.id, chapter.label]))
  const rowIds = [...new Set([...chosen.map(item => item.figure_id), ...figures.map(figure => figure.id)])]
  const preview = figureById.get(previewId)
  const invalid = chosen.some(item => !chapterById.has(item.chapter_id) || !figureById.has(item.figure_id))
  const dirty = !samePlacements(chosen, planned)
  const locked = !!busy || !initial.valid || thesis && initial.loading
  const saveDisabled = locked || !current?.template_id || invalid || conflict
  const figureDrag = useSciListDrag({
    items: chosen,
    id: item => item.figure_id,
    locked,
    range: index => {
      const chapter = chosen[index].chapter_id
      if (!chapterById.has(chapter)) return {first:index, last:index}
      return {
        first: chosen.findIndex(item => item.chapter_id === chapter),
        last: chosen.findLastIndex(item => item.chapter_id === chapter),
      }
    },
    onReorder: ordered => {
      let index = 0
      setDraft(entries.map(item => item.chapter_id ? ordered[index++] : item))
      setNotice('')
    },
  })
  useDraftLeaveGuard(registerLeaveGuard, dirty, !!busy)
  // Chapter requirements and thesis placements share the same profile revision.
  useEffect(() => {
    if (dirty || busy || chapterRevision === lastChapterRevision.current) return
    lastChapterRevision.current = chapterRevision
    refreshInitial()
  }, [busy, dirty, chapterRevision, refreshInitial])

  function update(value: SciPlacement) {
    const index = entries.findIndex(item => item.figure_id === value.figure_id)
    const next = index < 0 ? [...entries, value] : entries.map((item, i) => i === index ? value : item)
    setDraft(next)
    setNotice('')
    if (!conflict) setError('')
  }

  async function operate(mode: NonNullable<typeof busy>) {
    if (!current || request.current || mode !== 'refresh' && saveDisabled) return
    const controller = new AbortController()
    request.current = controller
    setBusy(mode); setError(''); setNotice('')
    const refresh = mode === 'refresh'
    try {
      const response = await intakeRequest<SciResources>(url, refresh ? {signal:controller.signal} : {
        method:'PUT', headers:{'Content-Type':'application/json'}, signal:controller.signal,
        body:JSON.stringify({expected_revision:current.revision, placements:payload}),
      })
      if (controller.signal.aborted) return
      if (!response || !Number.isSafeInteger(response.revision) || !Array.isArray(response.placements) ||
          !Array.isArray(response.figures) || !Array.isArray(response.chapters) ||
          !refresh && (response.template_id !== current.template_id || !samePlacements(response.placements, payload))) {
        throw new Error('资源配置结果待确认，请重试。')
      }
      setSnapshot(response)
      setConflict(false)
      const review = refresh && dirty && (conflict || response.revision !== current.revision)
      setReviewLatest(review)
      if (!refresh || !dirty) setDraft(null)
      if (mode === 'continue') onContinue?.()
      else if (review) setNotice('已读取最新资源。请核对当前草稿后再保存。')
      if (mode === 'save' && props.projectType === 'thesis') props.onSaved?.()
    } catch (cause) {
      if (controller.signal.aborted) return
      if (cause instanceof IntakeError && cause.status === 409) {
        setConflict(true)
        setError('资源配置已有更新。请重新读取并核对当前草稿。')
      } else setError(safeError(cause, refresh ? '读取资源配置失败，请重试。' : '资源配置保存失败，请重试。'))
    } finally {
      request.current = null
      if (!controller.signal.aborted) setBusy(null)
    }
  }

  if (thesis && current && !figures.length && !planned.length && !dirty) return <div className="sci-inline-controls">
    <p>{t('暂无可配置的正图。')}</p>
    <button type="button" className="button-accent" disabled={locked} onClick={onFigures}>{t('前往图件拼版')}</button>
  </div>

  return <section className={thesis ? 'thesis-figure-resources sci-resources' : 'customer-section sci-resources'}>
    {!thesis && <h1 ref={headingRef} tabIndex={-1} className="visually-hidden">{t('模板设定和资源配置')}</h1>}
    <div className="sci-resources-heading">
      <div className="sci-inline-controls">
        <h2>{t('资源配置')}</h2>
        {!thesis && <button type="button" className="button-accent" disabled={locked} onClick={onTemplate}>{t('返回模板设定')}</button>}
      </div>
      {current?.template_id && <button type="button" className="button-accent" disabled={locked || conflict}
        onClick={() => void operate('refresh')}>{t('刷新资源')}</button>}
    </div>
    {initial.error && !current ? <p role="alert" className="error-panel">{t(initial.error)} <button type="button" onClick={initial.refresh}>{t('重试')}</button></p>
      : !current ? <p role="status" className="visually-hidden">{t('正在读取资源配置……')}</p>
      : !current.template_id ? <div className="sci-inline-controls">
        <p>{t(thesis ? '请先采用学校模板。' : '请先核对并使用 SCI 模板。')}</p>
        {thesis && <button type="button" className="button-accent" disabled={locked} onClick={onFigures}>{t('前往图件拼版')}</button>}
      </div>
      : <>
        {!rowIds.length && !thesis && <p>{t('当前没有可选图件。可以保存空配置并继续。')} <button type="button" className="button-quiet" disabled={locked} onClick={onFigures}>{t('前往图件拼版')}</button></p>}
        {busy && <p role="status" className="visually-hidden">{t(busy === 'refresh' ? '正在读取资源配置……' : '正在保存……')}</p>}
        {error && <p role="alert" className="error-panel">{t(error)}{' '}
          {conflict && <button type="button" disabled={locked} onClick={() => void operate('refresh')}>{t('重新读取并核对')}</button>}
        </p>}
        {notice && <p role="status">{t(notice)}</p>}
        {reviewLatest && <div className="sci-resources-current">
          <h3>{t('最新已保存配置')}</h3>
          {planned.length > 0 ? <ul>{planned.map(item => <li key={item.figure_id}>
            {figureById.get(item.figure_id)?.title ?? t('原配图已不可用')} · {chapterById.get(item.chapter_id) ?? t('原章节已失效')}
            {item.caption && <p>{item.caption}</p>}
          </li>)}</ul> : <p>{t('暂无已选用的图件。')}</p>}
          <button type="button" className="button-quiet" disabled={locked} onClick={() => {
            setDraft(null); setReviewLatest(false); setNotice('')
          }}>{t('采用已保存配置')}</button>
        </div>}
        {invalid && <p role="alert" className="error-panel">{t('请为失效的图件配置重新指定章节，或设为未选用。')}</p>}
        {rowIds.length > 0 && <div className="sci-resource-editor" data-preview={!!preview || undefined}>
          <ol className="sci-resource-list sci-sortable-list" role="list" ref={figureDrag.listRef}
            data-sorting={figureDrag.sorting || undefined}>
            {rowIds.map((id, index) => {
              const figure = figureById.get(id)
              const name = figure?.title ?? t('原配图 {number}（已不可用）', {number:index + 1})
              const placement = entries.find(item => item.figure_id === id) ?? {figure_id:id, chapter_id:'', caption:''}
              const unavailableChapter = placement.chapter_id && !chapterById.has(placement.chapter_id)
              const position = chosen.indexOf(placement)
              const previous = chosen[position - 1]
              const next = chosen[position + 1]
              const earlier = previous?.chapter_id === placement.chapter_id ? previous : undefined
              const later = next?.chapter_id === placement.chapter_id ? next : undefined
              const canSort = placement.chapter_id && !unavailableChapter && (earlier || later)
              const previewButton = figure?.preview_url.startsWith(base + '/') &&
                <button type="button" className="button-quiet" aria-pressed={previewId === id}
                  aria-label={t('预览 {name}', {name})} onClick={() => setPreviewId(previewId === id ? '' : id)}>{t('预览')}</button>
              const grip = canSort && <button type="button" className="button-quiet sci-resource-grip"
                aria-label={t('拖动 {heading}', {heading:name})} title={t('拖动排序，或按方向键 ↑/↓')}
                aria-keyshortcuts={locked ? undefined : 'ArrowUp ArrowDown'} {...figureDrag.handle(position)}>
                <WorkspaceIcon name="menu" />
              </button>
              const fields = <>
                <label>{t('入稿章节')}
                  <select aria-label={t('入稿章节 {name}', {name})} disabled={locked} value={placement.chapter_id}
                    onChange={event => update({...placement, chapter_id:event.target.value})}>
                    <option value="">{t('未选用')}</option>
                    {unavailableChapter && <option value={placement.chapter_id} disabled>{t('原章节已失效')}</option>}
                    {!figure && placement.chapter_id && !unavailableChapter && <option value={placement.chapter_id} disabled>{chapterById.get(placement.chapter_id)}</option>}
                    {figure && chapters.map(chapter => <option value={chapter.id} key={chapter.id}>{chapter.label}</option>)}
                  </select>
                </label>
                {placement.chapter_id && <label>{t('图注（选填）')}
                  <textarea rows={1} aria-label={t('图注 {name}', {name})} disabled={locked || !figure} maxLength={20000}
                    value={placement.caption} onChange={event => update({...placement, caption:event.target.value})} />
                </label>}
              </>
              return <li className="sci-resource-card" key={id} {...(position >= 0 ? figureDrag.row(position) : {})}>
                <header className="sci-resource-card-heading">
                  <h3>{name}</h3>
                  {(previewButton || grip) && <div className="sci-resource-card-actions">{previewButton}{grip}</div>}
                </header>
                <div className="sci-resource-fields">{fields}</div>
              </li>
            })}
          </ol>
          {preview?.preview_url.startsWith(base + '/') && <aside className="sci-figure-preview">
            <h3>{preview.title}</h3>
            <ManuscriptImage url={preview.preview_url} title={t('预览 {name}', {name:preview.title})} timeoutMs={RESEARCH_TIMEOUT_MS} />
          </aside>}
        </div>}
      </>}
    {(!thesis || current?.template_id) && <footer className="customer-step-actions sci-figure-actions">
      {current?.template_id && <button type="button" className="button-accent" disabled={saveDisabled || thesis && !dirty}
        onClick={() => void operate('save')}>{t('保存资源配置')}</button>}
      {!thesis && <button type="button" className="button-primary" disabled={saveDisabled}
        onClick={() => void operate('continue')}>{t('下一步 文献与初稿')}</button>}
    </footer>}
  </section>
}
