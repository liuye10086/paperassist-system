import { useCallback, type Ref } from 'react'
import { useI18n } from '../../shared/i18n'
import type { Project } from '../projects/projectTypes'
import type { ReviewView } from '../projects/reviewViews'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import ReviewsWorkspace, { type ReviewRoundSelection } from '../reviews/ReviewsWorkspace'
import CustomerLegacyTask from './CustomerLegacyTask'
import type { CustomerReviewNavigation } from './customerReviewNavigation'

type Props = {
  project: Project
  projectType: 'sci' | 'thesis'
  navigation: CustomerReviewNavigation
  onNavigate: (update: (current: CustomerReviewNavigation) => CustomerReviewNavigation,
    options?: { confirmed?: boolean; replace?: boolean }) => void
  registerLeaveGuard: RegisterLeaveGuard
  headingRef: Ref<HTMLHeadingElement>
  onOpenAnalysisDeliveries: () => void
}

export default function CustomerReviewWorkflow({
  project, projectType, navigation, onNavigate, registerLeaveGuard, headingRef, onOpenAnalysisDeliveries,
}: Props) {
  const { t } = useI18n()
  const { roundId, itemId, manuscriptId, revision, previousRoundId, returnId, runId, documentId, taskId, taskView } = navigation
  const view = navigation.view === 'response' && projectType === 'thesis' ? 'documents' : navigation.view

  const selectView = useCallback((view: ReviewView) => onNavigate(current => {
    if (view === 'list') return { view }
    return { ...current, view, documentId: view === 'comparison' || view === 'response' ? undefined : current.documentId }
  }), [onNavigate])

  const selectRound = useCallback((roundId: string, selection?: ReviewRoundSelection) => {
    const continuation = selection?.continuation
    onNavigate(() => roundId ? { view: 'items', roundId } : {
      view: 'create',
      manuscriptId: continuation?.manuscript.id,
      revision: continuation?.manuscript.revision,
      previousRoundId: continuation?.previous_round_id,
      returnId: continuation?.user_return_id,
    }, { confirmed: selection?.created })
  }, [onNavigate])

  const selectItem = useCallback((itemId: string, view?: ReviewView) => {
    onNavigate(current => ({ ...current, itemId, view: view ?? current.view }))
  }, [onNavigate])

  const selectRun = useCallback((runId: string, automatic = false) => {
    onNavigate(current => ({ ...current, runId, documentId: undefined }), { confirmed: automatic, replace: automatic })
  }, [onNavigate])

  const selectDocument = useCallback((documentId: string, automatic = false) => {
    onNavigate(current => ({ ...current, documentId }), { confirmed: automatic, replace: automatic })
  }, [onNavigate])

  return <>
    <div hidden={!!taskId}>
      <section className="customer-section customer-manuscript-workflow customer-review-workflow">
        <div className="customer-section-heading">
          <h1 ref={taskId ? undefined : headingRef} tabIndex={-1}>{t('意见与返修')}</h1>
        </div>
        <ReviewsWorkspace
          projectId={project.id} projectType={projectType} active={!taskId} view={view}
          roundId={roundId ?? ''} selectedItemId={itemId ?? ''} initialManuscript={manuscriptId}
          initialRevision={revision} initialPreviousRound={previousRoundId} initialReturn={returnId}
          initialRun={runId ?? ''} initialDocument={documentId ?? ''}
          onViewChange={selectView} onSelectRound={selectRound} onSelectItem={selectItem}
          onSelectRun={selectRun} onSelectDocument={selectDocument} registerLeaveGuard={registerLeaveGuard}
          onOpenAnalysisDeliveries={onOpenAnalysisDeliveries}
          onOpenTask={taskId => onNavigate(current => ({ ...current, taskId }))} />
      </section>
    </div>
    {taskId && <CustomerLegacyTask project={project} taskId={taskId} taskView={taskView}
      headingRef={headingRef} registerLeaveGuard={registerLeaveGuard}
      onTaskViewChange={taskView => onNavigate(current => ({ ...current, taskView }))}
      returnToReviews={() => onNavigate(current => ({ ...current, taskId: undefined, taskView: undefined }))} />}
  </>
}
