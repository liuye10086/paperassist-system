import { manuscriptViews, type ManuscriptView } from '../projects/manuscriptViews'
import { fixedRevision, validCustomerRouteId } from './customerReviewNavigation'

// Paragraph identifiers are section-scoped, e.g. `discussion:2`, so they may hold a colon or a dot.
function validParagraphId(value: string | null): value is string {
  return !!value && /^[A-Za-z0-9_:.-]{1,128}$/.test(value)
}

export type UpdatePaperRoute = (patch: Record<string, string | number | undefined>, confirmed?: boolean, replace?: boolean) => void

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
  // `adopted=1`: the Word page was opened by adopting this version, so it says so (B03).
  const adopted = !!manuscriptId && params.get('adopted') === '1'
  // Coming back from adding a source (B03 task 7): the writing request and paragraph to reopen.
  const writing = !!manuscriptId && view === 'writing'
  const request = params.get('writingRequest'), paragraph = params.get('paragraph')
  const writingRequest = writing && validCustomerRouteId(request) ? request : undefined
  const writingParagraph = writingRequest && validParagraphId(paragraph) ? paragraph : undefined
  // Coming back from adopting a school template (B04 task 8): the chapter to focus, or `id: null` for the chapter panel.
  const chapterId = params.get('chapter')
  const chapter = view !== 'materials' ? undefined : validParagraphId(chapterId) ? { id: chapterId }
    : !params.has('chapter') && params.get('focus') === 'chapters' ? { id: null } : undefined
  // Opened from the template change preview (B04 task 9): the confirmed template to preselect for the migration.
  const targetId = params.get('target')
  const target = manuscriptId && view === 'school' && validCustomerRouteId(targetId) ? targetId : undefined
  return { manuscriptId, revision: manuscriptId ? revision : undefined, view, invalid, adopted, writingRequest, paragraph: writingParagraph, chapter, target }
}
