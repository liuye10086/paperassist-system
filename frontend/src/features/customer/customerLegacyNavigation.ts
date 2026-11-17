import { parseNavigation, validId } from '../projects/projectNavigation'

type LegacyStep = 'details' | 'upload' | 'deliveries' | 'materials' | 'citations' | 'manuscripts' | 'word' | 'school' | 'journals' | 'reviews' | 'tasks'

export function readLegacyCustomerRoute(hash: string) {
  const legacy = parseNavigation(hash)
  if (!legacy || legacy.workspaceView !== 'project') return null
  const { projectId } = legacy

  function destination(step: LegacyStep, selectors: Record<string, string | number | undefined> = {}) {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(selectors)) {
      if (value) params.set(key, String(value))
    }
    return { projectId, step, params }
  }

  switch (legacy.section) {
    case 'overview':
      return legacy.overviewView === 'deliveries'
        ? destination('deliveries', { delivery: legacy.deliveryId, snapshot: legacy.deliverySnapshotId })
        : destination('details')
    case 'files':
      return legacy.resourceNavigation.view === 'list' ? destination('upload') : null
    case 'literature':
      return destination(legacy.literatureNavigation.view === 'citations' ? 'citations' : 'materials', {
        view: legacy.literatureNavigation.view, search: legacy.literatureSearchId, reference: legacy.literatureNavigation.referenceId,
      })
    case 'manuscripts':
      if (legacy.writingDeliveryId) return destination('deliveries', { delivery: legacy.writingDeliveryId })
      return destination(legacy.manuscriptView === 'exports' ? 'word' : 'manuscripts', {
        view: legacy.manuscriptView, manuscript: legacy.manuscriptLink.id, revision: legacy.manuscriptLink.revision,
      })
    case 'school-templates':
      return destination('school', { view: legacy.schoolTemplateNavigation.view, template: legacy.schoolTemplateNavigation.templateId })
    case 'journals':
      if (legacy.journalView === 'submission') return destination('reviews', { view: 'progress' })
      return destination('journals', { view: legacy.journalView, adaptation: legacy.adaptationId })
    case 'reviews':
      return destination('reviews', {
        view: legacy.reviewView, round: legacy.reviewLink.round, item: legacy.reviewItemId,
        reviewManuscript: legacy.reviewLink.manuscript, reviewRevision: legacy.reviewLink.revision,
        reviewRun: legacy.reviewLink.run, reviewDocument: legacy.reviewLink.document,
      })
    case 'tasks':
      return validId(legacy.taskId) ? destination('tasks', { view: legacy.taskDetailView, task: legacy.taskId }) : null
    default:
      return null
  }
}
