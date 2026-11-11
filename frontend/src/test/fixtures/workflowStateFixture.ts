import type { Project } from '../../features/projects/projectTypes'
import type { WorkflowState } from '../../features/projects/useProjectFlow'

type Options = {
  readyFiles?: number
  services?: WorkflowState['requirements']['services']
  resultsAvailable?: boolean
}

export function workflowStateFixture(
  project: Pick<Project, 'id' | 'project_type' | 'file_count'>,
  { readyFiles = project.file_count, services = [], resultsAvailable = false }: Options = {},
): WorkflowState {
  const saved = services.length > 0
  const nextStep = readyFiles === 0 ? 'upload'
    : !saved ? 'requirements'
    : resultsAvailable ? 'results'
    : services.includes('analysis') ? 'analysis' : 'writing'

  return {
    project_id: project.id,
    project_type: project.project_type,
    files: { total: project.file_count, ready: readyFiles },
    requirements: { saved, version: saved ? 1 : null, services },
    results: { available: resultsAvailable },
    next_step: nextStep,
  }
}
