import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
import ProjectModelUsage from './ProjectModelUsage'

const budget = { scope_type: 'user', limit_micro_usd: null, revision: 0, estimated_micro_usd: 0,
  reserved_micro_usd: 0, available_micro_usd: null, exceeded: false }
const fixture = (page = 1) => ({ currency: 'USD', period: 'cumulative', enforcement_scope: 'unified_only',
  user_budget: budget, project_budget: { ...budget, scope_type: 'project' }, estimated_micro_usd: 0,
  reserved_micro_usd: 0, pending_count: 0, items: [] as Record<string, unknown>[], total: 0, page, page_size: 10 })
const call = (model = 'model-visible') => ({ id: 'internal-call', task_type: 'explanation', model, status: 'submission_unknown',
  provider_status: null, usage_status: 'pending', estimated_cost_micro_usd: null,
  created_at: '2026-10-08T01:00:00Z', updated_at: '2026-10-08T01:00:00Z' })
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
beforeEach(() => setApiSession('usage-test'))
afterEach(() => { cleanup(); clearApiSession(); setLocale('zh-CN'); vi.useRealTimers(); vi.unstubAllGlobals() })

test('renders honest empty scope and cumulative USD budgets in both languages', async () => {
  const fetch = vi.fn(async () => Response.json(fixture()))
  vi.stubGlobal('fetch', fetch)
  render(<ProjectModelUsage projectId="p1" />)
  expect(await screen.findByText('尚无统一模型调用记录。')).toBeTruthy()
  expect(screen.getByText('历史绘图和历史解释未计入统一账本；本面板统计新绘图和新解释等统一入口的调用。')).toBeTruthy()
  expect(screen.getAllByText('未配置').length).toBeGreaterThan(0)
  expect(screen.getByText('累计额度 · USD')).toBeTruthy()
  act(() => setLocale('en'))
  expect(screen.getByText('No unified model calls yet.')).toBeTruthy()
  expect(screen.getByText('Cumulative allowance · USD')).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(1)
})

test('keeps unknown costs distinct from estimates and shows over-budget state without identifiers', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...fixture(), total: 2, pending_count: 1,
    project_budget: { ...budget, scope_type: 'project', limit_micro_usd: 1_000_000, revision: 1,
      estimated_micro_usd: 2_000_000, available_micro_usd: -1_000_000, exceeded: true }, estimated_micro_usd: 2_000_000,
    items: [call(), { ...call('known-model'), id: 'internal-known', status: 'completed', usage_status: 'estimated',
      estimated_cost_micro_usd: 2_000_000, provider_response_id: 'private-response', input_digest: 'private-digest' }] })))
  render(<ProjectModelUsage projectId="p1" />)
  expect(await screen.findByText('已超出额度')).toBeTruthy()
  const row = screen.getByText('model-visible').closest('tr')!
  expect(within(row).getByText('待核对')).toBeTruthy()
  expect(within(row).queryByText(/0\.00/)).toBeNull()
  expect(within(screen.getByText('known-model').closest('tr')!).getByText('USD 2.000000')).toBeTruthy()
  expect(screen.getByText('内部估算，不是供应商账单。')).toBeTruthy()
  expect(screen.queryByText(/private-|internal-/)).toBeNull()
})

test('pages and refreshes recent calls', async () => {
  const fetch = vi.fn(async (url: string) => {
    const page = new URL(url, 'http://test').searchParams.get('page') === '2' ? 2 : 1
    return Response.json({ ...fixture(page), total: 11, items: [call(`page-${page}`)] })
  })
  vi.stubGlobal('fetch', fetch)
  render(<ProjectModelUsage projectId="p1" />)
  expect(await screen.findByText('page-1')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '模型调用下一页' }))
  expect(await screen.findByText('page-2')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '刷新模型用量' }))
  expect(await screen.findByText('page-2')).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(3)
})

test('does not read while inactive and aborts on overview exit or unmount', async () => {
  const first = deferred<Response>()
  const fetch = vi.fn(() => first.promise)
  vi.stubGlobal('fetch', fetch)
  const view = render(<ProjectModelUsage projectId="p1" active={false} />)
  expect(fetch).not.toHaveBeenCalled()
  view.rerender(<ProjectModelUsage projectId="p1" active />)
  expect(fetch).toHaveBeenCalledTimes(1)
  const signal = (fetch.mock.calls[0] as unknown as [string, RequestInit])[1].signal!
  view.rerender(<ProjectModelUsage projectId="p1" active={false} />)
  expect(signal.aborted).toBe(true)
  await act(async () => first.resolve(Response.json({ ...fixture(), total: 1, items: [call('late-model')] })))
  expect(screen.queryByText('late-model')).toBeNull()
  view.unmount()
})

test('rejects late project and session responses', async () => {
  const first = deferred<Response>()
  const second = deferred<Response>()
  const fetch = vi.fn().mockImplementationOnce(() => first.promise).mockImplementationOnce(() => second.promise)
  vi.stubGlobal('fetch', fetch)
  const view = render(<ProjectModelUsage projectId="p1" />)
  view.rerender(<ProjectModelUsage projectId="p2" />)
  await act(async () => first.resolve(Response.json({ ...fixture(), total: 1, items: [call('old-project')] })))
  expect(screen.queryByText('old-project')).toBeNull()
  act(() => setApiSession('new-session'))
  await act(async () => second.resolve(Response.json({ ...fixture(), total: 1, items: [call('old-session')] })))
  expect(screen.queryByText('old-session')).toBeNull()
  expect(screen.getByText('会话已失效，请重新登录。')).toBeTruthy()
})

test('times out after 15 seconds and refuses malformed amounts without exposing server prose', async () => {
  vi.useFakeTimers()
  const pending = deferred<Response>()
  vi.stubGlobal('fetch', vi.fn(() => pending.promise))
  const view = render(<ProjectModelUsage projectId="p1" />)
  await act(async () => vi.advanceTimersByTime(15_000))
  expect(screen.getByRole('alert').textContent).toBe('模型用量读取超时，请重试。')
  view.unmount()
  vi.useRealTimers()
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...fixture(), estimated_micro_usd: '0' })))
  render(<ProjectModelUsage projectId="p1" />)
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.getByRole('alert').textContent).toBe('模型用量读取失败，请重试。')
})

test('refresh aborts the old response and unmount aborts the active request', async () => {
  const old = deferred<Response>()
  const newest = deferred<Response>()
  const fetch = vi.fn().mockImplementationOnce(async () => Response.json(fixture()))
    .mockImplementationOnce(() => old.promise).mockImplementationOnce(() => newest.promise)
  vi.stubGlobal('fetch', fetch)
  const view = render(<ProjectModelUsage projectId="p1" />)
  await screen.findByText('尚无统一模型调用记录。')
  fireEvent.click(screen.getByRole('button', { name: '刷新模型用量' }))
  view.rerender(<ProjectModelUsage projectId="p1" active={false} />)
  view.rerender(<ProjectModelUsage projectId="p1" active />)
  await act(async () => old.resolve(Response.json({ ...fixture(), total: 1, items: [call('obsolete-refresh')] })))
  expect(screen.queryByText('obsolete-refresh')).toBeNull()
  const signal = (fetch.mock.calls[2] as [string, RequestInit])[1].signal!
  view.unmount()
  expect(signal.aborted).toBe(true)
})

test('displays confirmed zero and keeps partial estimate pending while translating safe errors', async () => {
  const fetch = vi.fn().mockImplementationOnce(async () => Response.json({ ...fixture(), total: 2,
    items: [{ ...call('zero-model'), id: 'zero', usage_status: 'estimated', estimated_cost_micro_usd: 0 },
      { ...call('partial-model'), id: 'partial', estimated_cost_micro_usd: 5 }] }))
    .mockImplementationOnce(async () => Response.json({ detail: { code: 'model_budget_missing', message: 'private-provider-body' } }, { status: 409 }))
  vi.stubGlobal('fetch', fetch)
  render(<ProjectModelUsage projectId="p1" />)
  expect(within((await screen.findByText('zero-model')).closest('tr')!).getByText('USD 0.000000')).toBeTruthy()
  expect(within(screen.getByText('partial-model').closest('tr')!).getByText('USD 0.000005')).toBeTruthy()
  expect(within(screen.getByText('partial-model').closest('tr')!).getByText('待核对')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '刷新模型用量' }))
  expect((await screen.findByRole('alert')).textContent).toBe('尚未配置模型预算，请联系管理员。')
  act(() => setLocale('en'))
  expect(screen.getByRole('alert').textContent).toBe('The model budget is not configured. Contact the administrator.')
  expect(screen.queryByText('private-provider-body')).toBeNull()
})

test('submitting requires confirmation and unknown outcomes preserve reservations', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...fixture(), total: 2, pending_count: 2,
    items: [{ ...call('await-confirmation'), id: 'confirm', status: 'submitting' }, call('unknown-outcome')] })))
  render(<ProjectModelUsage projectId="p1" />)
  expect(await screen.findByText('提交待确认')).toBeTruthy()
  expect(screen.getByText('提交结果未知')).toBeTruthy()
  expect(screen.getByText('提交待确认或结果未知的调用保留预留预算，等待核对。')).toBeTruthy()
  act(() => setLocale('en'))
  expect(screen.getByText('Submission awaiting confirmation')).toBeTruthy()
  expect(screen.getByText('Calls awaiting submission confirmation or with unknown outcomes keep their budget reservations until reconciled.')).toBeTruthy()
})
