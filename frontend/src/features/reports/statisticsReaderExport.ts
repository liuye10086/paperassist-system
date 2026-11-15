import { hash, object, text } from '../figure-workbench/contracts'
import type { Member, ReportNarrative } from '../research-results/contracts'

export const statisticsReaderPolicy = 'statistics_reader_export_v1'
export const statisticsReaderEngine = 'statistics_reader_report_v1'
export type StatisticsReportTask = 'word_report' | 'collection_word_report'
export type ReaderExportMarker = {
  policy: typeof statisticsReaderPolicy
  context_id: string
  report_version_id: string
  task_id: string
  task_type: StatisticsReportTask
  origin: 'saved_explanation_reuse'
  adapter_version: 'statistics_saved_explanation_v1'
}
export type ReaderExportFiles = { reader_export: ReaderExportMarker; members: Member[] }
export type StatisticsReaderExport = ReaderExportFiles & { reader_report: ReportNarrative }

const memberRoles = ['docx', 'xlsx', 'zip'] as const
const narrativeSections = ['abstract', 'design_and_data', 'quality_control', 'methods_summary', 'key_findings', 'limitations', 'reader_cautions'] as const
const identifier = (value: unknown): value is string => text(value) && /^[A-Za-z0-9_-]{1,64}$/.test(value)
const statement = (value: unknown): value is string => text(value) && !!value.trim()

export function hasReaderProjection(value: Record<string, unknown>) {
  return value.reader_export != null || value.reader_report != null || value.members != null
}

export function validReaderExportMarker(value: unknown, taskType: unknown, taskId?: string): value is ReaderExportMarker {
  return object(value) && (taskType === 'word_report' || taskType === 'collection_word_report')
    && value.policy === statisticsReaderPolicy && value.origin === 'saved_explanation_reuse'
    && value.adapter_version === 'statistics_saved_explanation_v1' && value.task_type === taskType
    && identifier(value.context_id) && identifier(value.report_version_id) && identifier(value.task_id)
    && (taskId === undefined || value.task_id === taskId)
}

export function validReaderExportFiles(value: unknown, projectId: string, taskType: unknown, taskId?: string): value is ReaderExportFiles & Record<string, unknown> {
  if (!object(value) || !validReaderExportMarker(value.reader_export, taskType, taskId)
    || !Array.isArray(value.members) || value.members.length !== memberRoles.length) return false
  const prefix = `/api/v1/projects/${encodeURIComponent(projectId)}/research-reports/${value.reader_export.report_version_id}/members/`
  if (!value.members.every(member => object(member) && identifier(member.id) && statement(member.key)
    && memberRoles.some(role => role === member.role) && member.role === member.format
    && hash(member.sha256) && Number.isSafeInteger(member.size_bytes) && Number(member.size_bytes) > 0
    && member.download_url === `${prefix}${member.id}/download`)) return false
  const members = value.members as Member[]
  if (new Set(members.map(member => member.id)).size !== memberRoles.length
    || new Set(members.map(member => member.role)).size !== memberRoles.length) return false
  const word = members.find(member => member.role === 'docx')!
  return (value.sha256 === undefined || value.sha256 === word.sha256)
    && (value.size_bytes === undefined || value.size_bytes === word.size_bytes)
}

export function validStatisticsReaderExport(value: unknown, projectId: string, taskType: unknown, taskId?: string, figureCount?: number): value is StatisticsReaderExport {
  if (!object(value) || !validReaderExportFiles(value, projectId, taskType, taskId) || !object(value.reader_report)) return false
  const report = value.reader_report
  const narrative = report.narrative
  return report.origin === 'saved_explanation_reuse' && object(narrative)
    && narrativeSections.every(section => statement(narrative[section]))
    && Array.isArray(report.figures) && (figureCount === undefined || report.figures.length === figureCount)
    && report.figures.every((figure, index) => object(figure) && figure.number === index + 1
      && ['title', 'reading', 'observations', 'interpretation', 'limitations', 'caption'].every(key => statement(figure[key])))
}

export function statisticsReportTaskHref(projectId: string, taskId: string, view: 'result' | 'actions' | 'events' = 'result') {
  return '#' + new URLSearchParams({ project: projectId, section: 'tasks', task: taskId, view })
}

export function statisticsFormalReportHref(projectId: string, reportId: string) {
  return '#' + new URLSearchParams({ project: projectId, section: 'artifacts', view: 'research-reports', artifact: reportId })
}
