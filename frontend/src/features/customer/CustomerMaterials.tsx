import { useState, type Ref } from 'react'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { useI18n } from '../../shared/i18n'
import BioUpload from '../bioinformatics/BioUpload'
import BatchUpload from '../files/BatchUpload'
import { parseStatusLabels, type FilePage } from '../files/fileLibraryApi'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'

const uploadKinds = [['documents', '文档与图片'], ['bio', '测序数据与样本表']] as const
const pageSize = 5

export default function CustomerMaterials({ projectId, headingRef, onContinue, onUnavailable, registerLeaveGuard }: {
  projectId: string
  headingRef: Ref<HTMLHeadingElement>
  onContinue: () => void
  onUnavailable: () => void
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  const [kind, setKind] = useState<'documents' | 'bio'>('documents')
  const [page, setPage] = useState(1)
  const filesUrl = projectBase(projectId) + '/files'
  const files = useResearchRead<FilePage>(`${filesUrl}?page=${page}&page_size=${pageSize}`, true)
  const pages = Math.max(1, Math.ceil((files.data?.total ?? 0) / pageSize))
  const uploadProps = { projectId, embedded: true, customerView: true, registerLeaveGuard, onChanged: files.refresh }

  return <div className="customer-section customer-materials">
    <div className="customer-section-heading">
      <h1 ref={headingRef} tabIndex={-1}>{t('上传资料')}</h1>
      <button type="button" className="button-primary" onClick={onContinue}>{t('下一步 选择需求')}</button>
    </div>
    <div className="customer-materials-body" tabIndex={0} role="region" aria-label={t('上传资料')}>
      <div className="customer-switches" role="group" aria-label={t('资料类型')}>
        {uploadKinds.map(([value, label]) => <button type="button" key={value} aria-pressed={kind === value}
          className="button-quiet" onClick={() => setKind(value)}>{t(label)}</button>)}
      </div>
      <div hidden={kind !== 'documents'}>
        <BatchUpload {...uploadProps} active={kind === 'documents'} onUnavailable={onUnavailable} />
      </div>
      <div hidden={kind !== 'bio'}>
        <BioUpload {...uploadProps} active={kind === 'bio'} />
      </div>
      <div className="customer-section-heading customer-material-history">
        <h3>{t('已上传资料')}</h3>
        <button type="button" className="button-quiet" disabled={files.loading} onClick={files.refresh}>{t('刷新资料')}</button>
      </div>
      {files.error && <p role="alert" className="error-panel">{t(files.error)}</p>}
      {!files.data && !files.error && <p role="status">{t('正在读取文件列表……')}</p>}
      {files.data && !files.error && (files.data.items.length === 0
        ? <p>{t('此项目还没有文件。')}</p>
        : <ul className="customer-list" aria-label={t('已上传资料')}>
          {files.data.items.map(file => <li key={file.id}>
            <div><strong>{file.filename}</strong><p className="muted">
              {t(file.parse_status === 'stored' ? '已上传' : parseStatusLabels[file.parse_status])}
            </p></div>
            <ProjectDownloadLink href={`${filesUrl}/${encodeURIComponent(file.id)}/download`} filename={file.filename}
              ariaLabel={t('下载 {name}', { name: file.filename })}>{t('下载原文件')}</ProjectDownloadLink>
          </li>)}
        </ul>)}
    </div>
    {files.data && (page > 1 || pages > 1) && <nav className="customer-pagination" aria-label={t('文件分页')}>
      <button type="button" onClick={() => setPage(value => value - 1)} disabled={page <= 1 || files.loading}>{t('上一页')}</button>
      <span>{t('第 {page} / {pages} 页 · 共 {count} 个文件', { page, pages, count: files.data.total })}</span>
      <button type="button" onClick={() => setPage(value => value + 1)}
        disabled={page >= pages || files.loading}>{t('下一页')}</button>
    </nav>}
  </div>
}
