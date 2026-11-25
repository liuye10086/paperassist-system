import { useLayoutEffect, useRef, type Ref } from 'react'
import type { Project } from '../projects/projectTypes'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import CustomerAnalysisResults from './CustomerAnalysisResults'
import CustomerMaterials from './CustomerMaterials'
import { useMaterialAnalysisPicks } from './paperMaterials'
import type { UpdatePaperRoute } from './customerPaperNavigation'
import { validCustomerRouteId } from './customerReviewNavigation'
import type { ReturnTarget } from './returnToken'

type Props = {
  project: Project
  headingRef: Ref<HTMLHeadingElement>
  onContinue: () => void
  onUnavailable: () => void
  registerLeaveGuard: RegisterLeaveGuard
  params: URLSearchParams
  onUpdateRoute: UpdatePaperRoute
  onOpenAnalysisResults: () => void
  materialsReturn: ReturnTarget | null
  onFollowReturn: (href: string) => void
}

export default function CustomerWritingMaterials({
  project, headingRef, onContinue, onUnavailable, registerLeaveGuard, params, onUpdateRoute, onOpenAnalysisResults, materialsReturn, onFollowReturn,
}: Props) {
  const analysisResults = params.get('view') === 'analysis-results'
  const analysisProject = params.get('analysisProject')
  const analysisSnapshot = params.get('analysisSnapshot')
  // Downloaded results, newest first; this browser tab only (closing it drops the prefilled source).
  const [picks, setPicks] = useMaterialAnalysisPicks(project.id)
  const pickButton = useRef<HTMLButtonElement>(null)
  const wasPicking = useRef(analysisResults)
  useLayoutEffect(() => {
    if (wasPicking.current && !analysisResults) pickButton.current?.focus({preventScroll:true})
    wasPicking.current = analysisResults
  }, [analysisResults])
  return <>
    {analysisResults && <CustomerAnalysisResults paperProjectId={project.id} purpose="materials"
      returnTarget={materialsReturn} headingRef={headingRef} onReturn={onFollowReturn}
      selected={validCustomerRouteId(analysisProject) && validCustomerRouteId(analysisSnapshot)
        ? { projectId: analysisProject, snapshotId: analysisSnapshot } : null}
      onSelect={selection => onUpdateRoute({ analysisProject: selection?.projectId, analysisSnapshot: selection?.snapshotId })}
      onPick={pick => setPicks(old => [pick, ...old.filter(item =>
        item.researchProjectName !== pick.researchProjectName || item.deliveryTitle !== pick.deliveryTitle)].slice(0, 20))} />}
    <CustomerMaterials projectId={project.id} headingRef={analysisResults ? undefined : headingRef}
      onContinue={onContinue} onUnavailable={onUnavailable} registerLeaveGuard={registerLeaveGuard}
      forWriting="thesis" active={!analysisResults} analysisPicks={picks} onAnalysisResults={onOpenAnalysisResults} analysisResultsRef={pickButton} />
  </>
}
