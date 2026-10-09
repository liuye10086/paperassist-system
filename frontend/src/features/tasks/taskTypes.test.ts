import { expect, it } from 'vitest'
import { displayNames, isEventPage, isTask, isTaskPage, isWorkspace, taskDisplayName, type TaskView } from './taskTypes'
import { eventsFixture, legacyTaskFixture, legacyWorkspaceFixture, pageFixture, taskFixture } from './taskFixtures'

it.each([
  ['queued', 'compute', 'queued', '待执行'], ['running', 'parse', 'parsing', '文件解析中'],
  ['running', 'plan', 'analyzing', 'AI 分析中'], ['running', 'compute', 'computing', '数据计算中'],
  ['running', 'search', 'searching', '文献检索中'], ['running', 'export', 'generating_document', '文档生成中'],
  ['waiting_input', 'compute', 'waiting_input', '待补充资料'], ['waiting_confirmation', 'compute', 'waiting_confirmation', '待用户确认'],
  ['succeeded', 'compute', 'succeeded', '已完成'], ['failed', 'export', 'failed', '执行失败'],
  ['running', 'interpret', 'analyzing', 'AI 分析中'], ['running', 'verify', 'analyzing', 'AI 分析中'],
  ['running', 'write', 'generating_document', '文档生成中'],
])('maps the user-visible lifecycle %s / %s', (status, phase, display, label) => {
  const task = { ...taskFixture, status, phase, display_status: display } as TaskView
  expect(taskDisplayName(task)).toBe(label)
  expect(Object.keys(displayNames)).toHaveLength(10)
})
const retainedRunningPhases = [
  ['parse', 'parsing'], ['plan', 'analyzing'], ['compute', 'computing'], ['search', 'searching'],
  ['interpret', 'analyzing'], ['write', 'generating_document'], ['export', 'generating_document'], ['verify', 'analyzing'],
] as const
const lifecycleLabels = [
  ['queued', '待执行'], ['waiting_input', '待补充资料'], ['waiting_confirmation', '待用户确认'],
  ['succeeded', '已完成'], ['failed', '执行失败'],
] as const
it.each(lifecycleLabels.flatMap(([status, label]) => retainedRunningPhases.map(([phase, display_status]) =>
  ({ status, label, phase, display_status }))))('prioritizes $status over retained running display $display_status / $phase',
  ({ status, label, phase, display_status }) => {
    expect(taskDisplayName({ ...taskFixture, status, phase, display_status } as TaskView)).toBe(label)
  })
it('rejects crossed project pages and inconsistent event cursors', () => {
  expect(isTaskPage(pageFixture, 'p2', 1)).toBe(false)
  expect(isEventPage(eventsFixture, 't2', 0)).toBe(false)
  expect(isEventPage({ ...eventsFixture, next_cursor: 50 }, 't1', 0)).toBe(false)
  expect(isEventPage({ ...eventsFixture, items: [...eventsFixture.items, ...eventsFixture.items] }, 't1', 0)).toBe(false)
})
it.each([-1, 4, 1.5, '1', false])('rejects an invalid task retry_count %j', retry_count => {
  expect(isTask({ ...taskFixture, retry_count }, 'p1')).toBe(false)
})
it.each([undefined, null, 0, 1, 2, 3])('accepts a task retry_count %j including legacy data', retry_count => {
  expect(isTask({ ...taskFixture, retry_count }, 'p1')).toBe(true)
})
it.each(['revision', 'current_attempt', 'updated_at'])('rejects missing or null unified %s', key => {
  for (const origin of [undefined, 'unified']) for (const value of [undefined, null]) {
    expect(isTask({ ...taskFixture, origin, [key]: value }, 'p1')).toBe(false)
  }
})
it('accepts mixed task pages, nullable legacy facts, and unchanged responses without origin', () => {
  expect(isTask(taskFixture, 'p1')).toBe(true)
  expect(isTask({ ...taskFixture, origin: 'unified' }, 'p1')).toBe(true)
  expect(isTask(legacyTaskFixture, 'p1')).toBe(true)
  expect(isWorkspace(legacyWorkspaceFixture, 'p1', legacyTaskFixture.id)).toBe(true)
  expect(isTaskPage({ ...pageFixture, total: 2, items: [...pageFixture.items,
    { task: legacyTaskFixture, source: legacyWorkspaceFixture.source }] }, 'p1', 1)).toBe(true)
})
it.each([['revision', 3], ['current_attempt', 1], ['retry_count', 0], ['updated_at', taskFixture.updated_at]])('requires legacy %s to be explicitly unknown', (key, recorded) => {
  expect(isTask({ ...legacyTaskFixture, [key]: undefined }, 'p1')).toBe(false)
  expect(isTask({ ...legacyTaskFixture, [key]: recorded }, 'p1')).toBe(false)
})
it('rejects legacy actions, waits, unknown origin, and invented input versions', () => {
  expect(isWorkspace({ ...legacyWorkspaceFixture, allowed_actions: ['retry'] }, 'p1', legacyTaskFixture.id)).toBe(false)
  expect(isWorkspace({ ...legacyWorkspaceFixture, wait: workspaceWait() }, 'p1', legacyTaskFixture.id)).toBe(false)
  expect(isTask({ ...taskFixture, origin: 'unknown' }, 'p1')).toBe(false)
  expect(isTask({ ...legacyTaskFixture, input_version: null }, 'p1')).toBe(false)
  expect(isTask({ ...legacyTaskFixture, input_version: { setup_revision: 0, output_language: 'zh-CN' } }, 'p1')).toBe(false)
})
function workspaceWait() {
  return { id: 'w1', kind: 'submission_unknown', status: 'open', task_revision: 1,
    input_version: taskFixture.input_version, reason_code: null, error_code: null, created_at: taskFixture.created_at, resolved_at: null }
}
it('accepts long canonical legacy identifiers without relaxing source or artifact identifiers', () => {
  const longId = `legacy-plot:${btoa('old/'.repeat(100)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')}`
  expect(isTask({ ...legacyTaskFixture, id: longId }, 'p1')).toBe(true)
  expect(isTask({ ...taskFixture, id: 'u'.repeat(65) }, 'p1')).toBe(false)
  expect(isWorkspace({ ...legacyWorkspaceFixture, source: { ...legacyWorkspaceFixture.source, file_id: 'f'.repeat(65) } }, 'p1', legacyTaskFixture.id)).toBe(false)
  expect(isTask({ ...legacyTaskFixture, result_figure_id: 'f'.repeat(65) }, 'p1')).toBe(false)
})
it('accepts a canonical UTF-8 legacy ID while enforcing its origin', () => {
  const encoded = btoa(Array.from(new TextEncoder().encode('历史任务/α'), byte => String.fromCharCode(byte)).join(''))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  const legacy = { ...legacyTaskFixture, id: `legacy-plot:${encoded}` }
  expect(isTask(legacy, 'p1')).toBe(true)
  expect(isTask({ ...legacy, origin: undefined }, 'p1')).toBe(false)
  expect(isTask({ ...taskFixture, id: legacy.id, origin: 'unified' }, 'p1')).toBe(false)
  expect(isTask({ ...legacy, id: 't1' }, 'p1')).toBe(false)
})
it('rejects a downstream report attached to a historical plot task', () => {
  expect(isWorkspace({ ...legacyWorkspaceFixture, task: { ...legacyTaskFixture, result_report_id: 'report1' },
    artifacts: { ...legacyWorkspaceFixture.artifacts,
      report: { filename: '下游报告.docx', download_url: '/api/v1/projects/p1/files/f1/analysis-runs/r1/report/report1/download' } } },
  'p1', legacyTaskFixture.id)).toBe(false)
})
it('rejects a downstream explanation attached to a historical plot task', () => {
  expect(isWorkspace({ ...legacyWorkspaceFixture, task: { ...legacyTaskFixture, result_explanation_id: 'explanation1' },
    artifacts: { ...legacyWorkspaceFixture.artifacts, explanation: { sections: [{ key: 'summary', title: '下游解释', text: '原文' }], limitations: [] } } },
  'p1', legacyTaskFixture.id)).toBe(false)
})
it('rejects an upstream plot attached to a historical explanation task', () => {
  const task = { ...legacyTaskFixture, id: 'legacy-explanation:b2xk', task_type: 'explanation', phase: 'interpret' }
  expect(isWorkspace({ ...legacyWorkspaceFixture, task }, 'p1', task.id)).toBe(false)
})
it.each(['legacy-plot:', 'legacy-other:b2xk', 'legacy-plot:b2xk=', 'legacy-plot:abc/def',
  'legacy-plot:A', 'legacy-plot:YR', 'legacy-plot:_w', 'legacy-explanation:b2xk'])('rejects invalid or mismatched legacy identity %s', id => {
  expect(isTask({ ...legacyTaskFixture, id }, 'p1')).toBe(false)
})
it.each([
  { retry_count: -1 }, { retry_count: 4 }, { retry_count: 1.5 }, { retry_count: '1' },
  { retry_delay_seconds: 0 }, { retry_delay_seconds: 20 }, { retry_delay_seconds: '10' },
  { error_code: {} }, { error_category: 'PRIVATE TRACE' }, { error_category: '__proto__' },
  { retry_reason: 'PRIVATE TRACE' }, { retry_reason: '__proto__' },
])('rejects invalid event metadata %j', metadata => {
  expect(isEventPage({ ...eventsFixture, items: [{ ...eventsFixture.items[0], ...metadata }] }, 't1', 0)).toBe(false)
})
it.each([
  {}, { error_code: null, error_category: null, retry_reason: null, retry_count: null, retry_delay_seconds: null },
  { error_code: 'model_provider_unavailable', error_category: 'temporary', retry_reason: 'temporary_provider_error', retry_count: 1, retry_delay_seconds: 10 },
  { error_code: 'PRIVATE', error_category: 'internal', retry_reason: 'manual_retry', retry_count: 0, retry_delay_seconds: null },
  { error_category: 'interrupted', retry_reason: 'worker_interrupted', retry_count: 3, retry_delay_seconds: 90 },
])('accepts nullable legacy or supported event metadata %j', metadata => {
  expect(isEventPage({ ...eventsFixture, items: [{ ...eventsFixture.items[0], ...metadata }] }, 't1', 0)).toBe(true)
})
