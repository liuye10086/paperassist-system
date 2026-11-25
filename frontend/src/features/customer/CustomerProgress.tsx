import type { Ref } from 'react'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { fileCountLabel, useI18n } from '../../shared/i18n'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'
import CustomerFeedback from './CustomerFeedback'
import { customerBase, latestSubmission, shortTime, type MaterialSubmission, type Progress } from './customerWorkspaceApi'

// Wireframe 03: empty, waiting for someone else, waiting for the customer, done.
const statuses: Record<Progress['status'], { label: string; detail: string }> = {
  draft: { label: '待提交需求', detail: '还没有提交需求。选择需要的分析并提交后，管理员会为你分配分析员。' },
  pending_assignment: { label: '待分配', detail: '需求已提交，等待分配分析员。你可以离开此页，稍后回到项目查看。' },
  assigned: { label: '已分配', detail: '项目已分配分析员，等待开始处理。' },
  analyzing: { label: '分析中', detail: '分析员正在处理项目。' },
  needs_materials: { label: '待补资料', detail: '请查看补充说明并上传所需资料。' },
  materials_submitted: { label: '已补交，等待核对', detail: '已补交资料，等待分析员核对。' },
  delivered: { label: '已交付', detail: '成果已发布，可以查看和下载。' },
}

export default function CustomerProgress({ projectId, headingRef, onRequirements, onUpload, onDeliveries, registerLeaveGuard }: {
  projectId: string
  headingRef: Ref<HTMLHeadingElement>
  onRequirements: () => void
  onUpload: () => void
  onDeliveries: () => void
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t, locale } = useI18n()
  const read = useResearchRead<Progress>(customerBase(projectId) + '/progress', true)
  const progress = read.data
  const state = progress && statuses[progress.status]
  const latest = latestSubmission(progress)
  const submissions = progress?.submissions ?? []
  return <div className="customer-section customer-progress">
    <div className="customer-section-heading">
      <h1 ref={headingRef} tabIndex={-1} className="visually-hidden">{t('任务进度')}</h1>
      <button type="button" className="button-quiet" disabled={read.loading} onClick={read.refresh}>{t('刷新进度')}</button>
    </div>
    {read.error && <p role="alert" className="error-panel">{t(read.error)}</p>}
    {!progress && !read.error && <p role="status">{t('正在读取任务进度……')}</p>}
    {progress && state && !read.error && <>
      <div className="customer-progress-state" data-status={progress.status}>
        <div className="customer-progress-status-row">
          <strong role="status" className="status-badge">{t(state.label)}</strong>
          {progress.status === 'draft' && <button type="button" className="button-primary" onClick={onRequirements}>{t('去选择需求')}</button>}
          {progress.status === 'needs_materials' && <button type="button" className="button-primary" onClick={onUpload}>{t('补交资料')}</button>}
          {progress.status === 'delivered' && <button type="button" className="button-primary" onClick={onDeliveries}>{t('查看已发布交付')}</button>}
        </div>
        {progress.status === 'needs_materials'
          ? <p className="customer-progress-note"><strong>{t('分析员需要你补充：')}</strong><span>{progress.note || t(state.detail)}</span></p>
          : progress.status === 'materials_submitted' && latest
            ? <p>{t('已补交 {files} · {date}，等待分析员核对', { files: fileCountLabel(latest.files.length), date: shortTime(latest.created_at, locale) })}</p>
            : <p>{t(state.detail)}</p>}
        {progress.note && progress.status !== 'needs_materials' && <p className="customer-progress-note">{progress.note}</p>}
        {progress.status === 'needs_materials' && progress.requirement_version != null
          ? <p className="muted">{t('需求第 {version} 版 · {date}', {
            version: progress.requirement_version, date: shortTime(progress.updated_at ?? progress.submitted_at, locale),
          })}</p>
          : progress.submitted_at && <p className="muted">
            {t('需求版本 {version} · 提交于 {date}', {
              version: progress.requirement_version ?? '—', date: new Date(progress.submitted_at).toLocaleString(locale),
            })}
          </p>}
        {progress.status !== 'needs_materials' && progress.updated_at && progress.updated_at !== progress.submitted_at && <p className="muted">
          {t('进度更新于 {date}', { date: new Date(progress.updated_at).toLocaleString(locale) })}
        </p>}
      </div>
      {submissions.length > 0 && <Submissions projectId={projectId} items={submissions} />}
      {progress.status !== 'draft' && <CustomerFeedback projectId={projectId} entries={progress.feedback} onSaved={read.refresh}
        registerLeaveGuard={registerLeaveGuard} />}
    </>}
  </div>
}

function Submissions({ projectId, items }: { projectId: string; items: MaterialSubmission[] }) {
  const { t, locale } = useI18n()
  const files = projectBase(projectId) + '/files'
  const ordered = [...items].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
  return <section className="customer-submissions" aria-label={t('补交记录')}>
    <h3>{t('补交记录')}</h3>
    <ul className="customer-list" aria-label={t('补交记录')}>
      {ordered.map(item => <li key={item.id}>
        <div>
          <strong>{shortTime(item.created_at, locale)} · {fileCountLabel(item.files.length)}</strong>
          {item.note && <p className="muted">{item.note}</p>}
          <div className="customer-submission-files">
            {item.files.map(file => <span key={file.id} className="sci-inline-controls">
              <span>{file.name}</span>
              <ProjectDownloadLink href={`${files}/${encodeURIComponent(file.id)}/download`} filename={file.name}
                ariaLabel={t('下载 {name}', { name: file.name })}>{t('下载')}</ProjectDownloadLink>
            </span>)}
          </div>
        </div>
      </li>)}
    </ul>
  </section>
}
