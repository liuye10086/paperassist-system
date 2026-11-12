import { useI18n } from '../../shared/i18n'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { useResearchRead } from '../research-results/api'
import CustomerFeedback from './CustomerFeedback'
import { customerBase, type Progress } from './customerWorkspaceApi'

const statuses: Record<Progress['status'], { label: string; detail: string }> = {
  draft: { label: '待提交需求', detail: '提交需求后，可以在这里查看处理进度。' },
  pending_assignment: { label: '待分配', detail: '需求已提交，等待分配分析员。' },
  assigned: { label: '已分配', detail: '项目已分配分析员，等待开始处理。' },
  analyzing: { label: '分析中', detail: '分析员正在处理项目。' },
  needs_materials: { label: '待补资料', detail: '请查看补充说明并上传所需资料。' },
  delivered: { label: '已交付', detail: '成果已发布，可以查看和下载。' },
}

export default function CustomerProgress({ projectId, onRequirements, onUpload, onDeliveries, registerLeaveGuard }: {
  projectId: string
  onRequirements: () => void
  onUpload: () => void
  onDeliveries: () => void
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t, locale } = useI18n()
  const read = useResearchRead<Progress>(customerBase(projectId) + '/progress', true)
  const progress = read.data
  const state = progress && statuses[progress.status]
  return <div className="customer-section">
    <div className="customer-section-heading">
      <h2>{t('任务进度')}</h2>
      <button type="button" className="button-quiet" disabled={read.loading} onClick={read.refresh}>{t('刷新进度')}</button>
    </div>
    {read.error && <p role="alert" className="error-panel">{t(read.error)}</p>}
    {!progress && !read.error && <p role="status">{t('正在读取任务进度……')}</p>}
    {progress && state && !read.error && <>
      <div className="customer-progress-state" data-status={progress.status}>
        <strong role="status" className="customer-status">{t(state.label)}</strong>
        <p>{t(state.detail)}</p>
        {progress.note && <p className="customer-progress-note">{progress.note}</p>}
        {progress.submitted_at && <p className="muted">
          {t('需求版本 {version} · 提交于 {date}', {
            version: progress.requirement_version ?? '—', date: new Date(progress.submitted_at).toLocaleString(locale),
          })}
        </p>}
        {progress.updated_at && progress.updated_at !== progress.submitted_at && <p className="muted">
          {t('进度更新于 {date}', { date: new Date(progress.updated_at).toLocaleString(locale) })}
        </p>}
        {progress.status === 'draft' && <button type="button" onClick={onRequirements}>{t('前往选择需求')}</button>}
        {progress.status === 'needs_materials' && <button type="button" className="button-primary" onClick={onUpload}>{t('补交资料')}</button>}
        {progress.status === 'delivered' && <button type="button" className="button-primary" onClick={onDeliveries}>{t('查看已发布交付')}</button>}
      </div>
      {progress.status !== 'draft' && <CustomerFeedback projectId={projectId} entries={progress.feedback} onSaved={read.refresh}
        registerLeaveGuard={registerLeaveGuard} />}
    </>}
  </div>
}
