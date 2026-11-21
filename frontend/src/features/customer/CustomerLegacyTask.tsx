import type { Ref } from 'react'
import { useI18n } from '../../shared/i18n'
import type { Project } from '../projects/projectTypes'
import type { TaskDetailView } from '../projects/reviewViews'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import TaskDetail from '../tasks/TaskDetail'
import ReturnBar from './ReturnBar'
import type { ReturnTarget } from './returnToken'

type Props = {
  project: Project
  taskId: string
  taskView?: TaskDetailView
  onTaskViewChange?: (view: TaskDetailView) => void
  /** Inside the review page: the only way back is to the review. */
  returnToReviews?: () => void
  /** On its own page (B05 task 9): a return token leads back, otherwise “返回项目资料”. */
  returnTarget?: ReturnTarget | null
  onFollowReturn?: (href: string) => void
  onBack?: () => void
  /** Opens the project files: uploads for an analysis project, writing materials for a paper project. */
  onOpenFiles?: () => void
  registerLeaveGuard: RegisterLeaveGuard
  headingRef: Ref<HTMLHeadingElement>
}

// One customer view for every project type (B01 inventory, sections 2 and 5). The task details are embedded, so this
// page owns the only heading and its focus; the allowed continue, retry and cancel actions stay as the server sends them.
export default function CustomerLegacyTask({
  project, taskId, taskView, onTaskViewChange, returnToReviews, returnTarget = null, onFollowReturn, onBack, onOpenFiles,
  registerLeaveGuard, headingRef,
}: Props) {
  const { t } = useI18n()
  const view = taskView === 'usage' ? 'overview' : taskView ?? 'overview'
  return <section className="customer-section">
    {!returnToReviews && <ReturnBar target={returnTarget} onReturn={onFollowReturn}>
      {t('正在查看“{place}”相关的任务', { place: returnTarget?.label ?? '' })}
    </ReturnBar>}
    <div className="customer-section-heading">
      <h1 ref={headingRef} tabIndex={-1}>{t('任务详情')}</h1>
      {returnToReviews
        ? <button type="button" className="button-quiet" onClick={returnToReviews}>{t('返回返修')}</button>
        : !returnTarget && onBack && <button type="button" className="button-quiet" onClick={onBack}>{t('返回项目资料')}</button>}
    </div>
    <TaskDetail projectId={project.id} taskId={taskId} view={view} onViewChange={onTaskViewChange} customerView embedded
      onOpenFiles={returnToReviews ? undefined : onOpenFiles}
      registerLeaveGuard={registerLeaveGuard} allowUsage={false} onChanged={() => {}} />
  </section>
}
