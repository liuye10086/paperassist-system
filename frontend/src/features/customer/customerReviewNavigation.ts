import { isReviewItemId, reviewViews, taskDetailViews, type ReviewView, type TaskDetailView } from '../projects/reviewViews'
import { isTaskId } from '../tasks/taskTypes'

export type CustomerReviewNavigation = {
  view: ReviewView
  roundId?: string
  itemId?: string
  manuscriptId?: string
  revision?: number
  previousRoundId?: string
  returnId?: string
  runId?: string
  documentId?: string
  taskId?: string
  taskView?: TaskDetailView
  /** `view=analysis-results` (B05 task 5): the review page stays mounted underneath and keeps `view` for it. */
  analysisResults?: boolean
  analysisProject?: string
  analysisSnapshot?: string
}

export function validCustomerRouteId(value: string | null): value is string {
  return !!value && /^[A-Za-z0-9_-]{1,64}$/.test(value)
}

export function fixedRevision(value: string | null) {
  if (!value || !/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value))) return undefined
  return Number(value)
}

export function readCustomerReviewNavigation(params: URLSearchParams): CustomerReviewNavigation | null {
  const ids = ['round', 'reviewManuscript', 'reviewPreviousRound', 'reviewReturn', 'reviewRun', 'reviewDocument', 'analysisProject', 'analysisSnapshot']
  if (ids.some(key => params.has(key) && !validCustomerRouteId(params.get(key)))) return null
  const roundId = params.get('round') ?? undefined
  const itemId = params.get('item') ?? undefined
  const manuscriptId = params.get('reviewManuscript') ?? undefined
  const revision = fixedRevision(params.get('reviewRevision'))
  const previousRoundId = params.get('reviewPreviousRound') ?? undefined
  const returnId = params.get('reviewReturn') ?? undefined
  const runId = params.get('reviewRun') ?? undefined
  const documentId = params.get('reviewDocument') ?? undefined
  const taskId = params.get('reviewTask') ?? undefined
  const taskView = taskDetailViews.find(view => view === params.get('taskView'))
  const analysisResults = params.get('view') === 'analysis-results'
  const analysisProject = params.get('analysisProject') ?? undefined
  const analysisSnapshot = params.get('analysisSnapshot') ?? undefined
  if ((itemId !== undefined && (!roundId || !isReviewItemId(itemId))) || (!roundId && runId) || (documentId && !runId) ||
      (!!manuscriptId !== !!revision) || (params.has('reviewRevision') && !revision) ||
      (roundId && manuscriptId) || (previousRoundId && !manuscriptId) || (returnId && !previousRoundId) ||
      (params.has('reviewTask') && !isTaskId(taskId)) || (params.has('taskView') && (!taskId || !taskView)) ||
      (!!analysisProject !== !!analysisSnapshot) || (!!analysisProject && !analysisResults)) return null
  const fallback = documentId ? 'documents' : runId ? 'revision' : roundId ? 'items' : manuscriptId ? 'create' : 'list'
  const requested = reviewViews.find(view => view === params.get('view'))
  const available = roundId ? requested !== 'create' : requested === 'list' || requested === 'create' || requested === 'progress'
  const view = requested && available ? requested : fallback
  const analysis = analysisResults ? { analysisResults, analysisProject, analysisSnapshot } : {}
  return { view, roundId, itemId, manuscriptId, revision, previousRoundId, returnId, runId, documentId, taskId, taskView, ...analysis }
}

export function customerReviewParams(route: CustomerReviewNavigation) {
  const params = new URLSearchParams({ view: route.analysisResults ? 'analysis-results' : route.view })
  const analysis = route.analysisResults ? { analysisProject: route.analysisProject, analysisSnapshot: route.analysisSnapshot } : {}
  const entries = {
    round: route.roundId, item: route.itemId, reviewManuscript: route.manuscriptId, reviewRevision: route.revision,
    reviewPreviousRound: route.previousRoundId, reviewReturn: route.returnId, reviewRun: route.runId,
    reviewDocument: route.documentId, reviewTask: route.taskId, taskView: route.taskView, ...analysis,
  }
  for (const [key, value] of Object.entries(entries)) if (value) params.set(key, String(value))
  return params
}
