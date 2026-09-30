export type Project = {
  id: string; name: string; research_topic: string; project_type: 'sci' | 'thesis'
  file_count: number; created_at: string; updated_at: string
}

export const typeNames = { sci: 'SCI 科研论文', thesis: '毕业论文' }
