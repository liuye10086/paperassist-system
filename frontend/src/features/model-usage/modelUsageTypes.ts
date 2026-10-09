export type Budget = {
  scope_type: 'user' | 'project' | 'task'; limit_micro_usd: number | null; revision: number
  estimated_micro_usd: number; accounted_micro_usd?: number; reserved_micro_usd: number; available_micro_usd: number | null; exceeded: boolean
}
export type CallReconciliation = {
  status: 'pending' | 'partial' | 'reconciled' | 'not_applicable'
  token_micro_usd: number | null; tool_micro_usd: number | null; tool_applicable: boolean
  actual_micro_usd: number | null; reconciled_at: string | null
}
export type ReconciliationSummary = {
  actual_micro_usd: number; reconciled_count: number; partial_count: number; pending_count: number
}
export type ModelCall = {
  id: string; task_type: 'boxplot' | 'explanation' | 'word_report'; model: string
  status: 'reserved' | 'submitting' | 'submitted' | 'submission_unknown' | 'completed' | 'failed' | 'released'
  provider_status: string | null; usage_status: 'pending' | 'estimated'; estimated_cost_micro_usd: number | null
  created_at: string; updated_at: string; reconciliation?: CallReconciliation
}
export type ProjectUsage = {
  currency: 'USD'; period: 'cumulative'; enforcement_scope: 'unified_only'
  user_budget: Budget; project_budget: Budget; estimated_micro_usd: number; reserved_micro_usd: number
  pending_count: number; items: ModelCall[]; total: number; page: number; page_size: number
  accounted_micro_usd?: number; reconciliation?: ReconciliationSummary
}
export type TaskUsage = ProjectUsage & { task_budget: Budget }
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const nonnegative = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
const nullableAmount = (value: unknown) => value === null || nonnegative(value)
const date = (value: unknown) => typeof value === 'string' && Number.isFinite(Date.parse(value))
const optionalAmount = (value: Record<string, unknown>, key: string) => !Object.hasOwn(value, key) || nonnegative(value[key])
function isBudget(value: unknown, scope: Budget['scope_type']): value is Budget {
  return record(value) && value.scope_type === scope && nullableAmount(value.limit_micro_usd)
    && nonnegative(value.revision) && nonnegative(value.estimated_micro_usd) && nonnegative(value.reserved_micro_usd)
    && optionalAmount(value, 'accounted_micro_usd')
    && (value.available_micro_usd === null || (typeof value.available_micro_usd === 'number'
      && Number.isSafeInteger(value.available_micro_usd))) && typeof value.exceeded === 'boolean'
}
function isCallReconciliation(value: unknown, status: unknown): value is CallReconciliation {
  if (!record(value) || !nullableAmount(value.token_micro_usd) || !nullableAmount(value.tool_micro_usd)
    || !nullableAmount(value.actual_micro_usd) || typeof value.tool_applicable !== 'boolean'
    || (!value.tool_applicable && value.tool_micro_usd !== null)) return false
  const tokenKnown = value.token_micro_usd !== null
  const toolKnown = value.tool_micro_usd !== null
  if (value.status === 'not_applicable' || value.status === 'pending') {
    return (value.status === 'not_applicable' ? status === 'released' : status !== 'released')
      && !tokenKnown && !toolKnown && value.actual_micro_usd === null && value.reconciled_at === null
  }
  if (!['completed', 'failed'].includes(String(status)) || !date(value.reconciled_at)
    || !nonnegative(value.actual_micro_usd)) return false
  const complete = tokenKnown && (!value.tool_applicable || toolKnown)
  if (value.status === 'reconciled' ? !complete : value.status !== 'partial' || complete || (!tokenKnown && !toolKnown)) return false
  return BigInt(value.actual_micro_usd) === BigInt(value.token_micro_usd as number | null ?? 0)
    + BigInt(value.tool_micro_usd as number | null ?? 0)
}
function isReconciliationSummary(value: unknown, total: number): value is ReconciliationSummary {
  return record(value) && nonnegative(value.actual_micro_usd) && nonnegative(value.reconciled_count)
    && nonnegative(value.partial_count) && nonnegative(value.pending_count)
    && BigInt(value.reconciled_count) + BigInt(value.partial_count) + BigInt(value.pending_count) <= BigInt(total)
    && (value.reconciled_count + value.partial_count > 0 || value.actual_micro_usd === 0)
}
function isCall(value: unknown): value is ModelCall {
  return record(value) && typeof value.id === 'string' && value.id.length > 0 && typeof value.model === 'string'
    && value.model.length > 0 && ['boxplot', 'explanation', 'word_report'].includes(String(value.task_type))
    && ['reserved', 'submitting', 'submitted', 'submission_unknown', 'completed', 'failed', 'released'].includes(String(value.status))
    && (value.provider_status === null || typeof value.provider_status === 'string')
    && ['pending', 'estimated'].includes(String(value.usage_status)) && nullableAmount(value.estimated_cost_micro_usd)
    && date(value.created_at) && date(value.updated_at)
    && (!Object.hasOwn(value, 'reconciliation') || isCallReconciliation(value.reconciliation, value.status))
}
export function isProjectUsage(value: unknown, page: number): value is ProjectUsage {
  return record(value) && value.currency === 'USD' && value.period === 'cumulative' && value.enforcement_scope === 'unified_only'
    && isBudget(value.user_budget, 'user') && isBudget(value.project_budget, 'project')
    && nonnegative(value.estimated_micro_usd) && nonnegative(value.reserved_micro_usd) && nonnegative(value.pending_count)
    && optionalAmount(value, 'accounted_micro_usd')
    && Array.isArray(value.items) && value.items.length <= 10 && value.items.every(isCall)
    && nonnegative(value.total) && value.items.length <= value.total && value.page === page && value.page_size === 10
    && (!Object.hasOwn(value, 'reconciliation') || isReconciliationSummary(value.reconciliation, value.total))
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
