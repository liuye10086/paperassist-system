import { projectBase } from '../research-intake/api'

export type PaperMaterialNote = {
  id: string
  file_id: string
  revision: number
  result: string
  target_id: string | null
  target_label: string | null
  target_available: boolean
}

export type PaperMaterialTarget = { id: string; label: string }
export type PaperMaterialsRead = { items: PaperMaterialNote[]; targets: PaperMaterialTarget[] }
export type PaperFile = { id: string; filename: string; file_type: string }

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
