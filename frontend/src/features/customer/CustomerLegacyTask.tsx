import type { Ref } from 'react'
import { useI18n } from '../../shared/i18n'
import type { Project } from '../projects/projectTypes'
import type { TaskDetailView } from '../projects/reviewViews'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import TaskDetail from '../tasks/TaskDetail'

type Props = {
  project: Project
  taskId: string
  taskView?: TaskDetailView
  onTaskViewChange?: (view: TaskDetailView) => void
  returnToReviews?: () => void
  registerLeaveGuard: RegisterLeaveGuard
  headingRef: Ref<HTMLHeadingElement>
}

export default function CustomerLegacyTask({ project, taskId, taskView, onTaskViewChange, returnToReviews, registerLeaveGuard, headingRef }: Props) {
  const { t } = useI18n()
  const view = taskView === 'usage' ? 'overview' : taskView ?? 'overview'
  return <section className="customer-section">
    <div className="customer-section-heading">
      <h1 ref={headingRef} tabIndex={-1}>{t('任务详情')}</h1>
      {returnToReviews && <button type="button" className="button-quiet" onClick={returnToReviews}>{t('返回返修')}</button>}
    </div>
    <TaskDetail projectId={project.id} taskId={taskId} view={view} onViewChange={onTaskViewChange}
      customerView={project.project_type === 'sci' || project.project_type === 'thesis'}
      registerLeaveGuard={registerLeaveGuard} allowUsage={false} onChanged={() => {}} />
  </section>
}
