export type Budget = {
  scope_type: 'user' | 'project' | 'task'; limit_micro_usd: number | null; revision: number
  estimated_micro_usd: number; reserved_micro_usd: number; available_micro_usd: number | null; exceeded: boolean
}
export type ModelCall = {
  id: string; task_type: 'boxplot' | 'explanation' | 'word_report'; model: string
  status: 'reserved' | 'submitting' | 'submitted' | 'submission_unknown' | 'completed' | 'failed' | 'released'
  provider_status: string | null; usage_status: 'pending' | 'estimated'; estimated_cost_micro_usd: number | null
  created_at: string; updated_at: string
}
export type ProjectUsage = {
  currency: 'USD'; period: 'cumulative'; enforcement_scope: 'unified_only'
  user_budget: Budget; project_budget: Budget; estimated_micro_usd: number; reserved_micro_usd: number
  pending_count: number; items: ModelCall[]; total: number; page: number; page_size: number
}
export type TaskUsage = ProjectUsage & { task_budget: Budget }
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const nonnegative = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
const nullableAmount = (value: unknown) => value === null || nonnegative(value)
const date = (value: unknown) => typeof value === 'string' && Number.isFinite(Date.parse(value))
function isBudget(value: unknown, scope: Budget['scope_type']): value is Budget {
  return record(value) && value.scope_type === scope && nullableAmount(value.limit_micro_usd)
    && nonnegative(value.revision) && nonnegative(value.estimated_micro_usd) && nonnegative(value.reserved_micro_usd)
    && (value.available_micro_usd === null || (typeof value.available_micro_usd === 'number'
      && Number.isSafeInteger(value.available_micro_usd))) && typeof value.exceeded === 'boolean'
}
function isCall(value: unknown): value is ModelCall {
  return record(value) && typeof value.id === 'string' && value.id.length > 0 && typeof value.model === 'string'
    && value.model.length > 0 && ['boxplot', 'explanation', 'word_report'].includes(String(value.task_type))
    && ['reserved', 'submitting', 'submitted', 'submission_unknown', 'completed', 'failed', 'released'].includes(String(value.status))
    && (value.provider_status === null || typeof value.provider_status === 'string')
    && ['pending', 'estimated'].includes(String(value.usage_status)) && nullableAmount(value.estimated_cost_micro_usd)
    && date(value.created_at) && date(value.updated_at)
}
export function isProjectUsage(value: unknown, page: number): value is ProjectUsage {
  return record(value) && value.currency === 'USD' && value.period === 'cumulative' && value.enforcement_scope === 'unified_only'
    && isBudget(value.user_budget, 'user') && isBudget(value.project_budget, 'project')
    && nonnegative(value.estimated_micro_usd) && nonnegative(value.reserved_micro_usd) && nonnegative(value.pending_count)
    && Array.isArray(value.items) && value.items.length <= 10 && value.items.every(isCall)
    && nonnegative(value.total) && value.items.length <= value.total && value.page === page && value.page_size === 10
}
export function isTaskUsage(value: unknown, page: number): value is TaskUsage {
  return record(value) && isBudget(value.task_budget, 'task') && isProjectUsage(value, page)
}
/** Exact fixed-point rendering; accounting stays in integer micro USD. */
export function formatMicroUsd(value: number): string {
  const integer = BigInt(value)
  const absolute = integer < 0n ? -integer : integer
  return `USD ${integer < 0n ? '-' : ''}${absolute / 1_000_000n}.${String(absolute % 1_000_000n).padStart(6, '0')}`
}
