import { expect, it } from 'vitest'
import { displayNames, isEventPage, isTaskPage, taskDisplayName, type TaskView } from './taskTypes'
import { eventsFixture, pageFixture, taskFixture } from './taskFixtures'

it.each([
  ['queued', 'compute', 'queued', '待执行'], ['running', 'parse', 'parsing', '文件解析中'],
  ['running', 'plan', 'analyzing', 'AI 分析中'], ['running', 'compute', 'computing', '数据计算中'],
  ['running', 'search', 'searching', '文献检索中'], ['running', 'export', 'generating_document', '文档生成中'],
  ['waiting_input', 'compute', 'waiting_input', '待补充资料'], ['waiting_confirmation', 'compute', 'waiting_confirmation', '待用户确认'],
  ['succeeded', 'compute', 'succeeded', '已完成'], ['failed', 'export', 'failed', '执行失败'],
])('maps the user-visible lifecycle %s / %s', (status, phase, display, label) => {
  const task = { ...taskFixture, status, phase, display_status: display } as TaskView
  expect(taskDisplayName(task)).toBe(label)
  expect(Object.keys(displayNames)).toHaveLength(10)
})
it('rejects crossed project pages and inconsistent event cursors', () => {
  expect(isTaskPage(pageFixture, 'p2', 1)).toBe(false)
  expect(isEventPage(eventsFixture, 't2', 0)).toBe(false)
  expect(isEventPage({ ...eventsFixture, next_cursor: 50 }, 't1', 0)).toBe(false)
  expect(isEventPage({ ...eventsFixture, items: [...eventsFixture.items, ...eventsFixture.items] }, 't1', 0)).toBe(false)
})
