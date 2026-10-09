// Synthetic API payloads for reconciliation interface tests; no provider evidence.
export const reconciliationTime = '2026-10-09T01:00:00Z'
export const reconciliationBudget = { scope_type: 'user', limit_micro_usd: 10_000_000, revision: 1,
  estimated_micro_usd: 1010, accounted_micro_usd: 1010, reserved_micro_usd: 600,
  available_micro_usd: 9_998_390, exceeded: false }
export const reconciliationCall = { id: 'private-call-id', task_type: 'boxplot', model: 'partial-model', status: 'completed',
  provider_status: 'completed', usage_status: 'estimated', estimated_cost_micro_usd: 1010,
  created_at: reconciliationTime, updated_at: reconciliationTime,
  reconciliation: { status: 'partial', token_micro_usd: null, tool_micro_usd: 600, tool_applicable: true,
    actual_micro_usd: 600, reconciled_at: reconciliationTime } }
export const reconciliationFixture = { currency: 'USD', period: 'cumulative', enforcement_scope: 'unified_only',
  user_budget: reconciliationBudget, project_budget: { ...reconciliationBudget, scope_type: 'project' },
  task_budget: { ...reconciliationBudget, scope_type: 'task' },
  estimated_micro_usd: 1010, accounted_micro_usd: 1010, reserved_micro_usd: 600, pending_count: 0,
  reconciliation: { actual_micro_usd: 600, reconciled_count: 0, partial_count: 1, pending_count: 0 },
  total: 1, page: 1, page_size: 10, items: [reconciliationCall] }
