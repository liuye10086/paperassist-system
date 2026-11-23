import { projectBase } from '../research-intake/api'
import useResearchDraft from '../research-results/useResearchDraft'
import type { AnalysisPick } from './CustomerAnalysisResults'

export function useMaterialAnalysisPicks(projectId: string) {
  return useResearchDraft<AnalysisPick[]>(projectId, 'analysis-pick:materials', () => [])
}

export type PaperMaterialNote = {
  id: string
  file_id: string
  revision: number
  result: string
  target_id: string | null
  target_label: string | null
  target_available: boolean
  worksheet_names?: string[] | null
}

export type PaperMaterialTarget = { id: string; label: string }
export type PaperMaterialsRead = {
  items: PaperMaterialNote[]; targets: PaperMaterialTarget[]; figure_targets?: PaperMaterialTarget[]
  template_source_file_ids?: string[]; review_figure_placement?: boolean
}
export type PaperFile = { id: string; filename: string; file_type: string }
export type PaperWorksheet = {
  name: string; columns: string[]; preview_rows: string[][]; row_count: number; values_ready: boolean
}

export function paperMaterialKind(file: PaperFile) {
  if (['png', 'jpeg', 'tiff'].includes(file.file_type)) return 'figure'
  if (['docx', 'xlsx'].includes(file.file_type)) return 'table'
  return null
}

export function paperMaterialsUrl(projectId: string, ids: string[] = []) {
  const query = new URLSearchParams()
  for (const id of ids) query.append('file_id', id)
  return projectBase(projectId) + '/paper-materials' + (query.size ? `?${query}` : '')
}
