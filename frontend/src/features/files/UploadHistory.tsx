import { useId, type ReactNode } from 'react'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { apiError, useI18n } from '../../shared/i18n'
import { uploadStatusLabels, type BatchItem } from './batchUploadApi'
import type { ProjectFile } from './fileLibraryApi'
import './batchUpload.css'

type FileDescription = { nature: string; actions?: ReactNode; details?: ReactNode }

export type MaterialHistory = {
  otherFiles: ProjectFile[]
  ready: boolean
  status: ReactNode
  pagination: ReactNode
  editing: boolean
  refresh: () => void
  describe: (id: string | null, filename: string, fileType: string) => FileDescription
}

export function UploadFileRow({ projectId, filename, fileId, status, statusLabel, material, error, retry }: {
  projectId: string; filename: string; fileId: string | null; status: BatchItem['status']; statusLabel?: string
  material?: FileDescription; error?: string; retry?: ReactNode
}) {
  const { t } = useI18n()
  return <li className="upload-batch-file">
    <strong className="upload-batch-file-name">{filename}</strong>
    {material && <span className="upload-batch-file-nature">{material.nature}</span>}
    <span className="upload-batch-file-state" data-status={status}>
      {!material && ' · '}{t(statusLabel || uploadStatusLabels[status])}
    </span>
    {error && <p className="upload-batch-file-error">{t(error)}</p>}
    {fileId && <span className="upload-batch-file-download">
      {material?.actions}
      <ProjectDownloadLink href={`/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}/download`}
        filename={filename} ariaLabel={t('下载 {name}', { name: filename })}>{t('下载原文件')}</ProjectDownloadLink>
    </span>}
    {material?.details && <div className="upload-batch-file-details">{material.details}</div>}
    {retry && <div className="upload-batch-file-retry">{retry}</div>}
  </li>
}

export function UploadBatchCard({ title, showColumns, actions, listLabel, children }: {
  title: string; showColumns?: boolean; actions?: ReactNode; listLabel?: string; children: ReactNode
}) {
  const { t } = useI18n()
  const headingId = useId()
  return <article className="upload-batch-card" aria-labelledby={headingId}>
    <header className="upload-batch-heading"><h4 id={headingId}>{title}</h4>{actions}</header>
    <div className="upload-batch-content">
      {showColumns && <div className="upload-batch-columns" aria-hidden="true">
        <span>{t('文件名')}</span><span>{t('文件性质')}</span><span>{t('解析状态')}</span><span>{t('操作')}</span>
      </div>}
      <ul className="upload-batch-files" aria-label={listLabel}>{children}</ul>
    </div>
  </article>
}

export function UploadHistory({ projectId, history, emptyBatches, batchPagination, onRefresh, children }: {
  projectId: string; history: MaterialHistory; emptyBatches: boolean; batchPagination: ReactNode
  onRefresh: () => void; children: ReactNode
}) {
  const { t } = useI18n()
  const title = t('已上传资料')
  return <section className="upload-batch-history material-upload-history" aria-label={title}>
    <div className="upload-batch-history-heading">
      <h3 className="upload-batches-title">{title}</h3>
      <button type="button" className="button-quiet" disabled={history.editing} onClick={() => {
        onRefresh()
        history.refresh()
      }}>{t('刷新资料')}</button>
    </div>
    {children}
    {batchPagination}
    {history.status}
    {history.ready && emptyBatches && history.otherFiles.length === 0 && <p>{t('此项目还没有文件。')}</p>}
    {history.otherFiles.length > 0 && <UploadBatchCard title={t('其他上传资料')} showColumns listLabel={title}>
      {history.otherFiles.map(file => <UploadFileRow key={file.id} projectId={projectId} filename={file.filename} fileId={file.id}
        status={file.parse_status} material={history.describe(file.id, file.filename, file.file_type)}
        error={file.error ? apiError(file.error, '文件处理失败，请重试。') : undefined} />)}
    </UploadBatchCard>}
    {history.pagination}
  </section>
}
