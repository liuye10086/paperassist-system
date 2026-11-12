import { useEffect, useRef, useState } from 'react'
import type { Intake, DeliveryKind, Version } from '../research-intake/contracts'
import { useResearchRead } from '../research-results/api'
import type { Project } from './projectTypes'
import type { ProjectSection } from './WorkspaceShell'
import type { OverviewView } from './projectNavigation'
import type { AnalysisNavigation } from './analysisViews'

export type WorkflowState = {
  project_id: string
  project_type: Project['project_type']
  files: { total: number; ready: number }
  requirements: { saved: boolean; version: number | null; services: DeliveryKind[] }
  results: { available: boolean }
  next_step: 'upload' | 'requirements' | 'analysis' | 'results' | 'writing'
}

export function projectFlowStep(section: ProjectSection, view: OverviewView, analysis: boolean) {
  if (section === 'overview') return ['requirements','design'].includes(view) ? 2 : view === 'deliveries' ? 4 : 0
  if (section === 'files' || section === 'literature') return 1
  if (section === 'analysis' || section === 'tasks') return 3
  if (section === 'artifacts') return 4
  if (section === 'manuscripts') return analysis ? 4 : 3
  return analysis ? 5 : 3
}

export function isAnalysisResultView(view: AnalysisNavigation['view'] | undefined) {
  return ['bio-result', 'bio-insight-result', 'bio-insight-runs', 'report'].includes(view ?? '')
}

export function flowBlockReason(step: number, state: { hasFiles: boolean; requirementSaved: boolean; reached: number; existingResults: boolean }) {
  // Viewing results and manuscripts is read-only, including their empty states.
  // Neither a visited page nor an older result proves this request is ready.
  if (step <= 1 || step >= 4) return ''
  if (step === 2) return state.hasFiles || state.requirementSaved ? '' : '请先完成第 2 步：文件上传/整理。'
  if (step === 3) return !state.requirementSaved ? '请先完成第 3 步：选择并保存需求。' : !state.hasFiles ? '请先完成第 2 步：文件上传/整理。' : ''
  return ''
}

export default function useProjectFlow(project: Project | null, section: ProjectSection, view: OverviewView, assigned = false) {
  const id = project?.id ?? ''
  const intakeActive = !!id && !assigned && section === 'overview' && ['requirements', 'design'].includes(view)
  const intake = useResearchRead<Intake>(id ? `/api/v1/projects/${id}/research-intake` : '', intakeActive)
  const workflow = useResearchRead<WorkflowState>(id ? `/api/v1/projects/${id}/workflow-state` : '', !!id)
  const [accepted, setAccepted] = useState<{ id: string; services: DeliveryKind[]; version?:Version } | null>(null)
  const acceptedRef = useRef(accepted)
  const services = accepted?.id === id ? accepted.services : workflow.data?.requirements.services
  const hasAnalysis = !Array.isArray(services) || services.includes('analysis')
  const step = projectFlowStep(section, view, hasAnalysis)
  const [visited, setVisited] = useState({ id, step })
  const reached = visited.id === id ? Math.max(visited.step, step) : step
  useEffect(() => { if (visited.id !== id || visited.step < step) setVisited({ id, step }) }, [id, step, visited])
  const existingResults = workflow.data?.results.available ?? false
  const requirement = accepted?.id===id&&accepted.version&&accepted.version.version>=(intake.data?.current_requirement?.version??0)?accepted.version:intake.data?.current_requirement??null
  const hasFiles = workflow.data ? workflow.data.files.ready > 0 || !!requirement?.material_refs?.some(ref=>ref.availability==='provided'&&ref.bio_dataset_version_id)
    : (project?.file_count ?? 0) > 0 || !!requirement?.material_refs?.some(ref=>ref.availability==='provided'&&ref.bio_dataset_version_id)
  const state = { hasFiles, requirementSaved: workflow.data?.requirements.saved ?? (Array.isArray(services) && services.length > 0), reached, existingResults }
  return {
    hasAnalysis,
    workflowState: workflow.data,
    savedRequirement: requirement,
    reason: (target: ProjectSection, overview: OverviewView = 'tasks') => {
      if(target==='tasks')return ''
      const latest = acceptedRef.current?.id === id ? acceptedRef.current.services : services
      const analysis = !Array.isArray(latest) || latest.includes('analysis')
      return target === 'analysis' && !analysis ? '本次未选择数据分析，请按已选服务继续写作。'
        : !analysis && projectFlowStep(target,overview,analysis)===3 && Array.isArray(latest) && latest.length>0 ? ''
        : flowBlockReason(projectFlowStep(target, overview, analysis), {...state, requirementSaved: Array.isArray(latest) && latest.length > 0})
    },
    acceptServices: (next: DeliveryKind[], version?:Version) => { acceptedRef.current = { id, services: next, version }; setAccepted(acceptedRef.current); intake.refresh(); workflow.refresh() },
    refresh: () => { acceptedRef.current = null; setAccepted(null); intake.refresh(); workflow.refresh() },
    error: intake.error || workflow.error,
  }
}
