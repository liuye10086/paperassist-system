export type Project = {
  id: string; name: string; research_topic: string; project_type: 'sci' | 'thesis'
  file_count: number; created_at: string; updated_at: string
}

export const typeNames = { sci: 'SCI 科研论文', thesis: '毕业论文' }

export type ProjectPage = { items: Project[]; total: number; page: number; page_size: number }

export function isProject(value: unknown): value is Project {
  if (!value || typeof value !== 'object') return false
  const project = value as Partial<Project>
  return typeof project.id === 'string' && typeof project.name === 'string' && typeof project.research_topic === 'string'
    && (project.project_type === 'sci' || project.project_type === 'thesis')
    && Number.isSafeInteger(project.file_count) && project.file_count! >= 0
    && typeof project.created_at === 'string' && typeof project.updated_at === 'string'
}
