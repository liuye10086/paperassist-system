import { useLayoutEffect, useRef, useState } from 'react'
import { useI18n } from '../../shared/i18n'
import useResearchDraft from '../research-results/useResearchDraft'
import ProjectLiterature from '../literature/ProjectLiterature'
import type { LiteratureView } from '../projects/literatureViews'
import type { Project } from '../projects/projectTypes'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import CustomerAnalysisResults, { type AnalysisPick } from './CustomerAnalysisResults'
import CustomerMaterials from './CustomerMaterials'
import type { UpdatePaperRoute } from './customerPaperNavigation'
import { validCustomerRouteId } from './customerReviewNavigation'
import type { ReturnTarget } from './returnToken'

const literatureViews: LiteratureView[] = ['list', 'search', 'history', 'detail', 'evidence', 'citations']

type Props = {
  project: Project
  startWithCitations: boolean
  projectKeywords?: readonly string[]
  literatureReady?: boolean
  onContinue: () => void
  onRequirements: () => void
  onUnavailable: () => void
  registerLeaveGuard: RegisterLeaveGuard
  params: URLSearchParams
  onUpdateRoute: UpdatePaperRoute
  /** Set while a paragraph waits for a source (B03 task 7). */
  onReferenceReady?: (referenceId: string) => void
  onUploaded?: () => void
  /** Opens the analysis results with a token back to the project files (B05 task 6, wireframe 18). */
  onOpenAnalysisResults?: () => void
  /** Set when the address carries a `materials` return token. */
  materialsReturn?: ReturnTarget | null
  onFollowReturn?: (href: string) => void
}

export default function CustomerWritingMaterials({
  project, startWithCitations, projectKeywords, literatureReady = true, onContinue, onRequirements, onUnavailable, registerLeaveGuard,
  params, onUpdateRoute, onReferenceReady, onUploaded, onOpenAnalysisResults, materialsReturn = null, onFollowReturn,
}: Props) {
  const { t } = useI18n()
  const routeView = params.get('view')
  const literatureView = literatureViews.find(view => view === routeView)
  // A third view (D3): the files and literature stay mounted underneath, so chosen files and drafts are kept.
  const analysisResults = routeView === 'analysis-results'
  const showUpload = !analysisResults && (routeView === 'files' || (!startWithCitations && !literatureView))
  const showLiterature = !analysisResults && !showUpload
  const analysisProject = params.get('analysisProject')
  const analysisSnapshot = params.get('analysisSnapshot')
  // Downloaded results, newest first; this browser tab only (closing it drops the prefilled source).
  const [picks, setPicks] = useResearchDraft<AnalysisPick[]>(project.id, 'analysis-pick:materials', () => [])
  // A paragraph that waits for a source already carries a token; tokens are never nested.
  const canPick = !!onOpenAnalysisResults && !analysisResults && params.get('returnLabel') !== 'paragraph'
  const search = params.get('search')
  const reference = params.get('reference')
  const searchId = validCustomerRouteId(search) ? search : ''
  const referenceId = validCustomerRouteId(reference) ? reference : ''
  const [openUpload, setOpenUpload] = useState(showUpload)
  const [openLiterature, setOpenLiterature] = useState(showLiterature)
  if (showUpload && !openUpload) setOpenUpload(true)
  if (showLiterature && !openLiterature) setOpenLiterature(true)
  const leaveResults = { analysisProject: undefined, analysisSnapshot: undefined }
  // The results heading took focus and is now unmounted; bring focus back to the materials instead of the page body.
  const pickButton = useRef<HTMLButtonElement>(null)
  const filesSwitch = useRef<HTMLButtonElement>(null)
  const wasAnalysisResults = useRef(analysisResults)
  useLayoutEffect(() => {
    const left = wasAnalysisResults.current && !analysisResults
    wasAnalysisResults.current = analysisResults
    if (left) (pickButton.current ?? filesSwitch.current)?.focus({ preventScroll: true })
  }, [analysisResults])
  return <>
    <div className="sci-inline-controls">
      <div className="customer-switches" role="group" aria-label={t('写作资料视图')}>
        <button ref={filesSwitch} type="button" className="button-quiet" aria-pressed={showUpload}
          onClick={() => onUpdateRoute({ view: 'files', ...leaveResults })}>{t('项目文件')}</button>
        <button type="button" className="button-quiet" aria-pressed={showLiterature}
          onClick={() => onUpdateRoute({ view: literatureView ?? 'list', ...leaveResults })}>{t('文献与引用')}</button>
      </div>
      {canPick && <button ref={pickButton} type="button" className="button-quiet" onClick={onOpenAnalysisResults}>{t('从我的分析项目取用成果')}</button>}
    </div>
    {analysisResults && <CustomerAnalysisResults paperProjectId={project.id} purpose="materials"
      returnTarget={materialsReturn} onReturn={href => onFollowReturn?.(href)}
      selected={validCustomerRouteId(analysisProject) && validCustomerRouteId(analysisSnapshot)
        ? { projectId: analysisProject, snapshotId: analysisSnapshot } : null}
      onSelect={selection => onUpdateRoute({ analysisProject: selection?.projectId, analysisSnapshot: selection?.snapshotId })}
      onPick={pick => setPicks(old => [pick, ...old.filter(item =>
        item.researchProjectName !== pick.researchProjectName || item.deliveryTitle !== pick.deliveryTitle)].slice(0, 20))} />}
    {openUpload && <div hidden={!showUpload}>
      <CustomerMaterials projectId={project.id} onContinue={onContinue} onUnavailable={onUnavailable}
        registerLeaveGuard={registerLeaveGuard} active={showUpload} forWriting={project.project_type === 'thesis' ? 'thesis' : 'sci'}
        onRequirements={onRequirements} onUploaded={onUploaded} analysisPicks={picks} />
    </div>}
    {showLiterature && !literatureReady && <p role="status">{t('正在读取项目关键词……')}</p>}
    {openLiterature && literatureReady && <ProjectLiterature projectId={project.id} researchTopic={project.research_topic}
      outputLanguage={project.default_output_language ?? 'zh-CN'} projectKeywords={projectKeywords} initialSearchId={searchId}
      literatureNavigation={{ view: literatureView ?? 'list', referenceId }}
      onSearchChange={search => onUpdateRoute({ search, view: 'list', reference: undefined }, true)}
      onLiteratureNavigate={({ view, referenceId }) => onUpdateRoute({ view, reference: referenceId }, true)}
      active={showLiterature} customerSci registerLeaveGuard={registerLeaveGuard} onReferenceReady={onReferenceReady} />}
  </>
}
