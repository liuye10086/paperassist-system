import { useCallback, useEffect, useRef, useState } from 'react'
import { apiError, safeError, useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import FileDetails from './FileDetails'
import { fileRequest, mergeFileMetadata, parseStatusLabels, purposeLabels } from './fileLibraryApi'
import type { FilePage, LibraryFile } from './fileLibraryApi'
import type { SavedPreviewState } from './ExcelPreview'
import './fileLibrary.css'
import type { ResourceNavigation } from '../projects/resourceViews'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'

export default function ProjectFileLibrary({ projectId, active, uploadVersion, busy, previewState, onPreview, onUnavailable, resourceNavigation, onResourceNavigate, registerLeaveGuard }: {
  projectId: string; active: boolean; uploadVersion: number; busy: boolean; previewState: SavedPreviewState | null
  onPreview: (id: string) => void; onUnavailable: () => void
  resourceNavigation?: ResourceNavigation; onResourceNavigate?: (next: ResourceNavigation) => void; registerLeaveGuard?: RegisterLeaveGuard
}) {
  const { t, locale } = useI18n()
  const [page, setPage] = useState(1)
  const [result, setResult] = useState<FilePage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [seenUpload, setSeenUpload] = useState(uploadVersion)
  const [localNavigation, setLocalNavigation] = useState<ResourceNavigation>({ view: 'list', fileId: '' })
  const navigation = resourceNavigation ?? localNavigation
  const selected = navigation.view === 'detail' ? navigation.fileId : null
  const [visited, setVisited] = useState<string[]>(selected ? [selected] : [])
  const [documentPreview, setDocumentPreview] = useState<string | null>(null)
  if (selected && !visited.includes(selected)) setVisited(current => [...current, selected])
  function openDetails(id: string, preview = false) {
    setDocumentPreview(preview ? id : null)
    const next = { view: 'detail' as const, fileId: id }
    if (onResourceNavigate) onResourceNavigate(next); else setLocalNavigation(next)
  }
  const listActive = active && navigation.view === 'list'
  const confirmedMetadata = useRef(new Map<string, LibraryFile>())
  const requestKey = `${projectId}:${listActive}:${page}:${attempt}:${uploadVersion}`
  const [previousRequest, setPreviousRequest] = useState(requestKey)
  if (previousRequest !== requestKey) {
    setPreviousRequest(requestKey)
    if (listActive) { setLoading(true); setError('') }
  }
  if (seenUpload !== uploadVersion) { setSeenUpload(uploadVersion); setPage(1) }
  const updated = useCallback((file: LibraryFile) => {
    const merged = mergeFileMetadata(file, confirmedMetadata.current.get(file.id))
    confirmedMetadata.current.set(file.id, merged)
    setResult(current => current && ({ ...current, items: current.items.map(item => item.id === file.id ? merged : item) }))
  }, [])

  useEffect(() => {
    if (!listActive) return
    const controller = new AbortController()
    let current = true
    const timeout = window.setTimeout(() => controller.abort(), 15_000)
    void fileRequest<FilePage>(`/api/v1/projects/${projectId}/files?page=${page}&page_size=5`, controller.signal, onUnavailable)
      .then(data => {
        if (!Array.isArray(data?.items) || !Number.isSafeInteger(data.total) || data.total < 0 || data.page !== page || data.page_size !== 5) throw new Error('format')
        if (current && !controller.signal.aborted) {
          const lastPage = Math.max(1, Math.ceil(data.total / 5))
          if (page > lastPage) setPage(lastPage)
          else setResult({ ...data, items: data.items.map(file => {
            const merged = mergeFileMetadata(file, confirmedMetadata.current.get(file.id))
            confirmedMetadata.current.set(file.id, merged)
            return merged
          }) })
        }
      })
      .catch(cause => {
        if (current) setError(controller.signal.aborted ? '文件列表读取超时，请重试。'
          : safeError(cause, '文件列表读取失败，请确认后端服务正常后重试。'))
      })
      .finally(() => { window.clearTimeout(timeout); if (current) setLoading(false) })
    return () => { current = false; controller.abort(); window.clearTimeout(timeout) }
  }, [projectId, page, attempt, listActive, uploadVersion, onUnavailable])

  return <>
    {!resourceNavigation && navigation.view === 'detail' && <button onClick={() => setLocalNavigation({ view: 'list', fileId: '' })}>{t('返回文件列表')}</button>}
    <section hidden={navigation.view !== 'list'} className="file-history" aria-labelledby="files-title">
      <div className="preview-heading"><div><span className="workspace-eyebrow">{t('研究资料')}</span><h2 id="files-title">{t('项目文件')}</h2>
        <p className="muted">{t('上传数据，查看工作表，保留研究的原始资料。')}</p></div>
        <button type="button" disabled={loading || busy} onClick={() => setAttempt(value => value + 1)}>{t('刷新文件列表')}</button></div>
      {loading && <p role="status">{t('正在读取文件列表……')}</p>}
      {error && <p className="error-panel" role="alert">{t(error)}</p>}
      {!loading && !error && result?.total === 0 && <p>{t('此项目还没有文件。')}</p>}
      {!loading && !error && result && <>
        <ul className="file-list">{result.items.map(file => <li key={file.id}
          aria-current={previewState?.id === file.id && previewState.status === 'ready' ? 'true' : undefined}>
          <div className="file-summary"><strong>{file.filename}</strong> · <span>{file.file_type?.toUpperCase()}</span>{' '}<span className={file.parse_status === 'failed' ? 'file-failed' : 'file-parsed'}>
            {t(parseStatusLabels[file.parse_status])}</span>
            <p className="muted">{t('{bytes} 字节 · {date}', { bytes: file.size_bytes.toLocaleString(locale), date: new Date(file.uploaded_at).toLocaleString(locale) })}</p>
            <details className="file-upload-source"><summary>{t('上传记录')}</summary><p className="muted">{file.upload_batch ? t('上传批次：{date} · 本批登记 {count} 项 · 第 {position} 项', {
              date: new Date(file.upload_batch.created_at).toLocaleString(locale), count: file.upload_batch.item_count,
              position: file.upload_batch.item_position,
            }) : t('未记录上传批次')}</p></details>
            <p className="muted">{file.purposes?.length ? file.purposes.map(purpose => t(purposeLabels[purpose])).join(' · ') : t('未指定用途')}</p>
            {file.error && <p className="file-failed">{t(apiError(file.error, '文件解析失败，请重新上传有效的工作簿。'))}</p>}
            {previewState?.id === file.id && <p className="file-preview-status" role="status">{t(previewState.status === 'loading'
              ? '正在读取预览……' : previewState.status === 'ready' ? '当前预览' : '读取预览失败。')}</p>}
          </div><div className="file-actions">
            <button type="button" aria-label={t('文件详情 {name}', { name: file.filename })} onClick={() => openDetails(file.id)}>{t('文件详情')}</button>
            {file.parse_status === 'parsed' && <button type="button" disabled={busy} aria-label={t('预览 {name}', { name: file.filename })}
              onClick={() => { if (file.file_type === 'xlsx') onPreview(file.id); else if (['docx','pdf','png','jpeg'].includes(file.file_type)) openDetails(file.id, true) }}>{t('预览')}</button>}
            <ProjectDownloadLink href={`/api/v1/projects/${projectId}/files/${file.id}/download`} filename={file.filename}
              ariaLabel={t('下载 {name}', { name: file.filename })}>{t('下载原文件')}</ProjectDownloadLink>
          </div>
        </li>)}</ul>
      </>}
      {result && <nav className="file-pagination" aria-label={t('文件分页')}>
          <button type="button" disabled={loading || page === 1} onClick={() => setPage(value => value - 1)}>{t('上一页')}</button>
          <span role="status">{t('第 {page} / {pages} 页 · 共 {count} 个文件', { page, pages: Math.max(1, Math.ceil(result.total / 5)), count: result.total })}</span>
          <button type="button" disabled={loading || page >= Math.ceil(result.total / 5) || page >= 1_000_000} onClick={() => setPage(value => value + 1)}>{t('下一页')}</button>
        </nav>}
    </section>
    {visited.map(id => <div key={id} hidden={selected !== id}><FileDetails projectId={projectId} fileId={id}
      active={active && selected === id} initialTask={documentPreview === id ? 'document' : undefined} registerLeaveGuard={registerLeaveGuard} onUnavailable={onUnavailable} onUpdated={updated} /></div>)}
  </>
}
