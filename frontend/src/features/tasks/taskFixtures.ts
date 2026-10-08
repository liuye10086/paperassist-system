// Synthetic task data shared by task interface tests.
export const taskFixture = { id: 't1', project_id: 'p1', task_type: 'boxplot', status: 'waiting_confirmation',
  phase: 'compute', display_status: 'waiting_confirmation', revision: 3, current_attempt: 1,
  reason_code: 'budget_exceeded', error_code: 'model_budget_missing', created_at: '2026-10-08T01:00:00Z',
  updated_at: '2026-10-08T01:01:00Z', input_version: { setup_revision: 1, output_language: 'zh-CN' },
  result_figure_id: null, result_explanation_id: null, result_report_id: null }
export const sourceFixture = { file_id: 'f1', filename: '实验.xlsx', analysis_run_id: 'r1', is_current: true }
export const workspaceFixture = { task: taskFixture, source: sourceFixture,
  wait: { id: 'w1', kind: 'budget_confirmation', status: 'open', task_revision: 3,
    input_version: taskFixture.input_version, reason_code: 'budget_exceeded', error_code: 'model_budget_missing',
    created_at: taskFixture.updated_at, resolved_at: null }, allowed_actions: ['resume'],
  artifacts: { figure: null, explanation: null, report: null } }
export const pageFixture = { project_id: 'p1', items: [{ task: taskFixture, source: sourceFixture }], total: 1, page: 1, page_size: 10 }
export const eventsFixture = { task_id: 't1', items: [{ seq: 1, task_revision: 1, event_type: 'created',
  status: 'queued', phase: 'compute', reason_code: null, created_at: taskFixture.created_at }], next_cursor: 1, has_more: false }
export const budgetFixture = { scope_type: 'user', limit_micro_usd: 5_000_000, revision: 1,
  estimated_micro_usd: 0, reserved_micro_usd: 100_000, available_micro_usd: 4_900_000, exceeded: false }
export const usageFixture = { currency: 'USD', period: 'cumulative', enforcement_scope: 'unified_only',
  user_budget: budgetFixture, project_budget: { ...budgetFixture, scope_type: 'project' },
  task_budget: { ...budgetFixture, scope_type: 'task', limit_micro_usd: 1_000_000, available_micro_usd: 900_000 },
  estimated_micro_usd: 0, reserved_micro_usd: 100_000, pending_count: 1, total: 1, page: 1, page_size: 10,
  items: [{ id: 'call-private', task_type: 'boxplot', model: 'test-model', status: 'completed', provider_status: 'completed',
    usage_status: 'pending', estimated_cost_micro_usd: null, created_at: taskFixture.created_at, updated_at: taskFixture.updated_at }] }
