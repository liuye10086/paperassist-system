import {validRevision,type Revision} from '../reviews/revisionTypes'
import {isTask,type TaskView} from '../tasks/taskTypes'
import {isSubmissionEvent,type SubmissionEvent} from '../journals/adaptationContracts'
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
type CompactRound={id:string;title:string;round_number:number;revision:number;synthetic:boolean;manuscript:{id:string;revision:number;version_id:string;title:string}}
export type ReviewSummary={actual_revisions?:Revision[];documents?:{id:string;revision_id:string;kind:'comparison'|'reply';version:number;language:'zh-CN'|'en';confirmed_at:string|null}[];state:'available';tasks:TaskView[];current_round:CompactRound|null;rounds:CompactRound[];opinions:{id:string;source_id:string;source_label?:string;number:number;category:string;status:'pending'|'waiting_confirmation'|'waiting_material'|'not_adopted'|'completed'|'executing';uncompleted_reason:string}[];pending_materials:{item_id:string;needs:{kind:string;description:string}[]}[]}
export type ProjectSummaryData = {
  journal?:{target_id:string;profile_name:string;recommendation_id:string;confirmed_at:string;progress:SubmissionEvent|null}|null
  thesis_profile?:{school:string;department:string;major:string;degree_type:string;education_level:string;applicable_version:string;bound_confirmation_id:string|null;template_name:string|null;template_version_label:string|null}|null
  layout_exports?:LayoutExport[]
  project_id: string; project_type: 'sci' | 'thesis' | 'research'
  tasks: SummaryPage<SummaryTask>; artifacts: SummaryPage<SummaryArtifact>
  future: {
    writing: (Unavailable & { current_manuscript: null; versions: never[] }) | {state:'available';current_manuscript:{id:string;title:string;current_revision:number}|null;versions:{id:string;manuscript_id:string;revision:number}[];tasks:never[]}
    revision: (Unavailable & { current_round: null; rounds: never[]; opinions: never[]; pending_materials: never[] }) | ReviewSummary
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

export function isProjectSummary(value: unknown, projectId: string, projectType: 'sci' | 'thesis' | 'research',
  taskPage: number, artifactPage: number): value is ProjectSummaryData {
  if (!record(value) || value.project_id !== projectId || value.project_type !== projectType || !record(value.future)) return false
  if(value.layout_exports!==undefined&&(!Array.isArray(value.layout_exports)||value.layout_exports.length>20||!value.layout_exports.every(x=>record(x)&&validLayoutExport(x,{projectId,sourceKind:x.source_kind as LayoutExport['source_kind'],sourceId:String(x.source_id)}))||new Set(value.layout_exports.map(x=>x.id)).size!==value.layout_exports.length))return false
  if(value.journal!=null){const j=value.journal;if(projectType!=='sci'||!record(j)||!['target_id','profile_name','recommendation_id','confirmed_at'].every(k=>typeof j[k]==='string'&&!!j[k])||j.progress!==null&&(!isSubmissionEvent(j.progress,projectId)||j.progress.target_id!==j.target_id))return false}
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
    && (unavailable(future.revision, ['rounds', 'opinions', 'pending_materials'], ['current_round']) || reviewSummary(future.revision,projectId))
    && (projectType === 'research' ? future.sci === null && future.thesis === null : projectType === 'sci'
      ? future.thesis === null && unavailable(future.sci, ['recommendations'], ['target_journal', 'submission_progress'])
      : future.sci === null && unavailable(future.thesis, [], ['school', 'degree', 'template', 'review_progress']))
}

function compactRound(v:unknown):v is CompactRound{return record(v)&&['id','title'].every(k=>typeof v[k]==='string'&&!!v[k])&&integer(v.round_number,1)&&integer(v.revision,1)&&typeof v.synthetic==='boolean'&&record(v.manuscript)&&['id','version_id','title'].every(k=>typeof (v.manuscript as Record<string,unknown>)[k]==='string')&&integer(v.manuscript.revision,1)}
function reviewSummary(v:unknown,projectId:string):v is ReviewSummary{return record(v)&&v.state==='available'&&Array.isArray(v.tasks)&&v.tasks.every(t=>isTask(t,projectId)&&['review_round_plan','review_revision','review_document_export'].includes(t.task_type))&&(v.actual_revisions===undefined||Array.isArray(v.actual_revisions)&&v.actual_revisions.every(r=>record(r)&&typeof r.round_id==='string'&&validRevision(r,projectId,r.round_id)))&&(v.documents===undefined||Array.isArray(v.documents)&&v.documents.every(d=>record(d)&&typeof d.id==='string'&&typeof d.revision_id==='string'&&['comparison','reply'].includes(String(d.kind))&&['zh-CN','en'].includes(String(d.language))&&integer(d.version,1)&&(d.confirmed_at===null||typeof d.confirmed_at==='string')))&&(v.current_round===null||compactRound(v.current_round))&&Array.isArray(v.rounds)&&v.rounds.length<=20&&v.rounds.every(compactRound)&&Array.isArray(v.opinions)&&v.opinions.every(i=>record(i)&&['id','source_id','category','uncompleted_reason'].every(k=>typeof i[k]==='string')&&integer(i.number,1)&&(['pending','waiting_confirmation','waiting_material','not_adopted','executing'].includes(String(i.status))||i.status==='completed'&&Array.isArray(v.actual_revisions)&&v.actual_revisions.some(r=>record(r)&&r.output_status==='published'&&record(r.result)&&Array.isArray(r.result.actual_changes)&&r.result.actual_changes.some(c=>record(c)&&c.item_id===i.id))))&&Array.isArray(v.pending_materials)&&v.pending_materials.every(m=>record(m)&&typeof m.item_id==='string'&&Array.isArray(m.needs)&&m.needs.every(n=>record(n)&&['material','analysis','experiment','literature'].includes(String(n.kind))&&typeof n.description==='string'))}
