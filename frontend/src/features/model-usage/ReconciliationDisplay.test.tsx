import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
import ProjectModelUsage from './ProjectModelUsage'
import TaskModelUsage from './TaskModelUsage'
import { reconciliationCall, reconciliationFixture, reconciliationTime } from './reconciliationFixtures'

beforeEach(() => setApiSession('reconciliation-test'))
afterEach(() => { cleanup(); clearApiSession(); setLocale('zh-CN'); vi.unstubAllGlobals() })
const panels = [
  { name: 'project', render: () => <ProjectModelUsage projectId="p1" />, refresh: '刷新模型用量' },
  { name: 'task', render: () => <TaskModelUsage taskId="t1" />, refresh: '刷新任务用量' },
]

for (const panel of panels) {
  test(`${panel.name} distinguishes estimate, budget accounting and partial actual cost in both languages with GET only`, async () => {
    const fetch = vi.fn(async () => Response.json({ ...reconciliationFixture,
      evidence_reference: 'private-reference', operator: 'private-operator', evidence_sha256: 'private-hash',
      items: [{ ...reconciliationCall, provider_object_id: 'private-provider-object' }] }))
    vi.stubGlobal('fetch', fetch)
    render(panel.render())
    const row = (await screen.findByText('partial-model')).closest('tr')!
    expect(within(row).getByText('USD 0.001010')).toBeTruthy()
    expect(within(row).getByText('USD 0.000600')).toBeTruthy()
    expect(within(row).getByText('部分已核对')).toBeTruthy()
    expect(within(row).getByText('模型费用：待核对')).toBeTruthy()
    expect(within(row).getByText('工具费用：USD 0.000600')).toBeTruthy()
    expect(screen.getAllByText('预算已计金额').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('已核对部分合计')).toBeTruthy()
    expect(screen.getByText('实际待核对调用')).toBeTruthy()
    expect(screen.getByText('部分核对仅记录已确认分项，不释放预留；全部核对后才按实际金额结算。')).toBeTruthy()
    expect(screen.queryByText(/private-/)).toBeNull()
    act(() => setLocale('en'))
    expect(within(row).getByText('Partially reconciled')).toBeTruthy()
    expect(within(row).getByText('Model cost: Awaiting reconciliation')).toBeTruthy()
    expect(within(row).getByText('Tool cost: USD 0.000600')).toBeTruthy()
    expect(screen.getByText('Reconciled components total')).toBeTruthy()
    expect(screen.getAllByText('Accounted amount').length).toBeGreaterThanOrEqual(2)
    expect(fetch).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: panel.name === 'project' ? 'Refresh model usage' : 'Refresh task usage' }))
    await screen.findByText('partial-model')
    for (const invocation of fetch.mock.calls) {
      const [url, init] = invocation as unknown as [string, RequestInit]
      expect(url).toContain('/model-usage?')
      expect(init?.method ?? 'GET').toBe('GET')
      expect(init?.body).toBeUndefined()
    }
    expect(screen.queryByRole('button', { name: /apply|reconcile|upload/i })).toBeNull()
  })

  test(`${panel.name} distinguishes actual zero, unknown and not applicable without overwriting original estimate`, async () => {
    const items = [
      { ...reconciliationCall, id: 'zero-private', model: 'zero-model', task_type: 'explanation',
        reconciliation: { status: 'reconciled', token_micro_usd: 0, tool_micro_usd: null,
          tool_applicable: false, actual_micro_usd: 0, reconciled_at: reconciliationTime } },
      { ...reconciliationCall, id: 'pending-private', model: 'pending-model',
        reconciliation: { status: 'pending', token_micro_usd: null, tool_micro_usd: null,
          tool_applicable: true, actual_micro_usd: null, reconciled_at: null } },
      { ...reconciliationCall, id: 'released-private', model: 'released-model', status: 'released',
        estimated_cost_micro_usd: null,
        reconciliation: { status: 'not_applicable', token_micro_usd: null, tool_micro_usd: null,
          tool_applicable: false, actual_micro_usd: null, reconciled_at: null } },
    ]
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...reconciliationFixture, items, total: 3,
      accounted_micro_usd: 0, reconciliation: { actual_micro_usd: 0, reconciled_count: 1, partial_count: 0, pending_count: 1 },
      user_budget: { ...reconciliationFixture.user_budget, accounted_micro_usd: 0 },
      project_budget: { ...reconciliationFixture.project_budget, accounted_micro_usd: 0 },
      task_budget: { ...reconciliationFixture.task_budget, accounted_micro_usd: 0 } })))
    render(panel.render())
    const zero = (await screen.findByText('zero-model')).closest('tr')!
    expect(within(zero).getByText('USD 0.000000')).toBeTruthy()
    expect(within(zero).getByText('USD 0.001010')).toBeTruthy()
    expect(within(zero).getByText('模型费用：USD 0.000000')).toBeTruthy()
    expect(within(zero).getByText('工具费用：不适用')).toBeTruthy()
    const unknown = screen.getByText('pending-model').closest('tr')!
    expect(within(unknown).getByText('尚未核对')).toBeTruthy()
    expect(within(unknown).getByText('模型费用：待核对')).toBeTruthy()
    expect(within(unknown).queryByText('USD 0.000000')).toBeNull()
    const released = screen.getByText('released-model').closest('tr')!
    expect(within(released).getByText('不适用')).toBeTruthy()
    expect(within(released).queryByText(/费用：待核对/)).toBeNull()
    act(() => setLocale('en'))
    expect(within(zero).getByText('Tool cost: Not applicable')).toBeTruthy()
    expect(within(unknown).getByText('Awaiting actual reconciliation')).toBeTruthy()
    expect(within(released).getByText('Not applicable')).toBeTruthy()
  })

  test(`${panel.name} keeps legacy responses readable and marks actual reconciliation unavailable`, async () => {
    const { reconciliation: _summary, accounted_micro_usd: _accounted, ...legacy } = reconciliationFixture
    const { reconciliation: _reconciliation, ...call } = reconciliationCall
    const { accounted_micro_usd: _budget, ...budget } = reconciliationFixture.user_budget
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...legacy, user_budget: budget,
      project_budget: { ...budget, scope_type: 'project' }, task_budget: { ...budget, scope_type: 'task' }, items: [call] })))
    render(panel.render())
    const row = (await screen.findByText('partial-model')).closest('tr')!
    expect(screen.getByText('实际核对数据暂不可用')).toBeTruthy()
    expect(within(row).getByText('暂不可用')).toBeTruthy()
    expect(within(row).queryByText('USD 0.000000')).toBeNull()
    act(() => setLocale('en'))
    expect(screen.getByText('Actual reconciliation data is temporarily unavailable.')).toBeTruthy()
  })

  test(`${panel.name} keeps a confirmed partial zero pending and shows complete actual settlement independently from estimate`, async () => {
    const fetch = vi.fn().mockImplementationOnce(async () => Response.json({ ...reconciliationFixture,
      reconciliation: { actual_micro_usd: 0, reconciled_count: 0, partial_count: 1, pending_count: 0 },
      items: [{ ...reconciliationCall, reconciliation: { ...reconciliationCall.reconciliation,
        tool_micro_usd: 0, actual_micro_usd: 0 } }] }))
      .mockImplementationOnce(async () => Response.json({ ...reconciliationFixture,
        accounted_micro_usd: 1600, reserved_micro_usd: 0,
        user_budget: { ...reconciliationFixture.user_budget, accounted_micro_usd: 1600, reserved_micro_usd: 0, available_micro_usd: 9_998_400 },
        project_budget: { ...reconciliationFixture.project_budget, accounted_micro_usd: 1600, reserved_micro_usd: 0, available_micro_usd: 9_998_400 },
        task_budget: { ...reconciliationFixture.task_budget, accounted_micro_usd: 1600, reserved_micro_usd: 0, available_micro_usd: 9_998_400 },
        reconciliation: { actual_micro_usd: 1600, reconciled_count: 1, partial_count: 0, pending_count: 0 },
        items: [{ ...reconciliationCall, reconciliation: { ...reconciliationCall.reconciliation,
          status: 'reconciled', token_micro_usd: 1000, actual_micro_usd: 1600 } }] }))
    vi.stubGlobal('fetch', fetch)
    render(panel.render())
    const partial = (await screen.findByText('partial-model')).closest('tr')!
    expect(within(partial).getByText('USD 0.000000')).toBeTruthy()
    expect(within(partial).getByText('部分已核对')).toBeTruthy()
    expect(within(partial).getByText('模型费用：待核对')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: panel.refresh }))
    await screen.findByText('全部已核对')
    const complete = screen.getByText('partial-model').closest('tr')!
    expect(within(complete).getByText('USD 0.001010')).toBeTruthy()
    expect(within(complete).getByText('USD 0.001600')).toBeTruthy()
    expect(within(complete).getByText('模型费用：USD 0.001000')).toBeTruthy()
    const projectBudget = screen.getByText('项目预算').closest<HTMLElement>('.usage-budget-card')!
    expect(within(projectBudget).getByText('USD 0.001010')).toBeTruthy()
    expect(within(projectBudget).getByText('USD 0.001600')).toBeTruthy()
    expect(within(projectBudget).getByText('USD 0.000000')).toBeTruthy()
    expect(within(projectBudget).getByText('USD 9.998400')).toBeTruthy()
  })

  test(`${panel.name} rejects a present but invalid actual reconciliation object`, async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...reconciliationFixture,
      items: [{ ...reconciliationCall, reconciliation: { ...reconciliationCall.reconciliation, actual_micro_usd: 601 } }] })))
    render(panel.render())
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.queryByText('partial-model')).toBeNull()
    expect(screen.queryByText('实际核对数据暂不可用')).toBeNull()
  })
}

test('summary uses API totals across pages and distinguishes no evidence from a proven zero', async () => {
  const fetch = vi.fn(async (url: string) => {
    const page = new URL(url, 'http://test').searchParams.get('page') === '2' ? 2 : 1
    return Response.json({ ...reconciliationFixture, page, total: 11,
      reconciliation: { actual_micro_usd: 4500, reconciled_count: 3, partial_count: 1, pending_count: 7 },
      items: [{ ...reconciliationCall, model: `page-${page}` }] })
  })
  vi.stubGlobal('fetch', fetch)
  const view = render(<ProjectModelUsage projectId="p1" />)
  await screen.findByText('page-1')
  expect(screen.getByText('USD 0.004500')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '模型调用下一页' }))
  await screen.findByText('page-2')
  expect(screen.getByText('USD 0.004500')).toBeTruthy()
  view.unmount()
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...reconciliationFixture, total: 0, items: [],
    reconciliation: { actual_micro_usd: 0, reconciled_count: 0, partial_count: 0, pending_count: 0 } })))
  render(<ProjectModelUsage projectId="p2" />)
  expect(await screen.findByText('尚无已核对金额')).toBeTruthy()
  act(() => setLocale('en'))
  expect(screen.getByText('No reconciled amount yet.')).toBeTruthy()
})
