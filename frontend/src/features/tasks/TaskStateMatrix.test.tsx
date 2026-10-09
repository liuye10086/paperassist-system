import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ProjectTasks from './ProjectTasks'
import TaskDetail from './TaskDetail'
import { eventsFixture, pageFixture, taskFixture, usageFixture, workspaceFixture } from './taskFixtures'
import { setLocale, type Locale } from '../../shared/i18n'
import type { TaskView, TaskWorkspace } from './taskTypes'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setLocale('zh-CN') })

// Explicit user expectations; no production display/phase/translation map is used as an oracle.
const states = [
  ['queued', 'compute', 'queued', '待执行', 'Queued', '计算与绘图', 'Compute and plot'],
  ['running', 'parse', 'parsing', '文件解析中', 'Parsing files', '解析资料', 'Parse materials'],
  ['running', 'plan', 'analyzing', 'AI 分析中', 'AI analysis in progress', '分析计划', 'Analysis plan'],
  ['running', 'compute', 'computing', '数据计算中', 'Computing data', '计算与绘图', 'Compute and plot'],
  ['running', 'search', 'searching', '文献检索中', 'Searching literature', '检索资料', 'Search materials'],
  ['running', 'export', 'generating_document', '文档生成中', 'Generating a document', '导出文档', 'Export document'],
  ['waiting_input', 'compute', 'waiting_input', '待补充资料', 'Waiting for input', '计算与绘图', 'Compute and plot'],
  ['waiting_confirmation', 'compute', 'waiting_confirmation', '待用户确认', 'Waiting for confirmation', '计算与绘图', 'Compute and plot'],
  ['succeeded', 'compute', 'succeeded', '已完成', 'Completed', '计算与绘图', 'Compute and plot'],
  ['failed', 'export', 'failed', '执行失败', 'Execution failed', '导出文档', 'Export document'],
  ['running', 'interpret', 'analyzing', 'AI 分析中', 'AI analysis in progress', '分析解释', 'Explanation'],
  ['running', 'verify', 'analyzing', 'AI 分析中', 'AI analysis in progress', '核查结果', 'Verify results'],
  ['running', 'write', 'generating_document', '文档生成中', 'Generating a document', '生成文字', 'Generate text'],
] as const
const locales: Locale[] = ['zh-CN', 'en']
const props = { projectId: 'p1', taskId: 't1', onChanged: vi.fn() }

function fixture(task: TaskView): TaskWorkspace {
  return { ...workspaceFixture, task, wait: null, allowed_actions: [] }
}
function mockApi(workspace: () => TaskWorkspace, usage: unknown = usageFixture) {
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url.includes('/model-usage')) return Response.json(usage)
    if (url.includes('/events')) return Response.json({ ...eventsFixture, items: [], next_cursor: 0 })
    if (url.includes('/projects/')) {
      const current = workspace()
      return Response.json({ ...pageFixture, items: [{ task: current.task, source: current.source }] })
    }
    return Response.json(workspace())
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}
function fact(detail: HTMLElement, label: string) {
  const term = within(detail).getByText(label, { selector: 'dt', exact: true })
  const value = term.parentElement?.querySelector('dd')
  expect(value).not.toBeNull()
  return value!
}

it.each(states)('shows exact bilingual list and detail facts for %s / %s', async (status, phase, display_status, zh, en, phaseZh, phaseEn) => {
  const task = { ...taskFixture, status, phase, display_status, reason_code: null, error_code: null,
    input_version: { setup_revision: 7, output_language: 'zh-CN' } } as TaskView
  const fetch = mockApi(() => fixture(task))
  render(<ProjectTasks projectId="p1" active selectedTaskId="t1" onSelectTask={vi.fn()} />)
  await screen.findByRole('table', { name: '项目任务列表' })
  await within(screen.getByRole('region', { name: '任务详情' })).findByText(zh, { selector: '.task-status', exact: true })
  for (const locale of locales) {
    act(() => setLocale(locale))
    const english = locale === 'en'
    const row = within(screen.getByRole('table', { name: english ? 'Project task list' : '项目任务列表' }))
      .getByText('实验.xlsx', { exact: true }).closest('tr')!
    const cells = within(row).getAllByRole('cell')
    expect(within(cells[1]).getByText(english ? en : zh, { selector: '.task-status', exact: true })).toBeTruthy()
    expect(within(cells[1]).getByText(english ? phaseEn : phaseZh, { selector: 'small', exact: true })).toBeTruthy()
    expect(within(cells[2]).getByText(english ? 'Analysis configuration v7' : '分析配置 v7', { selector: 'small', exact: true })).toBeTruthy()
    const detail = screen.getByRole('region', { name: english ? 'Task details' : '任务详情' })
    expect(within(detail).getByText(english ? en : zh, { selector: '.task-status', exact: true })).toBeTruthy()
    expect(fact(detail, english ? 'Processing stage' : '处理阶段').textContent).toBe(english ? phaseEn : phaseZh)
    expect(within(fact(detail, english ? 'Input version' : '输入版本'))
      .getByText(english ? 'Analysis configuration v7' : '分析配置 v7', { selector: 'span', exact: true })).toBeTruthy()
  }
  expect(fetch.mock.calls.filter(([, init]) => init?.method && init.method !== 'GET')).toHaveLength(0)
})

const unsupportedText = ['此任务需要的资料或确认暂未提供处理入口，请联系管理员。',
  'There is no supported input or confirmation form for this task yet. Contact the administrator.'] as const
it.each([
  ['unsupported_input', 'waiting_input', 'waiting_input'],
  ['unsupported_confirmation', 'waiting_confirmation', 'waiting_confirmation'],
] as const)('keeps %s read only in both languages and clears resolved instructions', async (kind, status, display_status) => {
  let current: TaskWorkspace = { ...fixture({ ...taskFixture, status, display_status, reason_code: null, error_code: null } as TaskView),
    wait: { ...workspaceFixture.wait, kind, status: 'open', reason_code: null, error_code: null,
      input_version: { setup_revision: 1, output_language: 'zh-CN' } } }
  const fetch = mockApi(() => current)
  render(<TaskDetail {...props} />)
  await screen.findByText(unsupportedText[0], { exact: true })
  for (const locale of locales) {
    act(() => setLocale(locale))
    const pending = screen.getByRole('region', { name: locale === 'en' ? 'Task actions' : '任务处理' })
    expect(within(pending).getByText(unsupportedText[locale === 'en' ? 1 : 0], { exact: true })).toBeTruthy()
    expect(within(pending).queryByRole('button')).toBeNull()
    expect(within(pending).queryByRole('textbox')).toBeNull()
    expect(within(pending).queryByRole('form')).toBeNull()
  }
  current = { ...current, task: { ...current.task, status: 'succeeded', display_status: 'succeeded' },
    wait: { ...current.wait!, status: 'resolved', resolved_at: taskFixture.updated_at } }
  fireEvent.click(screen.getByRole('button', { name: 'Reload task' }))
  await within(screen.getByRole('region', { name: 'Task details' })).findByText('Completed', { selector: '.task-status', exact: true })
  for (const locale of locales) {
    act(() => setLocale(locale))
    const pending = screen.getByRole('region', { name: locale === 'en' ? 'Task actions' : '任务处理' })
    expect(within(pending).queryByText(unsupportedText[locale === 'en' ? 1 : 0], { exact: true })).toBeNull()
    expect(within(pending).queryByRole('button')).toBeNull()
  }
  expect(fetch.mock.calls.filter(([, init]) => init?.method && init.method !== 'GET')).toHaveLength(0)
})

it('shows bilingual budget instructions without submitting on language changes', async () => {
  const fetch = mockApi(() => workspaceFixture as TaskWorkspace)
  render(<TaskDetail {...props} />)
  await screen.findByRole('button', { name: '预算或配置已调整，继续任务' })
  for (const locale of locales) {
    act(() => setLocale(locale))
    const english = locale === 'en'
    const pending = screen.getByRole('region', { name: english ? 'Task actions' : '任务处理' })
    expect(within(pending).getByText(english
      ? 'The task is waiting for budget or model configuration. Contact the administrator before continuing.'
      : '任务正在等待预算或模型配置，请联系管理员调整后继续。', { exact: true })).toBeTruthy()
    expect(within(pending).getByRole('button', { name: english ? 'Budget or configuration updated — continue task' : '预算或配置已调整，继续任务' })).toBeTruthy()
    expect(within(pending).getByText(english
      ? 'Continue this task. Model calls not yet submitted will follow the original policy and budget; existing calls reuse their saved results.'
      : '继续此任务；尚未提交的模型调用会按原策略和预算执行，已有调用沿用已保存结果。', { exact: true })).toBeTruthy()
  }
  expect(fetch.mock.calls.filter(([, init]) => init?.method && init.method !== 'GET')).toHaveLength(0)
})

it('shows bilingual unknown submission and pending cost without inventing a free call', async () => {
  const workspace = { ...workspaceFixture, task: { ...taskFixture, error_code: 'model_submission_unknown' },
    wait: { ...workspaceFixture.wait, kind: 'submission_unknown', reason_code: null, error_code: 'model_submission_unknown' },
    allowed_actions: [] } as TaskWorkspace
  const usage = { ...usageFixture, items: [{ ...usageFixture.items[0], status: 'submission_unknown', provider_status: null,
    reconciliation: { status: 'pending', token_micro_usd: null, tool_micro_usd: null, tool_applicable: true,
      actual_micro_usd: null, reconciled_at: null } }] }
  const fetch = mockApi(() => workspace, usage)
  render(<TaskDetail {...props} />)
  await screen.findByText('test-model', { exact: true })
  for (const locale of locales) {
    act(() => setLocale(locale))
    const english = locale === 'en'
    const pending = screen.getByRole('region', { name: english ? 'Task actions' : '任务处理' })
    expect(within(pending).getByText(english
      ? 'The submission outcome is unverified. Contact the administrator; do not resend the model request.'
      : '提交结果尚未核实，请联系管理员核对；不能重新发送模型请求。', { exact: true })).toBeTruthy()
    expect(within(pending).queryByRole('button')).toBeNull()
    expect(within(pending).queryByRole('textbox')).toBeNull()
    const usagePanel = screen.getByRole('region', { name: english ? 'Task usage' : '本次任务用量' })
    const row = within(usagePanel).getByText('test-model', { exact: true }).closest('tr')!
    const cells = within(row).getAllByRole('cell')
    expect(cells[1].textContent).toBe(english ? 'Awaiting reconciliation' : '待核对')
    expect(within(cells[2]).getByText(english ? 'Awaiting actual reconciliation' : '尚未核对', { exact: true })).toBeTruthy()
    expect(within(cells[2]).getByText(english ? 'Model cost: Awaiting reconciliation' : '模型费用：待核对', { exact: true })).toBeTruthy()
    expect(within(cells[2]).getByText(english ? 'Tool cost: Awaiting reconciliation' : '工具费用：待核对', { exact: true })).toBeTruthy()
    for (const cell of [cells[1], cells[2]]) expect(cell.textContent).not.toMatch(/USD|\$0|免费|free/i)
  }
  expect(fetch.mock.calls.filter(([, init]) => init?.method && init.method !== 'GET')).toHaveLength(0)
})
