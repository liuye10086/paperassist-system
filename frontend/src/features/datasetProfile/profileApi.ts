import { apiFetch } from '../../shared/api/client'
import { isDatasetSource, sameSource, type DatasetAnalysisSource } from '../analysis/datasetSource'
import { isDataset, isRows } from '../datasets/datasetApi'
import { columnLetter, isPreparedVersion } from '../datasetPreparation/preparationApi'
import { isQualityVersion, preparedStructure } from '../datasetPreparation/qualityApi'
import { issueKinds, type Profile, type ProfileBinding, type IssueKind, type IssuePage, type LocationRows } from './profileTypes'

const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
const count = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0
const text = (v: unknown): v is string => typeof v === 'string'
const nullableText = (v: unknown) => v === null || text(v)
const cellValue = (v: unknown) => nullableText(v) || typeof v === 'boolean'
const counts = (v: unknown) => object(v) && Object.values(v).every(count)
const kinds = ['blank', 'number', 'text', 'boolean', 'date', 'datetime', 'time', 'duration', 'error', 'formula']
const sourceKeys = ['kind', 'dataset_id', 'structure_id', 'dataset_version', 'file_id', 'sheet_index', 'sheet_name', 'source_sha256', 'parser_version'] as const
export function matchesBinding(source: unknown, binding: ProfileBinding): source is DatasetAnalysisSource {
 return isDatasetSource(source) && sourceKeys.every(key => source[key] === binding[key]) && (!binding.source || sameSource(source, binding.source))
}
export function isProfile(v: unknown, binding: ProfileBinding): v is Profile {
 if (!object(v) || v.schema_version !== 1 || v.rules_version !== 'excel_profile_v1' || !matchesBinding(v.source, binding) || !text(v.filename) || v.sheet_name !== binding.sheet_name || !nullableText(v.data_range)
  || !['record_count', 'blank_row_count', 'duplicate_groups', 'duplicate_rows', 'duplicate_extra_rows'].every(key => count(v[key])) || Number(v.blank_row_count) > Number(v.record_count)
  || !Array.isArray(v.fields) || v.fields.length > 256) return false
 return new Set(v.fields.map(f => object(f) ? f.column : null)).size === v.fields.length && v.fields.every(f => {
  if (!object(f) || !count(f.column) || f.column < 1 || f.column > 256 || f.letter !== columnLetter(f.column) || !text(f.name) || !object(f.unit) || !['confirmed', 'unconfirmed'].includes(String(f.unit.status)) || !nullableText(f.unit.value)
   || !counts(f.type_counts) || !object(f.type_counts) || !Object.keys(f.type_counts).every(k => kinds.includes(k)) || !['missing_count', 'non_missing_count', 'distinct_count'].every(k => count(f[k]))
   || Number(f.missing_count) + Number(f.non_missing_count) !== v.record_count || Number(f.distinct_count) > Number(f.non_missing_count) || !counts(f.issue_counts) || !object(f.issue_counts) || !Object.keys(f.issue_counts).every(k => issueKinds.includes(k as IssueKind))
   || !object(f.time_candidates) || !['valid_count', 'invalid_count', 'ambiguous_count'].every(k => count((f.time_candidates as Record<string, unknown>)[k]))) return false
  const n = f.numeric
  if (n !== null && (!object(n) || !['ok', 'unavailable'].includes(String(n.status)) || !count(n.n) || !count(n.outlier_count) || !['mean', 'std', 'min', 'max', 'q1', 'median', 'q3', 'iqr'].every(k => n[k] === null || typeof n[k] === 'number' && Number.isFinite(n[k]))
   || !nullableText(n.lower_fence) || !nullableText(n.upper_fence) || !Array.isArray(n.warnings) || !n.warnings.every(k => ['numeric_precision', 'numeric_unavailable', 'std_insufficient', 'metric_unavailable'].includes(String(k))))) return false
  const c = f.categories
  if (c !== null && (!object(c) || !count(c.distinct_count) || !count(c.other_count) || !Array.isArray(c.top) || c.top.length > 10 || !c.top.every(item => object(item) && count(item.count) && (item.kind === 'text' && text(item.value) || item.kind === 'boolean' && typeof item.value === 'boolean')))) return false
  return Array.isArray(f.temporal) && f.temporal.length <= 4 && new Set(f.temporal.map(item => object(item) ? item.kind : null)).size === f.temporal.length && f.temporal.every(item => object(item) && ['date', 'datetime', 'time', 'duration'].includes(String(item.kind)) && count(item.count) && text(item.min) && text(item.max))
 })
}
export function isIssuePage(v: unknown, source: DatasetAnalysisSource, kind: IssueKind, column: number | null, page: number): v is IssuePage {
 if (!object(v) || !sameSource(v.source as DatasetAnalysisSource, source) || v.rules_version !== 'excel_profile_v1' || v.kind !== kind || v.column !== column || v.page !== page || v.page_size !== 20 || !count(v.total) || !Array.isArray(v.items)
  || v.items.length !== Math.max(0, Math.min(20, v.total - (page - 1) * 20))) return false
 return v.items.every(item => object(item) && count(item.row) && item.row > 0 && (kind === 'duplicate'
  ? item.column === null && item.coordinate === null && item.kind === null && item.value === null && count(item.group_first_row) && item.group_first_row > 0 && item.group_first_row <= item.row && count(item.group_size) && item.group_size >= 2
  : item.column === column && item.coordinate === `${columnLetter(column!)}${item.row}` && (item.kind === null || kinds.includes(String(item.kind))) && cellValue(item.value) && item.group_first_row === null && item.group_size === null))
}
export function isLocationRows(v: unknown, source: DatasetAnalysisSource, start: number, target: number, fields: Profile['fields']): v is LocationRows {
 let finalRow = 100000
 if (!object(v) || !object(v.dataset) || v.dataset.id !== source.dataset_id || v.start_row !== start || v.limit !== 20 || !count(v.total_rows) || typeof v.has_more !== 'boolean' || !Array.isArray(v.rows)) return false
 if (source.kind === 'dataset_version') {
  if (!isDataset(v.dataset, source.file_id, source.structure_id) || v.dataset.version !== source.dataset_version || v.dataset.sheet_index !== source.sheet_index || v.dataset.sheet_name !== source.sheet_name || !isRows(v, v.dataset, start)) return false
 } else {
  if (!isPreparedVersion(v.dataset, source.file_id) || !sameSource(v.dataset.source, source)) return false
  const range = /^([A-Z]+)(\d+):([A-Z]+)(\d+)$/.exec(preparedStructure(v.dataset).data_range)
  if (!range) return false
  const first = Number(range[2]); const last = Number(range[4])
  finalRow = last
  if (start < first || target > last) return false
  if (isQualityVersion(v.dataset)) {
   if (v.total_rows !== v.dataset.summary.retained_record_count || v.rows.length > 20 || v.rows.length > v.total_rows || (v.has_more ? !count(v.next_start_row) || !v.rows.length || !object(v.rows[v.rows.length - 1]) || Number(v.next_start_row) <= Number(v.rows[v.rows.length - 1].row) : v.next_start_row !== null)) return false
  } else if (v.total_rows !== last - first + 1 || v.has_more !== (start + 19 < last) || v.rows.length !== Math.max(0, Math.min(20, last - start + 1))) return false
 }
 const allowed = new Set(fields.map(f => f.column))
 const rows = v.rows; const sparse = source.kind === 'prepared_dataset_version' && source.schema_version === 2
 return rows.length <= 20 && rows.some(r => object(r) && r.row === target) && rows.every((r, i) => object(r) && (sparse ? count(r.row) && r.row >= start && r.row <= finalRow && (!i || r.row > rows[i - 1].row) : r.row === start + i) && Array.isArray(r.cells) && new Set(r.cells.map(c => object(c) ? c.column : null)).size === r.cells.length
  && r.cells.every(c => object(c) && c.row === r.row && count(c.column) && (source.kind === 'dataset_version' || allowed.has(c.column)) && c.coordinate === `${columnLetter(c.column)}${r.row}` && kinds.includes(String(c.kind)) && cellValue(c.value)))
}
export const profileBase = (base: string, id: string) => `${base}/dataset-versions/${encodeURIComponent(id)}`
export async function profileRequest<T>(url: string, controller: AbortController, valid: (v: unknown) => v is T): Promise<T> {
 let timer = 0; let aborted = () => {}
 try {
  return await Promise.race([(async () => { const response = await apiFetch(url, { signal: controller.signal }); const value: unknown = await response.json().catch(() => null)
   if (controller.signal.aborted) throw new DOMException('aborted', 'AbortError')
   if (!response.ok || !valid(value)) throw new Error('数据概况读取失败，请重试。')
   return value
  })(), new Promise<never>((_, reject) => { aborted = () => reject(new DOMException('aborted', 'AbortError')); controller.signal.addEventListener('abort', aborted, { once: true }); timer = window.setTimeout(() => controller.abort(), 30_000); if (controller.signal.aborted) aborted() })])
 } finally { window.clearTimeout(timer); controller.signal.removeEventListener('abort', aborted) }
}
