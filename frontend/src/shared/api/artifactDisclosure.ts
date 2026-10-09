export type ArtifactDisclosure = {
  version: 1
  provider: 'openai'
  task_type: 'boxplot' | 'explanation'
  source_digest: string
  has_saved_result: boolean
  summary: { valid_count: number; excluded_count: number; group_count: number }
  labels: { key: string; value: string }[]
}
export type ExternalProcessingConfirmation = {
  version: 1; confirmed: true; source_digest: string; labels: Record<string, string>
}
export type ArtifactReviewDraft = { disclosure: ArtifactDisclosure; body: Record<string, unknown> }

export function isArtifactDisclosure(value: unknown, kind: ArtifactDisclosure['task_type']): value is ArtifactDisclosure {
  if (!value || typeof value !== 'object') return false
  const data = value as ArtifactDisclosure
  if (data.version !== 1 || data.provider !== 'openai' || data.task_type !== kind || typeof data.source_digest !== 'string'
    || !data.source_digest || typeof data.has_saved_result !== 'boolean' || !data.summary || !Array.isArray(data.labels)) return false
  if (![data.summary.valid_count, data.summary.excluded_count, data.summary.group_count].every(count => Number.isSafeInteger(count) && count >= 0)) return false
  const keys = ['numeric_name', 'unit', ...(kind === 'explanation' ? ['figure_title'] : [])]
  if (data.labels.some(label => label?.key === 'group_name')) {
    if (data.summary.group_count > data.labels.length) return false
    keys.push('group_name', ...Array.from({ length: data.summary.group_count }, (_, i) => `group:${i}`))
  }
  return data.labels.length === keys.length && keys.every(key => data.labels.filter(label => label?.key === key && typeof label.value === 'string').length === 1)
}
