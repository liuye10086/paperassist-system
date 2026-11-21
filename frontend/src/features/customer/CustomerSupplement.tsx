import { useEffect, useId, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import { parseStatusLabels, type LibraryFile } from '../files/fileLibraryApi'
import { IntakeError } from '../research-intake/api'
import useResearchDraft from '../research-results/useResearchDraft'
import { shortTime, submitMaterials, type Progress } from './customerWorkspaceApi'

// Supplement mode of the upload step (接口设计第二节 4, wireframe 02).

export type ClosedSupplement = { kind: 'revision'; submitted: number } | { kind: 'not_requested' }

export function SupplementRequest({ progress, error, closed, onRetry, onProgress }: {
  progress: Progress | null; error: string; closed: ClosedSupplement | null; onRetry: () => void; onProgress: () => void
}) {
  const { t, locale } = useI18n()
  if (closed || (progress && (progress.status !== 'needs_materials' || progress.requirement_version == null))) {
    let message = t('分析员当前没有请求补充资料。')
    if (closed?.kind === 'not_requested') message = t('分析员已不再等待补充资料，无需再提交。')
    if (closed?.kind === 'revision') {
      const current = progress?.requirement_version
      message = current != null && current !== closed.submitted
        ? t('需求已更新为第 {version} 版，这次补交请求已失效，已上传的文件仍保留在项目中。', { version: current })
        : t('需求已更新，这次补交请求已失效，已上传的文件仍保留在项目中。')
    }
    return <div className={closed ? 'error-panel customer-supplement-error' : 'customer-supplement-error'}>
      <p role={closed ? 'alert' : 'status'}>{message}</p>
      <button type="button" className="button-primary" onClick={onProgress}>{t('查看任务进度')}</button>
    </div>
  }
  if (error) return <p role="alert" className="error-panel">{t(error)}{' '}
    <button type="button" onClick={onRetry}>{t('重新读取')}</button></p>
  if (!progress) return <p role="status">{t('正在读取补充说明……')}</p>
  return <div className="customer-supplement-request">
    <p><strong>{t('分析员需要你补充：')}</strong><span>{progress.note || t('请查看补充说明并上传所需资料。')}</span></p>
    {progress.requirement_version != null && <p className="muted">{t('需求第 {version} 版 · {date}', {
      version: progress.requirement_version, date: shortTime(progress.updated_at ?? progress.submitted_at, locale),
    })}</p>}
  </div>
}

type Pending = { key: string; body: string }

export function SupplementForm({ projectId, version, recent, onClosed, onSubmitted }: {
  projectId: string
  version: number
  /** Newest project files first; files not in the first read are the ones uploaded on this page. */
  recent: LibraryFile[] | null
  onClosed: (reason: ClosedSupplement) => void
  onSubmitted: () => void
}) {
  const { t } = useI18n()
  const noteId = useId()
  const [baseline, setBaseline] = useState<Set<string> | null>(null)
  const [unchecked, setUnchecked] = useState<Set<string>>(() => new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useResearchDraft(projectId, `customer-supplement-note:${projectId}:${version}`, () => '')
  const pending = useRef<Pending | null>(null)
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])

  // The first file read marks what was already in the project when the customer arrived.
  if (recent && !baseline) setBaseline(new Set(recent.map(file => file.id)))
  const added = recent && baseline ? recent.filter(file => !baseline.has(file.id)) : []
  const selected = added.filter(file => !unchecked.has(file.id)).map(file => file.id)

  function toggle(id: string, checked: boolean) {
    setUnchecked(current => {
      const next = new Set(current)
      if (checked) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function submit() {
    if (!selected.length || request.current) return
    const body = { requirement_version: version, file_ids: selected, note: note.trim() || null }
    const text = JSON.stringify(body)
    // Retrying the same content reuses the key, so an unknown result is never submitted twice.
    if (pending.current?.body !== text) pending.current = { key: crypto.randomUUID(), body: text }
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setError('')
    try {
      await submitMaterials(projectId, body, pending.current.key, controller.signal)
      if (controller.signal.aborted) return
      pending.current = null
      setNote('')
      onSubmitted()
    } catch (cause) {
      if (controller.signal.aborted) return
      const code = cause instanceof IntakeError ? cause.code : ''
      if (cause instanceof IntakeError && cause.status < 500 && cause.status !== 408) pending.current = null
      if (code === 'research_revision_conflict') {
        onClosed({ kind: 'revision', submitted: version })
      } else if (code === 'materials_not_requested') {
        onClosed({ kind: 'not_requested' })
      } else {
        setError(pending.current ? '补交结果待确认，请重试原请求。' : safeError(cause, '补充资料提交失败，请重试。'))
      }
    } finally {
      if (request.current === controller) request.current = null
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return <section className="customer-supplement" aria-label={t('本次补交的文件')}>
    <h3>{t('本次补交的文件')}</h3>
    {added.length === 0
      ? <p className="muted">{t('上传后，本次新上传的文件会出现在这里并默认勾选。')}</p>
      : <ul className="customer-list customer-supplement-files">
        {added.map(file => <li key={file.id}>
          <label>
            <input type="checkbox" checked={!unchecked.has(file.id)} disabled={busy}
              onChange={event => toggle(file.id, event.target.checked)} />
            <span>{file.filename}</span>
          </label>
          <span className="muted">{t(file.parse_status === 'stored' ? '已上传' : parseStatusLabels[file.parse_status])}</span>
        </li>)}
      </ul>}
    <label htmlFor={noteId}>{t('给分析员的说明（选填）')}</label>
    <textarea id={noteId} rows={3} maxLength={4000} value={note} disabled={busy}
      onChange={event => { setNote(event.target.value); setError('') }} />
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    <div className="customer-supplement-actions">
      {!selected.length && <span className="muted">{t('先选择要补交的文件')}</span>}
      <button type="button" className="button-primary" disabled={busy || !selected.length}
        onClick={() => void submit()}>{t(busy ? '正在提交……' : '提交补充资料')}</button>
    </div>
  </section>
}
