import { useEffect, useRef, useState } from 'react'
import { apiFetch } from '../../shared/api/client'
import { apiError, useI18n } from '../../shared/i18n'
import ExcelPreview from '../files/ExcelPreview'
import type { SavedPreviewState } from '../files/ExcelPreview'
import AnalysisSetup from '../analysis/AnalysisSetup'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import type { ProjectSection } from './WorkspaceShell'

type ProjectFile = {
  id: string; filename: string; size_bytes: number; uploaded_at: string
  parse_status: 'parsed' | 'failed'; error: { code: string; message: string } | null
}

async function responseData(response: Response, fallback: string) {
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new Error(apiError(data, fallback))
  return data
}

export default function ProjectResources({ projectId, onSaved, section, onSectionChange }: { projectId: string; onSaved: () => void; section: ProjectSection; onSectionChange: (section: ProjectSection) => void }) {
  const { t, locale } = useI18n()
  const [files, setFiles] = useState<ProjectFile[]>([])
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [opened, setOpened] = useState<{ id: string; request: number } | null>(null)
  const [previewState, setPreviewState] = useState<SavedPreviewState | null>(null)
  const openSequence = useRef(0)

  function refresh() {
    setLoading(true)
    setError('')
    setAttempt(value => value + 1)
  }

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timeout = window.setTimeout(() => controller.abort(), 15_000)
    async function load() {
      try {
        const response = await apiFetch(`/api/v1/projects/${projectId}/files`, { signal: controller.signal })
        const result = await responseData(response, '文件列表读取失败。')
        if (!Array.isArray(result)) throw new Error('文件列表格式不正确。')
        if (active) setFiles(result)
      } catch {
        if (active) setError('文件列表读取失败，请确认后端服务正常后重试。')
      } finally {
        window.clearTimeout(timeout)
        if (active) setLoading(false)
      }
    }
    void load()
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [projectId, attempt])

  function uploaded() {
    setOpened(null)
    setPreviewState(null)
    refresh()
    onSaved()
  }

  return <>
    <div hidden={section !== 'files'} className="project-files-page">
    <section className="file-history" aria-labelledby="files-title">
      <div className="preview-heading">
        <div><span className="workspace-eyebrow">{t("研究资料")}</span><h2 id="files-title">{t("项目文件")}</h2><p className="muted">{t("上传数据，查看工作表，保留研究的原始资料。")}</p></div>
        <button type="button" disabled={loading || busy} onClick={refresh}>{t("刷新文件列表")}</button>
      </div>
      {loading && <p role="status">{t("正在读取文件列表……")}</p>}
      {error && <p className="error-panel" role="alert">{t(error)}</p>}
      {!loading && !error && files.length === 0 && <p>{t("此项目还没有文件。")}</p>}
      <ul className="file-list">{files.map(file => <li key={file.id}
        aria-current={previewState?.id === file.id && previewState.status === 'ready' ? 'true' : undefined}>
        <div className="file-summary">
          <strong>{file.filename}</strong>
          <span className={file.parse_status === 'failed' ? 'file-failed' : 'file-parsed'}>
            {file.parse_status === 'failed' ? t("解析失败") : t("可预览")}
          </span>
          <p className="muted">{t('{bytes} 字节 · {date}', { bytes: file.size_bytes.toLocaleString(locale), date: new Date(file.uploaded_at).toLocaleString(locale) })}</p>
          {file.error && <p className="file-failed">{t(apiError(file.error, '文件解析失败，请重新上传有效的工作簿。'))}</p>}
          {previewState?.id === file.id && <p className="file-preview-status" role="status">
            {previewState.status === 'loading' ? t('正在读取预览……')
              : previewState.status === 'ready' ? t('当前预览') : t('读取预览失败。')}
          </p>}
        </div>
        <div className="file-actions">
          {file.parse_status === 'parsed' && <button type="button" disabled={busy}
            aria-label={t('预览 {name}', { name: file.filename })} onClick={() => {
              setPreviewState({ id: file.id, status: 'loading' })
              setOpened({ id: file.id, request: ++openSequence.current })
            }}>{t("预览")}</button>}
          <ProjectDownloadLink href={`/api/v1/projects/${projectId}/files/${file.id}/download`} filename={file.filename} ariaLabel={t('下载 {name}', { name: file.filename })}>{t("下载原文件")}</ProjectDownloadLink>
        </div>
      </li>)}</ul>
    </section>
    <ExcelPreview projectId={projectId} savedFile={opened} onSaved={uploaded} onBusyChange={setBusy} onSavedPreviewChange={setPreviewState} />
    </div>
    <div hidden={section !== 'analysis'} className="project-analysis-page">
      <AnalysisSetup projectId={projectId} files={files} filesLoading={loading} filesError={error} onReloadFiles={refresh}
        onOpenFiles={() => onSectionChange('files')} />
    </div>
  </>
}
