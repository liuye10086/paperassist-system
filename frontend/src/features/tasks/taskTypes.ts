export const taskNames = { boxplot: '箱线图生成', explanation: 'AI 分析解释', word_report: 'Word 报告导出' }
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
export type InputVersion = { setup_revision: number; output_language: 'zh-CN' }
export type TaskView = { id: string; project_id: string; task_type: TaskType; status: TaskStatus; phase: keyof typeof phaseNames;
  display_status: keyof typeof displayNames; revision: number; current_attempt: number; reason_code: string | null;
  error_code: string | null; created_at: string; updated_at: string; input_version: InputVersion;
  result_figure_id?: string | null; result_explanation_id?: string | null; result_report_id?: string | null }
export type TaskSource = { file_id: string; filename: string; analysis_run_id: string; is_current: boolean }
export type TaskItem = { task: TaskView; source: TaskSource }
export type TaskPage = { project_id: string; items: TaskItem[]; total: number; page: number; page_size: number }
export type TaskOperation = 'resume' | 'retry'
export type TaskWait = { id: string; kind: 'budget_confirmation' | 'submission_unknown' | 'unsupported_input' | 'unsupported_confirmation';
  status: 'open' | 'resolved' | 'superseded'; task_revision: number; input_version: InputVersion;
  reason_code: string | null; error_code: string | null; created_at: string; resolved_at: string | null }
export type TaskWorkspace = TaskItem & { wait: TaskWait | null; allowed_actions: TaskOperation[]; artifacts: {
  figure: { title: string; caption: string; download_url: string } | null;
  explanation: { sections: { key: string; title: string; text: string }[]; limitations: string[] } | null;
  report: { filename: string; download_url: string } | null } }
export type TaskEvent = { seq: number; task_revision: number; event_type: keyof typeof eventNames; status: TaskStatus;
  phase: keyof typeof phaseNames; reason_code: string | null; created_at: string }
export type EventPage = { task_id: string; items: TaskEvent[]; next_cursor: number; has_more: boolean }

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const text = (value: unknown): value is string => typeof value === 'string'
const id = (value: unknown): value is string => text(value) && value.length > 0 && value.length <= 64 && !/\s/.test(value)
const integer = (value: unknown, min = 0): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= min
const date = (value: unknown) => text(value) && Number.isFinite(Date.parse(value))
const nullableText = (value: unknown) => value === null || text(value)
const own = (map: object, value: unknown) => text(value) && Object.hasOwn(map, value)
function version(value: unknown): value is InputVersion {
  return record(value) && integer(value.setup_revision, 1) && value.output_language === 'zh-CN'
}
export function isTask(value: unknown, projectId: string, taskId?: string): value is TaskView {
  if (!record(value) || !id(value.id) || (taskId !== undefined && value.id !== taskId) || value.project_id !== projectId
    || !own(taskNames, value.task_type) || !own(statusNames, value.status) || !own(phaseNames, value.phase)
    || !own(displayNames, value.display_status) || !integer(value.revision, 1) || !integer(value.current_attempt)
    || !nullableText(value.reason_code) || !nullableText(value.error_code) || !date(value.created_at) || !date(value.updated_at)
    || !version(value.input_version)) return false
  return ['result_figure_id', 'result_explanation_id', 'result_report_id'].every(key => value[key] == null || id(value[key]))
}
function source(value: unknown): value is TaskSource {
  return record(value) && id(value.file_id) && text(value.filename) && id(value.analysis_run_id) && typeof value.is_current === 'boolean'
}
export function isTaskPage(value: unknown, projectId: string, page: number): value is TaskPage {
  return record(value) && value.project_id === projectId && value.page === page && value.page_size === 10
    && integer(value.total) && Array.isArray(value.items) && value.items.length <= 10 && value.items.length <= value.total
    && value.items.every(item => record(item) && isTask(item.task, projectId) && source(item.source))
    && new Set(value.items.map(item => item.task.id)).size === value.items.length
}
function wait(value: unknown): value is TaskWait {
  return record(value) && id(value.id) && ['budget_confirmation', 'submission_unknown', 'unsupported_input', 'unsupported_confirmation'].includes(String(value.kind))
    && ['open', 'resolved', 'superseded'].includes(String(value.status)) && integer(value.task_revision, 1)
    && version(value.input_version) && nullableText(value.reason_code) && nullableText(value.error_code)
    && date(value.created_at) && (value.resolved_at === null || date(value.resolved_at))
}
export function isWorkspace(value: unknown, projectId: string, taskId: string): value is TaskWorkspace {
  if (!record(value) || !isTask(value.task, projectId, taskId) || !source(value.source) || !record(value.artifacts)
    || (value.wait !== null && !wait(value.wait)) || !Array.isArray(value.allowed_actions)
    || !value.allowed_actions.every(action => action === 'resume' || action === 'retry')
    || new Set(value.allowed_actions).size !== value.allowed_actions.length) return false
  const { figure, explanation, report } = value.artifacts
  const base = `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(value.source.file_id)}/analysis-runs/${encodeURIComponent(value.source.analysis_run_id)}`
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
      || !nullableText(event.reason_code) || !date(event.created_at)) return false
    previous = event.seq
  }
  return value.next_cursor === previous && (!value.has_more || value.items.length > 0)
}
export function taskDisplayName(task: TaskView) {
  // Waiting and terminal lifecycle states always take priority over a retained phase.
  return task.status === 'running' ? displayNames[task.display_status] : statusNames[task.status]
}
