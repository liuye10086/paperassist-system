import {validLayoutExport,type LayoutExport} from '../layout-exports/layoutApi'
export type SummarySource = {
  id: string; file_id: string; filename: string; analysis_run_id: string
  setup_revision: number; current_revision: number | null; engine_version: string
  recorded_at: string; figure_id: string | null; explanation_id: string | null
}
export type SummaryTask = SummarySource & {
  kind: 'statistics' | 'boxplot' | 'explanation' | 'report'
  status: 'queued' | 'submitting' | 'running' | 'waiting_input' | 'waiting_confirmation' | 'completed' | 'failed' | 'uncertain' | 'unknown'
}
export type SummaryArtifact = Omit<SummarySource,'analysis_run_id'|'setup_revision'> & {
  analysis_run_id:string|null;setup_revision:number|null
  kind: 'figure' | 'report'; download_filename: string; size_bytes: number; sha256: string; download_url: string
  figure_kind?:string|null;figure_config_version_id?:string|null
  collection_id?:string|null;collection_version_id?:string|null;collection_revision?:number|null
  export_revision?:number|null;collection_title?:string|null;result_count?:number|null
}
export type SummaryPage<T> = { items: T[]; total: number; page: number; page_size: number }
type Unavailable = { state: 'not_available'; tasks: never[] }
export type ProjectSummaryData = {
  thesis_profile?:{school:string;department:string;major:string;degree_type:string;education_level:string;applicable_version:string;bound_confirmation_id:string|null;template_name:string|null;template_version_label:string|null}|null
  layout_exports?:LayoutExport[]
  project_id: string; project_type: 'sci' | 'thesis'
  tasks: SummaryPage<SummaryTask>; artifacts: SummaryPage<SummaryArtifact>
  future: {
    writing: (Unavailable & { current_manuscript: null; versions: never[] }) | {state:'available';current_manuscript:{id:string;title:string;current_revision:number}|null;versions:{id:string;manuscript_id:string;revision:number}[];tasks:never[]}
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
  if(value.layout_exports!==undefined&&(!Array.isArray(value.layout_exports)||value.layout_exports.length>20||!value.layout_exports.every(x=>record(x)&&validLayoutExport(x,{projectId,sourceKind:x.source_kind as LayoutExport['source_kind'],sourceId:String(x.source_id)}))||new Set(value.layout_exports.map(x=>x.id)).size!==value.layout_exports.length))return false
  const future = value.future
  return page(value.tasks, taskPage, task => source(task) && record(task)
    && ['statistics', 'boxplot', 'explanation', 'report'].includes(String(task.kind))
    && ['queued', 'submitting', 'running', 'waiting_input', 'waiting_confirmation', 'completed', 'failed', 'uncertain', 'unknown'].includes(String(task.status)))
    && page(value.artifacts, artifactPage, artifact => {
      if (!record(artifact) || !['figure', 'report'].includes(String(artifact.kind))
        || typeof artifact.download_filename !== 'string' || !artifact.download_filename
        || !integer(artifact.size_bytes) || typeof artifact.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(artifact.sha256)) return false
      if(artifact.collection_id!=null){
        if(artifact.kind!=='report'||!source({...artifact,analysis_run_id:'collection',setup_revision:1})||artifact.analysis_run_id!==null||artifact.setup_revision!==null||artifact.current_revision!==null||artifact.figure_id!==null||artifact.explanation_id!==null||artifact.figure_config_version_id!=null||!['collection_id','collection_version_id','collection_title'].every(key=>typeof artifact[key]==='string'&&artifact[key]!=='' )||!integer(artifact.collection_revision,1)||!integer(artifact.export_revision,1)||!integer(artifact.result_count,1))return false
        return artifact.download_url===`/api/v1/projects/${encodeURIComponent(projectId)}/report-collections/${encodeURIComponent(String(artifact.collection_id))}/reports/${encodeURIComponent(String(artifact.id))}/download`
      }
      if(!source(artifact))return false
      const base = `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(artifact.file_id)}/analysis-runs/${encodeURIComponent(artifact.analysis_run_id)}`
      if(artifact.figure_config_version_id!=null)return artifact.kind==='figure'&&typeof artifact.figure_config_version_id==='string'&&!!artifact.figure_config_version_id&&['boxplot','group_boxplot','paired_connected','scatter','correlation_heatmap','line','bar','violin','forest','roc_curve','kaplan_meier'].includes(String(artifact.figure_kind))&&artifact.download_url===`${base}/figure-workbench/figures/${encodeURIComponent(artifact.id)}/png`
      return artifact.download_url === `${base}/${artifact.kind === 'figure' ? 'figures' : 'report'}/${encodeURIComponent(artifact.id)}/download`
    })
    && (unavailable(future.writing, ['versions'], ['current_manuscript']) || record(future.writing)&&future.writing.state==='available'&&Array.isArray(future.writing.tasks)&&future.writing.tasks.length===0&&(future.writing.current_manuscript===null||record(future.writing.current_manuscript)&&['id','title'].every(k=>typeof (future.writing as Record<string,unknown>).current_manuscript==='object'&&typeof ((future.writing as Record<string,unknown>).current_manuscript as Record<string,unknown>)[k]==='string')&&integer(future.writing.current_manuscript.current_revision,1))&&Array.isArray(future.writing.versions)&&future.writing.versions.every(v=>record(v)&&typeof v.id==='string'&&typeof v.manuscript_id==='string'&&integer(v.revision,1)))
    && unavailable(future.revision, ['rounds', 'opinions', 'pending_materials'], ['current_round'])
    && (projectType === 'sci'
      ? future.thesis === null && unavailable(future.sci, ['recommendations'], ['target_journal', 'submission_progress'])
      : future.sci === null && unavailable(future.thesis, [], ['school', 'degree', 'template', 'review_progress']))
}
