import { isDatasetSource, sameSource, type DatasetAnalysisSource } from '../analysis/datasetSource'
import { isReviewSource, sameReviewSource, type ReviewInputVersion } from '../documents/ocrReviewTypes'
export const taskNames = { boxplot: '箱线图生成', explanation: 'AI 分析解释', word_report: 'Word 报告导出', parse_file: '文件解析', extract_dataset: 'Excel 结构提取', prepare_dataset: '数据整理', analysis_plan: '分析计划', review_ocr:'文字人工核对' }
export const statusNames = { queued: '待执行', running: '运行中', waiting_input: '待补充资料',
  waiting_confirmation: '待用户确认', succeeded: '已完成', failed: '执行失败' }
export const displayNames = { queued: '待执行', parsing: '文件解析中', analyzing: 'AI 分析中', computing: '数据计算中',
  searching: '文献检索中', generating_document: '文档生成中', waiting_input: '待补充资料', waiting_confirmation: '待用户确认',
  succeeded: '已完成', failed: '执行失败' }
export const phaseNames = { parse: '解析资料', plan: '分析计划', compute: '计算与绘图', search: '检索资料',
  interpret: '分析解释', write: '生成文字', export: '导出文档', verify: '核查结果' }
export const eventNames = { created: '任务已建立', started: '开始执行', phase_changed: '处理阶段已更新', waiting: '等待处理',
  succeeded: '成果已保存', failed: '本次执行失败', requeued: '任务已重新排队', deferred: '等待后续处理' }
export type TaskType = keyof typeof taskNames
export type TaskStatus = keyof typeof statusNames
const errorCategories = ['temporary', 'authentication', 'permission', 'configuration', 'source', 'output',
  'submission_unknown', 'budget', 'interrupted', 'internal'] as const
const retryReasons = ['temporary_provider_error', 'worker_interrupted', 'manual_retry'] as const
export type ErrorCategory = typeof errorCategories[number]
export type RetryReason = typeof retryReasons[number]
export type RetryCount = 0 | 1 | 2 | 3
export type PreparationInputVersion = { kind: 'dataset_preparation'; source: DatasetAnalysisSource; workflow_version: 'dataset_preparation_v1'; setup_revision?: never; output_language?: never }
export type AnalysisPlanInputVersion = { kind: 'analysis_plan'; source: DatasetAnalysisSource; workflow_version: 'analysis_plan_v1'; setup_revision?: never; output_language?: never }
export type InputVersion = ReviewInputVersion | PreparationInputVersion | AnalysisPlanInputVersion | { kind: 'dataset_analysis'; setup_revision: number; output_language: 'zh-CN'; source: DatasetAnalysisSource } | { kind: 'excel_structure'; structure_id: string; source_sha256: string; parser_version: string; setup_revision?: never; output_language?: never } | { setup_revision: number; output_language: 'zh-CN'; kind?: never } | { kind: 'parse_file'; parse_id: string; source_sha256: string; parser_version: string; setup_revision?: never; output_language?: never }
export type TaskView = { id: string; project_id: string; task_type: TaskType; status: TaskStatus; phase: keyof typeof phaseNames;
  display_status: keyof typeof displayNames; reason_code: string | null;
  error_code: string | null; created_at: string; input_version: InputVersion;
  result_figure_id?: string | null; result_explanation_id?: string | null; result_report_id?: string | null } & (
  { origin?: 'unified'; revision: number; current_attempt: number; retry_count?: RetryCount | null; updated_at: string }
  | { origin: 'legacy'; revision: null; current_attempt: null; retry_count: null; updated_at: null })
export type TaskSource = { file_id: string; filename: string; analysis_run_id: string | null; is_current: boolean; dataset_source?: DatasetAnalysisSource }
export type TaskItem = { task: TaskView; source: TaskSource }
export type TaskPage = { project_id: string; items: TaskItem[]; total: number; page: number; page_size: number }
export type TaskOperation = 'resume' | 'retry' | 'approve' | 'revise'
export type TaskWait = { id: string; kind: 'ocr_review_confirmation' | 'dataset_preparation_confirmation' | 'analysis_plan_confirmation' | 'budget_confirmation' | 'submission_unknown' | 'unsupported_input' | 'unsupported_confirmation';
  status: 'open' | 'resolved' | 'superseded'; task_revision: number; input_version: InputVersion;
  reason_code: string | null; error_code: string | null; created_at: string; resolved_at: string | null }
export type TaskWorkspace = TaskItem & { wait: TaskWait | null; allowed_actions: TaskOperation[]; artifacts: {
  figure: { title: string; caption: string; download_url: string } | null;
  explanation: { sections: { key: string; title: string; text: string }[]; limitations: string[] } | null;
  report: { filename: string; download_url: string } | null; dataset?: { filename: string; download_url: string } } }
export type TaskEvent = { seq: number; task_revision: number; event_type: keyof typeof eventNames; status: TaskStatus;
  phase: keyof typeof phaseNames; reason_code: string | null; created_at: string;
  error_code?: string | null; error_category?: ErrorCategory | null; retry_reason?: RetryReason | null;
  retry_count?: RetryCount | null; retry_delay_seconds?: 10 | 30 | 90 | null }
export type EventPage = { task_id: string; items: TaskEvent[]; next_cursor: number; has_more: boolean }

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const text = (value: unknown): value is string => typeof value === 'string'
const id = (value: unknown): value is string => text(value) && value.length > 0 && value.length <= 64 && !/\s/.test(value)
const integer = (value: unknown, min = 0): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= min
const retryCount = (value: unknown) => value == null || (integer(value) && value <= 3)
const date = (value: unknown) => text(value) && Number.isFinite(Date.parse(value))
const nullableText = (value: unknown) => value === null || text(value)
const own = (map: object, value: unknown) => text(value) && Object.hasOwn(map, value)
function legacyTaskId(value: string): boolean {
  const match = /^legacy-(plot|explanation):([A-Za-z0-9_-]+)$/.exec(value)
  if (!match) return false
  try {
    const encoded = match[2]
    const bytes = atob(encoded.replace(/-/g, '+').replace(/_/g, '/'))
    if (btoa(bytes).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '') !== encoded) return false
    // Historical IDs are canonical base64url of a nonempty UTF-8 string.
    new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(bytes, char => char.charCodeAt(0)))
    return true
  } catch { return false }
}
export function isTaskId(value: unknown): value is string {
  return text(value) && (value.startsWith('legacy-') ? legacyTaskId(value) : id(value))
}
function version(value: unknown, parse: boolean | string = false): value is InputVersion {
  if (parse === 'review_ocr') return record(value) && value.kind === 'ocr_review' && value.workflow_version === 'ocr_review_v1' && isReviewSource(value.source) && !('setup_revision' in value) && !('output_language' in value)
  if (parse === 'prepare_dataset') return record(value) && value.kind === 'dataset_preparation' && value.workflow_version === 'dataset_preparation_v1' && isDatasetSource(value.source) && value.source.kind === 'dataset_version'
  if (parse === 'analysis_plan') return record(value) && Object.keys(value).length === 3 && value.kind === 'analysis_plan' && value.workflow_version === 'analysis_plan_v1' && isDatasetSource(value.source) && value.source.kind === 'prepared_dataset_version'
  if (parse === 'extract_dataset') return record(value) && value.kind === 'excel_structure' && id(value.structure_id) && text(value.source_sha256) && /^[a-f0-9]{64}$/.test(value.source_sha256) && text(value.parser_version) && value.parser_version.length > 0 && !('setup_revision' in value) && !('output_language' in value)
  if (parse) return record(value) && value.kind === 'parse_file' && id(value.parse_id) && text(value.source_sha256) && /^[a-f0-9]{64}$/.test(value.source_sha256) && text(value.parser_version) && value.parser_version.length > 0 && !('setup_revision' in value) && !('output_language' in value)
  if (record(value) && value.kind === 'dataset_analysis') return Object.keys(value).length === 4 && integer(value.setup_revision, 1) && value.output_language === 'zh-CN' && isDatasetSource(value.source)
  return record(value) && !('kind' in value) && !('source' in value) && integer(value.setup_revision, 1) && value.output_language === 'zh-CN'
}
export function sameInputVersion(a: InputVersion, b: InputVersion): boolean {
  if (a.kind === 'ocr_review' || b.kind === 'ocr_review') return a.kind === 'ocr_review' && b.kind === 'ocr_review' && a.workflow_version === b.workflow_version && sameReviewSource(a.source,b.source)
  if (a.kind === 'dataset_preparation' || b.kind === 'dataset_preparation') return a.kind === 'dataset_preparation' && b.kind === 'dataset_preparation' && a.workflow_version === b.workflow_version && sameSource(a.source, b.source)
  if (a.kind === 'analysis_plan' || b.kind === 'analysis_plan') return a.kind === 'analysis_plan' && b.kind === 'analysis_plan' && a.workflow_version === b.workflow_version && sameSource(a.source, b.source)
  if (a.kind === 'dataset_analysis' || b.kind === 'dataset_analysis') return a.kind === 'dataset_analysis' && b.kind === 'dataset_analysis' && a.setup_revision === b.setup_revision && a.output_language === b.output_language && sameSource(a.source, b.source)
  if (a.kind === 'excel_structure' && b.kind === 'excel_structure') return a.structure_id === b.structure_id && a.source_sha256 === b.source_sha256 && a.parser_version === b.parser_version
  if (a.kind === 'parse_file' && b.kind === 'parse_file') return a.parse_id === b.parse_id && a.source_sha256 === b.source_sha256 && a.parser_version === b.parser_version
  return a.kind === undefined && b.kind === undefined && a.setup_revision === b.setup_revision && a.output_language === b.output_language
}
export function isTask(value: unknown, projectId: string, taskId?: string): value is TaskView {
  if (!record(value) || !isTaskId(value.id) || (taskId !== undefined && value.id !== taskId) || value.project_id !== projectId
    || !own(taskNames, value.task_type) || !own(statusNames, value.status) || !own(phaseNames, value.phase)
    || !own(displayNames, value.display_status)
    || !nullableText(value.reason_code) || !nullableText(value.error_code) || !date(value.created_at)
    || !version(value.input_version, ['extract_dataset','prepare_dataset','analysis_plan','review_ocr'].includes(String(value.task_type)) ? String(value.task_type) : value.task_type === 'parse_file')) return false
  if (['parse_file', 'extract_dataset'].includes(String(value.task_type)) && (value.phase !== 'parse' || ['result_figure_id', 'result_explanation_id', 'result_report_id'].some(key => value[key] != null))) return false
  if (value.origin === 'legacy') {
    if (value.input_version.kind === 'dataset_analysis' || !legacyTaskId(value.id) || value.revision !== null || value.current_attempt !== null
      || value.retry_count !== null || value.updated_at !== null
      || value.task_type !== (value.id.startsWith('legacy-plot:') ? 'boxplot' : 'explanation')) return false
  } else if ((value.origin !== undefined && value.origin !== 'unified') || value.id.startsWith('legacy-')
    || !integer(value.revision, 1) || !integer(value.current_attempt) || !date(value.updated_at)
    || !retryCount(value.retry_count)) return false
  return ['result_figure_id', 'result_explanation_id', 'result_report_id'].every(key => value[key] == null || id(value[key]))
}
function sourceMatchesTask(task: TaskView, projection: TaskSource) {
  if (task.input_version.kind === 'ocr_review') return task.input_version.source.file_id === projection.file_id && projection.dataset_source === undefined
  return (task.input_version.kind === 'dataset_analysis' || task.input_version.kind === 'dataset_preparation' || task.input_version.kind === 'analysis_plan') ? sameSource(task.input_version.source, projection.dataset_source) : projection.dataset_source === undefined
}
function source(value: unknown, parse = false): value is TaskSource {
  return record(value) && id(value.file_id) && text(value.filename) && (parse ? value.analysis_run_id === null : id(value.analysis_run_id)) && typeof value.is_current === 'boolean' && (!('dataset_source' in value) || isDatasetSource(value.dataset_source) && value.dataset_source.file_id === value.file_id)
}
export function isTaskPage(value: unknown, projectId: string, page: number): value is TaskPage {
  return record(value) && value.project_id === projectId && value.page === page && value.page_size === 10
    && integer(value.total) && Array.isArray(value.items) && value.items.length <= 10 && value.items.length <= value.total
    && value.items.every(item => record(item) && isTask(item.task, projectId) && source(item.source, ['parse_file', 'extract_dataset', 'prepare_dataset', 'analysis_plan', 'review_ocr'].includes(item.task.task_type)) && sourceMatchesTask(item.task, item.source))
    && new Set(value.items.map(item => item.task.id)).size === value.items.length
}
export function isTaskWait(value: unknown): value is TaskWait {
  return record(value) && id(value.id) && ['ocr_review_confirmation', 'dataset_preparation_confirmation', 'analysis_plan_confirmation', 'budget_confirmation', 'submission_unknown', 'unsupported_input', 'unsupported_confirmation'].includes(String(value.kind))
    && ['open', 'resolved', 'superseded'].includes(String(value.status)) && integer(value.task_revision, 1)
    && version(value.input_version, value.kind === 'ocr_review_confirmation' ? 'review_ocr' : value.kind === 'dataset_preparation_confirmation' ? 'prepare_dataset' : value.kind === 'analysis_plan_confirmation' ? 'analysis_plan' : false) && nullableText(value.reason_code) && nullableText(value.error_code)
    && date(value.created_at) && (value.resolved_at === null || date(value.resolved_at))
}
export function isWorkspace(value: unknown, projectId: string, taskId: string): value is TaskWorkspace {
  if (!record(value) || !isTask(value.task, projectId, taskId) || !source(value.source, ['parse_file', 'extract_dataset', 'prepare_dataset', 'analysis_plan', 'review_ocr'].includes(value.task.task_type)) || !record(value.artifacts)
    || (value.wait !== null && !isTaskWait(value.wait)) || !Array.isArray(value.allowed_actions)
    || !value.allowed_actions.every(action => action === 'resume' || action === 'retry' || action === 'approve' || action === 'revise')
    || new Set(value.allowed_actions).size !== value.allowed_actions.length) return false
  if (value.task.origin === 'legacy' && (value.wait !== null || value.allowed_actions.length !== 0)) return false
  if (!sourceMatchesTask(value.task, value.source)) return false
  if (value.wait && !sameInputVersion(value.wait.input_version, value.task.input_version)) return false
  const { figure, explanation, report } = value.artifacts
  if (value.task.task_type === 'review_ocr') return figure === null && explanation === null && report === null && value.task.input_version.kind === 'ocr_review' && value.task.input_version.source.file_id === value.source.file_id && value.allowed_actions.every(action=>['retry','approve','revise'].includes(action)) && (!value.allowed_actions.some(a=>a==='approve'||a==='revise') || value.task.status==='waiting_confirmation' && value.wait?.status==='open' && value.wait.kind==='ocr_review_confirmation' && value.wait.task_revision===value.task.revision)
  if (value.task.task_type === 'prepare_dataset') return (!value.allowed_actions.some(a => a === 'approve' || a === 'revise') || value.task.status === 'waiting_confirmation' && value.wait?.status === 'open' && value.wait.kind === 'dataset_preparation_confirmation' && value.wait.task_revision === value.task.revision) && figure === null && explanation === null && report === null && value.allowed_actions.every(action => action === 'retry' || action === 'approve' || action === 'revise')
  if (value.task.task_type === 'analysis_plan') return value.task.phase === 'plan' && (!value.allowed_actions.some(a => a === 'approve' || a === 'revise') || value.task.status === 'waiting_confirmation' && value.wait?.status === 'open' && value.wait.kind === 'analysis_plan_confirmation' && value.wait.task_revision === value.task.revision) && figure === null && explanation === null && report === null && value.allowed_actions.every(action => action === 'retry' || action === 'approve' || action === 'revise')
  if (['parse_file', 'extract_dataset'].includes(value.task.task_type)) return value.wait === null && value.allowed_actions.every(action => action === 'retry') && figure === null && explanation === null && report === null
  if (value.task.origin === 'legacy' && (report !== null
    || (value.task.task_type === 'boxplot' ? explanation !== null : figure !== null))) return false
  const base = `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(value.source.file_id)}/analysis-runs/${encodeURIComponent(value.source.analysis_run_id ?? '')}`
  return (figure === null || (record(figure) && text(figure.title) && text(figure.caption) && id(value.task.result_figure_id)
    && figure.download_url === `${base}/figures/${encodeURIComponent(value.task.result_figure_id)}/download`))
    && (report === null || (record(report) && text(report.filename) && id(value.task.result_report_id)
      && report.download_url === `${base}/report/${encodeURIComponent(value.task.result_report_id)}/download`))
    && (explanation === null || (record(explanation) && Array.isArray(explanation.sections)
      && explanation.sections.every(section => record(section) && text(section.key) && text(section.title) && text(section.text))
      && Array.isArray(explanation.limitations) && explanation.limitations.every(text)))
}
export function isEventPage(value: unknown, taskId: string, after: number): value is EventPage {
  if (!record(value) || value.task_id !== taskId || !Array.isArray(value.items) || value.items.length > 50
    || !integer(value.next_cursor, after) || typeof value.has_more !== 'boolean') return false
  let previous = after
  for (const event of value.items) {
    if (!record(event) || !integer(event.seq, previous + 1) || !integer(event.task_revision, 1)
      || !own(eventNames, event.event_type) || !own(statusNames, event.status) || !own(phaseNames, event.phase)
      || !nullableText(event.reason_code) || !date(event.created_at)
      || (event.error_code != null && !text(event.error_code))
      || (event.error_category != null && !errorCategories.some(category => category === event.error_category))
      || (event.retry_reason != null && !retryReasons.some(reason => reason === event.retry_reason))
      || !retryCount(event.retry_count)
      || (event.retry_delay_seconds != null && ![10, 30, 90].includes(event.retry_delay_seconds as number))) return false
    previous = event.seq
  }
  return value.next_cursor === previous && (!value.has_more || value.items.length > 0)
}
export function taskDisplayName(task: TaskView) {
  // Waiting and terminal lifecycle states always take priority over a retained phase.
  return task.status === 'running' ? displayNames[task.display_status] : statusNames[task.status]
}
export function taskPhaseName(task: TaskView) {
  if (task.task_type === 'review_ocr') return task.phase === 'verify' ? '生成核对版本' : '逐条核对'
  return task.task_type === 'prepare_dataset' && task.phase === 'plan' ? '整理预览' : phaseNames[task.phase]
}
