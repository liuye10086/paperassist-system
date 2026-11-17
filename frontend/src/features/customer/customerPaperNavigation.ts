import { manuscriptViews, type ManuscriptView } from '../projects/manuscriptViews'
import { fixedRevision, validCustomerRouteId } from './customerReviewNavigation'

export type UpdatePaperRoute = (patch: Record<string, string | number | undefined>, confirmed?: boolean) => void

export function customerManuscriptNavigation(params: URLSearchParams, wordOnly: boolean, thesis = false) {
  const id = params.get('manuscript')
  const revision = fixedRevision(params.get('revision'))
  const invalid = (params.has('manuscript') || params.has('revision')) && (!validCustomerRouteId(id) || !revision)
  const manuscriptId = !invalid && id && revision ? id : undefined
  const requested = manuscriptViews.find(view => view === params.get('view'))
  const fallback: ManuscriptView = manuscriptId ? (wordOnly ? 'exports' : 'body') : 'list'
  const allowedViews: ManuscriptView[] = wordOnly ? ['list', 'exports'] :
    ['list', 'materials', 'body', 'evidence', 'versions', 'writing', 'exports']
  if (thesis && !wordOnly) allowedViews.push('school')
  const view = !invalid && requested && allowedViews.includes(requested) ? requested : fallback
  return { manuscriptId, revision: manuscriptId ? revision : undefined, view, invalid }
}
