import { useState } from 'react'
import { useI18n } from '../../shared/i18n'
import { projectBase } from '../research-intake/api'
import type { Intake } from '../research-intake/contracts'
import type { DeliverySnapshot } from '../research-intake/deliveryPackageContracts'
import DeliveryPackagePanel from '../research-intake/DeliveryPackagePanel'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { useResearchRead } from '../research-results/api'
import { AnalystPublications, AnalystWorkspaceStatus } from './AnalystProgress'
import type { AnalystWorkspace } from './useAnalystWorkspace'

function PublishSnapshot({ snapshot, workspace }: { snapshot: DeliverySnapshot; workspace: AnalystWorkspace }) {
  const { t } = useI18n()
  const [title, setTitle] = useState('')
  if (!workspace.value) return null
  if (workspace.value.publications.some(item => item.id === snapshot.id)) return <p>{t('此快照已发布给客户。')}</p>
  if (workspace.value.requirement?.id !== snapshot.requirement_version_id) return <p>{t('请使用最新提交的需求版本冻结快照后再发布。')}</p>
  return <form className="analyst-form" onSubmit={event => {
    event.preventDefault()
    if (!workspace.busy && title.trim()) workspace.publish(snapshot.id, title)
  }}>
    <label>{t('交付标题')}<input value={title} required maxLength={200} disabled={workspace.busy} onChange={event => setTitle(event.target.value)}/></label>
    <button type="submit" className="button-primary" disabled={workspace.busy || !title.trim()}>{t('发布给客户')}</button>
  </form>
}

export default function AnalystDelivery({ projectId, active, snapshotId, deliveryId, onSelect, registerLeaveGuard, workspace }: {
  projectId: string; active: boolean; deliveryId?: string; snapshotId?: string
  onSelect: (delivery: string, snapshot: string) => void; registerLeaveGuard?: RegisterLeaveGuard
  workspace?: AnalystWorkspace
}) {
  const { t } = useI18n()
  const intake = useResearchRead<Intake>(`${projectBase(projectId)}/research-intake`, active)
  const delivery = intake.data?.deliveries?.find(item => item.kind === 'analysis')
  return <section hidden={!active} className="research-intake analyst-card" aria-label={t('分析交付')}>
    <header className="analyst-card-heading"><h2>{t('分析交付')}</h2>
      {workspace && <AnalystWorkspaceStatus workspace={workspace}/>}
    </header>
    {intake.error && <p role="alert">{t(intake.error)} <button type="button" onClick={intake.refresh}>{t('重新读取')}</button></p>}
    {!intake.error && !intake.data && <p role="status">{t('正在读取分析交付……')}</p>}
    {intake.data && !delivery && <p>{t('暂无分析交付登记。')}</p>}
    {delivery && <DeliveryPackagePanel projectId={projectId} deliveryId={delivery.id} analysisOnly
      active={active} snapshotId={deliveryId === delivery.id ? snapshotId : undefined} onSelect={snapshot => onSelect(delivery.id, snapshot)}
      requiredVersionId={workspace ? workspace.value?.requirement?.id ?? '' : undefined}
      registerLeaveGuard={registerLeaveGuard}
      renderSnapshotActions={workspace && (snapshot => <PublishSnapshot key={snapshot.id} snapshot={snapshot} workspace={workspace}/>)}/>}
    {workspace?.value && <AnalystPublications publications={workspace.value.publications}/>}
  </section>
}
