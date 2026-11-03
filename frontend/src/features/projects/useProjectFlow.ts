import { useEffect, useRef, useState } from 'react'
import type { Intake, DeliveryKind } from '../research-intake/contracts'
import { useResearchRead } from '../research-results/api'
import type { Project } from './projectTypes'
import type { ProjectSection } from './WorkspaceShell'
import type { OverviewView } from './projectNavigation'
import type { ProjectSummaryData } from './projectSummaryTypes'

export function projectFlowStep(section: ProjectSection, view: OverviewView, analysis: boolean) {
  if (section === 'overview') return ['requirements','design'].includes(view) ? 2 : view === 'deliveries' ? 4 : 0
  if (section === 'files' || section === 'literature') return 1
  if (section === 'analysis' || section === 'tasks') return 3
  if (section === 'artifacts') return 4
  return analysis ? 5 : 3
}

export function flowBlockReason(step: number, state: { hasFiles: boolean; requirementSaved: boolean; reached: number; existingResults: boolean }) {
  if (step <= 1 || step <= state.reached || state.existingResults) return ''
  if (state.reached < 2 && !state.hasFiles) return '请先完成第 2 步：上传文件。'
  if (step >= 3 && state.reached < 3 && !state.requirementSaved) return '请先完成第 3 步：选择并保存需求。'
  if (step >= 4 && state.reached < 3) return '请先进入第 4 步，按顺序处理本次需求。'
  if (step >= 5 && state.reached < 4) return '请先查看本次结果，再继续写作。'
  return ''
}

export default function useProjectFlow(project: Project | null, section: ProjectSection, view: OverviewView) {
  const id = project?.id ?? ''
  const intake = useResearchRead<Intake>(id ? `/api/v1/projects/${id}/research-intake` : '', !!id)
  const summary = useResearchRead<ProjectSummaryData>(id ? `/api/v1/projects/${id}/summary?task_page=1&artifact_page=1&page_size=10` : '', !!id)
  const [accepted, setAccepted] = useState<{ id: string; services: DeliveryKind[] } | null>(null)
  const acceptedRef = useRef(accepted)
  const services = accepted?.id === id ? accepted.services : intake.data?.current_requirement?.content.services
  const hasAnalysis = !Array.isArray(services) || services.includes('analysis')
  const step = projectFlowStep(section, view, hasAnalysis)
  const [visited, setVisited] = useState({ id, step })
  const reached = visited.id === id ? Math.max(visited.step, step) : step
  useEffect(() => { if (visited.id !== id || visited.step < step) setVisited({ id, step }) }, [id, step, visited])
  const existingResults = (summary.data?.artifacts?.total ?? 0) > 0 || !!summary.data?.future?.writing?.current_manuscript
    || (summary.data?.tasks?.total ?? 0) > 0
  const state = { hasFiles: (project?.file_count ?? 0) > 0, requirementSaved: Array.isArray(services) && services.length > 0, reached, existingResults }
  return {
    hasAnalysis,
    reason: (target: ProjectSection, overview: OverviewView = 'tasks') => {
      const latest = acceptedRef.current?.id === id ? acceptedRef.current.services : services
      const analysis = !Array.isArray(latest) || latest.includes('analysis')
      return target === 'analysis' && !analysis ? '本次未选择数据分析，请按已选服务继续写作。'
        : flowBlockReason(projectFlowStep(target, overview, analysis), {...state, requirementSaved: Array.isArray(latest) && latest.length > 0})
    },
    acceptServices: (next: DeliveryKind[]) => { acceptedRef.current = { id, services: next }; setAccepted(acceptedRef.current); intake.refresh() },
    refresh: () => { acceptedRef.current = null; setAccepted(null); intake.refresh(); summary.refresh() },
    error: intake.error || summary.error,
  }
}
