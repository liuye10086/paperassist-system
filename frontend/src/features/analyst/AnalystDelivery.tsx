import { useEffect, useState, type ReactNode } from 'react'
import { useI18n } from '../../shared/i18n'
import { projectBase } from '../research-intake/api'
import type { Intake } from '../research-intake/contracts'
import type { DeliverySnapshot } from '../research-intake/deliveryPackageContracts'
import DeliveryPackagePanel from '../research-intake/DeliveryPackagePanel'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { useResearchRead } from '../research-results/api'
import useResearchDraft from '../research-results/useResearchDraft'
import { AnalystPublications, AnalystWorkspaceStatus } from './AnalystProgress'
import type { AnalystWorkspace } from './useAnalystWorkspace'
import './analystDelivery.css'

function PublishSnapshot({ projectId, assignmentRevision, snapshot, workspace }: {
  projectId: string; assignmentRevision: number; snapshot: DeliverySnapshot; workspace: AnalystWorkspace
}) {
  const { t, locale } = useI18n()
  const [title, setTitle] = useResearchDraft(projectId, `analyst-publish:${assignmentRevision}:${snapshot.id}`, () => '')
  const [submitted, setSubmitted] = useState(false)
  const publication = workspace.value?.publications.find(item => item.id === snapshot.id)
  // The publish response alone confirms the release; the refreshed list may still be loading or fail to load.
  const published = !!publication || workspace.published.includes(snapshot.id)
  useEffect(() => {
    if (published && title) setTitle('')
  }, [published, setTitle, title])
  if (published) return <div className="analyst-delivery-published">
    <p role="status">{t('此快照已发布给客户。')}</p>
    {publication && <p className="analyst-delivery-hint">{t('发布时间')} <time dateTime={publication.published_at}>{new Date(publication.published_at).toLocaleString(locale)}</time></p>}
  </div>
  if (!workspace.value) return null
  if (workspace.value.requirement?.id !== snapshot.requirement_version_id) return <p>{t('请关联客户最新提交的需求，重新确认交付内容后再发布。')}</p>
  return <form className="analyst-delivery-row analyst-delivery-publish" onSubmit={event => {
    event.preventDefault()
    if (!workspace.busy && title.trim()) {
      setSubmitted(true)
      workspace.publish(snapshot.id, title)
    }
  }}>
    <label>{t('交付标题')}<input value={title} required maxLength={200} disabled={workspace.busy} onChange={event => setTitle(event.target.value)}/></label>
    <button type="submit" className="button-primary" disabled={workspace.busy || !title.trim()}>{t('发布给客户')}</button>
    {submitted && workspace.busy && <p role="status">{t('正在发布给客户……')}</p>}
  </form>
}

export default function AnalystDelivery({ projectId, active, snapshotId, deliveryId, onSelect, registerLeaveGuard, workspace, onBackToResults, headerAction }: {
  projectId: string; active: boolean; deliveryId?: string; snapshotId?: string
  onSelect: (delivery: string, snapshot: string) => void; registerLeaveGuard?: RegisterLeaveGuard
  workspace?: AnalystWorkspace; onBackToResults: () => void; headerAction: ReactNode
}) {
  const { t } = useI18n()
  const intake = useResearchRead<Intake>(`${projectBase(projectId)}/research-intake`, active)
  const delivery = intake.data?.deliveries?.find(item => item.kind === 'analysis')
  // From the assignment itself, so a published snapshot stays confirmed even if the refreshed progress fails to load.
  const assignmentRevision = workspace?.assignmentRevision
  return <div hidden={!active} className="analyst-delivery">
    <header className="analyst-project-details-heading">
      <h1>{t('分析交付')}</h1>
      <div className="analyst-delivery-actions">
        <button type="button" className="button-quiet" onClick={onBackToResults}>{t('返回成果列表')}</button>
        {headerAction}
      </div>
    </header>
    {intake.error && <p role="alert">{t(intake.error)} <button type="button" onClick={intake.refresh}>{t('重新读取')}</button></p>}
    {!intake.error && !intake.data && <p role="status">{t('正在读取分析交付……')}</p>}
    {intake.data && !delivery && <p>{t('暂无分析交付登记。')}</p>}
    {delivery && <DeliveryPackagePanel projectId={projectId} deliveryId={delivery.id} analysisOnly
      active={active} snapshotId={deliveryId === delivery.id ? snapshotId : undefined} onSelect={snapshot => onSelect(delivery.id, snapshot)}
      requiredVersionId={workspace ? workspace.value?.requirement?.id ?? '' : undefined}
      registerLeaveGuard={registerLeaveGuard}
      publicationHistory={workspace && <>
        <AnalystWorkspaceStatus workspace={workspace} showRefresh={false}/>
        {workspace.value && <AnalystPublications publications={workspace.value.publications} headerAction={
          <button type="button" onClick={workspace.refresh} disabled={workspace.busy}>{t('刷新进度与反馈')}</button>
        }/>}
      </>}
      renderSnapshotActions={workspace && assignmentRevision !== undefined
        ? snapshot => <PublishSnapshot key={snapshot.id} projectId={projectId} assignmentRevision={assignmentRevision} snapshot={snapshot} workspace={workspace}/>
        : undefined}/>}
  </div>
}
