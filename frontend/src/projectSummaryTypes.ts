export type SummarySource = {
  id: string; file_id: string; filename: string; analysis_run_id: string
  setup_revision: number; current_revision: number | null; engine_version: string
  recorded_at: string; figure_id: string | null; explanation_id: string | null
}
export type SummaryTask = SummarySource & {
  kind: 'statistics' | 'boxplot' | 'explanation' | 'report'
  status: 'submitting' | 'running' | 'completed' | 'failed' | 'uncertain' | 'unknown'
}
export type SummaryArtifact = SummarySource & {
  kind: 'figure' | 'report'; download_filename: string; size_bytes: number; sha256: string; download_url: string
}
export type SummaryPage<T> = { items: T[]; total: number; page: number; page_size: number }
type Unavailable = { state: 'not_available'; tasks: never[] }
export type ProjectSummaryData = {
  project_id: string; project_type: 'sci' | 'thesis'
  tasks: SummaryPage<SummaryTask>; artifacts: SummaryPage<SummaryArtifact>
  future: {
    writing: Unavailable & { current_manuscript: null; versions: never[] }
    revision: Unavailable & { current_round: null; rounds: never[]; opinions: never[]; pending_materials: never[] }
    sci: (Unavailable & { target_journal: null; recommendations: never[]; submission_progress: null }) | null
    thesis: (Unavailable & { school: null; degree: null; template: null; review_progress: null }) | null
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function integer(value: unknown, minimum = 0): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= minimum
}
function source(value: unknown): value is SummarySource & Record<string, unknown> {
  return record(value) && ['id', 'file_id', 'filename', 'analysis_run_id', 'engine_version', 'recorded_at']
    .every(key => typeof value[key] === 'string' && value[key] !== '')
    && Number.isFinite(Date.parse(value.recorded_at as string)) && integer(value.setup_revision, 1)
    && (value.current_revision === null || integer(value.current_revision, 1))
    && ['figure_id', 'explanation_id'].every(key => value[key] === null || typeof value[key] === 'string')
}
function page(value: unknown, expected: number, item: (value: unknown) => boolean): boolean {
  return record(value) && integer(value.total) && value.page === expected && value.page_size === 10
    && Array.isArray(value.items) && value.items.length <= 10 && value.items.length <= value.total && value.items.every(item)
}
function unavailable(value: unknown, arrays: string[], nulls: string[]): boolean {
  return record(value) && value.state === 'not_available'
    && ['tasks', ...arrays].every(key => Array.isArray(value[key]) && value[key].length === 0)
    && nulls.every(key => value[key] === null)
}

export function isProjectSummary(value: unknown, projectId: string, projectType: 'sci' | 'thesis',
  taskPage: number, artifactPage: number): value is ProjectSummaryData {
  if (!record(value) || value.project_id !== projectId || value.project_type !== projectType || !record(value.future)) return false
  const future = value.future
  return page(value.tasks, taskPage, task => source(task) && record(task)
    && ['statistics', 'boxplot', 'explanation', 'report'].includes(String(task.kind))
    && ['submitting', 'running', 'completed', 'failed', 'uncertain', 'unknown'].includes(String(task.status)))
    && page(value.artifacts, artifactPage, artifact => {
      if (!source(artifact) || !record(artifact) || !['figure', 'report'].includes(String(artifact.kind))
        || typeof artifact.download_filename !== 'string' || !artifact.download_filename
        || !integer(artifact.size_bytes) || typeof artifact.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(artifact.sha256)) return false
      const base = `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(artifact.file_id)}/analysis-runs/${encodeURIComponent(artifact.analysis_run_id)}`
      return artifact.download_url === `${base}/${artifact.kind === 'figure' ? 'figures' : 'report'}/${encodeURIComponent(artifact.id)}/download`
    })
    && unavailable(future.writing, ['versions'], ['current_manuscript'])
    && unavailable(future.revision, ['rounds', 'opinions', 'pending_materials'], ['current_round'])
    && (projectType === 'sci'
      ? future.thesis === null && unavailable(future.sci, ['recommendations'], ['target_journal', 'submission_progress'])
      : future.sci === null && unavailable(future.thesis, [], ['school', 'degree', 'template', 'review_progress']))
}
