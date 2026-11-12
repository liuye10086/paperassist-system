export type Project = {
  id: string; name: string; research_topic: string; project_type: 'sci' | 'thesis' | 'research'
  file_count: number; created_at: string; updated_at: string
  default_output_language?: 'zh-CN' | 'en'
  assignment_revision?: number
}

export const typeNames = { sci: 'SCI 科研论文', thesis: '毕业论文', research: '研究项目' }
export const PROJECT_PAGE_SIZE = 5

export type ProjectPage = { items: Project[]; total: number; page: number; page_size: number }

export function isProjectPage(value: unknown, page: number): value is ProjectPage {
  if (!value || typeof value !== 'object') return false
  const result = value as Partial<ProjectPage>
  return Array.isArray(result.items) && result.items.every(isProject)
    && Number.isSafeInteger(result.total) && result.total! >= 0
    && result.page === page && result.page_size === PROJECT_PAGE_SIZE
}

export function isProject(value: unknown): value is Project {
  if (!value || typeof value !== 'object') return false
  const project = value as Partial<Project>
  return typeof project.id === 'string' && typeof project.name === 'string' && typeof project.research_topic === 'string'
    && (project.project_type === 'sci' || project.project_type === 'thesis' || project.project_type === 'research')
    && Number.isSafeInteger(project.file_count) && project.file_count! >= 0
    && typeof project.created_at === 'string' && typeof project.updated_at === 'string'
    && (project.default_output_language === undefined || project.default_output_language === 'zh-CN' || project.default_output_language === 'en')
    && (project.assignment_revision === undefined || (Number.isSafeInteger(project.assignment_revision) && project.assignment_revision > 0))
}
