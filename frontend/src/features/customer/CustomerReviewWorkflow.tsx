import { useCallback, type Ref } from 'react'
import { useI18n } from '../../shared/i18n'
import useResearchDraft from '../research-results/useResearchDraft'
import type { Project } from '../projects/projectTypes'
import type { ReviewView } from '../projects/reviewViews'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import ReviewsWorkspace, { type AnalysisPlace, type ManuscriptPlace, type ReviewRoundSelection } from '../reviews/ReviewsWorkspace'
import type { ManuscriptInput } from '../reviews/continuationTypes'
import CustomerAnalysisResults, { type AnalysisPick } from './CustomerAnalysisResults'
import CustomerLegacyTask from './CustomerLegacyTask'
import { readCustomerReviewNavigation, type CustomerReviewNavigation } from './customerReviewNavigation'
import type { ReturnTarget } from './returnToken'

type Props = {
  project: Project
  projectType: 'sci' | 'thesis'
  navigation: CustomerReviewNavigation
  onNavigate: (update: (current: CustomerReviewNavigation) => CustomerReviewNavigation,
    options?: { confirmed?: boolean; replace?: boolean }) => void
  registerLeaveGuard: RegisterLeaveGuard
  headingRef: Ref<HTMLHeadingElement>
  /** The return token of the current address, read by the workspace. */
  returnTarget: ReturnTarget | null
  onFollowReturn: (href: string) => void
  /** Opens the analysis results for one opinion with a token back to it (B05 task 5, wireframe 17). */
  onOpenAnalysisResults: (place: AnalysisPlace) => void
  /** Opens one fixed manuscript version on the customer manuscript page with a token back here (B05 task 7). */
  onOpenManuscript: (manuscript: ManuscriptInput, place: ManuscriptPlace) => void
}

export default function CustomerReviewWorkflow({
  project, projectType, navigation, onNavigate, registerLeaveGuard, headingRef, returnTarget, onFollowReturn, onOpenAnalysisResults,
  onOpenManuscript,
}: Props) {
  const { t } = useI18n()
  const { roundId, itemId, manuscriptId, revision, previousRoundId, returnId, runId, documentId, taskId, taskView, analysisResults } = navigation
  const [analysisPicks, setAnalysisPicks] = useResearchDraft<Record<string, AnalysisPick>>(project.id, 'analysis-picks:review-items', () => ({}))
  const analysisPick = roundId && itemId ? analysisPicks[roundId + '/' + itemId] : null
  function rememberAnalysisPick(pick: AnalysisPick) {
    if (!returnTarget) return
    const params = new URLSearchParams(returnTarget.href.slice(1))
    const origin = readCustomerReviewNavigation(params)
    if (params.get('step') === 'reviews' && origin?.view === 'supplements' && origin.roundId && origin.itemId) {
      const key = origin.roundId + '/' + origin.itemId
      setAnalysisPicks(current => ({ ...current, [key]: pick }))
    }
  }
  const covered = !!taskId || !!analysisResults
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

  // The returned Word page links to other rounds inside the customer address, so the return token is kept (B04 task 13).
  const openRound = useCallback((roundId: string) => onNavigate(() => ({ view: 'items', roundId })), [onNavigate])

  return <>
    <div hidden={covered}>
      <section className="customer-section customer-manuscript-workflow customer-review-workflow">
        <div className="customer-section-heading">
          <h1 ref={covered ? undefined : headingRef} tabIndex={-1}>{t('意见与返修')}</h1>
        </div>
        <ReviewsWorkspace customer
          projectId={project.id} projectType={projectType} active={!covered} view={view}
          roundId={roundId ?? ''} selectedItemId={itemId ?? ''} initialManuscript={manuscriptId}
          initialRevision={revision} initialPreviousRound={previousRoundId} initialReturn={returnId}
          initialRun={runId ?? ''} initialDocument={documentId ?? ''}
          onViewChange={selectView} onSelectRound={selectRound} onSelectItem={selectItem}
          onSelectRun={selectRun} onSelectDocument={selectDocument} registerLeaveGuard={registerLeaveGuard}
          onOpenAnalysisResults={onOpenAnalysisResults} analysisPick={analysisPick} onOpenRound={openRound} onOpenManuscript={onOpenManuscript}
          onOpenTask={taskId => onNavigate(current => ({ ...current, taskId }))} />
      </section>
    </div>
    {analysisResults && !taskId && <CustomerAnalysisResults paperProjectId={project.id} purpose="reviews"
      returnTarget={returnTarget} onReturn={onFollowReturn} headingRef={headingRef}
      selected={navigation.analysisProject && navigation.analysisSnapshot
        ? { projectId: navigation.analysisProject, snapshotId: navigation.analysisSnapshot } : null}
      onSelect={selection => onNavigate(current => ({
        ...current, analysisProject: selection?.projectId, analysisSnapshot: selection?.snapshotId,
      }))}
      onPick={rememberAnalysisPick} />}
    {taskId && <CustomerLegacyTask project={project} taskId={taskId} taskView={taskView}
      headingRef={headingRef} registerLeaveGuard={registerLeaveGuard}
      onTaskViewChange={taskView => onNavigate(current => ({ ...current, taskView }))}
      returnToReviews={() => onNavigate(current => ({ ...current, taskId: undefined, taskView: undefined }))} />}
  </>
}
