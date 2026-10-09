import { expect, test } from 'vitest'
import { isProjectUsage, isTaskUsage } from './modelUsageTypes'
import { reconciliationCall, reconciliationFixture, reconciliationTime } from './reconciliationFixtures'

test('accepts frozen reconciliation projection with partial, complete zero, pending and released calls', () => {
  expect(isProjectUsage(reconciliationFixture, 1)).toBe(true)
  expect(isTaskUsage(reconciliationFixture, 1)).toBe(true)
  for (const reconciliation of [
    { status: 'reconciled', token_micro_usd: 0, tool_micro_usd: null, tool_applicable: false, actual_micro_usd: 0, reconciled_at: reconciliationTime },
    { status: 'reconciled', token_micro_usd: 1000, tool_micro_usd: 600, tool_applicable: true, actual_micro_usd: 1600, reconciled_at: reconciliationTime },
    { status: 'pending', token_micro_usd: null, tool_micro_usd: null, tool_applicable: true, actual_micro_usd: null, reconciled_at: null },
    { status: 'not_applicable', token_micro_usd: null, tool_micro_usd: null, tool_applicable: false, actual_micro_usd: null, reconciled_at: null },
  ]) {
    const value = { ...reconciliationFixture, items: [{ ...reconciliationCall,
      status: reconciliation.status === 'not_applicable' ? 'released' : 'completed', reconciliation }] }
    expect(isProjectUsage(value, 1)).toBe(true)
  }
})

test('rejects malformed optional accounted amounts at every scope', () => {
  for (const amount of [null, undefined, -1, 0.5, '0', false, Number.MAX_SAFE_INTEGER + 1]) {
    expect(isProjectUsage({ ...reconciliationFixture, accounted_micro_usd: amount }, 1)).toBe(false)
    for (const key of ['user_budget', 'project_budget', 'task_budget'] as const) {
      expect(isTaskUsage({ ...reconciliationFixture, [key]: { ...reconciliationFixture[key], accounted_micro_usd: amount } }, 1)).toBe(false)
    }
  }
})

test('rejects malformed summaries while accepting a zero sum with only pending calls', () => {
  for (const field of ['actual_micro_usd', 'reconciled_count', 'partial_count', 'pending_count']) {
    for (const invalid of [null, undefined, -1, '0', 0.1, Number.MAX_SAFE_INTEGER + 1]) {
      expect(isProjectUsage({ ...reconciliationFixture, reconciliation: { ...reconciliationFixture.reconciliation, [field]: invalid } }, 1)).toBe(false)
    }
  }
  for (const invalid of [null, undefined, [], 'pending']) {
    expect(isProjectUsage({ ...reconciliationFixture, reconciliation: invalid }, 1)).toBe(false)
  }
  expect(isProjectUsage({ ...reconciliationFixture,
    reconciliation: { actual_micro_usd: 0, reconciled_count: 0, partial_count: 0, pending_count: 1 },
    items: [{ ...reconciliationCall, reconciliation: { status: 'pending', token_micro_usd: null,
      tool_micro_usd: null, tool_applicable: true, actual_micro_usd: null, reconciled_at: null } }] }, 1)).toBe(true)
  expect(isProjectUsage({ ...reconciliationFixture, reconciliation: { actual_micro_usd: 0,
    reconciled_count: 1, partial_count: 1, pending_count: 0 } }, 1)).toBe(false)
  expect(isProjectUsage({ ...reconciliationFixture, reconciliation: { actual_micro_usd: 1,
    reconciled_count: 0, partial_count: 0, pending_count: 1 } }, 1)).toBe(false)
})

test('rejects invalid component types, status combinations, sums and timestamps', () => {
  const base = reconciliationCall.reconciliation
  const invalid = [null, undefined, [], { ...base, status: 'unreconciled' }, { ...base, tool_applicable: 'true' },
    { ...base, token_micro_usd: -1 }, { ...base, tool_micro_usd: 0.5 }, { ...base, actual_micro_usd: '600' },
    { ...base, actual_micro_usd: 601 }, { ...base, actual_micro_usd: null }, { ...base, tool_micro_usd: null },
    { ...base, token_micro_usd: 1 }, { ...base, tool_applicable: false }, { ...base, reconciled_at: 'bad date' },
    { ...base, reconciled_at: null }, { ...base, status: 'pending' }, { ...base, status: 'reconciled' },
    { ...base, status: 'not_applicable' }, { ...base, status: 'reconciled', token_micro_usd: Number.MAX_SAFE_INTEGER,
      tool_micro_usd: 1, actual_micro_usd: Number.MAX_SAFE_INTEGER + 1 },
  ]
  for (const reconciliation of invalid) {
    expect(isProjectUsage({ ...reconciliationFixture, items: [{ ...reconciliationCall, reconciliation }] }, 1)).toBe(false)
  }
  for (const status of ['released', 'submitted', 'submission_unknown']) {
    expect(isProjectUsage({ ...reconciliationFixture, items: [{ ...reconciliationCall, status }] }, 1)).toBe(false)
  }
  expect(isProjectUsage({ ...reconciliationFixture, items: [{ ...reconciliationCall,
    reconciliation: { ...base, tool_micro_usd: 0, actual_micro_usd: 0 } }] }, 1)).toBe(true)
})

test('keeps old responses compatible without inventing reconciliation fields', () => {
  const { reconciliation: _summary, accounted_micro_usd: _accounted, ...legacy } = reconciliationFixture
  const { accounted_micro_usd: _budget, ...budget } = reconciliationFixture.user_budget
  const { reconciliation: _call, ...call } = reconciliationCall
  const value = { ...legacy, user_budget: budget, project_budget: { ...budget, scope_type: 'project' },
    task_budget: { ...budget, scope_type: 'task' }, items: [call] }
  expect(isProjectUsage(value, 1)).toBe(true)
  expect(isTaskUsage(value, 1)).toBe(true)
})
