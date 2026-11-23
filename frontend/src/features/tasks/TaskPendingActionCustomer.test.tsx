import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import TaskPendingAction from './TaskPendingAction'
import { taskFixture, workspaceFixture } from './taskFixtures'
import { setLocale } from '../../shared/i18n'

afterEach(() => { cleanup(); setLocale('zh-CN') })
const internal = /NCBI|Worker|冻结|外网|调用模型|模型调用|管理员|回执|预算/
function workspace(kind: string | null, actions: string[], taskType = 'boxplot') {
  return { ...workspaceFixture, task: { ...taskFixture, task_type: taskType, error_code: null, reason_code: null },
    wait: kind ? { ...workspaceFixture.wait, kind, error_code: null } : null, allowed_actions: actions } as never
}
function mount(value: never, customerView?: boolean) {
  render(<TaskPendingAction workspace={value} blocked={false} onChanged={() => {}} customerView={customerView} />)
}

it.each([
  ['literature_model_authorization', '文献检索暂不可用，任务已保存。'],
  ['literature_configuration', '文献检索暂不可用，任务已保存。'],
  ['budget_confirmation', '系统正在核对，请稍后刷新或联系客服。'],
  ['remote_observation', '系统正在核对，请稍后刷新或联系客服。'],
  ['unsupported_input', '系统正在核对，请稍后刷新或联系客服。'],
  ['unsupported_confirmation', '系统正在核对，请稍后刷新或联系客服。'],
])('customer view explains the %s wait without internal wording', (kind, text) => {
  mount(workspace(kind, ['resume']), true)
  expect(screen.getByText(text)).toBeTruthy()
  expect(document.body.textContent).not.toMatch(internal)
  expect(screen.getByRole('button', { name: '继续原任务' })).toBeTruthy()
})

it('customer view never offers a resend for an unconfirmed submission and keeps it customer readable', () => {
  mount(workspace('submission_unknown', ['resume']), true)
  expect(screen.getByText('系统正在核对，请稍后刷新或联系客服。')).toBeTruthy()
  expect(screen.queryByRole('button')).toBeNull()
  expect(document.body.textContent).not.toMatch(internal)
})

it.each([
  [['retry'], '重试原任务', 'journal_adaptation'],
  [['cancel'], '取消任务', 'bio_analysis'],
  [['resume'], '继续原任务', 'literature_search'],
])('customer view keeps the %s operation with one customer scope note', (actions, label, taskType) => {
  mount(workspace(null, actions, taskType), true)
  expect(screen.getByRole('button', { name: label })).toBeTruthy()
  expect(screen.getByText('使用原资料重新处理；取消后已有成果不变。')).toBeTruthy()
  expect(document.body.textContent).not.toMatch(internal)
})

it('customer view translates its wording in English', () => {
  setLocale('en')
  mount(workspace('literature_configuration', ['resume']), true)
  expect(screen.getByText('Literature search is temporarily unavailable. The task has been saved.')).toBeTruthy()
  expect(screen.getByText('Reprocesses with the original materials; cancelling keeps existing results.')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Continue original task' })).toBeTruthy()
})

it('staff can continue an old wait without changing settings', () => {
  mount(workspace('budget_confirmation', ['resume']))
  expect(screen.queryByText(/预算/)).toBeNull()
  expect(screen.getByRole('button', { name: '继续原任务' })).toBeTruthy()
})
