import { intakeRequest, jsonRequest, projectBase } from '../research-intake/api'
import type { DeliveryKind } from '../research-intake/contracts'

export const customerBase = (projectId: string) => `${projectBase(projectId)}/customer-workspace`

export type Feedback = { id: string; message: string; created_at: string }
export type MaterialSubmission = {
  id: string
  requirement_version: number
  file_ids: string[]
  files: { id: string; name: string }[]
  note: string | null
  created_at: string
}
export type Progress = {
  status: 'draft' | 'pending_assignment' | 'assigned' | 'analyzing' | 'needs_materials' | 'materials_submitted' | 'delivered'
  requirement_version: number | null
  submitted_at: string | null
  updated_at: string | null
  note: string | null
  feedback: Feedback[]
  /** Every supplement submitted for the current requirement version, kept after reassignment. */
  submissions?: MaterialSubmission[]
}
export type SummaryTarget = {
  delivery_id: string | null
  snapshot_id: string | null
  manuscript_id: string | null
  revision: number | null
  round_id: string | null
  item_id: string | null
  template_version_id: string | null
  view: string | null
  mode: 'supplement' | null
}
/** Landing for “打开项目” (接口设计第一节 2). Only `step` and `target` are used for routing. */
export type Summary = {
  project_id: string
  project_type: 'research' | 'sci' | 'thesis'
  kind: string
  actor: 'customer' | 'analyst' | 'admin' | 'none'
  step: string
  target: SummaryTarget
  message_key: string
  message_params: Record<string, number | string>
  updated_at: string | null
}

// `target` field → workspace address parameter; empty values are never written.
const summaryParams: [keyof SummaryTarget, string][] = [
  ['delivery_id', 'delivery'], ['snapshot_id', 'snapshot'], ['manuscript_id', 'manuscript'], ['revision', 'revision'],
  ['round_id', 'round'], ['item_id', 'item'], ['template_version_id', 'template'], ['view', 'view'], ['mode', 'mode'],
]

/** Address parameters for a summary landing, or null when the response is not one for this project. */
export function summaryRoute(value: unknown, projectId: string): { step: string; params: URLSearchParams } | null {
  const summary = value as Summary | null
  if (!summary || typeof summary !== 'object' || summary.project_id !== projectId || typeof summary.step !== 'string' ||
    !summary.target || typeof summary.target !== 'object') return null
  const params = new URLSearchParams()
  for (const [field, key] of summaryParams) {
    const item = summary.target[field]
    if (typeof item === 'string' && item) params.set(key, item)
    else if (typeof item === 'number' && Number.isSafeInteger(item) && item > 0) params.set(key, String(item))
    else if (item !== null && item !== undefined) return null
  }
  if (summary.step === 'school' || (summary.project_type === 'thesis' && summary.step === 'details' &&
      (summary.kind === 'template_conflicts' || summary.kind === 'template_needed'))) {
    if (summary.project_type !== 'thesis') return null
    const view = params.get('view') ?? 'list'
    const panel = view === 'confirm' ? 'detail' : view
    if (!['upload','list','detail'].includes(panel) || (panel === 'detail' && !params.has('template'))) return null
    params.set('schoolView', panel)
    params.delete('view')
    return {step:'school', params}
  }
  return { step: summary.step, params }
}

/** “11-18 15:02” in the interface language, used beside requests and submissions. */
export function shortTime(value: string | null | undefined, locale: string) {
  const time = value ? new Date(value) : null
  return time && !Number.isNaN(time.getTime())
    ? time.toLocaleString(locale, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''
}

export function latestSubmission(progress: Progress | null | undefined) {
  return (progress?.submissions ?? []).reduce<MaterialSubmission | null>((latest, item) =>
    !latest || Date.parse(item.created_at) > Date.parse(latest.created_at) ? item : latest, null)
}

// The landing only chooses where to open; the customer can already work on project details,
// so a slow read is treated as unavailable instead of waiting for the standard request bound.
export const SUMMARY_TIMEOUT_MS = 15_000

export async function readSummary(projectId: string, signal: AbortSignal) {
  return await intakeRequest<unknown>(customerBase(projectId) + '/summary', { signal }, SUMMARY_TIMEOUT_MS)
}

export async function submitMaterials(projectId: string, body: { requirement_version: number; file_ids: string[]; note: string | null },
  key: string, signal: AbortSignal) {
  const result = await intakeRequest<MaterialSubmission>(customerBase(projectId) + '/material-submissions',
    { ...jsonRequest(body, key), signal })
  if (!result?.id || !Array.isArray(result.file_ids) || !Number.isFinite(Date.parse(result.created_at))) {
    throw new Error('Invalid material submission receipt')
  }
  return result
}
export type DeliverySummary = {
  id: string
  delivery_id: string
  title: string
  kind: DeliveryKind
  revision: number
  published_at: string
  member_count: number
}
export type DeliveryMember = { id: string; name: string; format: string; size_bytes: number; download_url: string }
export type DeliveryDetail = DeliverySummary & {
  members: DeliveryMember[]
  package_url: string | null
  feedback: Feedback[]
}
